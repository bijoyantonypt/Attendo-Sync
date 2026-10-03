"""Local attendance history and payroll calculations, independent of the UI."""

import calendar
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


STANDARD_HOURS = 8.5
DEFAULT_PAY = 100.0
# Scans closer together than this are one double-scan, not a clock-in and clock-out.
MIN_SHIFT = timedelta(minutes=60)
# Earlier punches were testing data and are hidden from the app, exports, and backups.
FIRST_VALID_DATE = date(2026, 9, 28)
# Admin accounts that are not tracked as staff; retired once from the employee list.
ADMIN_NAMES = ("bijoy", "aju")


class AttendanceStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS employees (
                    user_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    daily_pay REAL NOT NULL DEFAULT 100 CHECK(daily_pay >= 0),
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS punches (
                    user_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                    status TEXT NOT NULL, punch TEXT NOT NULL,
                    PRIMARY KEY(user_id, timestamp, status, punch)
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(employees)")}
            if "active" not in columns:
                connection.execute("ALTER TABLE employees ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            self._retire_admins(connection)

    @staticmethod
    def _retire_admins(connection):
        if connection.execute("SELECT 1 FROM settings WHERE key='admins_retired'").fetchone():
            return
        retired = connection.execute(
            "UPDATE employees SET active=0 WHERE lower(trim(name)) IN (?, ?)", ADMIN_NAMES).rowcount
        if retired:
            connection.execute("INSERT OR REPLACE INTO settings VALUES ('admins_retired', 'yes')")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def merge(self, rows, users=None):
        with self.connect() as connection:
            for user_id, name in (users or {}).items():
                connection.execute(
                    "INSERT INTO employees(user_id, name) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
                    (str(user_id), name or "Unknown"),
                )
            for row in rows:
                if row.get("user_id") is None or not row.get("timestamp"):
                    raise ValueError("A device record is missing its employee ID or timestamp.")
                timestamp = datetime.fromisoformat(row["timestamp"])
                if timestamp.tzinfo is not None:
                    raise ValueError("Device timestamps must use local time without a timezone.")
                user_id = str(row["user_id"])
                connection.execute(
                    "INSERT INTO employees(user_id, name) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET name=CASE "
                    "WHEN excluded.name='Unknown' THEN employees.name ELSE excluded.name END",
                    (user_id, row.get("user_name") or "Unknown"),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO punches VALUES (?, ?, ?, ?)",
                    (user_id, timestamp.isoformat(), json.dumps(row.get("status")),
                     json.dumps(row.get("punch"))),
                )
            self._retire_admins(connection)

    def snapshot(self):
        with self.connect() as connection:
            employees = {
                user_id: {"name": name, "daily_pay": daily_pay}
                for user_id, name, daily_pay in connection.execute(
                    "SELECT user_id, name, daily_pay FROM employees WHERE active=1 "
                    "ORDER BY name COLLATE NOCASE, user_id"
                )
            }
            rows = [
                {"user_id": user_id, "user_name": employees[user_id]["name"],
                 "timestamp": timestamp, "status": json.loads(status), "punch": json.loads(punch)}
                for user_id, timestamp, status, punch in connection.execute(
                    "SELECT user_id, timestamp, status, punch FROM punches WHERE timestamp >= ? "
                    "ORDER BY timestamp, user_id", (FIRST_VALID_DATE.isoformat(),)
                ) if user_id in employees
            ]
        return employees, rows

    def add_employee(self, user_id, name, daily_pay=DEFAULT_PAY):
        user_id = str(user_id).strip()
        name = " ".join(str(name).split())
        if not user_id or not name:
            raise ValueError("Enter both the employee ID and name.")
        daily_pay = float(daily_pay)
        if not math.isfinite(daily_pay) or daily_pay < 0:
            raise ValueError("Daily pay must be a finite, non-negative number.")
        with self.connect() as connection:
            existing = connection.execute("SELECT active FROM employees WHERE user_id=?", (user_id,)).fetchone()
            if existing and existing[0]:
                raise ValueError(f"Employee ID {user_id} already exists.")
            connection.execute(
                "INSERT INTO employees(user_id, name, daily_pay) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, daily_pay=excluded.daily_pay, active=1",
                (user_id, name, daily_pay),
            )

    def remove_employee(self, user_id):
        # Punches are kept so re-adding the ID restores its history; fetches do not re-activate it.
        with self.connect() as connection:
            connection.execute("UPDATE employees SET active=0 WHERE user_id=?", (str(user_id),))

    def set_pay(self, user_id, amount):
        amount = float(amount)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Daily pay must be a finite, non-negative number.")
        with self.connect() as connection:
            connection.execute("UPDATE employees SET daily_pay=? WHERE user_id=?", (amount, user_id))

    def setting(self, key, default=""):
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))


def daily_summary(rows):
    # The device reports every scan as the same punch mode, so the earliest scan of a day is the
    # clock-in and the latest is the clock-out, whatever the punch mode says.
    grouped = defaultdict(set)
    for row in rows:
        timestamp = datetime.fromisoformat(row["timestamp"])
        grouped[(str(row["user_id"]), timestamp.date())].add(timestamp)
    result = {}
    for key, scans in grouped.items():
        clock_in, clock_out = min(scans), max(scans)
        complete = clock_out - clock_in >= MIN_SHIFT
        result[key] = {
            "clock_in": clock_in, "clock_out": clock_out if complete else None,
            "hours": (clock_out - clock_in).total_seconds() / 3600 if complete else 0.0,
            "complete": complete, "issues": "OK" if complete else "Missing clock-out",
        }
    return result


def monthly_summary(employees, daily, month, today=None):
    today = today or date.today()
    result = []
    for user_id, employee in sorted(employees.items(), key=lambda item: (item[1]["name"].casefold(), item[0])):
        entries = [entry for (employee_id, day), entry in daily.items()
                   if employee_id == user_id and day.strftime("%Y-%m") == month and day <= today]
        completed = [entry for entry in entries if entry["complete"]]
        paid_hours = sum(entry["hours"] for entry in completed)
        net_hours = paid_hours - len(completed) * STANDARD_HOURS
        day_equivalent = net_hours / STANDARD_HOURS
        extra_days = max(0.0, day_equivalent)
        rate = Decimal(str(employee["daily_pay"]))
        salary = rate * (Decimal(len(completed)) + Decimal(str(day_equivalent)) *
                         (2 if day_equivalent > 0 else 1))
        result.append({
            "user_id": user_id, "name": employee["name"], "days": len(completed),
            "hours": sum(entry["hours"] for entry in entries), "net_hours": net_hours,
            "extra_days": extra_days,
            "salary": float(max(Decimal(0), salary).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "daily_pay": float(rate), "review_days": len(entries) - len(completed),
        })
    return result


def month_days(month):
    year, month_number = map(int, month.split("-"))
    return [date(year, month_number, day) for day in range(1, calendar.monthrange(year, month_number)[1] + 1)]