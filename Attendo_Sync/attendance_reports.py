"""Excel exports from the same summaries used by the dashboard."""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from attendance_data import daily_summary, monthly_summary


def export_workbook(path, employees, rows, month, today=None):
    today = today or date.today()
    daily = daily_summary(rows)
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
                yield [day.isoformat(), user_id, employees[user_id]["name"],
                       entry["clock_in"].strftime("%H:%M:%S") if entry["clock_in"] else "",
                       entry["clock_out"].strftime("%H:%M:%S") if entry["clock_out"] else "",
                       round(entry["hours"], 4), entry["issues"]]

    daily_headers = ["Date", "Employee ID", "Employee", "Clock-in", "Clock-out", "Hours", "Status"]
    today_rows = list(daily_records(lambda day: day == today))
    recorded_ids = {row[1] for row in today_rows}
    today_rows.extend([today.isoformat(), user_id, employee["name"], "", "", 0, "No punches"]
                      for user_id, employee in employees.items() if user_id not in recorded_ids)
    today_rows.sort(key=lambda row: (row[2].casefold(), row[1]))
    sheet("Today", daily_headers, today_rows)
    sheet("Monthly payroll", ["Month", "Employee ID", "Employee", "Paid days", "Total hours",
                              "Excess / deficit hours", "Extra days", "Review days", "Salary (INR)", "Daily pay (INR)"],
          ([month, row["user_id"], row["name"], row["days"], row["hours"], row["net_hours"], row["extra_days"],
            row["review_days"], row["salary"], row["daily_pay"]]
           for row in monthly_summary(employees, daily, month, today)))
    sheet("Daily history", daily_headers, daily_records(lambda day: True))
    sheet("Raw punches", ["Employee ID", "Employee", "Timestamp", "Status", "Punch"],
          ([row.get(key) for key in ("user_id", "user_name", "timestamp", "status", "punch")] for row in rows))
    sheet("Payroll policy", ["Setting", "Value"], [
        ["Report month", month], ["Generated on", today.isoformat()], ["Standard day", "8.5 hours"],
        ["Base pay", "Completed days x employee daily pay"],
        ["Net hours", "Completed-day hours minus completed days x 8.5"],
        ["Extra days", "Positive net hours / 8.5 (fractional days)"],
        ["Overtime pay", "Extra days x daily pay x 2"],
        ["Deficit deduction", "Negative net hours / 8.5 x daily pay"],
        ["Incomplete days", "Only one scan in the day (no clock-out); excluded from payroll, shown as review days"],
        ["No punches", "No pay and no deficit; no work calendar is configured"],
        ["Daily pay changes", "Current employee rate applies to all months"],
        ["Punch interpretation", "First scan of the day = clock-in; last scan = clock-out (at least 60 minutes later, otherwise a double-scan); hours = clock-out minus clock-in"],
        ["Data start", "Punches before 28 September 2026 were testing data and are excluded"],
        ["Status", "OK when both clock-in and clock-out exist, otherwise Missing clock-out"],
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