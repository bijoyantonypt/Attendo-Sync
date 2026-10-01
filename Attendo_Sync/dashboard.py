"""Desktop attendance dashboard."""

import queue
import threading
from datetime import date, datetime
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk
from ttkbootstrap import Style

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PIL import Image, ImageTk

from attendance_data import daily_summary, month_days, monthly_summary


BG = "#F3F5F7"
INK = "#202A30"
MUTED = "#65747D"
TEAL = "#167B91"
GREEN = "#23815C"


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
        self.month = tk.StringVar(value=date.today().strftime("%Y-%m"))
        self.employee_filter = tk.StringVar(value="All employees")
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
        toolbar = ttk.Frame(self.root, style="Surface.TFrame", padding=(24, 0, 24, 12))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Device IP", style="Surface.TLabel").pack(side="left", padx=(0, 8))
        self.ip_entry = ttk.Entry(toolbar, textvariable=self.ip, width=17)
        self.ip_entry.pack(side="left", padx=(0, 16), ipady=5)
        self.fetch_btn = ttk.Button(toolbar, text="Fetch & Update", style="primary.TButton", command=self.start)
        self.fetch_btn.pack(side="left", padx=(0, 8))
        self.send_btn = ttk.Button(toolbar, text="Fetch & Send", style="outline-primary.TButton",
                                   command=lambda: self.start(send=True))
        self.send_btn.pack(side="left", padx=(0, 8))
        self.export_btn = ttk.Button(toolbar, text="Excel Export", style="outline-secondary.TButton", command=self.export)
        self.export_btn.pack(side="left")
        self.settings_btn = ttk.Button(toolbar, text="Settings", style="outline-secondary.TButton", command=self.settings)
        self.settings_btn.pack(side="right")
        if self.demo:
            self.fetch_btn.configure(state="disabled")
            self.send_btn.configure(state="disabled")

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
        self.daily_count = ttk.Label(daily_header, anchor="center", foreground=MUTED)
        self.daily_count.pack(fill="x", pady=(6, 0))
        self.daily_table = self._table(self.daily_tab, [
            ("name", "Employee", 220), ("id", "ID", 75), ("in", "Clock-in", 115),
            ("out", "Clock-out", 115), ("hours", "Hours worked", 125), ("status", "Status", 210),
        ])
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
            ("name", "Employee", 190), ("id", "ID", 65), ("days", "Paid days", 90),
            ("hours", "Total hours", 100), ("net", "Excess / deficit h", 135),
            ("extra", "Extra days", 100), ("review", "Review days", 100),
            ("salary", "Salary (INR)", 130), ("rate", "Daily pay (edit)", 145),
        ])
        self.monthly_table.bind("<Double-1>", self._edit_rate_cell)
        self.monthly_table.bind("<Return>", lambda event: self.edit_rate())
        self.pay_menu = tk.Menu(self.root, tearoff=False)
        self.pay_menu.add_command(label="Edit daily pay", command=self.edit_rate)
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
        self.current_month_label = ttk.Label(heading, foreground=MUTED)
        self.current_month_label.pack(side="right")
        metrics = ttk.Frame(self.dashboard)
        metrics.pack(fill="x")
        metrics.columnconfigure((0, 1), weight=1, uniform="metrics")
        self.salary_value, self.salary_detail = self._metric(metrics, 0, "TOTAL SALARY PAYABLE", TEAL)
        self.hours_value, self.hours_detail = self._metric(metrics, 1, "AVERAGE HOURS / EMPLOYEE", GREEN)
        chart_header = ttk.Frame(self.dashboard)
        chart_header.pack(fill="x", pady=(12, 6))
        ttk.Label(chart_header, text="Attendance by employee", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.chart_month_picker = ttk.Combobox(chart_header, textvariable=self.month, state="readonly", width=10)
        self.chart_month_picker.pack(side="right")
        self.chart_month_picker.bind("<<ComboboxSelected>>", lambda event: self.refresh_month())
        self.employee_picker = ttk.Combobox(chart_header, textvariable=self.employee_filter, state="readonly", width=24)
        self.employee_picker.pack(side="right", padx=10)
        self.employee_picker.bind("<<ComboboxSelected>>", lambda event: self.draw_chart())
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
        self.daily = daily_summary(self.rows)
        today = date.today()
        self.today = today
        current = today.strftime("%Y-%m")
        months = sorted({row["timestamp"][:7] for row in self.rows} | {current}, reverse=True)
        for picker in (self.month_picker, self.chart_month_picker):
            picker.configure(values=months)
        if self.month.get() not in months:
            self.month.set(current)
        self.filter_ids = {f"{employee['name']} ({user_id})": user_id for user_id, employee in self.employees.items()}
        self.employee_picker.configure(values=["All employees", *self.filter_ids])
        if self.employee_filter.get() not in self.filter_ids:
            self.employee_filter.set("All employees")
        current_rows = monthly_summary(self.employees, self.daily, current)
        total_salary = sum(row["salary"] for row in current_rows)
        average_hours = sum(row["hours"] for row in current_rows) / len(current_rows) if current_rows else 0
        reviews = sum(row["review_days"] for row in current_rows)
        self.salary_value.configure(text=f"INR {total_salary:,.2f}")
        self.salary_detail.configure(text=f"{sum(row['days'] for row in current_rows)} paid employee-days | {reviews} days to review")
        self.hours_value.configure(text=f"{average_hours:,.2f} h")
        self.hours_detail.configure(text=f"{len(self.employees)} employees | Month to date")
        self.current_month_label.configure(text=today.strftime("%B %Y"))
        self.today_label.configure(text=today.strftime("%A, %d %B %Y"))
        self.daily_table.delete(*self.daily_table.get_children())
        present = 0
        for index, (user_id, employee) in enumerate(self.employees.items()):
            entry = self.daily.get((user_id, today))
            present += bool(entry)
            values = [employee["name"], user_id, "--", "--", "0.00", "No punches"]
            tags = ["odd"] if index % 2 else []
            if entry:
                values[2:] = [entry["clock_in"].strftime("%H:%M:%S") if entry["clock_in"] else "--",
                              entry["clock_out"].strftime("%H:%M:%S") if entry["clock_out"] else "--",
                              f"{entry['hours']:.2f}", entry["issues"]]
                if not entry["complete"]:
                    tags.append("review")
            self.daily_table.insert("", "end", iid=user_id, values=values, tags=tags)
        self.daily_count.configure(text=f"{present} with punches | {len(self.employees)} employees")
        self.last_fetch.set("Last fetch: " + self.store.setting("last_fetch", "Never"))
        self.refresh_month()

    def refresh_month(self):
        self.month_label.configure(text=datetime.strptime(self.month.get(), "%Y-%m").strftime("%B %Y"))
        self.monthly_rows = monthly_summary(self.employees, self.daily, self.month.get())
        self.monthly_table.delete(*self.monthly_table.get_children())
        for index, row in enumerate(self.monthly_rows):
            tags = ["odd"] if index % 2 else []
            if row["review_days"]:
                tags.append("review")
            self.monthly_table.insert("", "end", iid=row["user_id"], tags=tags, values=(
                row["name"], row["user_id"], row["days"], f"{row['hours']:.2f}", f"{row['net_hours']:+.2f}",
                f"{row['extra_days']:.3f}", row["review_days"], f"{row['salary']:,.2f}", f"{row['daily_pay']:,.2f}  [Edit]",
            ))
        self.month_totals.configure(text=f"INR {sum(row['salary'] for row in self.monthly_rows):,.2f} payable"
                                   f"   |   {sum(row['hours'] for row in self.monthly_rows):,.2f} hours"
                                   f"   |   {sum(row['review_days'] for row in self.monthly_rows)} days to review")
        self.draw_chart()

    def draw_chart(self):
        self.axes.clear()
        self.chart_lines = []
        days = month_days(self.month.get())
        selected = self.filter_ids.get(self.employee_filter.get())
        colors = [TEAL, "#D17631", GREEN, "#AF496A", "#5D63A0", "#947533", "#4675AD", "#676B70"]
        has_data = False
        for index, (user_id, employee) in enumerate(self.employees.items()):
            if selected is not None and user_id != selected:
                continue
            values = []
            for day in days:
                entry = self.daily.get((user_id, day))
                has_data = has_data or bool(entry)
                values.append(float("nan") if day > date.today() or (entry and not entry["complete"])
                              else entry["hours"] if entry else 0)
            line, = self.axes.plot([day.day for day in days], values, label=f"{employee['name']} ({user_id})",
                                   color=colors[index % len(colors)], linewidth=1.8, marker="o", markersize=3)
            self.chart_lines.append(line)
        self.axes.axhline(8.5, color="#99A7AA", linestyle="--", linewidth=1)
        self.axes.set_ylabel("Worked hours", color=MUTED)
        self.axes.set_xlabel(datetime.strptime(self.month.get(), "%Y-%m").strftime("%B %Y"), color=MUTED)
        self.axes.set_xlim(0.5, len(days) + 0.5)
        self.axes.set_ylim(bottom=0, top=max(10, self.axes.get_ylim()[1]))
        self.axes.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=16))
        self.axes.grid(axis="y", color="#E6EBEE")
        self.axes.spines[["top", "right"]].set_visible(False)
        self.axes.spines[["left", "bottom"]].set_color("#D3DCE0")
        self.axes.tick_params(colors=MUTED)
        if self.chart_lines and len(self.chart_lines) <= 8:
            self.axes.legend(loc="upper left", fontsize=8, frameon=False, ncol=2)
        if not has_data:
            self.axes.text(0.5, 0.5, "No attendance records for this month", transform=self.axes.transAxes,
                           ha="center", va="center", color=MUTED, fontsize=12)
        self.annotation = self.axes.annotate("", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                                             bbox={"boxstyle": "round,pad=0.5", "fc": "white", "ec": "#CCD8DC"})
        self.annotation.set_visible(False)
        self.navigation.update()
        self.canvas.draw_idle()

    def _chart_hover(self, event):
        if event.inaxes == self.axes and not self.navigation.mode:
            for line in self.chart_lines:
                hit, details = line.contains(event)
                if hit:
                    index = details["ind"][0]
                    day, hours = line.get_data()[0][index], line.get_data()[1][index]
                    self.annotation.xy = (day, hours)
                    self.annotation.set_text(f"{line.get_label()}\nDay {day}: {hours:.2f} h")
                    self.annotation.set_position((-12 if day > 16 else 12, 12))
                    self.annotation.set_ha("right" if day > 16 else "left")
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
        amount = simpledialog.askfloat("Daily pay", f"{employee['name']} ({user_id})\nDaily pay in INR (8.5 hours):",
                                       initialvalue=employee["daily_pay"], minvalue=0, parent=self.root)
        if amount is None:
            return
        if not messagebox.askokcancel("Recalculate payroll", "This rate applies to all months, including historical reports.", parent=self.root):
            return
        try:
            self.store.set_pay(user_id, amount)
            self.refresh()
            self.status.set(f"Daily pay updated for {employee['name']}")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Daily pay", str(exc), parent=self.root)

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
        for widget in (self.export_btn, self.settings_btn, self.ip_entry):
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
            self.store.set_setting("last_fetch", datetime.now().strftime("%d %b %Y, %H:%M"))
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
        month = self.month.get()

        def worker():
            try:
                from attendance_reports import export_workbook
                export_workbook(path, employees, rows, month)
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