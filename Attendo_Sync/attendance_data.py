"""Local attendance history and payroll calculations, independent of the UI."""

import calendar
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


STANDARD_HOURS = 8.5
DEFAULT_PAY = 100.0


class AttendanceStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS employees (
                    user_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    daily_pay REAL NOT NULL DEFAULT 100 CHECK(daily_pay >= 0)
                );
                CREATE TABLE IF NOT EXISTS punches (
                    user_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                    status TEXT NOT NULL, punch TEXT NOT NULL,
                    PRIMARY KEY(user_id, timestamp, status, punch)
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

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

    def snapshot(self):
        with self.connect() as connection:
            employees = {
                user_id: {"name": name, "daily_pay": daily_pay}
                for user_id, name, daily_pay in connection.execute(
                    "SELECT user_id, name, daily_pay FROM employees ORDER BY name COLLATE NOCASE, user_id"
                )
            }
            rows = [
                {"user_id": user_id, "user_name": employees[user_id]["name"],
                 "timestamp": timestamp, "status": json.loads(status), "punch": json.loads(punch)}
                for user_id, timestamp, status, punch in connection.execute(
                    "SELECT user_id, timestamp, status, punch FROM punches ORDER BY timestamp, user_id"
                )
            ]
        return employees, rows

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
    grouped = defaultdict(dict)
    for row in rows:
        timestamp = datetime.fromisoformat(row["timestamp"])
        grouped[(str(row["user_id"]), timestamp.date())][(timestamp, row.get("punch"))] = row
    result = {}
    for key, records in grouped.items():
        ordered = sorted(records, key=lambda item: (item[0], str(item[1])))
        pending = None
        first_in = None
        last_out = None
        hours = 0.0
        issues = set()
        pairs = 0
        for timestamp, punch in ordered:
            if punch == 0:
                if pending is None:
                    pending = timestamp
                    first_in = first_in or timestamp
                else:
                    issues.add("Repeated in")
            elif punch == 1:
                if pending is not None and timestamp > pending:
                    hours += (timestamp - pending).total_seconds() / 3600
                    pairs += 1
                    last_out = timestamp
                    pending = None
                else:
                    issues.add("Missing in")
            else:
                issues.add("Unknown punch mode")
        if pending is not None:
            issues.add("Missing out")
        complete = pairs > 0 and not (issues - {"Repeated in"})
        result[key] = {
            "clock_in": first_in, "clock_out": last_out, "hours": hours,
            "complete": complete, "issues": ", ".join(sorted(issues)) or "Complete",
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