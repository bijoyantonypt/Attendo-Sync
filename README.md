# Attendo Sync

## Current Desktop Dashboard

The application now runs attendance reporting and payroll locally. Google Sheets
is an optional raw-history backup, not a requirement for viewing or calculating data.
The original eSSL device connection routine is unchanged.

### Run

For a target PC, use the standalone **Windows 10/11 x64** executable at
`Attendo_Sync/dist/Attendo_Sync.exe`. Transfer just that EXE and double-click it.
Python, pip, Microsoft Excel, eSSL software, and separately installed Python libraries
are not required. GUI resources, charts, Excel writing, SQLite, and device libraries
are bundled. The EXE extracts its runtime into the user's temporary directory on launch.
The PC must allow running the application and writing to its temp and local-app-data
directories. No administrator privileges are requested by the app.

The target PC must reach the device IP and port (normally `192.168.29.201:4370`).
The unchanged device routine also requires ping reachability. Network isolation,
firewall rules, unsupported device protocols, or device passwords can prevent connection.
Local fetching and reporting need no internet. Google backup alone requires internet,
your service-account JSON key, and spreadsheet access; secrets are not embedded in the EXE.
Local history belongs to each PC and is not automatically synchronized between PCs.

This is not a universal binary for macOS, Linux, 32-bit Windows, or every eSSL model.
Test it on the intended Windows PC before production use. Windows SmartScreen or
corporate application policies may require approval for an unsigned executable.
Do not disable security software to run it.

The instructions below apply only to developers running from source or rebuilding.
The build script creates an isolated `.build-venv`, runs the tests, and packages a
single-file EXE so unrelated packages on the build PC are not included.

Use a full Python 3.10+ installation with Tkinter on Windows, not an embedded Python runtime.
From the repository directory:

```powershell
python -m pip install -r Attendo_Sync/Requirements.txt
python Attendo_Sync/Attendo_Sync.py
```

To preview isolated sample data without a device or Google access:

```powershell
python Attendo_Sync/Attendo_Sync.py --demo
```

The sample dates are shifted to the latest three days when the demo database is
first created. Demo mode disables fetching and cloud backup and uses a separate database.

### Screens And Actions

- **Dashboard**: salary payable and average hours per employee for a selectable month
  (default current month; past months show their own totals). **Manage Employees** adds
  (device ID, name, hourly pay, role), removes employees, changes any employee's role, and
  defines roles (default Driver, Cook, Quality, Cleaner, Normal). **Manage roles** adds, renames,
  and deletes any role, and a checkbox marks roles that get no extra pay (Driver by default). The
  default role for new employees (Normal) can be renamed but not deleted; deleting another role moves
  its employees to the default role. An employee's role changes as soon as it is picked in the list.
  Removed employees are hidden from views, payroll, exports,
  and backups, and device fetches do not bring them back. The bar chart shows each employee's
  average hours worked per day (completed days only) for the selected month or **Till date**.
  Hover a bar for details. No-extra-pay roles are excluded from the chart and the average-hours card.
  Punches before 28-09-2026 were testing data and are not shown, exported, or backed up.
- **Daily Attendance**: pick any recorded date (default today). Shows alphabetical employee names,
  clock-in (first scan), clock-out (last scan), hours worked, excess / deficit against 8.5 hours
  (for example `+2 hours 30 minutes`), and status (OK / OK (manual) / Missing clock-in / Missing
  clock-out). Select an employee and use **Edit clock-in / clock-out** (or double-click the row) to
  enter a missing time by hand; a manual time replaces the device scan and a cleared field
  goes back to the scan.
- **Monthly Attendance**: select any recorded month. View role, completed paid days, total
  hours, excess / deficit in hours and minutes, extra pay, remaining days in the month, and salary.
  Double-click the final **Hourly pay (edit)** cell, press Enter on a selected employee, or use the
  right-click menu to change their rate from the selected month onward (earlier months keep their rate). Horizontal scrolling exposes remaining columns in smaller windows.
- Dates are shown as DD-MM-YYYY and months as MM-YYYY, in the app and the Excel export.
- **Fetch & Update**: fetch from the configured IP (default `192.168.29.201`, port
  `4370`), merge punches into local history, and refresh all views. No Google key is needed.
