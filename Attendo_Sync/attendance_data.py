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
DEFAULT_HOURLY_PAY = 12.0
DEFAULT_ROLE = "Normal"
DRIVER_ROLE = "Driver"
DEFAULT_ROLES = (DRIVER_ROLE, "Cook", "Quality", "Cleaner", DEFAULT_ROLE)
# Extra pay is 2x the hourly rate; deficit hours are deducted at the same 2x rate.
EXTRA_PAY_MULTIPLIER = 2
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
                    hourly_pay REAL NOT NULL DEFAULT 12 CHECK(hourly_pay >= 0),
                    role TEXT NOT NULL DEFAULT 'Normal',
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS punches (
                    user_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                    status TEXT NOT NULL, punch TEXT NOT NULL,
                    PRIMARY KEY(user_id, timestamp, status, punch)
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS roles (
                    name TEXT PRIMARY KEY COLLATE NOCASE, no_extra_pay INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pay_history (
                    user_id TEXT NOT NULL, month TEXT NOT NULL,
                    hourly_pay REAL NOT NULL CHECK(hourly_pay >= 0),
                    PRIMARY KEY(user_id, month)
                );
                CREATE TABLE IF NOT EXISTS manual_times (
                    user_id TEXT NOT NULL, day TEXT NOT NULL, clock_in TEXT, clock_out TEXT,
                    PRIMARY KEY(user_id, day)
                );
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(employees)")}
            if "active" not in columns:
                connection.execute("ALTER TABLE employees ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            if "role" not in columns:
                connection.execute("ALTER TABLE employees ADD COLUMN role TEXT NOT NULL DEFAULT 'Normal'")
            if "hourly_pay" not in columns:
                connection.execute("ALTER TABLE employees ADD COLUMN hourly_pay REAL NOT NULL DEFAULT 12")
                if "daily_pay" in columns:
                    connection.execute("UPDATE employees SET hourly_pay=ROUND(daily_pay / ?, 2)", (STANDARD_HOURS,))
            if "no_extra_pay" not in {row[1] for row in connection.execute("PRAGMA table_info(roles)")}:
                connection.execute("ALTER TABLE roles ADD COLUMN no_extra_pay INTEGER NOT NULL DEFAULT 0")
                connection.execute("UPDATE roles SET no_extra_pay=1 WHERE name=?", (DRIVER_ROLE,))
            if not connection.execute("SELECT 1 FROM settings WHERE key='roles_seeded'").fetchone():
                connection.executemany("INSERT OR IGNORE INTO roles VALUES (?, ?)",
                                       [(role, int(role == DRIVER_ROLE)) for role in DEFAULT_ROLES])
                connection.execute("INSERT INTO settings VALUES ('roles_seeded', 'yes')")
            connection.execute("INSERT OR IGNORE INTO settings VALUES ('default_role', ?)", (DEFAULT_ROLE,))
            connection.execute("INSERT OR IGNORE INTO roles(name) SELECT value FROM settings WHERE key='default_role'")
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
                user_id: {"name": name, "hourly_pay": hourly_pay, "role": role,
                          "no_extra_pay": bool(no_extra_pay), "pay_history": {}}
                for user_id, name, hourly_pay, role, no_extra_pay in connection.execute(
                    "SELECT e.user_id, e.name, e.hourly_pay, e.role, COALESCE(r.no_extra_pay, 0) "
                    "FROM employees e LEFT JOIN roles r ON r.name = e.role WHERE e.active=1 "
                    "ORDER BY e.name COLLATE NOCASE, e.user_id"
                )
            }
            for user_id, month, hourly_pay in connection.execute(
                    "SELECT user_id, month, hourly_pay FROM pay_history ORDER BY month"):
                if user_id in employees:
                    employees[user_id]["pay_history"][month] = hourly_pay
            rows = [
                {"user_id": user_id, "user_name": employees[user_id]["name"],
                 "timestamp": timestamp, "status": json.loads(status), "punch": json.loads(punch)}
                for user_id, timestamp, status, punch in connection.execute(
                    "SELECT user_id, timestamp, status, punch FROM punches WHERE timestamp >= ? "
                    "ORDER BY timestamp, user_id", (FIRST_VALID_DATE.isoformat(),)
                ) if user_id in employees
            ]
        return employees, rows

    def add_employee(self, user_id, name, hourly_pay=DEFAULT_HOURLY_PAY, role=None):
        user_id = str(user_id).strip()
        name = " ".join(str(name).split())
        if not user_id or not name:
            raise ValueError("Enter both the employee ID and name.")
        hourly_pay = self._valid_pay(hourly_pay)
        with self.connect() as connection:
            existing = connection.execute("SELECT active FROM employees WHERE user_id=?", (user_id,)).fetchone()
            if existing and existing[0]:
                raise ValueError(f"Employee ID {user_id} already exists.")
            role = self._canonical_role(connection, role or self._default_role(connection))
            connection.execute(
                "INSERT INTO employees(user_id, name, hourly_pay, role) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, hourly_pay=excluded.hourly_pay, "
                "role=excluded.role, active=1",
                (user_id, name, hourly_pay, role),
            )

    def remove_employee(self, user_id):
        # Punches are kept so re-adding the ID restores its history; fetches do not re-activate it.
        with self.connect() as connection:
            connection.execute("UPDATE employees SET active=0 WHERE user_id=?", (str(user_id),))

    @staticmethod
    def _valid_pay(amount):
        amount = float(amount)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Hourly pay must be a finite, non-negative number.")
        return amount

    @staticmethod
    def _canonical_role(connection, role):
        row = connection.execute("SELECT name FROM roles WHERE name=?", (" ".join(str(role).split()),)).fetchone()
        if not row:
            raise ValueError(f"Role '{role}' does not exist. Add it first.")
        return row[0]

    def set_hourly_pay(self, user_id, amount, month):
        """Set the rate from `month` (YYYY-MM) onward; earlier months keep their rate."""
        amount = self._valid_pay(amount)
        datetime.strptime(month, "%Y-%m")
        with self.connect() as connection:
            connection.execute("DELETE FROM pay_history WHERE user_id=? AND month>?", (str(user_id), month))
            connection.execute("INSERT OR REPLACE INTO pay_history VALUES (?, ?, ?)", (str(user_id), month, amount))

    @staticmethod
    def _default_role(connection):
        return connection.execute("SELECT value FROM settings WHERE key='default_role'").fetchone()[0]

    def roles(self):
        with self.connect() as connection:
            return [row[0] for row in connection.execute("SELECT name FROM roles ORDER BY rowid")]

    def role_details(self):
        """Returns ([(name, no_extra_pay)], default_role)."""
        with self.connect() as connection:
            details = [(name, bool(flag)) for name, flag in
                       connection.execute("SELECT name, no_extra_pay FROM roles ORDER BY rowid")]
            return details, self._default_role(connection)

    def set_role(self, user_id, role):
        with self.connect() as connection:
            role = self._canonical_role(connection, role)
            connection.execute("UPDATE employees SET role=? WHERE user_id=?", (role, str(user_id)))

    def add_role(self, name, no_extra_pay=False):
        name = " ".join(str(name).split())
        if not name:
            raise ValueError("Enter a role name.")
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM roles WHERE name=?", (name,)).fetchone():
                raise ValueError(f"Role '{name}' already exists.")
            connection.execute("INSERT INTO roles VALUES (?, ?)", (name, int(no_extra_pay)))

    def rename_role(self, old, new):
        new = " ".join(str(new).split())
        if not new:
            raise ValueError("Enter a role name.")
        with self.connect() as connection:
            old = self._canonical_role(connection, old)
            if connection.execute("SELECT 1 FROM roles WHERE name=? AND name<>?", (new, old)).fetchone():
                raise ValueError(f"Role '{new}' already exists.")
            connection.execute("UPDATE roles SET name=? WHERE name=?", (new, old))
            connection.execute("UPDATE employees SET role=? WHERE role=?", (new, old))
            connection.execute("UPDATE settings SET value=? WHERE key='default_role' AND value=?", (new, old))

    def set_role_no_extra_pay(self, name, no_extra_pay):
        with self.connect() as connection:
            name = self._canonical_role(connection, name)
            connection.execute("UPDATE roles SET no_extra_pay=? WHERE name=?", (int(no_extra_pay), name))

    def delete_role(self, name):
        with self.connect() as connection:
            name = self._canonical_role(connection, name)
            default = self._default_role(connection)
            if name == default:
                raise ValueError(f"{name} is the default role for new employees and cannot be deleted.")
            connection.execute("UPDATE employees SET role=? WHERE role=?", (default, name))
            connection.execute("DELETE FROM roles WHERE name=?", (name,))

    def set_manual_times(self, user_id, day, clock_in, clock_out):
        """Store hand-entered clock times for a day; None means use the device scan."""
        for value in (clock_in, clock_out):
            if value is not None and value.date() != day:
                raise ValueError("Clock times must fall on the selected date.")
        if clock_in and clock_out and clock_out <= clock_in:
            raise ValueError("Clock-out must be after clock-in.")
        with self.connect() as connection:
            if clock_in is None and clock_out is None:
                connection.execute("DELETE FROM manual_times WHERE user_id=? AND day=?", (str(user_id), day.isoformat()))
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO manual_times VALUES (?, ?, ?, ?)",
                    (str(user_id), day.isoformat(), clock_in.isoformat() if clock_in else None,
                     clock_out.isoformat() if clock_out else None))

    def manual_times(self):
        with self.connect() as connection:
            records = connection.execute(
                "SELECT m.user_id, m.day, m.clock_in, m.clock_out FROM manual_times m "
                "JOIN employees e ON e.user_id=m.user_id WHERE e.active=1 AND m.day >= ?",
                (FIRST_VALID_DATE.isoformat(),)).fetchall()
        return {(user_id, date.fromisoformat(day)): {
                    "clock_in": datetime.fromisoformat(clock_in) if clock_in else None,
                    "clock_out": datetime.fromisoformat(clock_out) if clock_out else None}
                for user_id, day, clock_in, clock_out in records}

    def setting(self, key, default=""):
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))


