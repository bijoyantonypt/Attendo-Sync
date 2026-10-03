import json
import os
import subprocess
import sys
import tempfile
import tkinter
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from attendance_data import (DEFAULT_HOURLY_PAY, AttendanceStore, daily_summary, format_date, format_duration,
                             hourly_rate, monthly_summary, month_display, month_key)


def punch(day, clock, mode, user_id="101"):
    return {"user_id": user_id, "user_name": "Anil", "timestamp": f"2026-09-{day}T{clock}:00",
            "status": 1, "punch": mode}


class AttendanceTests(unittest.TestCase):
    def test_first_scan_is_in_last_scan_is_out(self):
        daily = daily_summary([punch("01", "13:00", 0), punch("01", "09:00", 0),
                               punch("01", "12:00", 0), punch("01", "18:30", 0)])
        entry = daily[("101", date(2026, 9, 1))]
        self.assertEqual(entry["clock_in"].strftime("%H:%M"), "09:00")
        self.assertEqual(entry["clock_out"].strftime("%H:%M"), "18:30")
        self.assertEqual(entry["hours"], 9.5)
        self.assertTrue(entry["complete"])
        self.assertEqual(entry["issues"], "OK")

    def test_single_scan_is_missing_clock_out(self):
        entry = daily_summary([punch("01", "09:00", 0), punch("01", "09:00", 0),
                               {**punch("01", "09:00", 0), "timestamp": "2026-09-01T09:02:00"}])[("101", date(2026, 9, 1))]
        self.assertIsNone(entry["clock_out"])
        self.assertFalse(entry["complete"])
        self.assertEqual(entry["hours"], 0)
        self.assertEqual(entry["issues"], "Missing clock-out")

    def test_net_overtime_and_deficit_pay(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 10, "role": "Normal"}}
        for clock_out, salary, net, extra in [("17:30", 85, 0, 0), ("18:30", 105, 1, 20), ("16:30", 65, -1, -20)]:
            with self.subTest(clock_out=clock_out):
                daily = daily_summary([punch("01", "09:00", 0), punch("01", clock_out, 1)])
                row = monthly_summary(employees, daily, "2026-09", date(2026, 10, 1))[0]
                self.assertEqual(row["salary"], salary)
                self.assertEqual(row["net_hours"], net)
                self.assertEqual(row["extra_pay"], extra)

    def test_driver_gets_no_extra_pay(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 10, "role": "Driver", "no_extra_pay": True}}
        daily = daily_summary([punch("01", "09:00", 0), punch("01", "19:30", 1)])
        row = monthly_summary(employees, daily, "2026-09", date(2026, 10, 1))[0]
        self.assertEqual((row["extra_pay"], row["salary"]), (0, 85))
        short = daily_summary([punch("01", "09:00", 0), punch("01", "16:30", 1)])
        self.assertEqual(monthly_summary(employees, short, "2026-09", date(2026, 10, 1))[0]["salary"], 65)

    def test_hourly_pay_applies_from_the_edited_month(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 10, "role": "Normal", "pay_history": {"2026-10": 12}}}
        rows = [punch("28", "09:00", 0), punch("28", "17:30", 1),
                {**punch("01", "09:00", 0), "timestamp": "2026-10-01T09:00:00"},
                {**punch("01", "17:30", 0), "timestamp": "2026-10-01T17:30:00"}]
        daily = daily_summary(rows)
        self.assertEqual(monthly_summary(employees, daily, "2026-09", date(2026, 10, 3))[0]["salary"], 85)
        self.assertEqual(monthly_summary(employees, daily, "2026-10", date(2026, 10, 3))[0]["salary"], 102)
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "attendance.db")
            store.merge([], {"101": "Anil"})
            store.set_hourly_pay("101", 15, "2026-11")
            store.set_hourly_pay("101", 13, "2026-10")
            employee = store.snapshot()[0]["101"]
            self.assertEqual((employee["hourly_pay"], employee["pay_history"]), (DEFAULT_HOURLY_PAY, {"2026-10": 13}))
            self.assertEqual([hourly_rate(employee, month) for month in ("2026-09", "2026-10", "2026-12")],
                             [DEFAULT_HOURLY_PAY, 13, 13])

    def test_monthly_netting_and_remaining_days(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 10, "role": "Normal"}}
        rows = [punch("01", "09:00", 0), punch("01", "18:30", 1),
                punch("02", "09:00", 0), punch("02", "16:30", 1), punch("03", "09:00", 0)]
        summary = monthly_summary(employees, daily_summary(rows), "2026-09", date(2026, 9, 20))[0]
        self.assertEqual(summary["salary"], 170)
        self.assertEqual(summary["net_hours"], 0)
        self.assertEqual(summary["remaining_days"], 10)
        self.assertEqual(monthly_summary(employees, daily_summary(rows), "2026-08", date(2026, 9, 20))[0]["remaining_days"], 0)
        self.assertEqual(monthly_summary(employees, daily_summary(rows), "2026-08", date(2026, 9, 20))[0]["salary"], 0)

    def test_extra_pay_is_prorated_by_the_minute(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 60, "role": "Normal"}}
        for clock_out, extra, salary in [("17:31:20", 2, 512), ("17:28:00", -4, 506), ("17:30:20", 0, 510)]:
            with self.subTest(clock_out=clock_out):
                rows = [punch("01", "09:00", 0), {**punch("01", "09:00", 1), "timestamp": f"2026-09-01T{clock_out}"}]
                row = monthly_summary(employees, daily_summary(rows), "2026-09", date(2026, 10, 1))[0]
                self.assertEqual((row["extra_pay"], row["salary"]), (extra, salary))

    def test_absent_days_skip_sundays_today_and_testing_data(self):
        employees = {"101": {"name": "Anil", "hourly_pay": 10, "role": "Normal"}}
        rows = [punch("28", "09:00", 0), punch("30", "09:00", 0),
                {**punch("01", "09:00", 0), "timestamp": "2026-10-01T09:00:00"}]
        daily = daily_summary(rows)
        today = date(2026, 10, 5)
        self.assertEqual(monthly_summary(employees, daily, "2026-09", today)[0]["absent_days"], 1)
        self.assertEqual(monthly_summary(employees, daily, "2026-10", today)[0]["absent_days"], 2)
        self.assertEqual(monthly_summary(employees, daily, "2026-10", date(2026, 10, 4))[0]["absent_days"], 2)
        self.assertEqual(monthly_summary(employees, daily, "2026-08", today)[0]["absent_days"], 0)

    def test_formatting(self):
        self.assertEqual(format_duration(2.5, signed=True), "+2 hours 30 minutes")
        self.assertEqual(format_duration(-1.25, signed=True), "-1 hour 15 minutes")
        self.assertEqual(format_duration(0, signed=True), "0 minutes")
        self.assertEqual(format_duration(1 / 60), "1 minute")
        self.assertEqual(format_date(date(2026, 10, 3)), "03-10-2026")
        self.assertEqual(month_key(month_display("2026-09")), "2026-09")

    def test_manual_clock_times(self):
        day = date(2026, 9, 28)
        key = ("101", day)
        at = lambda clock: datetime.fromisoformat(f"2026-09-28T{clock}")
        single = [punch("28", "09:00", 0)]
        entry = daily_summary(single, {key: {"clock_in": None, "clock_out": at("18:00:00")}})[key]
        self.assertTrue(entry["complete"])
        self.assertEqual((entry["hours"], entry["issues"]), (9.0, "OK (manual)"))
        forgot_in = daily_summary([punch("28", "18:00", 0)], {key: {"clock_in": at("09:00:00"), "clock_out": None}})[key]
        self.assertEqual(forgot_in["hours"], 9.0)
        only_manual = daily_summary([], {key: {"clock_in": at("09:00:00"), "clock_out": at("17:30:00")}})[key]
        self.assertEqual(only_manual["hours"], 8.5)
        self.assertEqual(daily_summary(single)[key]["issues"], "Missing clock-out")
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "attendance.db")
            store.merge(single, {"101": "Anil"})
            store.set_manual_times("101", day, None, at("18:00:00"))
            self.assertEqual(store.manual_times(), {key: {"clock_in": None, "clock_out": at("18:00:00")}})
            with self.assertRaises(ValueError):
                store.set_manual_times("101", day, at("10:00:00"), at("09:00:00"))
            with self.assertRaises(ValueError):
                store.set_manual_times("101", day, datetime(2026, 9, 29, 9), None)
            store.set_manual_times("101", day, None, None)
            self.assertEqual(store.manual_times(), {})

    def test_roles_and_hourly_pay(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "attendance.db")
            self.assertEqual(store.roles(), ["Driver", "Cook", "Quality", "Cleaner", "Normal"])
            store.merge([], {"5": "Ravi"})
            self.assertEqual(store.snapshot()[0]["5"]["role"], "Normal")
            store.set_role("5", "driver")
            employee = store.snapshot()[0]["5"]
            self.assertEqual((employee["role"], employee["no_extra_pay"]), ("Driver", True))
            store.rename_role("Driver", "Chauffeur")
            employee = store.snapshot()[0]["5"]
            self.assertEqual((employee["role"], employee["no_extra_pay"]), ("Chauffeur", True))
            store.set_role_no_extra_pay("Chauffeur", False)
            self.assertFalse(store.snapshot()[0]["5"]["no_extra_pay"])
            store.rename_role("Normal", "Regular")
            self.assertEqual(store.role_details()[1], "Regular")
            store.rename_role("Regular", "Normal")
            store.add_role("Security", no_extra_pay=True)
            store.rename_role("Security", "Guard")
            store.set_role("5", "Guard")
            self.assertTrue(store.snapshot()[0]["5"]["no_extra_pay"])
            store.delete_role("Guard")
            self.assertEqual(store.snapshot()[0]["5"]["role"], "Normal")
            for action in (lambda: store.rename_role("Cook", "Quality"), lambda: store.delete_role("Normal"),
                           lambda: store.add_role("cook"), lambda: store.set_role("5", "Pilot"),
                           lambda: store.add_employee("6", "Sam", 10, "Pilot")):
                with self.assertRaises(ValueError):
                    action()
            store.add_employee("6", "Sam", 10, "Cook")
            self.assertEqual(store.snapshot()[0]["6"], {"name": "Sam", "hourly_pay": 10, "role": "Cook",
                                                      "no_extra_pay": False, "pay_history": {}})

    def test_daily_pay_migrates_to_hourly(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                "CREATE TABLE employees (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, daily_pay REAL NOT NULL DEFAULT 100);"
                "INSERT INTO employees VALUES ('7', 'Old Hand', 170);")
            connection.commit()
            connection.close()
            employees = AttendanceStore(path).snapshot()[0]
            self.assertEqual(employees["7"], {"name": "Old Hand", "hourly_pay": 20, "role": "Normal",
                                              "no_extra_pay": False, "pay_history": {}})

    def test_punch_mode_is_ignored(self):
        daily = daily_summary([punch("01", "09:00", 4), punch("01", "18:00", 1)])
        self.assertTrue(daily[("101", date(2026, 9, 1))]["complete"])

    def test_admins_retired_and_employees_managed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "attendance.db")
            store.merge([{**punch("28", "09:00", 0, "1"), "user_name": "Bijoy"},
                         {**punch("28", "17:30", 0, "1"), "user_name": "Bijoy"}],
                        {"1": "Bijoy", "2": "Aju", "3": "Treesa"})
            employees, rows = store.snapshot()
            self.assertEqual(list(employees), ["3"])
            self.assertEqual(rows, [])
            store.merge([], {"1": "Bijoy"})
            self.assertNotIn("1", store.snapshot()[0])
            store.add_employee("30", "  New   Person ", 120)
            self.assertEqual(store.snapshot()[0]["30"], {"name": "New Person", "hourly_pay": 120, "role": "Normal",
                                                       "no_extra_pay": False, "pay_history": {}})
            with self.assertRaises(ValueError):
                store.add_employee("30", "Duplicate")
            with self.assertRaises(ValueError):
                store.add_employee("31", "")
            store.remove_employee("30")
            store.merge([], {"30": "New Person"})
            self.assertNotIn("30", store.snapshot()[0])
            store.add_employee("30", "New Person")
            self.assertIn("30", store.snapshot()[0])

    def test_history_dedup_rates_and_atomic_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "attendance.db")
            records = [punch("28", "09:00", 0), punch("28", "17:30", 1)]
            store.merge(records, {"102": "Bindu"})
            store.set_hourly_pay("101", 150, "2026-09")
            store.merge(records)
            store.merge([punch("29", "09:00", 0), punch("27", "09:00", 0)])
            employees, rows = store.snapshot()
            self.assertEqual(len(rows), 3)
            self.assertEqual(employees["101"]["pay_history"], {"2026-09": 150})
            self.assertIn("102", employees)
            with self.assertRaises(ValueError):
                store.merge([punch("30", "09:00", 0), {"user_id": "101"}])
            self.assertEqual(len(store.snapshot()[1]), 3)
            for amount in [-1, float("nan"), float("inf")]:
                with self.assertRaises(ValueError):
                    store.set_hourly_pay("101", amount, "2026-09")
            store.set_setting("device_ip", "192.168.29.201")
            self.assertEqual(AttendanceStore(store.path).setting("device_ip"), "192.168.29.201")


