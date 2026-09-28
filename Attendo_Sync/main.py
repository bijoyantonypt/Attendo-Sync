""" AttendanceTracker — main GUI entry point.
On launch: shows Device IP field, auto-fetches attendance data, updates both
databases, computes payroll, and displays the dashboard.
"""

import os
import sys
import json
import threading
import sqlite3
from datetime import datetime  # NEW — timestamped report filenames
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import attendance_engine
import db_manager
import payroll_manager
import charts


def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    default = {
        "device_ip": "192.168.29.201",
        "drive_sync_folder": "",
        "default_hourly_rate": 100.0,
        "standard_workday_hours": 9,
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            default.update(json.load(f))
    return default


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ─────────────────────── Excel export helpers ───────────────────────

def _style_header(ws, ncols):
    fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    font = Font(color="FFFFFF", bold=True)
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")


def _autofit_columns(ws):
    for col in ws.columns:
        max_len = max(
            (len(str(c.value)) if c.value is not None else 0) for c in col
        )
        ws.column_dimensions[col[0].column_letter].width = max_len + 4


def export_attendance_to_excel(attendance_db_path, output_path, standard_workday_hours=9):
    """
    Reads daily_attendance from SQLite and writes a styled 3-sheet Excel file:
      Sheet 1 – Daily Attendance
      Sheet 2 – Monthly Summary
      Sheet 3 – Raw Punches (date + clock_in + clock_out per row as stored)
    """
    if not os.path.exists(attendance_db_path):
        raise FileNotFoundError("attendance.db not found. Fetch data first.")

    conn = sqlite3.connect(attendance_db_path)
    try:
        import pandas as pd
        daily_df = pd.read_sql(
            "SELECT * FROM daily_attendance ORDER BY name, date", conn
        )
        monthly_df = pd.read_sql(
            "SELECT * FROM monthly_summary ORDER BY name, year_month", conn
        )
    finally:
        conn.close()

    wb = Workbook()
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    # ── Sheet 1: Daily Attendance ──
    ws1 = wb.active
    ws1.title = "Daily Attendance"
    headers1 = [
        "S.No", "Name", "Date", "Clock-In", "Clock-Out",
        "Total Hours", "Excess Hours", "Deficit Hours", "Flags",
    ]
    ws1.append(headers1)

    for idx, row in enumerate(daily_df.itertuples(index=False), start=1):
        data_row = [
            idx,
            row.name,
            row.date,
            row.clock_in if row.clock_in else "Missing",
            row.clock_out if row.clock_out else "Missing",
            row.total_hours if row.total_hours is not None else "N/A",
            row.excess_hours if row.excess_hours else 0,
            row.deficit_hours if row.deficit_hours else 0,
            row.flags if row.flags else "",
        ]
        ws1.append(data_row)
        if row.flags:  # red highlight for flagged rows
            for cell in ws1[ws1.max_row]:
                cell.fill = red_fill

    _style_header(ws1, len(headers1))
    _autofit_columns(ws1)
    ws1.freeze_panes = "A2"

    # ── Sheet 2: Monthly Summary ──
    ws2 = wb.create_sheet("Monthly Summary")
    headers2 = [
        "S.No", "Name", "Month", "Days Present", "Total Hours",
        "Excess Hours", "Deficit Hours",
        f"Equivalent Full Days ({standard_workday_hours}h)", "Flagged Days",
    ]
    ws2.append(headers2)

    for idx, row in enumerate(monthly_df.itertuples(index=False), start=1):
        ws2.append([
            idx, row.name, row.year_month, row.days_present, row.total_hours,
            row.excess_hours, row.deficit_hours, row.equivalent_full_days,
            row.flagged_days,
        ])

    _style_header(ws2, len(headers2))
    _autofit_columns(ws2)
    ws2.freeze_panes = "A2"

    # ── Sheet 3: Raw Punches ──
    ws3 = wb.create_sheet("Raw Punches")
    headers3 = ["S.No", "Name", "Date", "Clock-In", "Clock-Out", "Flags"]
    ws3.append(headers3)

    for idx, row in enumerate(daily_df.itertuples(index=False), start=1):
        ws3.append([
            idx, row.name, row.date,
            row.clock_in if row.clock_in else "—",
            row.clock_out if row.clock_out else "—",
            row.flags if row.flags else "",
        ])

    _style_header(ws3, len(headers3))
    _autofit_columns(ws3)
    ws3.freeze_panes = "A2"

    wb.save(output_path)


# ───────────────────── NEW: Payroll report generator ─────────────────────

def export_payroll_report(payroll_db_path, output_path):
    """
    Reads payroll.db (daily_pay + employee_rates) and writes a styled
    3-sheet Excel payroll report:
      Sheet 1 – Month-wise Payroll   (per employee per month, with grand total)
      Sheet 2 – Monthly Totals       (TOTAL amount for each month)
      Sheet 3 – Employee Details     (name + hourly rate)
    """
    if not os.path.exists(payroll_db_path):
        raise FileNotFoundError("payroll.db not found. Fetch & compute data first.")

    import pandas as pd
    from collections import OrderedDict

    conn = sqlite3.connect(payroll_db_path)
    try:
        daily_pay = pd.read_sql("SELECT * FROM daily_pay", conn)
        rates = pd.read_sql("SELECT * FROM employee_rates ORDER BY name", conn)
    finally:
        conn.close()

    if daily_pay.empty:
        return False  # signal to caller: nothing to export

    daily_pay["year_month"] = daily_pay["date"].astype(str).str[:7]
    monthly = (
        daily_pay.groupby(["name", "year_month"])
        .agg(
            days_paid=("date", "count"),
            total_hours=("total_hours", "sum"),
            total_pay=("daily_pay", "sum"),
        )
        .reset_index()
        .sort_values(["year_month", "name"])
    )

    # Monthly totals across all employees
    totals = OrderedDict()
    for _, r in monthly.iterrows():
        ym = r["year_month"]
        d, h, p = totals.get(ym, (0, 0.0, 0.0))
        totals[ym] = (
            d + r["days_paid"],
            round(h + r["total_hours"], 2),
            round(p + r["total_pay"], 2),
        )

    green_fill = PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid")
    wb = Workbook()

    # ── Sheet 1: Month-wise Payroll ──
    ws1 = wb.active
    ws1.title = "Month-wise Payroll"
    headers1 = ["S.No", "Month", "Name", "Days Paid", "Total Hours", "Total Amount (₹)"]
    ws1.append(headers1)

    grand_total = 0.0
    for idx, (_, r) in enumerate(monthly.iterrows(), start=1):
        ws1.append([
            idx, r["year_month"], r["name"],
            r["days_paid"], round(r["total_hours"], 2), round(r["total_pay"], 2),
        ])
        grand_total += r["total_pay"]

    # Grand total row
    total_row = ws1.max_row + 1
    ws1.cell(row=total_row, column=3, value="GRAND TOTAL").font = Font(bold=True)
    ws1.cell(row=total_row, column=6, value=round(grand_total, 2)).font = Font(bold=True)
    for c in range(1, 7):
        ws1.cell(row=total_row, column=c).fill = green_fill

    _style_header(ws1, len(headers1))
    _autofit_columns(ws1)
    ws1.freeze_panes = "A2"
    for cell in ws1["F"][1:]:
        cell.number_format = "#,##0.00"

    # ── Sheet 2: Monthly Totals ──
    ws2 = wb.create_sheet("Monthly Totals")
    headers2 = ["S.No", "Month", "Total Days Paid", "Total Hours", "Total Amount (₹)"]
    ws2.append(headers2)
    for i, (ym, (d, h, p)) in enumerate(totals.items(), start=1):
        ws2.append([i, ym, d, h, p])
    _style_header(ws2, len(headers2))
    _autofit_columns(ws2)
    ws2.freeze_panes = "A2"
    for cell in ws2["E"][1:]:
        cell.number_format = "#,##0.00"

    # ── Sheet 3: Employee Details ──
    ws3 = wb.create_sheet("Employee Details")
    headers3 = ["S.No", "Name", "Hourly Rate (₹)"]
    ws3.append(headers3)
    if not rates.empty:
        for idx, r in enumerate(rates.itertuples(index=False), start=1):
            ws3.append([idx, r.name, r.hourly_rate])
    _style_header(ws3, len(headers3))
    _autofit_columns(ws3)
    ws3.freeze_panes = "A2"
    for cell in ws3["C"][1:]:
        cell.number_format = "#,##0.00"

    wb.save(output_path)
    return True


# ────────────────────────────────────────────────────────────────────────────


class AttendanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Attendance Tracker & Payroll Dashboard")
        self.root.geometry("1100x750")
        self.cfg = load_config()
        self.attendance_db = db_manager.get_db_path(BASE_DIR)
        self.payroll_db = payroll_manager.get_db_path(BASE_DIR)
        self.status_var = tk.StringVar(value="Ready.")

        self._build_top_bar()
        self._build_tabs()
        self._build_status_bar()
        self.root.after(500, self.fetch_and_refresh)

    # ---------------- Top control bar ----------------
    def _build_top_bar(self):
        bar = ttk.Frame(self.root, padding=10)
        bar.pack(fill="x")

        ttk.Label(bar, text="Device IP:").pack(side="left")
        self.ip_var = tk.StringVar(value=self.cfg.get("device_ip", "192.168.29.201"))
        ttk.Entry(bar, textvariable=self.ip_var, width=16).pack(side="left", padx=5)
        ttk.Button(bar, text="Fetch Latest & Update", command=self.fetch_and_refresh).pack(side="left", padx=5)

        ttk.Label(bar, text=" Google Drive Folder:").pack(side="left")
        self.drive_var = tk.StringVar(value=self.cfg.get("drive_sync_folder", ""))
        ttk.Entry(bar, textvariable=self.drive_var, width=35).pack(side="left", padx=5)
        ttk.Button(bar, text="Browse...", command=self.browse_drive_folder).pack(side="left")

        # ── NEW: Payroll report button ──
        ttk.Button(bar, text="Export Payroll Report", command=self.on_export_payroll_report).pack(side="left", padx=5)

        # ── NEW: Attendance report button ──
        ttk.Button(bar, text="Export Attendance", command=self.on_export_attendance).pack(side="left", padx=5)

    # ---------------- Status bar ----------------
    def _build_status_bar(self):
        self.status_var = tk.StringVar(value="Ready.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w", padding=4)
        status_bar.pack(side="bottom", fill="x")

    # ---------------- NEW: Export handlers ----------------
    def on_export_payroll_report(self):
        """Generate the monthly payroll Excel report on button click."""
        try:
            out_dir = os.path.join(BASE_DIR, "reports")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            out_path = os.path.join(out_dir, f"payroll_report_{ts}.xlsx")

            self.status_var.set("Generating payroll report...")
            ok = export_payroll_report(self.payroll_db, out_path)

            if ok:
                self.status_var.set(f"Payroll report saved: {out_path}")
                messagebox.showinfo("Payroll Report", f"Report saved to:\n{out_path}")
            else:
                self.status_var.set("No payroll records found.")
                messagebox.showwarning("Payroll Report", "No payroll records found. Fetch data first.")
        except Exception as e:
            self.status_var.set("Export failed.")
            messagebox.showerror("Export Failed", str(e))

    def on_export_attendance(self):
        """Generate the attendance Excel report on button click."""
        try:
            out_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                initialfile="attendance_report.xlsx",
            )
            if not out_path:
                return
            self.status_var.set("Generating attendance report...")
            export_attendance_to_excel(
                self.attendance_db, out_path,
                self.cfg.get("standard_workday_hours", 9),
            )
            self.status_var.set(f"Attendance report saved: {out_path}")
            messagebox.showinfo("Attendance Report", f"Report saved to:\n{out_path}")
        except Exception as e:
            self.status_var.set("Export failed.")
            messagebox.showerror("Export Failed", str(e))

    # ---------------- Placeholder wired to your existing logic ----------------
    def _build_tabs(self):
        """Build tabs. Extend with your existing notebook setup here."""
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        # NOTE: keep your existing tab widgets. This stub keeps the app runnable.
        self.tab1 = ttk.Frame(notebook)
        notebook.add(self.tab1, text="Dashboard")
        ttk.Label(self.tab1, text="Attendance & Payroll Dashboard").pack(pady=20)

    def browse_drive_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.drive_var.set(folder)
            self.cfg["drive_sync_folder"] = folder
            save_config(self.cfg)

    def fetch_and_refresh(self):
        """
        Placeholder — wire this to your existing fetch pipeline:
        attendance_engine → compute_and_store_daily_pay → refresh charts.
        """
        self.status_var.set("Ready.")


def main():
    root = tk.Tk()
    app = AttendanceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
