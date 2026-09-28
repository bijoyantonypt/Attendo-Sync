# Interactive Employee Attendance Dashboard – Full Implementation Plan

## 1. Project Overview

Build a Windows desktop application that pulls attendance data from an eSSL biometric terminal on the local network, uploads the cleaned result to Google Cloud storage and Google Sheets, and then visualizes the data in a dashboard using Google Apps Script. The system should be reliable, auditable, and easy to operate by a non-technical user.

This project has three major layers:

1. Local Windows EXE application
2. Google Cloud / Google Sheets data layer
3. Google Apps Script dashboard layer

The core eSSL communication logic must remain unchanged. The fetch routine should continue to use the device IP address to query the attendance device exactly as it already does, then the rest of the workflow should wrap around that result for cleaning, validation, and upload.

> Critical requirement: Do not rewrite the existing IP-based eSSL fetch logic. Keep the device connection and raw record retrieval logic intact. Only add validation, normalization, logging, upload, and reporting around it.

---

## 2. Scope and Architecture

### High-level system flow

1. Windows machine connects to eSSL device using the configured device IP.
2. The EXE collects raw attendance records.
3. Data is validated, normalized, and merged with employee metadata.
4. Records are uploaded to Google Sheets or Drive-based data repositories.
5. Apps Script loads that data and builds charts, summaries, and status widgets.
6. A scheduled refresh keeps the dashboard updated automatically.
7. Logs and error alerts provide operational visibility.

### Main components

- Local EXE application (Python + tkinter or PySide if needed)
- eSSL device connector (existing IP-based connection)
- Google Cloud service account authentication
- Google Sheets data repository
- Apps Script dashboard automation
- Scheduled triggers and monitoring

---

## 3. Phase 1 — Google Cloud and Authentication Setup

### Step 1: Create the Google account and organization structure

- Use a dedicated business Gmail or Google Workspace account.
- Create or identify a company-owned Google Cloud project.
- Define naming conventions such as:
  - Project: `attendance-dashboard-prod`
  - Service account: `attendance-sync-sa`
  - Folder: `Attendance Dashboard / Raw Data`

### Step 2: Initialize the Google Cloud project

1. Visit Google Cloud Console.
2. Create a new project.
3. Enable billing if required for the APIs used.
4. Set up a project ID and note it for configuration.
5. Keep all credentials in a safe place and never commit them to source control.

### Step 3: Create a service account

Create a service account with these roles or equivalent least-privilege permissions:

- Google Sheets: edit access to target spreadsheets
- Google Drive: folder creation and file management
- Cloud IAM: minimal permissions for service usage

Example service account naming:

```text
attendance-sync-sa@attendance-dashboard-prod.iam.gserviceaccount.com
```

### Step 4: Enable required APIs

Enable these APIs in the project:

- Google Sheets API
- Google Drive API
- Google Cloud Logging API (optional but useful)

### Step 5: Generate credentials

- Create a JSON key for the service account.
- Download it securely to a protected folder such as:

```text
C:\secure\attendance\gcloud\attendance-sync-sa.json
```

- Restrict local file permissions to authorized users only.
- Store the file outside the project repository and never in Git.

### Step 6: Security practices

- Use environment variables or encrypted config files.
- Do not hardcode the credentials JSON path in public repos.
- Rotate service account keys periodically.
- Use least privilege instead of broad editor roles.

Example configuration snippet:

```python
import os

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    r"C:\secure\attendance\gcloud\attendance-sync-sa.json"
)
```

---

## 4. Phase 2 — Database and Storage Configuration

### Step 1: Decide the storage model

Use Google Sheets as the primary operational repository and Google Drive as the folder and file organization layer.

Recommended structure:

```text
Attendance Dashboard/
  01_Raw_Data/
    attendance_raw_YYYYMMDD.xlsx
    employee_master.csv
  02_Processed_Data/
    attendance_processed.csv
    attendance_daily_summary.csv
  03_Reports/
    dashboard_snapshot.pdf
  04_Logs/
    app_log.txt
    error_log.txt
```

### Step 2: Create the Google Sheets data repository

Create separate sheets for each logical data set:

