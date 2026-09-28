"""
Connects to the ESSL device, pulls raw punches, and applies the
noon-split clock-in/out + anomaly detection logic.
Returns plain Python data structures (no file writing here).
"""

from zk import ZK
from datetime import time
from collections import defaultdict

NOON = time(12, 0, 0)
DUPLICATE_WINDOW_SECONDS = 60
MAX_REASONABLE_HOURS = 14
MIN_REASONABLE_HOURS = 1


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


def _detect_duplicates(timestamps):
    dups = []
    ts = sorted(timestamps)
    for i in range(1, len(ts)):
        if (ts[i] - ts[i - 1]).total_seconds() <= DUPLICATE_WINDOW_SECONDS:
            dups.append(ts[i])
    return dups


def process_attendance(attendance, user_map, standard_hours=9):
    grouped = defaultdict(list)
    for r in attendance:
        grouped[(r.user_id, r.timestamp.date())].append(r)

    same_second_map = defaultdict(list)
    for r in attendance:
        same_second_map[r.timestamp.replace(microsecond=0)].append(r.user_id)

    daily_records = []
    for (user_id, date), records in grouped.items():
        timestamps = sorted(r.timestamp for r in records)
        morning = [t for t in timestamps if t.time() < NOON]
        afternoon = [t for t in timestamps if t.time() >= NOON]

        clock_in = min(morning) if morning else None
        clock_out = max(afternoon) if afternoon else None

        total_hours = None
        if clock_in and clock_out:
            total_hours = round((clock_out - clock_in).total_seconds() / 3600, 2)

        excess = deficit = 0
        if total_hours is not None:
            diff = round(total_hours - standard_hours, 2)
            excess = diff if diff > 0 else 0
            deficit = abs(diff) if diff < 0 else 0

        flags = []
        if _detect_duplicates(timestamps):
            flags.append(f"Duplicate punch within {DUPLICATE_WINDOW_SECONDS}s")
        if len(timestamps) == 1:
            flags.append("Only 1 punch recorded")
        elif len(timestamps) > 4:
            flags.append(f"Unusually high punch count ({len(timestamps)})")
        if total_hours is not None:
            if total_hours < MIN_REASONABLE_HOURS:
                flags.append(f"Suspiciously short day ({total_hours}h)")
            elif total_hours > MAX_REASONABLE_HOURS:
                flags.append(f"Suspiciously long day ({total_hours}h)")
        if clock_in and clock_out and clock_in == clock_out:
            flags.append("Clock-in equals clock-out")
        if date.weekday() >= 5:
            flags.append("Weekend activity")
        for t in timestamps:
            others = set(same_second_map[t.replace(microsecond=0)]) - {user_id}
            if others:
                flags.append(f"Same-second punch as user(s) {sorted(others)}")
                break

        daily_records.append({
            "name": user_map.get(user_id, "Unknown"),
            "date": date.isoformat(),
            "clock_in": clock_in.strftime("%H:%M:%S") if clock_in else None,
            "clock_out": clock_out.strftime("%H:%M:%S") if clock_out else None,
            "total_hours": total_hours,
            "excess_hours": excess,
            "deficit_hours": deficit,
            "flags": "; ".join(flags)
        })

    daily_records.sort(key=lambda r: (r["name"].lower(), r["date"]))
    return daily_records


def fetch_and_process(device_ip, standard_hours=9):
    attendance, user_map = fetch_raw_attendance(device_ip)
    return process_attendance(attendance, user_map, standard_hours)
