"""
payroll_report.py — Generates a monthly payroll Excel report from payroll.db.

Reads the payroll database (employee_rates + daily_pay), rolls up each
employee's pay by month, and writes a styled multi-sheet Excel workbook:

  Sheet 1  Month-wise Payroll (Total Amount)  -> total per employee per month (₹)
  Sheet 2  Monthly Totals                     -> overall total amount per month (₹)
  Sheet 3  Employee Details                   -> name + hourly rate + days & pay

No device connection is required — it uses payroll.db already on disk.
"""

import os
import sqlite3
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


DB_NAME = "payroll.db"
OUTPUT_DIR = "reports"


def get_db_path(base_dir=None):
    """Resolve payroll.db location (works both in dev and frozen .exe)."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    # In a PyInstaller build, the db sits next to the executable.
    return os.path.join(base_dir, DB_NAME)


# ---------------------------------------------------------------- styling ---
def style_header(ws, ncols):
    fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    font = Font(color="FFFFFF", bold=True)
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")


def autofit_columns(ws):
    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4


def money_fmt(value):
    """Format a numeric amount as an Indian-style currency string."""
    return f"{value:,.2f}"


# ------------------------------------------------------------- data access ---
def load_payroll_tables(db_path):
    """Return (daily_pay rows, monthly_payroll rows, employee_rates rows)."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"{db_path} not found. Run the main app once to fetch & compute payroll first."
        )

    conn = sqlite3.connect(db_path)
    try:
        daily = conn.execute(
            "SELECT * FROM daily_pay ORDER BY name, date"
        ).fetchall()

        # Monthly roll-up: group pay by employee + month.
        monthly = conn.execute(
            """
            SELECT name,
                   substr(date, 1, 7) AS year_month,
                   COUNT(*)            AS days_paid,
                   ROUND(SUM(total_hours), 2) AS total_hours,
                   ROUND(SUM(daily_pay),   2) AS total_pay
            FROM daily_pay
            GROUP BY name, substr(date, 1, 7)
            ORDER BY substr(date, 1, 7), name
            """
        ).fetchall()

        rates = conn.execute(
            "SELECT * FROM employee_rates ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return daily, monthly, rates


# ---------------------------------------------------------------- builders ---
def build_monthwise_payroll(monthly_rows):
    """Sheet 1: one row per employee per month, with running total per month."""
    return [["S.No", "Month", "Name", "Days Paid", "Total Hours", "Total Amount (₹)"]]


def build_monthly_totals(monthly_rows):
    """
    Sheet 2: overall total amount per month.

    monthly_rows rows are (name, year_month, days_paid, total_hours, total_pay).
    """
    from collections import OrderedDict

    totals = OrderedDict()  # year_month -> (days_paid_sum, hours_sum, pay_sum)
    for _, ym, days, hours, pay in monthly_rows:
        d, h, p = totals.get(ym, (0, 0.0, 0.0))
        totals[ym] = (d + days, round(h + hours, 2), round(p + pay, 2))

    rows = [["S.No", "Month", "Total Days Paid", "Total Hours", "Total Amount (₹)"]]
    for i, (ym, (d, h, p)) in enumerate(totals.items(), start=1):
        rows.append([i, ym, d, h, money_fmt(p)])
    return rows


def build_employee_details(rates_rows):
    """Sheet 3: employee name + hourly rate."""
    rows = [["S.No", "Name", "Hourly Rate (₹)"]]
    for i, (name, rate) in enumerate(rates_rows, start=1):
        rows.append([i, name, money_fmt(rate)])
    return rows


# ----------------------------------------------------------------- export ---
def export_payroll_report(db_path, output_dir=OUTPUT_DIR):
    daily, monthly, rates = load_payroll_tables(db_path)

    if not monthly and not daily:
        print("No payroll records found in the database. Nothing to export.")
        return None

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(output_dir, f"payroll_report_{ts}.xlsx")

    wb = Workbook()

    # ---- Sheet 1: Month-wise Payroll (detail) ----
    ws1 = wb.active
    ws1.title = "Month-wise Payroll"
    ws1.append(
        ["S.No", "Month", "Name", "Days Paid", "Total Hours", "Total Amount (₹)"]
    )
    grand = 0.0
    for idx, (name, ym, days, hours, pay) in enumerate(monthly, start=1):
        ws1.append([idx, ym, name, days, hours, money_fmt(pay)])
        grand += pay

    # grand total row
    total_row = ws1.max_row + 1
    ws1.cell(row=total_row, column=1, value="")
    ws1.cell(row=total_row, column=3, value="GRAND TOTAL").font = Font(bold=True)
    ws1.cell(row=total_row, column=6, value=money_fmt(grand)).font = Font(bold=True)
    for c in range(1, 7):
        ws1.cell(row=total_row, column=c).fill = PatternFill(
            start_color="C8E6C9", end_color="C8E6C9", fill_type="solid"
        )

    style_header(ws1, 6)
    autofit_columns(ws1)
    ws1.freeze_panes = "A2"
    # currency format for the amount column
    for cell in ws1["F"][1:]:
        cell.number_format = '#,##0.00'

    # ---- Sheet 2: Monthly Totals ----
    ws2 = wb.create_sheet("Monthly Totals")
    totals_rows = build_monthly_totals(monthly)
    for row in totals_rows:
        ws2.append(row)
    style_header(ws2, len(totals_rows[0]))
    autofit_columns(ws2)
    ws2.freeze_panes = "A2"
    for cell in ws2["E"][1:]:
        cell.number_format = '#,##0.00'

    # ---- Sheet 3: Employee Details ----
    ws3 = wb.create_sheet("Employee Details")
    for row in build_employee_details(rates):
        ws3.append(row)
    style_header(ws3, 3)
    autofit_columns(ws3)
    ws3.freeze_panes = "A2"
    for cell in ws3["C"][1:]:
        cell.number_format = '#,##0.00'

    wb.save(filename)
    return filename


# -------------------------------------------------------------------- main ---
def main():
    db_path = get_db_path()
    try:
        out = export_payroll_report(db_path)
        if out:
            print(f"Payroll report saved to: {out}")
    except FileNotFoundError as e:
        print(e)


if __name__ == "__main__":
    main()