- `Employees`
- `Attendance_Raw`
- `Attendance_Processed`
- `Daily_Summary`
- `Exceptions`
- `Settings`

Example schema for `Attendance_Raw`:

| Column | Description |
|---|---|
| employee_id | Unique ID from the device |
| employee_name | Employee display name |
| date | Attendance date |
| clock_in | First in-punch |
| clock_out | Last out-punch |
| total_hours | Calculated hours |
| source_ip | eSSL device IP |
| imported_at | Upload timestamp |
| sync_status | Success / failed / retry |

Example schema for `Employees`:

| Column | Description |
|---|---|
| employee_id | Unique employee ID |
| name | Employee name |
| department | Department or team |
| shift_type | Morning / evening / flexible |
| hourly_rate | Default wage rate |
| active | Active or inactive |

### Step 3: Folder sharing and permissions

- Share the drive folder with the service account email.
- Grant the service account edit access only to required folders.
- Keep read access limited to managers or dashboard viewers.
- Use a separate shared spreadsheet for dashboard users.

---

## 5. Phase 3 — Google Apps Script Dashboard Development

### Goal

Google Apps Script should read the processed dataset, compute dashboard views, refresh automatically, and present a clear interactive UI.

### Step 1: Create the dashboard spreadsheet

- Create a new Google Sheet.
- Add tabs: `Overview`, `Daily Trend`, `Department View`, `Exceptions`, `Settings`.
- Add charts using the processed attendance summary.

### Step 2: Create Apps Script functions

Example Apps Script skeleton:

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
    Logger.log('No attendance rows found');
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

### Step 3: Build visualization dashboard

Create charts for:

- Total hours by date
- Late arrivals and early exits
- Department-wise attendance summary
- Exception trends and duplicate punches
- Monthly attendance performance

### Step 4: Schedule refresh

Set a time-driven trigger:

- Daily refresh at 6:00 AM
- or every 2 hours depending on business need

Example trigger logic:

```javascript
function createDailyTrigger() {
  ScriptApp.newTrigger('refreshAttendanceData')
    .timeBased()
    .everyDays(1)
    .atHour(6)
    .create();
}
```

### Step 5: Error handling and logging

- Log failures with timestamps and step names.
- Keep a dedicated `Logs` sheet or Drive log file.
- If the data source is empty, send a notification instead of failing silently.
- Validate sheets before chart creation.

---

## 6. Phase 4 — Windows EXE Development

### Step 1: Keep the IP-based device fetch layer unchanged

The existing extraction logic should stay intact. It is the layer that connects to the eSSL device using the configured IP and retrieves raw attendance records.

Example pattern that must remain stable:

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

This logic should not be replaced or restructured unless the device specification changes later. The project currently assumes the device is reachable on the local network by IP address, and the behavior should remain unchanged while the surrounding system is built around it.

### Step 2: Build the local processing pipeline

After the raw records are retrieved:

1. Validate that the device response is not empty.
2. Normalize date and time formats.
3. Remove duplicates.
4. Filter suspicious or incomplete entries.
5. Match employee IDs to names.
6. Compute totals and exceptions.
7. Upload data to Google Sheets.

### Step 3: Example processing flow

```python
import os
import json
from datetime import datetime


def validate_record(record):
    if record is None:
        return False
    return True


def normalize_attendance(attendance, user_map):
    cleaned = []
    for record in attendance:
        if not validate_record(record):
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

### Step 4: Google Cloud upload logic

Use a service account JSON file to authenticate and write rows to the right sheet.

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build


def connect_google_sheets(json_path, spreadsheet_id):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = service_account.Credentials.from_service_account_file(
        json_path, scopes=scopes
    )
    service = build('sheets', 'v4', credentials=credentials)
    return service, credentials


def append_rows_to_sheet(service, spreadsheet_id, range_name, rows):
    body = {"values": rows}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()
```

### Step 5: Error handling and retry logic

Implement retry wrappers for transient failures:

```python
import time


def retry(operation, retries=3, delay=5):
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt == retries:
                raise exc
            time.sleep(delay)
```

Use this around:

