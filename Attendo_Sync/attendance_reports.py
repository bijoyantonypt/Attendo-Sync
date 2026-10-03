"""Excel exports from the same summaries used by the dashboard."""

from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from attendance_data import (STANDARD_HOURS, daily_summary, format_date, format_datetime, format_duration,
                             month_display, monthly_summary)


def export_workbook(path, employees, rows, month, today=None, manual=None):
    today = today or date.today()
    daily = daily_summary(rows, manual)
    workbook = Workbook()
    workbook.remove(workbook.active)

    def sheet(title, headers, records):
        worksheet = workbook.create_sheet(title)
        worksheet.append(headers)
        for record in records:
            worksheet.append(record)
        for row in worksheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="center")
                if cell.row > 1 and cell.row % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F3F6F8")
                if isinstance(cell.value, float):
                    cell.number_format = "0.00"
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="167B91")
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for index, column in enumerate(worksheet.columns, 1):
            width = min(60, max(len(str(cell.value or "")) for cell in column) + 3)
            worksheet.column_dimensions[get_column_letter(index)].width = max(14, width)
        return worksheet

    def daily_records(day_filter):
        for (user_id, day), entry in sorted(daily.items(), key=lambda item: (
                item[0][1], employees[item[0][0]]["name"].casefold(), item[0][0])):
            if day_filter(day):
                yield [format_date(day), user_id, employees[user_id]["name"], employees[user_id]["role"],
                       entry["clock_in"].strftime("%H:%M:%S") if entry["clock_in"] else "",
                       entry["clock_out"].strftime("%H:%M:%S") if entry["clock_out"] else "",
                       round(entry["hours"], 4),
                       format_duration(entry["hours"] - STANDARD_HOURS, signed=True) if entry["complete"] else "",
                       entry["issues"]]

    daily_headers = ["Date", "Employee ID", "Employee", "Role", "Clock-in", "Clock-out", "Hours",
                     "Excess / deficit", "Status"]
    today_rows = list(daily_records(lambda day: day == today))
    recorded_ids = {row[1] for row in today_rows}
    today_rows.extend([format_date(today), user_id, employee["name"], employee["role"], "", "", 0, "", "No punches"]
                      for user_id, employee in employees.items() if user_id not in recorded_ids)
    today_rows.sort(key=lambda row: (row[2].casefold(), row[1]))
    sheet("Today", daily_headers, today_rows)
    sheet("Monthly payroll", ["Month", "Employee ID", "Employee", "Role", "Worked days", "Absent days",
                              "Total hours", "Excess / deficit", "Extra pay (INR)", "Remaining days",
                              "Salary (INR)", "Hourly pay (INR)"],
          ([month_display(month), row["user_id"], row["name"], row["role"], row["days"], row["absent_days"],
            row["hours"], format_duration(row["net_hours"], signed=True), row["extra_pay"],
            row["remaining_days"], row["salary"], row["hourly_pay"]]
           for row in monthly_summary(employees, daily, month, today)))
    sheet("Daily history", daily_headers, daily_records(lambda day: True))
    sheet("Raw punches", ["Employee ID", "Employee", "Timestamp", "Status", "Punch"],
          ([row["user_id"], row["user_name"], format_datetime(datetime.fromisoformat(row["timestamp"])),
            row["status"], row["punch"]] for row in rows))
    sheet("Payroll policy", ["Setting", "Value"], [
        ["Report month", month_display(month)], ["Generated on", format_date(today)], ["Standard day", "8.5 hours"],
        ["Base pay", "Completed days x 8.5 hours x hourly pay of that month"],
        ["Net hours", "Excess hours minus deficit hours: completed-day hours minus completed days x 8.5"],
        ["Extra pay", "(Excess minutes - deficit minutes) x (hourly pay / 60) x 2; negative when hours fall short"],
        ["Salary", "Base pay + extra pay"],
        ["No-extra-pay roles (Driver)", "No extra pay for extra hours; only a deficit reduces pay; excluded from average-hours figures"],
        ["Remaining days", "Calendar days left in the month after today"],
        ["Absent days", "Days from 28-09-2026 up to yesterday, excluding Sundays, with no punches"],
        ["Incomplete days", "Missing clock-in or clock-out; excluded from payroll until completed"],
        ["No punches", "No pay and no deficit; no work calendar is configured"],
        ["Hourly pay changes", "A new rate applies from the month it was set onward; earlier months keep their previous rate"],
        ["Punch interpretation", "First scan of the day = clock-in; last scan = clock-out (at least 60 minutes later, otherwise a double-scan); hours = clock-out minus clock-in"],
        ["Manual edits", "A clock-in or clock-out entered by hand replaces the device scan; status shows OK (manual)"],
        ["Data start", "Punches before 28-09-2026 were testing data and are excluded"],
        ["Status", "OK when both clock-in and clock-out exist, otherwise Missing clock-in / Missing clock-out"],
        ["Overnight shifts", "Not paired across midnight; each calendar day is evaluated on its own"],
    ])
    path = Path(path)
    with NamedTemporaryFile(dir=path.parent, suffix=".xlsx", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        workbook.save(temporary_path)
        temporary_path.replace(path)
    finally:
        workbook.close()
        temporary_path.unlink(missing_ok=True)