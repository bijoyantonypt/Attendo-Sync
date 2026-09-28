""" Manages payroll.db — a SEPARATE database from attendance.db.
Stores per-employee hourly rates and per-day computed pay, then rolls it
up into monthly payroll totals. Exposes helpers to power the monthly
payroll Excel report as well as the dashboard. """

import os
import sqlite3
import pandas as pd

DB_NAME = "payroll.db"


def get_db_path(base_dir):
    return os.path.join(base_dir, DB_NAME)


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employee_rates (
            name TEXT PRIMARY KEY,
            hourly_rate REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_pay (
            name TEXT,
            date TEXT,
            total_hours REAL,
            hourly_rate REAL,
            daily_pay REAL,
            PRIMARY KEY (name, date)
        )
    """)
    conn.commit()


def get_rate(conn, name, default_rate):
    cur = conn.execute("SELECT hourly_rate FROM employee_rates WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO employee_rates (name, hourly_rate) VALUES (?, ?)",
        (name, default_rate),
    )
    conn.commit()
    return default_rate


def update_rate(conn, name, new_rate):
    conn.execute(
        """
        INSERT INTO employee_rates (name, hourly_rate) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET hourly_rate=excluded.hourly_rate
        """,
        (name, new_rate),
    )
    conn.commit()


def compute_and_store_daily_pay(payroll_db_path, daily_attendance_df, default_rate=100.0):
    conn = sqlite3.connect(payroll_db_path)
    try:
        init_db(conn)
        for _, row in daily_attendance_df.iterrows():
            name = row["name"]
            hours = row["total_hours"] or 0
            rate = get_rate(conn, name, default_rate)
            pay = round(hours * rate, 2)
            conn.execute(
                """
                INSERT INTO daily_pay (name, date, total_hours, hourly_rate, daily_pay)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name, date) DO UPDATE SET
                    total_hours=excluded.total_hours,
                    hourly_rate=excluded.hourly_rate,
                    daily_pay=excluded.daily_pay
                """,
                (name, row["date"], hours, rate, pay),
            )
        conn.commit()
    finally:
        conn.close()


def load_payroll_data(payroll_db_path):
    if not os.path.exists(payroll_db_path):
        return pd.DataFrame(), pd.DataFrame()
    conn = sqlite3.connect(payroll_db_path)
    daily_pay = pd.read_sql("SELECT * FROM daily_pay", conn)
    rates = pd.read_sql("SELECT * FROM employee_rates", conn)
    conn.close()
    if daily_pay.empty:
        return daily_pay, pd.DataFrame()

    daily_pay["year_month"] = daily_pay["date"].str[:7]
    monthly_payroll = (
        daily_pay.groupby(["name", "year_month"])
        .agg(
            days_paid=("date", "count"),
            total_hours=("total_hours", "sum"),
            total_pay=("daily_pay", "sum"),
        )
        .reset_index()
    )
    monthly_payroll["total_hours"] = monthly_payroll["total_hours"].round(2)
    monthly_payroll["total_pay"] = monthly_payroll["total_pay"].round(2)
    return daily_pay, monthly_payroll


def load_monthly_payroll_totals(payroll_db_path):
    """
    Return one row per month with the TOTAL amount across all employees.
    Useful for the "payroll by month" summary view and the Excel report.

    Columns: year_month, total_days_paid, total_hours, total_amount
    """
    daily_pay, _ = load_payroll_data(payroll_db_path)
    if daily_pay.empty:
        return pd.DataFrame(
            columns=["year_month", "total_days_paid", "total_hours", "total_amount"]
        )
    totals = (
        daily_pay.groupby("year_month")
        .agg(
            total_days_paid=("date", "count"),
            total_hours=("total_hours", "sum"),
            total_amount=("daily_pay", "sum"),
        )
        .reset_index()
    )
    totals["total_hours"] = totals["total_hours"].round(2)
    totals["total_amount"] = totals["total_amount"].round(2)
    return totals
