"""Attendo Sync: pulls attendance from an eSSL device and sends it to Google Sheets."""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import filedialog, ttk

import gspread
from zk import ZK

# Next to the EXE when frozen, so the backup export lands beside it.
ROOT_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR))
OUTPUT_FILE = ROOT_DIR / "attendance_export.json"
SAMPLE_FILE_NAME = "sample_essl_attendance.json"
ICON_ICO = "Atteno_Sync_Icon.ico"
ICON_PNG = "Atteno_Sync_Icon.png"

# Fixed values for this EXE.
DEFAULT_DEVICE_IP = "192.168.29.201"
DEFAULT_PORT = 4370
DEVICE_TIMEOUT = 10
DEFAULT_CREDENTIALS_FILE = "C:/secure/attendance/gcloud/attendo-sync-f3615fbacce2.json"
SPREADSHEET_ID = "1VbfEv-e-AEeYGobS-E8O31Zi1OYwtsPxLIXXXtAB0BQ"
WORKSHEET_NAME = "Eurobia Attendance"
SAMPLE_WORKSHEET_NAME = "Sample_Test"
BUILD_ID = "2026-09-30 build 4"

BLUE = "#2080A6"
DARK = "#16607D"
BG = "#F3F6F8"
TEXT = "#1E2A32"
MUTED = "#5B6B76"


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


def attendance_to_rows(attendance, user_map):
    rows = []
    for record in attendance:
        user_id = getattr(record, "user_id", None)
        timestamp = getattr(record, "timestamp", None)
        rows.append({
            "user_id": user_id,
            "user_name": user_map.get(user_id, "Unknown"),
            "timestamp": timestamp.isoformat() if timestamp else None,
            "status": getattr(record, "status", None),
            "punch": getattr(record, "punch", None),
        })
    return rows


def fetch_records(device_ip: str, port: int):
    attendance, user_map = fetch_raw_attendance(device_ip, port=port, timeout=DEVICE_TIMEOUT)
    return attendance_to_rows(attendance, user_map)


def load_sample_records():
    """Loads eSSL-shaped sample punches and runs them through the same conversion as real device data."""
    for folder in (ROOT_DIR, BUNDLE_DIR):
        sample_path = folder / SAMPLE_FILE_NAME
        if sample_path.exists():
            break
    else:
        raise FileNotFoundError(f"{SAMPLE_FILE_NAME} not found next to the application.")

    with sample_path.open("r", encoding="utf-8") as fh:
        sample = json.load(fh)

    user_map = {u["user_id"]: u["name"] for u in sample["users"]}
    attendance = [
        SimpleNamespace(
            uid=r["uid"],
            user_id=r["user_id"],
            timestamp=datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S"),
            status=r["status"],
            punch=r["punch"],
        )
        for r in sample["attendance"]
    ]
    return attendance_to_rows(attendance, user_map)


def export_rows(rows, output_path: Path):
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)


def build_worksheet_rows(rows):
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet_rows = [["user_id", "user_name", "timestamp", "status", "punch", "uploaded_at"]]
    for row in rows:
        sheet_rows.append([
            row.get("user_id"),
            row.get("user_name"),
            row.get("timestamp"),
            row.get("status"),
            row.get("punch"),
            uploaded_at,
        ])
    return sheet_rows