- **Fetch & Send**: perform the same local update, then back up all locally retained
  punches to Google Sheets. Existing backup rows are never cleared; already-backed-up
  punches are skipped. A cloud failure does not discard the local fetch.
- **Excel Export**: save an `.xlsx` workbook containing today's attendance, the
  selected month's payroll, all daily history, all raw punches, and payroll policy.
- **Settings**: change the device port, service-account JSON path, spreadsheet ID,
  and backup worksheet. Share the spreadsheet with the service account as an editor.
  The existing six-column backup schema is supported (header names are matched ignoring case
  and spaces); an incompatible tab is rejected without modification and the error shows the
  header found. Enter a new worksheet name in Settings to have the app create a fresh tab. Run only one backup writer against a worksheet at a time.

### Payroll Rules

Every employee has an editable **hourly pay** (new employees default to INR 12; databases created
before hourly pay was introduced are converted from the old daily rate divided by 8.5).

- The device sends every scan with the same punch mode, so the **first scan of a day is the
  clock-in and the last scan is the clock-out**. Hours = clock-out minus clock-in. Status is
  **OK** when both exist; a lone scan (or scans under 60 minutes apart, treated as a double-scan)
  is **Missing clock-out**. Manually entered times replace the scans.
- Days without both times are incomplete and excluded from paid days and payroll until completed.
- Net hours = excess minus deficit = completed-day hours minus `8.5 x completed days`.
- Extra pay = net hours x hourly pay x **2** for the month (negative when hours fall short).
  Roles marked no-extra-pay (Driver) get no extra pay; only a deficit reduces their pay.
- Salary = completed days x 8.5 x hourly pay + extra pay (never below zero).
- Excess and deficit hours offset each other within the selected month. For example, at
  INR 10/hour, one 9.5-hour day pays INR 105 (85 base + 20 extra); one 7.5-hour day pays INR 65.
- Remaining days = calendar days left in the month after today (0 for past months).
- Days with no punches have no pay and no deficit. No holiday, leave, or scheduled
  work calendar is assumed. No-extra-pay roles are left out of average-hours figures.
- A rate edit made while viewing a month applies from that month onward and replaces any later
  rate changes; earlier months keep their previous rate. Finalized payroll is not locked, so
  changing hours or manual times still recalculates a month.

### Storage And Verification

History, employee rates, and connection settings are stored in
`%LOCALAPPDATA%\AttendoSync\attendance.sqlite3`; demo data uses `demo.sqlite3`.
Use `--data-dir PATH` to choose another writable location. Back up the SQLite file
while the app is closed to preserve rates and settings; Google Sheets stores raw
punch history only. Protect local files and exported workbooks as employee data.
The credential file itself is never copied into the database or bundled into the EXE.
An existing `attendance_export.json` beside the application is imported once on startup.

```powershell
python -m unittest discover -s Attendo_Sync -p "test_attendance_data.py" -v
```

Tests cover payroll, persistence, backup deduplication, Excel values, offline failure
recovery, and real Tk window construction. They need a desktop session but do not
contact the device or Google. Build the Windows EXE with `Attendo_Sync\build_exe.bat`;
the output is `Attendo_Sync\dist\Attendo_Sync.exe`.

## Earlier Architecture Proposal

The sections below are retained as historical planning material. References to
Apps Script, Drive reporting, cloud-primary storage, and planned modules below
are not the behavior of the current local desktop dashboard described above.

<div align="center">

🏢 **Employee Attendance Tracking & Payroll System** 📊

A desktop application that syncs data from ESSL biometric devices, calculates attendance patterns, computes daily wages, and provides visual analytics.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

