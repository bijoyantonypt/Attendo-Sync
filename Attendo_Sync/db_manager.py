"""
Manages attendance.db (SQLite) — keeps full history across every run,
and copies the file into your local Google Drive sync folder.
"""

import os
import shutil
import sqlite3
import pandas as pd

DB_NAME = "attendance.db"


def get_db_path(base_dir):
    return os.path.join(base_dir, DB_NAME)


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_attendance (
            name TEXT, date TEXT, clock_in TEXT, clock_out TEXT,
            total_hours REAL, excess_hours REAL, deficit_hours REAL,
            flags TEXT, PRIMARY KEY (name, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_summary (
            name TEXT, year_month TEXT, days_present INTEGER,
            total_hours REAL, excess_hours REAL, deficit_hours REAL,
            equivalent_full_days REAL, flagged_days INTEGER,
            PRIMARY KEY (name, year_month)
        )
    """)
    conn.commit()


def upsert_daily_records(conn, records):
    cur = conn.cursor()
    for r in records:
        cur.execute("""
            INSERT INTO daily_attendance
                (name, date, clock_in, clock_out, total_hours, excess_hours, deficit_hours, flags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, date) DO UPDATE SET
                clock_in=excluded.clock_in, clock_out=excluded.clock_out,
                total_hours=excluded.total_hours, excess_hours=excluded.excess_hours,
                deficit_hours=excluded.deficit_hours, flags=excluded.flags
        """, (r["name"], r["date"], r["clock_in"], r["clock_out"],
              r["total_hours"], r["excess_hours"], r["deficit_hours"], r["flags"]))
    conn.commit()


def recompute_monthly_summary(conn):
    conn.execute("DELETE FROM monthly_summary")
    conn.execute("""
        INSERT INTO monthly_summary
        SELECT name, strftime('%Y-%m', date), COUNT(*),
               ROUND(SUM(COALESCE(total_hours,0)),2),
               ROUND(SUM(COALESCE(excess_hours,0)),2),
               ROUND(SUM(COALESCE(deficit_hours,0)),2),
               ROUND(SUM(COALESCE(total_hours,0))/9.0,2),
               SUM(CASE WHEN flags != '' THEN 1 ELSE 0 END)
        FROM daily_attendance GROUP BY name, strftime('%Y-%m', date)
    """)
    conn.commit()


def update_attendance_db(db_path, records):
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        upsert_daily_records(conn, records)
        recompute_monthly_summary(conn)
    finally:
        conn.close()


def load_dataframes(db_path):
    if not os.path.exists(db_path):
        return pd.DataFrame(), pd.DataFrame()
    conn = sqlite3.connect(db_path)
    daily = pd.read_sql("SELECT * FROM daily_attendance", conn)
    monthly = pd.read_sql("SELECT * FROM monthly_summary", conn)
    conn.close()
    return daily, monthly


def sync_file_to_drive(local_path, drive_folder):
    """Copies a local file into the local Google Drive sync folder."""
    if not drive_folder or not os.path.isdir(drive_folder):
        return False, "Google Drive sync folder not set or not found."
    try:
        dest = os.path.join(drive_folder, os.path.basename(local_path))
        shutil.copy2(local_path, dest)
        return True, f"Synced to: {dest}"
    except Exception as e:
        return False, str(e)