def upload_to_google_sheets(rows, credentials_path, worksheet_name, log=print):
    credentials_file = Path(credentials_path)
    if not credentials_path or not credentials_file.is_file():
        raise ValueError(f"Key file not found: {credentials_path or '(empty)'}")

    log(f"Reading key file: {credentials_file}")
    try:
        key = json.loads(credentials_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("The selected file is not valid JSON.") from None
    if not isinstance(key, dict):
        raise ValueError("The selected JSON is not an object, so it cannot be a service account key.")
    log("Fields found in file: " + ", ".join(sorted(key)))

    missing = [f for f in ("type", "client_email", "private_key", "token_uri") if f not in key]
    if missing or key.get("type") != "service_account":
        raise ValueError(
            "This is not a Google service account key (missing: " + ", ".join(missing or ["type=service_account"]) + ").\n"
            "Create one in Google Cloud Console: IAM & Admin > Service Accounts > your account > "
            "Keys > Add key > Create new key > JSON, then select that downloaded file."
        )
    log(f"Service account: {key['client_email']}")

    log("Connecting to Google Sheets...")
    client = gspread.service_account(filename=str(credentials_file))
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    log(f"Opened spreadsheet: {spreadsheet.title}")

    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        log(f"Tab '{worksheet_name}' not found, creating it.")
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=str(max(100, len(rows) + 20)),
            cols="20",
        )

    log(f"Writing {len(rows)} rows to tab '{worksheet_name}'...")
    worksheet.clear()
    worksheet.append_rows(build_worksheet_rows(rows), value_input_option="RAW")
    return worksheet.url


def find_resource(name):
    for folder in (BUNDLE_DIR, ROOT_DIR):
        path = folder / name
        if path.exists():
            return path
    return None


class AttendoSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Attendo Sync")
        self.root.geometry("560x720")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        icon = find_resource(ICON_ICO)
        if icon:
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass

        self._build_styles()
        self._build_header()
        self._build_body()

    def _build_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Card.TFrame", background="white")
        style.configure("Field.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TEntry", fieldbackground="#FFFFFF", padding=6)
        style.configure(
            "Accent.TButton", background=BLUE, foreground="white",
            font=("Segoe UI", 10, "bold"), padding=(14, 9), borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", DARK), ("disabled", "#9CC3D3")])
        style.configure(
            "Ghost.TButton", background="#E4ECF0", foreground=TEXT,
            font=("Segoe UI", 10), padding=(14, 9), borderwidth=0,
        )
        style.map("Ghost.TButton", background=[("active", "#D3DEE4"), ("disabled", "#EEF2F4")])
        style.configure("Browse.TButton", background="#E4ECF0", foreground=TEXT, padding=(10, 6), borderwidth=0)
        style.map("Browse.TButton", background=[("active", "#D3DEE4")])
        style.configure("Sync.Horizontal.TProgressbar", troughcolor="#E4ECF0", background=BLUE, borderwidth=0)

    def _build_header(self):
        header = tk.Frame(self.root, bg=BLUE)
        header.pack(fill="x")

        logo_path = find_resource(ICON_PNG)
        self.logo = None
        if logo_path:
            try:
                self.logo = tk.PhotoImage(file=str(logo_path)).subsample(6, 6)
            except Exception:
                self.logo = None
        if self.logo:
            tk.Label(header, image=self.logo, bg=BLUE).pack(side="left", padx=(20, 12), pady=14)

        titles = tk.Frame(header, bg=BLUE)
        titles.pack(side="left", pady=14)
        tk.Label(titles, text="Attendo Sync", bg=BLUE, fg="white", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(titles, text="eSSL attendance to Google Sheets", bg=BLUE, fg="#D6EAF2",
                 font=("Segoe UI", 10)).pack(anchor="w")

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=18)

        card = ttk.Frame(body, style="Card.TFrame", padding=18)
        card.pack(fill="x")

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ip_col = ttk.Frame(row, style="Card.TFrame")
        ip_col.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Label(ip_col, text="Device IP", style="Field.TLabel").pack(anchor="w")
        self.ip_var = tk.StringVar(value=DEFAULT_DEVICE_IP)
        ttk.Entry(ip_col, textvariable=self.ip_var, font=("Segoe UI", 11)).pack(fill="x", pady=(3, 0))

        port_col = ttk.Frame(row, style="Card.TFrame")
        port_col.pack(side="left")
        ttk.Label(port_col, text="Port", style="Field.TLabel").pack(anchor="w")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(port_col, textvariable=self.port_var, width=8, font=("Segoe UI", 11)).pack(pady=(3, 0))

        ttk.Label(card, text="Google service account key (JSON)", style="Field.TLabel").pack(anchor="w", pady=(14, 0))
        cred_row = ttk.Frame(card, style="Card.TFrame")
        cred_row.pack(fill="x", pady=(3, 0))
        self.credentials_var = tk.StringVar(value=DEFAULT_CREDENTIALS_FILE)
        ttk.Entry(cred_row, textvariable=self.credentials_var, font=("Segoe UI", 10)).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(cred_row, text="Browse...", style="Browse.TButton", command=self.browse_credentials).pack(side="left")

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill="x", pady=(16, 0))
        self.fetch_btn = ttk.Button(buttons, text="Fetch & Send to Google Sheets", style="Accent.TButton",
                                    command=lambda: self.start(sample=False))
        self.fetch_btn.pack(fill="x")
        self.sample_btn = ttk.Button(buttons, text="Send Sample Data (test)", style="Ghost.TButton",
                                     command=lambda: self.start(sample=True))
        self.sample_btn.pack(fill="x", pady=(8, 0))

        self.progress = ttk.Progressbar(body, mode="indeterminate", style="Sync.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(16, 0))

        log_frame = tk.Frame(body, bg=BG)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(log_frame, text="Log", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        text_wrap = tk.Frame(log_frame, bg="#C9D5DC", padx=1, pady=1)
        text_wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(text_wrap, height=12, wrap="word", font=("Consolas", 10), bg="white", fg=TEXT,
                                relief="flat", padx=8, pady=6, state="disabled")
        scrollbar = ttk.Scrollbar(text_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("info", foreground=TEXT)
        self.log_text.tag_configure("ok", foreground="#1B7F3B", font=("Consolas", 10, "bold"))
        self.log_text.tag_configure("error", foreground="#B3261E", font=("Consolas", 10, "bold"))
        self.log(f"Attendo Sync ready ({BUILD_ID}).")

    def browse_credentials(self):
        current = self.credentials_var.get().strip()
        path = filedialog.askopenfilename(
            title="Select Google service account JSON",
            initialdir=str(Path(current).parent) if current else None,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.credentials_var.set(path)

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.fetch_btn.configure(state=state)
        self.sample_btn.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def log(self, text, level="info"):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def log_threadsafe(self, text, level="info"):
        self.root.after(0, lambda: self.log(text, level))

    def start(self, sample: bool):
        try:
            device_ip = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
        except ValueError:
            self.log("Port must be a number.", "error")
            return
        credentials_path = self.credentials_var.get().strip()
        if not sample and not device_ip:
            self.log("Device IP is required.", "error")
            return
        if not credentials_path:
            self.log("Select the Google service account JSON file.", "error")
            return

        self._set_busy(True)
        self.log("--- Sending sample data ---" if sample else "--- Fetching attendance from device ---")
        threading.Thread(target=self.run_sync, args=(sample, device_ip, port, credentials_path), daemon=True).start()

    def run_sync(self, sample, device_ip, port, credentials_path):
        try:
            if sample:
                rows = load_sample_records()
                tab = SAMPLE_WORKSHEET_NAME
                self.log_threadsafe(f"Loaded {len(rows)} sample punches.")
            else:
                self.log_threadsafe(f"Connecting to device {device_ip}:{port}...")
                rows = fetch_records(device_ip, port)
                self.log_threadsafe(f"Fetched {len(rows)} punches from device.")
                export_rows(rows, OUTPUT_FILE)
                self.log_threadsafe(f"Backup saved: {OUTPUT_FILE}")
                tab = WORKSHEET_NAME
            upload_to_google_sheets(rows, credentials_path, tab, log=self.log_threadsafe)
            message, error = f"Done: {len(rows)} rows sent to '{tab}'.", False
        except Exception as exc:
            message, error = f"Failed: {type(exc).__name__}: {exc}", True

        self.root.after(0, lambda: self._finish(message, error))

    def _finish(self, message, error):
        self._set_busy(False)
        self.log(message, "error" if error else "ok")


def main():
    root = tk.Tk()
    AttendoSyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