</div>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Core Architecture](#core-architecture)
- [Implementation Plan](#implementation-plan)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Security Best Practices](#security-best-practices)
- [Deployment and Testing](#deployment-and-testing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## 🎯 Overview

Attendo Sync is an intelligent attendance management solution designed for small to medium-sized organizations using ESSL biometric attendance devices. It automates the entire workflow:

1. **Data Collection**: Fetches attendance records directly from ESSL devices via TCP/IP
2. **Intelligent Processing**: Applies logic for split shifts, detects anomalies, and flags irregularities
3. **Payroll Calculation**: Computes daily wages based on hours worked and customized hourly rates
4. **Visual Analytics**: Provides interactive dashboards with trend analysis
5. **Cloud Sync**: Stores processed results in Google Sheets and Drive-based reporting layers

The application runs locally on Windows machines and does not require internet access for the local device fetch itself.

---

## 🏗️ Core Architecture

```text
Local Windows PC
  ├─ eSSL device connection (IP-based retrieval)
  │    └─ fetch raw attendance records
  ├─ validation and transformation layer
  ├─ Google Cloud authentication
  ├─ Google Sheets / Drive storage
  └─ Google Apps Script dashboard
```

### Important requirement

The current IP-based eSSL extraction logic is the boundary of the device integration and should remain unchanged while the rest of the system is implemented around it.

```python
from zk import ZK


def fetch_raw_attendance(device_ip, port=4370, timeout=10):
    zk = ZK(device_ip, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = zk.connect()
    try:
        users = conn.get_users()
        user_map = {u.user_id: u.name for u in users}
        attendance = conn.get_attendance()
        return attendance, user_map
    finally:
        conn.disconnect()
```

This logic may be used as-is while the application adds validation, formatting, upload, and visualization layers around it.

---

## 🧭 Implementation Plan

### Phase 1 — Google Cloud and Authentication

1. Create a dedicated Google Workspace or business Gmail account.
2. Open a Google Cloud project for the dashboard system.
3. Create a service account for automation.
4. Enable Google Sheets API and Google Drive API.
5. Download the JSON credentials file and store it securely in a protected local folder.
6. Grant least-privilege permissions to the service account.
7. Keep keys out of version control and out of public folders.

Example configuration:

```python
import os

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    r"C:\secure\attendance\gcloud\attendance-sync-sa.json"
)
```

### Phase 2 — Storage Design

Create a folder structure such as:

```text
Attendance Dashboard/
  01_Raw_Data/
    attendance_raw_YYYYMMDD.csv
    employee_master.csv
  02_Processed_Data/
    attendance_processed.csv
    daily_summary.csv
  03_Reports/
    dashboard_snapshot.pdf
  04_Logs/
    attendance_sync.log
```

Create Google Sheets with these tabs:

- Employees
- Attendance_Raw
- Attendance_Processed
- Daily_Summary
- Exceptions
- Settings

Recommended raw schema:

| Column | Description |
|---|---|
| employee_id | Unique employee ID |
| employee_name | Employee display name |
| date | Attendance date |
| clock_in | Recorded entry time |
| clock_out | Recorded exit time |
| total_hours | Calculated hours worked |
| imported_at | Sync timestamp |
| source_ip | Device IP |
| sync_status | Success / retry / failed |

### Phase 3 — Apps Script Dashboard

1. Create a dashboard sheet and define tabs for KPIs, trends, exceptions, and attendance summaries.
2. Write Apps Script to read processed attendance data from Sheets.
3. Build summary charts and visuals.
4. Add scheduled triggers for automatic refresh.
5. Log refresh errors and alert administrators when needed.

Example Apps Script:

```javascript
function refreshAttendanceData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Attendance_Processed');

  if (!sheet) {
    Logger.log('Attendance_Processed sheet not found');
    return;
  }

  const data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    Logger.log('No rows to process');
    return;
  }

  buildDashboardSummary(data);
  Logger.log('Dashboard refreshed successfully');
}

function buildDashboardSummary(data) {
  const summary = {};

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const date = row[2];
    const hours = Number(row[5]) || 0;

    if (!summary[date]) summary[date] = 0;
    summary[date] += hours;
  }

  const target = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Overview');
  const rows = [['Date', 'Total Hours']];
  Object.entries(summary).forEach(([date, total]) => rows.push([date, total]));

  target.clear();
  target.getRange(1, 1, rows.length, 2).setValues(rows);
}
```

### Phase 4 — Local Windows EXE Development

1. Keep the eSSL fetch function intact.
2. Validate the raw attendance response.
3. Normalize employee names, dates, and times.
4. Remove duplicates or suspicious records.
5. Upload validated rows to Google Sheets.
6. Write logs for all steps and errors.
7. Package the app as a Windows executable.

Example validation pipeline:

```python
from datetime import datetime


def normalize_attendance(attendance, user_map):
    cleaned = []
    for record in attendance:
        if record is None:
            continue

        cleaned.append({
            "employee_id": record.user_id,
            "employee_name": user_map.get(record.user_id, "Unknown"),
            "date": record.timestamp.date().isoformat(),
            "time": record.timestamp.strftime("%H:%M:%S"),
            "source_ip": "192.168.1.100",
            "imported_at": datetime.utcnow().isoformat(timespec="seconds"),
        })
    return cleaned
```

### Phase 5 — Testing and Deployment

1. Validate the data fetch in a local network environment.
2. Run unit tests for cleaning and transformation logic.
3. Test Google API upload with a service account.
4. Run a full end-to-end check using sample attendance data.
5. Package the app as `AttendoSync.exe` with PyInstaller.
6. Deploy it to the target Windows workstation.
7. Confirm the dashboard updates via Apps Script trigger.

### Phase 6 — Operations and Maintenance

- Keep a monthly backup of raw and processed data.
- Review logs each week.
- Update the service account and API access regularly.
- Schedule regular dashboard refresh checks.
- Maintain a rollback plan before releasing changes.

---

## 💻 System Requirements

### Hardware

- Processor: Intel Core i3 or equivalent (i5 recommended)
- RAM: 4 GB minimum (8 GB recommended)
- Storage: 500 MB free space
- Network: Local network connectivity to the ESSL device

### Software

- Windows 10 or later
- Python 3.8+
- Google Cloud project with activated APIs
- Google Sheets and Drive access
- PyInstaller for executable packaging

### Network Configuration

- Device IP must be reachable from the host machine
- Port 4370 is commonly used, depending on the device configuration
- Firewall rules must allow the required local communication

---

## 🚀 Installation

### Quick Start

1. Clone the repository.
2. Create a Python virtual environment.
3. Install dependencies from the project requirements file.
4. Configure the Google service account JSON path.
5. Set the eSSL device IP in the application settings.
6. Run the Windows EXE or the local Python entry point.

### Example

```bash
python -m venv venv
venv\Scripts\activate
pip install -r Requirements.txt
```

---

## ⚙️ Configuration

Set these values before deployment:

- device IP address
- polling interval
- Google Sheet IDs
- Drive folder IDs
- service account file path
- default hourly rate and shift settings

Example config file:

```json
{
  "device_ip": "192.168.1.100",
  "port": 4370,
  "timeout": 10,
  "spreadsheet_id": "YOUR_SPREADSHEET_ID",
  "google_service_account_file": "C:/secure/attendance/gcloud/attendance-sync-sa.json",
  "default_hourly_rate": 75,
  "standard_hours": 9
}
```

---

## 🔐 Security Best Practices

- Store all API credentials outside the Git working directory.
- Use least-privilege roles for service accounts.
- Restrict access to the shared spreadsheet and drive folder.
- Log without exposing credentials or internal tokens.
- Validate all uploaded data before writing to Sheets.
- Rotate service account keys regularly.
- Never share raw JSON files through email or public channels.

---

## 🚚 Deployment and Testing

### Deployment checklist

- Confirm device IP reachability on the LAN
- Verify the port is open and reachable
- Test the service account permissions in Sheets and Drive
- Run a sample import with realistic data
- Confirm the dashboard reflects expected results
- Validate error logging and retry logic

### Testing procedure

1. Local unit test for date formatting and validation
2. LAN test for raw device record retrieval
3. Test for duplicate punch detection
4. Test Google Sheets append reliability
5. Test dashboard refresh and chart creation
6. Perform a final pilot run using real employee records

### Troubleshooting

- Device not reachable: verify IP and local network access
- Google permissions failing: check the JSON key and account rights
- Empty dashboard: confirm processed data has rows and trigger is active
- Duplicate records: deduplicate timestamps before writing to the report sheet
- Missing employee names: validate user map data from the device

---

## 📜 License

This project is distributed under the MIT License unless otherwise stated.

---

## ✅ Final Deliverable Summary

The final solution should include:

- a Windows executable app for local attendance collection
- secure Google Cloud integration
- a Sheets-based data repository
- App Script-powered dashboard visualization
- testing, logging, and maintenance documentation
- a design that preserves the existing eSSL IP-based fetch logic until a real device is available for testing

This keeps the core attendance retrieval layer stable while allowing the rest of the workflow to be implemented, validated, and deployed safely.