def format_duration(hours, signed=False):
    minutes = round(abs(hours) * 60)
    whole_hours, rest = divmod(minutes, 60)
    parts = []
    if whole_hours:
        parts.append(f"{whole_hours} hour{'s' if whole_hours != 1 else ''}")
    if rest or not parts:
        parts.append(f"{rest} minute{'s' if rest != 1 else ''}")
    text = " ".join(parts)
    return ("+" if hours > 0 else "-") + text if signed and minutes else text


def format_date(day):
    return day.strftime("%d-%m-%Y")


def format_datetime(timestamp):
    return timestamp.strftime("%d-%m-%Y %H:%M:%S")


def month_display(month):
    return datetime.strptime(month, "%Y-%m").strftime("%m-%Y")


def month_key(display):
    return datetime.strptime(display, "%m-%Y").strftime("%Y-%m")


def daily_summary(rows, manual=None):
    # The device reports every scan as the same punch mode, so the earliest scan of a day is the
    # clock-in and the latest is the clock-out, whatever the punch mode says.
    manual = manual or {}
    grouped = defaultdict(set)
    for row in rows:
        timestamp = datetime.fromisoformat(row["timestamp"])
        grouped[(str(row["user_id"]), timestamp.date())].add(timestamp)
    result = {}
    for key in grouped.keys() | manual.keys():
        scans = grouped.get(key, set())
        override = manual.get(key, {})
        clock_in = override.get("clock_in") or (min(scans) if scans else None)
        clock_out = override.get("clock_out")
        if clock_out is None and scans and clock_in and max(scans) - clock_in >= MIN_SHIFT:
            clock_out = max(scans)
        complete = bool(clock_in and clock_out and clock_out > clock_in)
        edited = bool(override.get("clock_in") or override.get("clock_out"))
        result[key] = {
            "clock_in": clock_in, "clock_out": clock_out if complete or override.get("clock_out") else None,
            "hours": (clock_out - clock_in).total_seconds() / 3600 if complete else 0.0,
            "complete": complete, "edited": edited,
            "issues": ("OK (manual)" if edited else "OK") if complete
                      else "Missing clock-in" if not clock_in else "Missing clock-out",
        }
    return result


