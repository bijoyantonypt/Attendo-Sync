"""Desktop attendance dashboard."""

import queue
import threading
from collections import Counter
from datetime import date, datetime
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk
from ttkbootstrap import Style

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from PIL import Image, ImageTk

from attendance_data import (DEFAULT_HOURLY_PAY, STANDARD_HOURS, daily_summary, format_date, format_duration,
                             hourly_rate, month_display, month_key, monthly_summary)


BG = "#F3F5F7"
INK = "#202A30"
MUTED = "#65747D"
TEAL = "#167B91"
GREEN = "#23815C"
ALL_DATES = "Till date"


class AttendoSyncApp:
    def __init__(self, root, store, fetch_attendance, upload, defaults, demo=False, logo_path=None):
        self.root = root
        self.store = store
        self.fetch_attendance = fetch_attendance
        self.upload = upload
        self.defaults = defaults
        self.demo = demo
        self.logo_path = logo_path
        self.busy = False
        self.events = queue.Queue()
        current_month = month_display(date.today().strftime("%Y-%m"))
        self.month = tk.StringVar(value=current_month)
        self.kpi_month = tk.StringVar(value=current_month)
        self.daily_date = tk.StringVar()
        self.chart_period = tk.StringVar(value=current_month)
        self.ip = tk.StringVar(value=store.setting("device_ip", defaults["device_ip"]))
        self.status = tk.StringVar(value="Local history ready" if not demo else "Demo data | Separate local database")
        self.last_fetch = tk.StringVar()
        self.root.title("Attendo-Sync | Attendance & Payroll" + (" | DEMO" if demo else ""))
        self.root.geometry("1280x860")
        self.root.minsize(1000, 700)
        self.root.configure(background=BG)
        self._styles()
        self._header()
        self._footer()
        self._tabs()
        self.refresh()
        self.poll_id = self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _styles(self):
        style = Style()
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Surface.TFrame", background="white")
        style.configure("Surface.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=INK)
        style.configure("Metric.TLabel", background="white", font=("Segoe UI", 24, "bold"), foreground=INK)
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 9))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(24, 12), font=("Segoe UI", 11, "bold"))
        style.configure("Treeview", rowheight=40, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=(8, 12))
        style.map("Treeview", background=[("selected", "#D9EEF0")], foreground=[("selected", INK)])

    def _header(self):
        header = ttk.Frame(self.root, style="Surface.TFrame", padding=(24, 10))
        header.pack(fill="x")
        if self.logo_path:
            try:
                with Image.open(self.logo_path) as source:
                    source.thumbnail((48, 48), Image.Resampling.LANCZOS)
                    self.logo = ImageTk.PhotoImage(source.copy(), master=self.root)
                ttk.Label(header, image=self.logo, background="white").pack(side="left", padx=(0, 14))
            except OSError:
                pass
        ttk.Label(header, text="Attendo-Sync", font=("Segoe UI", 22, "bold"),
                  foreground=TEAL, background="white").pack(side="left")
        ttk.Label(header, text="ATTENDANCE / PAYROLL", style="Surface.TLabel").pack(side="left", padx=24)
        ttk.Label(header, text="DEMO" if self.demo else "LOCAL WORKSPACE", foreground=GREEN,
                  background="white", font=("Segoe UI", 10, "bold")).pack(side="right")
        toolbar = ttk.Frame(self.root, style="Surface.TFrame")
        toolbar.pack(fill="x", padx=24, pady=(0, 12))
        device_field = ttk.Frame(toolbar, style="Surface.TFrame")
        ttk.Label(device_field, text="Device IP", style="Surface.TLabel").pack(side="left", padx=(0, 8))
        self.ip_entry = ttk.Entry(device_field, textvariable=self.ip, width=17)
        self.ip_entry.pack(side="left", ipady=5)
        self.fetch_btn = ttk.Button(toolbar, text="Fetch & Update", style="primary.TButton", command=self.start)
        self.send_btn = ttk.Button(toolbar, text="Fetch & Send", style="outline-primary.TButton",
                                   command=lambda: self.start(send=True))
        self.export_btn = ttk.Button(toolbar, text="Excel Export", style="outline-secondary.TButton", command=self.export)
        self.settings_btn = ttk.Button(toolbar, text="Settings", style="outline-secondary.TButton", command=self.settings)
        self.toolbar_items = (device_field, self.fetch_btn, self.send_btn, self.export_btn, self.settings_btn)
        toolbar.bind("<Configure>", self._layout_toolbar)
        if self.demo:
            self.fetch_btn.configure(state="disabled")
            self.send_btn.configure(state="disabled")

    def _layout_toolbar(self, event):
        available_width = event.width
        position_x = position_y = row_height = 0
        for widget in self.toolbar_items:
            width = widget.winfo_reqwidth()
            height = widget.winfo_reqheight()
            if position_x and position_x + width > available_width:
                position_x = 0
                position_y += row_height + 8
                row_height = 0
            widget.place(x=position_x, y=position_y, width=width, height=height)
            position_x += width + 8
            row_height = max(row_height, height)
        required_height = position_y + row_height
        if event.widget.winfo_reqheight() != required_height:
            event.widget.configure(height=required_height)

    def _tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=(12, 0))
        dashboard_tab = ttk.Frame(self.notebook)
        dashboard_tab.rowconfigure(0, weight=1)
        dashboard_tab.columnconfigure(0, weight=1)
        self.dashboard_viewport = tk.Canvas(dashboard_tab, background=BG, highlightthickness=0)
        self.dashboard_viewport.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(dashboard_tab, orient="vertical", command=self.dashboard_viewport.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(dashboard_tab, orient="horizontal", command=self.dashboard_viewport.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.dashboard_viewport.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.dashboard = ttk.Frame(self.dashboard_viewport, padding=(0, 10))
        self.dashboard_window = self.dashboard_viewport.create_window(0, 0, window=self.dashboard, anchor="nw")
        self.dashboard_viewport.bind("<Configure>", self._resize_dashboard)
        self.dashboard.bind("<Configure>", self._resize_dashboard)
        self.daily_tab = ttk.Frame(self.notebook, padding=(0, 18))
        self.monthly_tab = ttk.Frame(self.notebook, padding=(0, 18))
        self.notebook.add(dashboard_tab, text="Dashboard")
        self.notebook.add(self.daily_tab, text="Daily Attendance")
        self.notebook.add(self.monthly_tab, text="Monthly Attendance")
        self._dashboard()
        daily_header = ttk.Frame(self.daily_tab)
        daily_header.pack(fill="x", pady=(0, 16))
        self.today_label = ttk.Label(daily_header, style="Title.TLabel", anchor="center")
        self.today_label.pack(fill="x")
        self.date_picker = ttk.Combobox(daily_header, textvariable=self.daily_date, state="readonly", width=12)
        self.date_picker.pack(pady=10)
        self.date_picker.bind("<<ComboboxSelected>>", lambda event: self.refresh_daily())
        self.edit_times_btn = ttk.Button(daily_header, text="Edit clock-in / clock-out",
                                         style="outline-primary.TButton", command=self.edit_times)
        self.edit_times_btn.pack()
        self.daily_count = ttk.Label(daily_header, anchor="center", foreground=MUTED)
        self.daily_count.pack(fill="x", pady=(6, 0))
        self.daily_table = self._table(self.daily_tab, [
            ("name", "Employee", 220), ("in", "Clock-in", 110), ("out", "Clock-out", 110),
            ("hours", "Hours worked", 120), ("excess", "Excess / deficit", 190), ("status", "Status", 170),
        ])
        self.daily_table.bind("<Double-1>", lambda event: self.edit_times())
        monthly_header = ttk.Frame(self.monthly_tab)
        monthly_header.pack(fill="x", pady=(0, 12))
        self.month_label = ttk.Label(monthly_header, style="Title.TLabel", anchor="center")
        self.month_label.pack(fill="x")
        self.month_picker = ttk.Combobox(monthly_header, textvariable=self.month, state="readonly", width=12)
        self.month_picker.pack(pady=10)
        self.month_picker.bind("<<ComboboxSelected>>", lambda event: self.refresh_month())
        self.month_totals = ttk.Label(monthly_header, anchor="center", foreground=MUTED)
        self.month_totals.pack(fill="x")
        self.monthly_table = self._table(self.monthly_tab, [
            ("name", "Employee", 180), ("role", "Role", 100), ("days", "Paid days", 85),
            ("hours", "Total hours", 95), ("net", "Excess / deficit", 170),
            ("extra", "Extra pay (INR)", 125), ("remaining", "Remaining days", 115),
            ("salary", "Salary (INR)", 120), ("rate", "Hourly pay (edit)", 150),
        ])
        self.monthly_table.bind("<Double-1>", self._edit_rate_cell)
        self.monthly_table.bind("<Return>", lambda event: self.edit_rate())
        self.pay_menu = tk.Menu(self.root, tearoff=False)
        self.pay_menu.add_command(label="Edit hourly pay", command=self.edit_rate)
        self.monthly_table.bind("<Button-3>", self._pay_menu)

    def _resize_dashboard(self, event=None):
        width = max(self.dashboard_viewport.winfo_width(), self.dashboard.winfo_reqwidth())
        height = max(self.dashboard_viewport.winfo_height(), self.dashboard.winfo_reqheight())
        self.dashboard_viewport.itemconfigure(self.dashboard_window, width=width, height=height)
        self.dashboard_viewport.configure(scrollregion=(0, 0, width, height))

    def _dashboard(self):
        heading = ttk.Frame(self.dashboard)
        heading.pack(fill="x", pady=(0, 8))
        ttk.Label(heading, text="Monthly overview", style="Title.TLabel").pack(side="left")
        self.manage_btn = ttk.Button(heading, text="Manage Employees", style="outline-primary.TButton",
                                     command=self.manage_employees)
        self.manage_btn.pack(side="left", padx=20)
        self.kpi_picker = ttk.Combobox(heading, textvariable=self.kpi_month, state="readonly", width=10)
        self.kpi_picker.pack(side="right")
        self.kpi_picker.bind("<<ComboboxSelected>>", lambda event: self.refresh_kpis())
        metrics = ttk.Frame(self.dashboard)
        metrics.pack(fill="x")
        metrics.columnconfigure((0, 1), weight=1, uniform="metrics")
        self.salary_value, self.salary_detail = self._metric(metrics, 0, "TOTAL SALARY PAYABLE", TEAL)
        self.hours_value, self.hours_detail = self._metric(metrics, 1, "AVERAGE HOURS / EMPLOYEE", GREEN)
        chart_header = ttk.Frame(self.dashboard)
        chart_header.pack(fill="x", pady=(12, 6))
        ttk.Label(chart_header, text="Average hours worked per day", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.chart_month_picker = ttk.Combobox(chart_header, textvariable=self.chart_period, state="readonly", width=12)
        self.chart_month_picker.pack(side="right")
        self.chart_month_picker.bind("<<ComboboxSelected>>", lambda event: self.draw_chart())
        self.figure = Figure(figsize=(9, 3.5), dpi=100, facecolor="white", layout="constrained")
        self.axes = self.figure.add_subplot(111)
        chart_height = round(320 * self.root.winfo_fpixels("1i") / 96)
        chart_area = ttk.Frame(self.dashboard, height=chart_height)
        chart_area.pack_propagate(False)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_area)
        self.navigation = NavigationToolbar2Tk(self.canvas, self.dashboard, pack_toolbar=False)
        self.navigation.update()
        self.navigation.pack(side="bottom", fill="x")
        chart_area.pack(fill="both", expand=True)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("motion_notify_event", self._chart_hover)

    def _metric(self, parent, column, title, color):
        card = ttk.Frame(parent, style="Surface.TFrame", padding=(16, 10))
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        ttk.Label(card, text=title, style="Surface.TLabel", foreground=color).pack(anchor="w")
        value = ttk.Label(card, text="--", style="Metric.TLabel")
        value.pack(anchor="w", pady=(2, 2))
        detail = ttk.Label(card, style="Surface.TLabel")
        detail.pack(anchor="w")
        return value, detail

    def _table(self, parent, columns):
        wrapper = ttk.Frame(parent, style="Surface.TFrame")
        wrapper.pack(fill="both", expand=True)
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        table = ttk.Treeview(wrapper, columns=[column[0] for column in columns], show="headings", selectmode="browse")
        for key, title, width in columns:
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=width, anchor="w" if key in ("name", "status") else "center")
        table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(wrapper, orient="vertical", command=table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(wrapper, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.tag_configure("odd", background="#F6F8F9")
        table.tag_configure("review", foreground="#A34E1D")
        return table

    def _footer(self):
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="primary.Horizontal.TProgressbar")
        self.progress.pack(side="bottom", fill="x", padx=24)
        footer = ttk.Frame(self.root, padding=(24, 10))
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, textvariable=self.status, wraplength=660).pack(side="left")
        ttk.Label(footer, textvariable=self.last_fetch, foreground=MUTED).pack(side="right")

    def refresh(self):
        self.employees, self.rows = self.store.snapshot()
        self.manual = self.store.manual_times()
        self.device_daily = daily_summary(self.rows)
        self.daily = daily_summary(self.rows, self.manual)
        today = date.today()
        previous_today = getattr(self, "today", today)
        self.today = today
        current = month_display(today.strftime("%Y-%m"))
        months = [month_display(key) for key in
                  sorted({row["timestamp"][:7] for row in self.rows} | {today.strftime("%Y-%m")}, reverse=True)]
        self.month_picker.configure(values=months)
        self.kpi_picker.configure(values=months)
        self.chart_month_picker.configure(values=[ALL_DATES, *months])
        for variable, allowed in ((self.month, months), (self.kpi_month, months),
                                  (self.chart_period, [ALL_DATES, *months])):
            if variable.get() not in allowed:
                variable.set(current)
        dates = [format_date(day) for day in sorted({day for _, day in self.daily} | {today}, reverse=True)]
        self.date_picker.configure(values=dates)
        if self.daily_date.get() not in dates or (today != previous_today
                                                  and self.daily_date.get() == format_date(previous_today)):
            self.daily_date.set(format_date(today))
        names = Counter(employee["name"] for employee in self.employees.values())
        self.employee_labels = {user_id: employee["name"] if names[employee["name"]] == 1
                                else f"{employee['name']} ({user_id})"
                                for user_id, employee in self.employees.items()}
        self.last_fetch.set("Last fetch: " + self.store.setting("last_fetch", "Never"))
        self.refresh_kpis()
        self.refresh_daily()
        self.refresh_month()

    def refresh_kpis(self):
        key = month_key(self.kpi_month.get())
        rows = monthly_summary(self.employees, self.daily, key)
        staff = [row for row in rows if not row["no_extra_pay"]]
        average_hours = sum(row["hours"] for row in staff) / len(staff) if staff else 0
        remaining = rows[0]["remaining_days"] if rows else 0
        self.salary_value.configure(text=f"INR {sum(row['salary'] for row in rows):,.2f}")
        self.salary_detail.configure(text=f"{sum(row['days'] for row in rows)} paid employee-days | "
                                          f"{remaining} days remaining")
        self.hours_value.configure(text=f"{average_hours:,.2f} h")
        self.hours_detail.configure(text=f"{len(staff)} employees (no-extra-pay roles excluded) | "
                                         + ("Month to date" if key == self.today.strftime("%Y-%m") else "Full month"))

    def refresh_daily(self):
        day = datetime.strptime(self.daily_date.get(), "%d-%m-%Y").date()
        self.today_label.configure(text=f"{day.strftime('%A')}, {format_date(day)}")
        self.daily_table.delete(*self.daily_table.get_children())
        present = 0
        for index, (user_id, employee) in enumerate(self.employees.items()):
            entry = self.daily.get((user_id, day))
            present += bool(entry)
            values = [employee["name"], "--", "--", "0.00", "--", "No punches"]
            tags = ["odd"] if index % 2 else []
            if entry:
                values[1:] = [entry["clock_in"].strftime("%H:%M:%S") if entry["clock_in"] else "--",
                              entry["clock_out"].strftime("%H:%M:%S") if entry["clock_out"] else "--",
                              f"{entry['hours']:.2f}",
                              format_duration(entry["hours"] - STANDARD_HOURS, signed=True) if entry["complete"] else "--",
                              entry["issues"]]
                if not entry["complete"]:
                    tags.append("review")
            self.daily_table.insert("", "end", iid=user_id, values=values, tags=tags)
        self.daily_count.configure(text=f"{present} with punches | {len(self.employees)} employees")

    def refresh_month(self):
        key = month_key(self.month.get())
        self.month_label.configure(text=datetime.strptime(key, "%Y-%m").strftime("%B %Y"))
        self.monthly_rows = monthly_summary(self.employees, self.daily, key)
        self.monthly_table.delete(*self.monthly_table.get_children())
        for index, row in enumerate(self.monthly_rows):
            self.monthly_table.insert("", "end", iid=row["user_id"], tags=["odd"] if index % 2 else [], values=(
                row["name"], row["role"], row["days"], f"{row['hours']:.2f}",
                format_duration(row["net_hours"], signed=True), f"{row['extra_pay']:,.2f}",
                row["remaining_days"], f"{row['salary']:,.2f}", f"{row['hourly_pay']:,.2f}  [Edit]",
            ))
        remaining = self.monthly_rows[0]["remaining_days"] if self.monthly_rows else 0
        self.month_totals.configure(text=f"INR {sum(row['salary'] for row in self.monthly_rows):,.2f} payable"
                                   f"   |   {sum(row['hours'] for row in self.monthly_rows):,.2f} hours"
                                   f"   |   {remaining} days remaining")
        self.draw_chart()

    def draw_chart(self):
        self.axes.clear()
        period = self.chart_period.get()
        key = None if period == ALL_DATES else month_key(period)
        in_period = (lambda day: day <= date.today()) if key is None else (
            lambda day: day.strftime("%Y-%m") == key and day <= date.today())
        self.chart_info = []
        for user_id, employee in self.employees.items():
            if employee["no_extra_pay"]:
                continue
            hours = [entry["hours"] for (employee_id, day), entry in self.daily.items()
                     if employee_id == user_id and entry["complete"] and in_period(day)]
            self.chart_info.append((self.employee_labels[user_id], sum(hours) / len(hours) if hours else 0.0, len(hours)))
        positions = range(len(self.chart_info))
        self.chart_bars = self.axes.bar(positions, [info[1] for info in self.chart_info], color=TEAL, width=0.65)
        self.axes.axhline(STANDARD_HOURS, color="#99A7AA", linestyle="--", linewidth=1)
        self.axes.set_xticks(list(positions), [info[0] for info in self.chart_info], rotation=45, ha="right", fontsize=8)
        self.axes.set_ylabel("Average hours per day", color=MUTED)
        self.axes.set_xlabel("All dates to today" if key is None
                             else datetime.strptime(key, "%Y-%m").strftime("%B %Y"), color=MUTED)
        self.axes.set_ylim(bottom=0, top=max(10, self.axes.get_ylim()[1]))
        self.axes.grid(axis="y", color="#E6EBEE")
        self.axes.set_axisbelow(True)
        self.axes.spines[["top", "right"]].set_visible(False)
        self.axes.spines[["left", "bottom"]].set_color("#D3DCE0")
        self.axes.tick_params(colors=MUTED)
        if not any(info[2] for info in self.chart_info):
            self.axes.text(0.5, 0.5, "No completed attendance days for this period", transform=self.axes.transAxes,
                           ha="center", va="center", color=MUTED, fontsize=12)
        self.annotation = self.axes.annotate("", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                                             bbox={"boxstyle": "round,pad=0.5", "fc": "white", "ec": "#CCD8DC"})
        self.annotation.set_visible(False)
        self.navigation.update()
        self.canvas.draw_idle()

    def _chart_hover(self, event):
        if event.inaxes == self.axes and not self.navigation.mode:
            for bar, (label, average, days) in zip(self.chart_bars, self.chart_info):
                if bar.contains(event)[0]:
                    self.annotation.xy = (bar.get_x() + bar.get_width() / 2, average)
                    self.annotation.set_text(f"{label}\n{average:.2f} h average over {days} day(s)")
                    right_half = bar.get_x() > len(self.chart_info) / 2
                    self.annotation.set_position((-12 if right_half else 12, 12))
                    self.annotation.set_ha("right" if right_half else "left")
                    self.annotation.set_visible(True)
                    self.canvas.draw_idle()
                    return
        if self.annotation.get_visible():
            self.annotation.set_visible(False)
            self.canvas.draw_idle()

    def _edit_rate_cell(self, event):
        if self.monthly_table.identify_column(event.x) == "#9":
            user_id = self.monthly_table.identify_row(event.y)
            if user_id:
                self.monthly_table.selection_set(user_id)
                self.edit_rate()

    def _pay_menu(self, event):
        user_id = self.monthly_table.identify_row(event.y)
        if user_id:
            self.monthly_table.selection_set(user_id)
            self.pay_menu.tk_popup(event.x_root, event.y_root)

    def edit_rate(self):
        selection = self.monthly_table.selection()
        if not selection or self.busy:
            return
        user_id = selection[0]
        employee = self.employees[user_id]
        month = month_key(self.month.get())
        amount = simpledialog.askfloat("Hourly pay", f"{employee['name']}\nHourly pay in INR from {self.month.get()} onward:",
                                       initialvalue=hourly_rate(employee, month), minvalue=0, parent=self.root)
        if amount is None:
            return
        if not messagebox.askokcancel(
                "Change hourly pay",
                f"The new rate applies to {self.month.get()} and all later months.\n"
                "Earlier months keep their previous rate.", parent=self.root):
            return
        try:
            self.store.set_hourly_pay(user_id, amount, month)
            self.refresh()
            self.status.set(f"Hourly pay updated for {employee['name']} from {self.month.get()}")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Hourly pay", str(exc), parent=self.root)

    def manage_employees(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage employees")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=24)
        content.pack(fill="both", expand=True)
        count = ttk.Label(content, font=("Segoe UI", 14, "bold"))
        count.pack(anchor="w", pady=(0, 8))
        table = self._table(content, [("name", "Employee", 230), ("role", "Role", 130), ("pay", "Hourly pay now (INR)", 170)])
        table.configure(height=8)
        table.master.pack_configure(expand=False)
        role_var = tk.StringVar()
        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=8)
        ttk.Label(actions, text="Role of selected employee").pack(side="left", padx=(0, 8))
        role_picker = ttk.Combobox(actions, textvariable=role_var, state="readonly", width=14)
        role_picker.pack(side="left")
        this_month = date.today().strftime("%Y-%m")

        def reload():
            selected = table.selection()
            table.delete(*table.get_children())
            for user_id, employee in self.employees.items():
                table.insert("", "end", iid=user_id, values=(
                    employee["name"], employee["role"], f"{hourly_rate(employee, this_month):,.2f}"))
            if selected and selected[0] in self.employees:
                table.selection_set(selected[0])
            roles = self.store.roles()
            role_picker.configure(values=roles)
            add_role_picker.configure(values=roles)
            if new_role.get() not in roles:
                new_role.set(self.store.role_details()[1])
            count.configure(text=f"{len(self.employees)} employees")

        def show_role(event=None):
            selection = table.selection()
            if selection:
                role_var.set(self.employees[selection[0]]["role"])

        def set_role(event=None):
            selection = table.selection()
            if not selection:
                messagebox.showinfo("Role", "Select an employee first.", parent=dialog)
                return
            try:
                self.store.set_role(selection[0], role_var.get())
            except ValueError as exc:
                messagebox.showerror("Role", str(exc), parent=dialog)
                return
            self.refresh()
            reload()
            self.status.set(f"Role updated for {self.employees[selection[0]]['name']}")

        role_picker.bind("<<ComboboxSelected>>", set_role)

        def edit_roles():
            roles_dialog = tk.Toplevel(dialog)
            roles_dialog.title("Manage roles")
            roles_dialog.transient(dialog)
            roles_dialog.grab_set()
            roles_dialog.resizable(False, False)
            box = ttk.Frame(roles_dialog, padding=20)
            box.pack(fill="both", expand=True)
            ttk.Label(box, text="Select a role to rename it or change its pay rule.", foreground=MUTED).pack(anchor="w", pady=(0, 6))
            listbox = tk.Listbox(box, height=8, width=40, exportselection=False, font=("Segoe UI", 10))
            listbox.pack(fill="x")
            name_var = tk.StringVar()
            flag_var = tk.BooleanVar()
            ttk.Entry(box, textvariable=name_var).pack(fill="x", pady=(10, 6), ipady=4)
            roles = []
            flags = {}

            def fill():
                details, default = self.store.role_details()
                roles[:] = [name for name, _ in details]
                flags.update(details)
                listbox.delete(0, "end")
                for name, flag in details:
                    notes = [note for note, shown in (("default for new employees", name == default),
                                                      ("no extra pay", flag)) if shown]
                    listbox.insert("end", name + (f"  ({', '.join(notes)})" if notes else ""))

            def selected_role():
                selection = listbox.curselection()
                if not selection:
                    messagebox.showinfo("Roles", "Select a role first.", parent=roles_dialog)
                    return None
                return roles[selection[0]]

            def apply(action):
                try:
                    action()
                except ValueError as exc:
                    messagebox.showerror("Roles", str(exc), parent=roles_dialog)
                    return False
                self.refresh()
                fill()
                reload()
                show_role()
                return True

            def add():
                if apply(lambda: self.store.add_role(name_var.get())):
                    name_var.set("")

            def rename():
                role = selected_role()
                if role and apply(lambda: self.store.rename_role(role, name_var.get())):
                    listbox.selection_set(roles.index(" ".join(name_var.get().split())))

            def delete():
                role = selected_role()
                if role and messagebox.askokcancel(
                        "Delete role",
                        f"Delete {role}? Employees with this role move to the default role.",
                        parent=roles_dialog):
                    apply(lambda: self.store.delete_role(role))

            def toggle_flag():
                selection = listbox.curselection()
                role = roles[selection[0]] if selection else None
                if not role:
                    messagebox.showinfo("Roles", "Select a role first.", parent=roles_dialog)
                    flag_var.set(False)
                    return
                apply(lambda: self.store.set_role_no_extra_pay(role, flag_var.get()))
                listbox.selection_set(roles.index(role))

            def on_select(event=None):
                selection = listbox.curselection()
                if selection:
                    name_var.set(roles[selection[0]])
                    flag_var.set(flags[roles[selection[0]]])

            listbox.bind("<<ListboxSelect>>", on_select)
            ttk.Checkbutton(box, text="No extra pay for this role (excluded from averages)",
                            variable=flag_var, command=toggle_flag).pack(anchor="w", pady=(0, 10))
            buttons = ttk.Frame(box)
            buttons.pack(fill="x")
            ttk.Button(buttons, text="Add", style="primary.TButton", command=add).pack(side="left")
            ttk.Button(buttons, text="Rename selected", style="outline-primary.TButton",
                       command=rename).pack(side="left", padx=8)
            ttk.Button(buttons, text="Delete selected", style="outline-danger.TButton", command=delete).pack(side="left")
            fill()

        def remove():
            selection = table.selection()
            if not selection:
                messagebox.showinfo("Remove employee", "Select an employee to remove.", parent=dialog)
                return
            name = self.employees[selection[0]]["name"]
            if not messagebox.askokcancel(
                    "Remove employee",
                    f"Remove {name} from the attendance portal?\nTheir punches are kept but no longer shown "
                    "or included in payroll, exports, and backups.", parent=dialog):
                return
            self.store.remove_employee(selection[0])
            self.refresh()
            reload()
            self.status.set(f"{name} removed from the attendance portal")

        ttk.Button(actions, text="Manage roles", style="outline-secondary.TButton", command=edit_roles).pack(side="left", padx=8)
        ttk.Button(actions, text="Remove selected", style="outline-danger.TButton", command=remove).pack(side="right")
        table.bind("<<TreeviewSelect>>", show_role)
        ttk.Separator(content).pack(fill="x", pady=8)
        ttk.Label(content, text="Add employee", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        form = ttk.Frame(content)
        form.pack(fill="x", pady=8)
        new_role = tk.StringVar(value=self.store.role_details()[1])
        fields = {"id": tk.StringVar(), "name": tk.StringVar(), "pay": tk.StringVar(value=f"{DEFAULT_HOURLY_PAY:g}")}
        for column, (key, label, width) in enumerate([("id", "Device ID", 10), ("name", "Name", 22), ("pay", "Hourly pay", 10)]):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky="w", padx=(0, 8))
            ttk.Entry(form, textvariable=fields[key], width=width).grid(row=1, column=column, sticky="w", padx=(0, 8), ipady=4)
        ttk.Label(form, text="Role").grid(row=0, column=3, sticky="w", padx=(0, 8))
        add_role_picker = ttk.Combobox(form, textvariable=new_role, state="readonly", width=12)
        add_role_picker.grid(row=1, column=3, sticky="w", padx=(0, 8))

        def add():
            try:
                self.store.add_employee(fields["id"].get(), fields["name"].get(), fields["pay"].get(), new_role.get())
            except ValueError as exc:
                messagebox.showerror("Add employee", str(exc), parent=dialog)
                return
            name = " ".join(fields["name"].get().split())
            for variable in (fields["id"], fields["name"]):
                variable.set("")
            self.refresh()
            reload()
            self.status.set(f"{name} added to the attendance portal")

        ttk.Button(form, text="Add employee", style="primary.TButton", command=add).grid(row=1, column=4, padx=(8, 0))
        reload()

    def edit_times(self):
        selection = self.daily_table.selection()
        if not selection:
            messagebox.showinfo("Edit clock times", "Select an employee row first.", parent=self.root)
            return
        user_id = selection[0]
        day = datetime.strptime(self.daily_date.get(), "%d-%m-%Y").date()
        entry = self.daily.get((user_id, day))
        device = self.device_daily.get((user_id, day))
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit clock times")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=24)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=f"{self.employees[user_id]['name']} | {format_date(day)}",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(content, text="24-hour time as HH:MM or HH:MM:SS. A cleared field uses the device scan.",
                  foreground=MUTED).pack(anchor="w", pady=(4, 10))
        times = {}
        for key, label in (("clock_in", "Clock-in"), ("clock_out", "Clock-out")):
            value = entry[key].strftime("%H:%M:%S") if entry and entry[key] else ""
            times[key] = tk.StringVar(value=value)
            ttk.Label(content, text=label).pack(anchor="w", pady=(6, 2))
            ttk.Entry(content, textvariable=times[key], width=16).pack(anchor="w", ipady=4)

        def parse(key):
            text = times[key].get().strip()
            if not text:
                return None
            for pattern in ("%H:%M:%S", "%H:%M"):
                try:
                    moment = datetime.combine(day, datetime.strptime(text, pattern).time())
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Enter times as HH:MM or HH:MM:SS (24-hour).")
            scan = device[key] if device else None
            return None if scan and scan.strftime("%H:%M:%S") == moment.strftime("%H:%M:%S") else moment

        def save():
            try:
                self.store.set_manual_times(user_id, day, parse("clock_in"), parse("clock_out"))
            except ValueError as exc:
                messagebox.showerror("Edit clock times", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh()
            self.status.set(f"Clock times updated for {self.employees[user_id]['name']} on {format_date(day)}")

        ttk.Button(content, text="Save", style="primary.TButton", command=save).pack(anchor="e", pady=(20, 0))

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Connection & backup settings")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=24)
        content.pack(fill="both", expand=True)
        fields = {}
        for key, label in [("port", "Device port"), ("credentials", "Google service account JSON"),
                           ("spreadsheet_id", "Google spreadsheet ID"), ("worksheet", "Backup worksheet")]:
            ttk.Label(content, text=label).pack(anchor="w", pady=(10, 4))
            variable = tk.StringVar(value=self.store.setting(key, self.defaults[key]))
            fields[key] = variable
            ttk.Entry(content, textvariable=variable, width=64).pack(fill="x")
            if key == "credentials":
                def browse():
                    path = filedialog.askopenfilename(parent=dialog, filetypes=[("JSON files", "*.json")])
                    if path:
                        fields["credentials"].set(path)
                ttk.Button(content, text="Browse...", command=browse).pack(anchor="e", pady=6)

        def save():
            try:
                port = int(fields["port"].get())
                if not 1 <= port <= 65535:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Settings", "Port must be between 1 and 65535.", parent=dialog)
                return
            for key, variable in fields.items():
                self.store.set_setting(key, variable.get().strip())
            dialog.destroy()
        ttk.Button(content, text="Save settings", style="primary.TButton", command=save).pack(anchor="e", pady=(20, 0))

    def _busy(self, busy):
        self.busy = busy
        for button in (self.fetch_btn, self.send_btn):
            button.configure(state="disabled" if busy or self.demo else "normal")
        for widget in (self.export_btn, self.settings_btn, self.manage_btn, self.ip_entry):
            widget.configure(state="disabled" if busy else "normal")
        self.progress.start(12) if busy else self.progress.stop()

    def start(self, send=False):
        if self.busy or self.demo:
            return
        device_ip = self.ip.get().strip()
        if not device_ip:
            messagebox.showerror("Device IP", "Enter the device IP address.", parent=self.root)
            return
        settings = {key: self.store.setting(key, value) for key, value in self.defaults.items()}
        if send and not all(settings[key] for key in ("credentials", "spreadsheet_id", "worksheet")):
            self.settings()
            return
        self.store.set_setting("device_ip", device_ip)
        self._busy(True)
        self.status.set(f"Connecting to {device_ip}...")
        threading.Thread(target=self._sync_worker, args=(device_ip, settings, send), daemon=True).start()

    def _sync_worker(self, device_ip, settings, send):
        saved = False
        try:
            rows, users = self.fetch_attendance(device_ip, int(settings["port"]))
            self.store.merge(rows, users)
            self.store.set_setting("last_fetch", datetime.now().strftime("%d-%m-%Y %H:%M"))
            saved = True
            self.events.put(("refresh", None))
            if send:
                self.events.put(("status", "Local history saved. Backing up to Google Sheets..."))
                self.upload(self.store.snapshot()[1], settings["credentials"], settings["worksheet"],
                            log=lambda text: self.events.put(("status", text)), spreadsheet_id=settings["spreadsheet_id"])
                self.store.set_setting("last_backup", datetime.now().isoformat(timespec="seconds"))
            self.events.put(("done", f"{len(rows)} device punches fetched | Local history updated" +
                             (" | Google backup complete" if send else "")))
        except Exception as exc:
            prefix = "Local history saved; Google backup failed" if saved else "Fetch failed; existing history retained"
            self.events.put(("error", f"{prefix}: {exc}"))

    def export(self):
        if self.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".xlsx",
                                           initialfile=f"Attendo-Sync-{self.month.get()}.xlsx",
                                           filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        self._busy(True)
        self.status.set("Exporting workbook...")
        employees, rows = self.store.snapshot()
        manual = self.store.manual_times()
        month = month_key(self.month.get())

        def worker():
            try:
                from attendance_reports import export_workbook
                export_workbook(path, employees, rows, month, manual=manual)
                self.events.put(("done", f"Excel export saved: {path}"))
            except Exception as exc:
                self.events.put(("error", f"Excel export failed: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "refresh":
                    self.refresh()
                else:
                    self.status.set(message)
                    if kind in ("done", "error"):
                        self._busy(False)
                    if kind == "error":
                        messagebox.showerror("Attendo-Sync", message, parent=self.root)
        except queue.Empty:
            pass
        if date.today() != self.today:
            self.refresh()
        self.poll_id = self.root.after(100, self._poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation in progress", "Wait for the current operation to finish before closing.", parent=self.root)
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()