class IntegrationTests(unittest.TestCase):
    def test_backup_appends_missing_punches_without_clearing(self):
        import Attendo_Sync as app
        with tempfile.TemporaryDirectory() as folder:
            credentials = Path(folder) / "key.json"
            credentials.write_text(json.dumps({"type": "service_account", "client_email": "test@example.invalid",
                                               "private_key": "test-only", "token_uri": "test-only"}))
            old = punch("01", "09:00", 0)
            new = punch("01", "17:30", 1)
            worksheet = Mock()
            existing = app.build_worksheet_rows([old])
            worksheet.get_all_values.side_effect = lambda: existing
            worksheet.append_rows.side_effect = lambda records, **kwargs: existing.extend(records)
            client = Mock()
            client.open_by_key.return_value.worksheet.return_value = worksheet
            with patch.object(app.gspread, "service_account", return_value=client):
                app.upload_to_google_sheets([old, new, new], credentials, "Backup", log=lambda text: None)
                self.assertEqual(len(existing), 3)
                app.upload_to_google_sheets([old, new], credentials, "Backup", log=lambda text: None)
                self.assertEqual(worksheet.append_rows.call_count, 1)
                worksheet.clear.assert_not_called()
                existing[0] = ["incompatible"]
                with self.assertRaises(ValueError):
                    app.upload_to_google_sheets([old], credentials, "Backup", log=lambda text: None)

    def test_excel_values_and_untrusted_names(self):
        from attendance_reports import export_workbook
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as folder:
            rows = [punch("01", "09:00", 0), punch("01", "18:30", 1)]
            employees = {"101": {"name": "=1+1", "hourly_pay": 10, "role": "Normal"},
                         "102": {"name": "Bindu", "hourly_pay": 10, "role": "Driver"}}
            path = Path(folder) / "report.xlsx"
            export_workbook(path, employees, rows, "2026-09", today=date(2026, 9, 1))
            workbook = load_workbook(path)
            try:
                self.assertEqual(len(workbook.sheetnames), 5)
                payroll = workbook["Monthly payroll"]
                self.assertEqual([cell.value for cell in payroll[1]][4:6], ["Worked days", "Absent days"])
                self.assertEqual([cell.value for cell in payroll[1]][8:11], ["Extra pay (INR)", "Remaining days", "Salary (INR)"])
                self.assertEqual((payroll["A2"].value, payroll["H2"].value, payroll["I2"].value, payroll["K2"].value),
                                 ("09-2026", "+1 hour", 20, 105))
                self.assertEqual(payroll["C2"].data_type, "s")
                self.assertEqual(workbook["Today"].max_row, 3)
                self.assertEqual(workbook["Today"]["A2"].value, "01-09-2026")
                self.assertEqual(workbook["Daily history"]["H2"].value, "+1 hour")
                self.assertEqual(workbook["Raw punches"].max_row, 3)
                self.assertEqual(workbook["Raw punches"]["C2"].value, "01-09-2026 09:00:00")
            finally:
                workbook.close()

    def test_fetch_failures_preserve_local_data(self):
        from dashboard import AttendoSyncApp
        import queue
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "history.sqlite3")
            records = [punch("28", "09:00", 0), punch("28", "17:30", 1)]
            worker = object.__new__(AttendoSyncApp)
            worker.store = store
            worker.events = queue.Queue()
            worker.fetch_attendance = Mock(return_value=(records, {"101": "Anil"}))
            worker.upload = Mock(side_effect=RuntimeError("Cloud unavailable"))
            settings = {"port": "4370", "credentials": "key", "worksheet": "Backup", "spreadsheet_id": "sheet"}
            worker._sync_worker("192.168.29.201", settings, True)
            self.assertEqual(len(store.snapshot()[1]), 2)
            messages = list(worker.events.queue)
            self.assertEqual(messages[-1][0], "error")
            self.assertIn("Local history saved", messages[-1][1])
            worker.fetch_attendance.side_effect = RuntimeError("Device offline")
            worker._sync_worker("192.168.29.201", settings, False)
            self.assertEqual(len(store.snapshot()[1]), 2)
            self.assertIn("existing history retained", list(worker.events.queue)[-1][1])
            worker.fetch_attendance.side_effect = None
            worker.upload.reset_mock()
            worker._sync_worker("192.168.29.201", settings, False)
            worker.upload.assert_not_called()
            self.assertEqual(len(store.snapshot()[1]), 2)

    def test_dashboard_at_high_dpi(self):
        for scaling in ("2.0", "2.6667", "3.3333"):
            with self.subTest(scaling=scaling):
                environment = os.environ.copy()
                environment["ATTENDO_TEST_TK_SCALING"] = scaling
                result = subprocess.run(
                    [sys.executable, "-m", "unittest",
                     "test_attendance_data.IntegrationTests.test_dashboard_tabs_filters_and_pay_edit", "-v"],
                    cwd=Path(__file__).resolve().parent, env=environment,
                    capture_output=True, text=True, timeout=90,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertNotIn("axes sizes collapsed", output)

    def test_dashboard_tabs_filters_and_pay_edit(self):
        import Attendo_Sync as app
        from PIL import ImageGrab
        with tempfile.TemporaryDirectory() as folder:
            store = AttendanceStore(Path(folder) / "history.sqlite3")
            store.merge(app.load_sample_records())
            defaults = {"device_ip": app.DEFAULT_DEVICE_IP, "port": "4370", "credentials": "",
                        "spreadsheet_id": app.SPREADSHEET_ID, "worksheet": app.WORKSHEET_NAME}
            root = app.ttkbootstrap.Window(themename="flatly")
            if os.getenv("ATTENDO_TEST_TK_SCALING"):
                root.tk.call("tk", "scaling", float(os.environ["ATTENDO_TEST_TK_SCALING"]))
            view = app.AttendoSyncApp(root, store, Mock(), Mock(), defaults, logo_path=app.find_resource(app.ICON_PNG))
            try:
                self.assertEqual(len(view.notebook.tabs()), 3)
                self.assertEqual(len(view.daily_table.get_children()), 5)
                self.assertEqual(view.daily_table.cget("columns"), ("name", "in", "out", "hours", "excess", "status"))
                view.manage_employees()
                root.update()
                dialog = [child for child in root.winfo_children() if isinstance(child, tkinter.Toplevel)][-1]
                dialog.destroy()
                past = min(view.date_picker.cget("values"), key=lambda text: datetime.strptime(text, "%d-%m-%Y"))
                self.assertNotEqual(past, format_date(date.today()))
                view.daily_date.set(past)
                view.refresh_daily()
                self.assertIn("OK", [view.daily_table.item(item)["values"][-1] for item in view.daily_table.get_children()])
                self.assertEqual(view.daily_table.item("101")["values"][4], "+34 minutes")
                view.daily_date.set("30-09-2026")
                view.refresh_daily()
                self.assertEqual(view.daily_table.item("101")["values"][-1], "Missing clock-out")
                view.daily_table.selection_set("101")
                view.edit_times()
                root.update()
                [child for child in root.winfo_children() if isinstance(child, tkinter.Toplevel)][-1].destroy()
                store.set_manual_times("101", date(2026, 9, 30), None, datetime(2026, 9, 30, 17, 20))
                view.refresh()
                self.assertEqual(view.daily_table.item("101")["values"][-1], "OK (manual)")
                view.kpi_month.set("09-2026")
                view.refresh_kpis()
                self.assertTrue(view.salary_value.cget("text").startswith("INR"))
                self.assertEqual(view.salary_value.cget("style"), "Metric.TLabel")
                self.assertGreaterEqual(int(app.ttkbootstrap.Style().lookup("Treeview", "rowheight")), 36)
                view.month.set("09-2026")
                view.refresh_month()
                names = [view.monthly_table.item(item)["values"][0] for item in view.monthly_table.get_children()]
                self.assertEqual(names, sorted(names, key=str.casefold))
                view.chart_period.set("Till date")
                view.draw_chart()
                self.assertEqual(len(view.chart_bars), len(view.employees))
                store.set_role("102", "Driver")
                view.refresh()
                self.assertEqual(len(view.chart_bars), len(view.employees) - 1)
                view.chart_period.set("09-2026")
                view.draw_chart()
                anil = [info for info in view.chart_info if info[0] == "Anil Kumar"][0]
                self.assertGreater(anil[1], 8)
                self.assertGreater(anil[2], 0)
                view.monthly_table.selection_set("101")
                with patch("dashboard.simpledialog.askfloat", return_value=150), patch("dashboard.messagebox.askokcancel", return_value=True):
                    view.edit_rate()
                self.assertEqual(store.snapshot()[0]["101"]["pay_history"], {"2026-09": 150})
                self.assertIn("150.00", view.monthly_table.item("101")["values"][-1])
                for width, height in [(1280, 860), (1000, 700), (1280, 860)]:
                    root.geometry(f"{width}x{height}+0+0")
                    for index in range(3):
                        view.notebook.select(index)
                        root.update()
                        view.canvas.draw()
                        self.assertTrue(view.progress.winfo_ismapped())
                        if index == 0:
                            self.assertTrue(view.navigation.winfo_ismapped())
                            self.assertGreater(view.navigation.winfo_height(), 20)
                            self.assertGreater(view.axes.get_window_extent().height, 110)
                            self.assertGreaterEqual(view.dashboard.winfo_height(), view.dashboard.winfo_reqheight())
                            view.dashboard_viewport.yview_moveto(1)
                            root.update()
                            self.assertAlmostEqual(view.dashboard_viewport.yview()[1], 1.0)
                            view.dashboard_viewport.yview_moveto(0)
                        for button in (view.fetch_btn, view.send_btn, view.export_btn, view.settings_btn):
                            self.assertTrue(button.winfo_ismapped())
                            self.assertGreater(button.winfo_width(), 50)
                            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), root.winfo_rootx() + root.winfo_width())
                        if os.getenv("ATTENDO_SCREENSHOT_DIR"):
                            output = Path(os.environ["ATTENDO_SCREENSHOT_DIR"])
                            output.mkdir(parents=True, exist_ok=True)
                            ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                                root.winfo_rootx() + root.winfo_width(),
                                                root.winfo_rooty() + root.winfo_height())).save(output / f"tab-{index}-{width}.png")
            finally:
                view.close()


if __name__ == "__main__":
    unittest.main()