"""Simple EXE entry point for the Attendo Sync attendance fetch flow.

This version keeps the current device IP fetch logic untouched by importing the
existing function from attendance_engine.py and wrapping it with a small UI and
JSON export flow.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


ROOT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = ROOT_DIR / "simple_exe_config.json"
OUTPUT_FILE = ROOT_DIR / "attendance_export.json"


def load_config():
    default = {
        "device_ip": "192.168.1.201",
        "port": 4370,
        "timeout": 10,
        "output_file": "attendance_export.json",
    }

    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            default.update(loaded)
        except Exception:
            # Keep defaults if the config file is unreadable.
            pass

    return default


def save_config(cfg):
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def fetch_records(device_ip: str, port: int, timeout: int):
    """Calls the unchanged eSSL fetch logic from the existing attendance engine."""
    try:
        from attendance_engine import fetch_raw_attendance
    except ImportError as exc:
        raise RuntimeError(
            "Could not import attendance_engine. Ensure the module is present in the same folder."
        ) from exc

    attendance, user_map = fetch_raw_attendance(device_ip, port=port, timeout=timeout)
    rows = []
    for record in attendance:
        rows.append({
            "user_id": getattr(record, "user_id", None),
            "user_name": user_map.get(getattr(record, "user_id", None), "Unknown"),
            "timestamp": record.timestamp.isoformat() if getattr(record, "timestamp", None) else None,
            "status": getattr(record, "status", None),
        })
    return rows


def export_rows(rows, output_path: Path):
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)


class SimpleExeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Attendo Sync - Simple EXE")
        self.root.geometry("520x320")
        self.root.resizable(False, False)

        self.config = load_config()

        tk.Label(root, text="Device IP", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(18, 4))
        self.ip_var = tk.StringVar(value=self.config.get("device_ip", "192.168.1.201"))
        self.ip_entry = tk.Entry(root, width=30, textvariable=self.ip_var, font=("Segoe UI", 11))
        self.ip_entry.pack(fill="x", padx=18)

        tk.Label(root, text="Port", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(12, 4))
        self.port_var = tk.StringVar(value=str(self.config.get("port", 4370)))
        self.port_entry = tk.Entry(root, width=12, textvariable=self.port_var, font=("Segoe UI", 11))
        self.port_entry.pack(anchor="w", padx=18)

        tk.Label(root, text="Timeout (seconds)", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(12, 4))
        self.timeout_var = tk.StringVar(value=str(self.config.get("timeout", 10)))
        self.timeout_entry = tk.Entry(root, width=12, textvariable=self.timeout_var, font=("Segoe UI", 11))
        self.timeout_entry.pack(anchor="w", padx=18)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status_var, foreground="#1f5f8b").pack(anchor="w", padx=18, pady=(14, 0))

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", padx=18, pady=(14, 18))

        self.fetch_btn = ttk.Button(button_frame, text="Fetch Attendance", command=self.start_fetch)
        self.fetch_btn.pack(side="left", padx=(0, 10))

        self.close_btn = ttk.Button(button_frame, text="Exit", command=self.root.destroy)
        self.close_btn.pack(side="left")

        self.output_label = tk.Label(
            root,
            text=f"Output: {self.config.get('output_file', 'attendance_export.json')}",
            justify="left",
            wraplength=480,
        )
        self.output_label.pack(anchor="w", padx=18, pady=(8, 0))

    def start_fetch(self):
        self.fetch_btn.configure(state="disabled")
        self.status_var.set("Fetching attendance from eSSL device...")

        thread = threading.Thread(target=self.fetch_and_save, daemon=True)
        thread.start()

    def fetch_and_save(self):
        try:
            device_ip = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
            timeout = int(self.timeout_var.get().strip())

            if not device_ip:
                raise ValueError("Device IP is required.")

            cfg = {
                "device_ip": device_ip,
                "port": port,
                "timeout": timeout,
                "output_file": self.config.get("output_file", "attendance_export.json"),
            }
            save_config(cfg)

            rows = fetch_records(device_ip=device_ip, port=port, timeout=timeout)
            output_name = self.config.get("output_file", "attendance_export.json")
            output_path = ROOT_DIR / output_name
            export_rows(rows, output_path)

            self.root.after(0, lambda: self.status_var.set(f"Success: {len(rows)} rows saved to {output_path}"))
            self.root.after(0, lambda: self.fetch_btn.configure(state="normal"))
            self.root.after(0, lambda: self.output_label.config(text=f"Output: {output_path}"))

        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Fetch failed", str(exc)))
            self.root.after(0, lambda: self.status_var.set(f"Error: {exc}"))
            self.root.after(0, lambda: self.fetch_btn.configure(state="normal"))


def main():
    root = tk.Tk()
    app = SimpleExeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