- device connection
- raw attendance fetch
- Google API upload
- sheet append calls

### Step 6: Logging and status reporting

Add a simple local log file to record:

- start time
- device IP
- record count
- upload success/failure
- retry attempts
- exception tracebacks

Example log format:

```python
import logging

logging.basicConfig(
    filename=r"C:\logs\attendance_sync.log",
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
```

### Step 7: Packaging the Windows EXE

Use PyInstaller to build the executable:

```bat
pyinstaller --onefile --windowed --name AttendoSync main.py
```

Create a folder structure:

```text
dist/
  AttendoSync.exe
  config.json
  logs/
```

---

## 7. Phase 5 — Deployment, Testing, and Operations

### Step 1: Testing strategy

Perform tests in layers:

1. Unit tests for normalization and validation logic
2. Integration tests for Google Sheets upload
3. LAN tests for eSSL device connectivity
4. Functional test for dashboard charts
5. End-to-end run with real attendance data

Recommended checks:

- Empty dataset handling
- Duplicate record detection
- Holidays / weekends
- Missing employee mapping
- Google API failure recovery
- Dashboard refresh reliability

### Step 2: Deployment checklist

- Ensure the target Windows host has access to the eSSL IP address
- Confirm the firewall allows TCP connectivity
- Store service account credentials in a secure folder
- Test the scheduler or automatic trigger
- Check that the Google permissions allow spreadsheet editing
- Confirm the dashboard is viewable by intended stakeholders

### Step 3: Troubleshooting guide

Common issues:

- Device unreachable: verify IP, network, port, and credentials
- Google auth failures: check the service account JSON and IAM permissions
- Empty dashboard: inspect the processed sheet and refresh trigger
- Duplicate uploads: enforce unique keys or timestamps
- Missing employees: verify employee master sheet mapping

### Step 4: Maintenance strategy

- Version the EXE and the Apps Script project together
- Keep configuration values in one place
- Archive raw data snapshots monthly
- Review logs weekly
- Back up the Google Sheet exports periodically
- Create a rollback procedure before making major updates

---

## 8. Security Best Practices

- Never store service account JSON files inside the repo
- Restrict file permissions on Windows
- Use environment variables for secrets
- Validate all incoming records before writing them to Google Sheets
- Limit service account access to only needed APIs and sheets
- Avoid shared personal Gmail accounts for production automation
- Log without exposing sensitive credentials

---

## 9. Recommended Delivery Sequence

1. Prepare Google Cloud project and service account
2. Create Google Sheets and folder structure
3. Build the Apps Script dashboard skeleton
4. Test data refresh logic in Sheets
5. Preserve the existing eSSL device fetch logic
6. Add validation, formatting, and upload logic around it
7. Package the EXE
8. Deploy to the target Windows PC
9. Run end-to-end verification
10. Monitor logs and refine dashboard metrics

---

## 10. Final Implementation Notes

The key design principle is to keep the device access logic stable while building a clean integration layer around it. The fetch from the eSSL system by IP is the system boundary; everything else should be treated as processing, validation, storage, visualization, and monitoring.

This approach minimizes regression risk, preserves compatibility with the current local network device, and allows future improvements without breaking the connection path that retrieves the raw attendance data.

---

## 11. Suggested Project Timeline

### Week 1
- Google Cloud setup
- Service account configuration
- Sheets structure creation

### Week 2
- Apps Script dashboard
- Trigger creation
- Data quality checks

### Week 3
- EXE development
- Local validation pipeline
- Google upload module

### Week 4
- Integration testing
- Pilot deployment
- Final hardening and rollout

---

## 12. Deliverables Summary

By the end of the project, the team should have:

- A configured Google Cloud project
- A secure service account with credentials stored safely
- A structured Google Sheets repository for attendance data
- Google Apps Script dashboards for live reporting
- A Windows executable that fetches attendance from the eSSL device via IP
- A tested and documented deployment procedure
- Monitoring and troubleshooting documentation for maintenance

This plan gives a practical blueprint for implementing the attendance dashboard while respecting the real-world requirement to keep the existing eSSL device retrieval logic intact until the hardware is available for testing.