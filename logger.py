"""Logger: appends every probe cycle to a CSV for later reporting."""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from health import HealthSnapshot

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "netpilot.csv"

FIELDS = [
    "timestamp",
    "ssid",
    "gateway",
    "gw_loss_pct",
    "gw_avg_ms",
    "net_loss_pct",
    "net_avg_ms",
    "net_jitter_ms",
    "net_score",
    "net_verdict",
]


def append_row(
    ssid: str | None,
    gateway: str | None,
    gw_snap: HealthSnapshot | None,
    net_snap: HealthSnapshot,
) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    is_new = not LOG_FILE.exists()
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ssid": ssid or "unknown",
        "gateway": gateway or "",
        "gw_loss_pct": f"{gw_snap.loss_pct:.1f}" if gw_snap else "",
        "gw_avg_ms": f"{gw_snap.avg_ms:.1f}" if gw_snap and gw_snap.avg_ms is not None else "",
        "net_loss_pct": f"{net_snap.loss_pct:.1f}",
        "net_avg_ms": f"{net_snap.avg_ms:.1f}" if net_snap.avg_ms is not None else "",
        "net_jitter_ms": f"{net_snap.jitter_ms:.1f}" if net_snap.jitter_ms is not None else "",
        "net_score": f"{net_snap.score:.1f}",
        "net_verdict": net_snap.verdict,
    }
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def log_path() -> str:
    return str(LOG_FILE)


def row_count() -> int:
    if not LOG_FILE.exists():
        return 0
    with open(LOG_FILE, encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def os_name() -> str:
    return os.name