def hourly_rate(employee, month):
    rate = employee["hourly_pay"]
    for effective, amount in sorted(employee.get("pay_history", {}).items()):
        if effective <= month:
            rate = amount
    return rate


def monthly_summary(employees, daily, month, today=None):
    today = today or date.today()
    remaining_days = sum(1 for day in month_days(month) if day > today)
    result = []
    for user_id, employee in sorted(employees.items(), key=lambda item: (item[1]["name"].casefold(), item[0])):
        entries = [entry for (employee_id, day), entry in daily.items()
                   if employee_id == user_id and day.strftime("%Y-%m") == month and day <= today]
        completed = [entry for entry in entries if entry["complete"]]
        net_hours = sum(entry["hours"] for entry in completed) - len(completed) * STANDARD_HOURS
        no_extra_pay = employee.get("no_extra_pay", False)
        rate = Decimal(str(hourly_rate(employee, month)))
        # Net hours (excess minus deficit) are paid at the extra-pay multiplier; such roles only lose pay on a deficit.
        paid_net_hours = min(0.0, net_hours) if no_extra_pay else net_hours
        extra_pay = rate * Decimal(str(paid_net_hours)) * EXTRA_PAY_MULTIPLIER
        salary = rate * Decimal(str(len(completed) * STANDARD_HOURS)) + extra_pay
        result.append({
            "user_id": user_id, "name": employee["name"], "role": employee.get("role", DEFAULT_ROLE),
            "no_extra_pay": no_extra_pay, "days": len(completed),
            "hours": sum(entry["hours"] for entry in entries), "net_hours": net_hours,
            "extra_pay": float(extra_pay.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "salary": float(max(Decimal(0), salary).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "hourly_pay": float(rate), "remaining_days": remaining_days,
        })
    return result


def month_days(month):
    year, month_number = map(int, month.split("-"))
    return [date(year, month_number, day) for day in range(1, calendar.monthrange(year, month_number)[1] + 1)]