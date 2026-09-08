"""Logger v2: appends every probe cycle to CSV for reporting.

Schema v2 adds radio, DNS, VPN and per-domain score columns. A legacy v1
file (from NetPilot 1.x) is archived automatically on first write.
"""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "netpilot.csv"

FIELDS = [
    "timestamp",
    "ssid",
    "bssid",
    "band",
    "channel",
    "signal_pct",
    "tx_rate_mbps",
    "cochannel_aps",
    "gateway",
    "gw_loss_pct",
    "gw_avg_ms",
    "net_loss_pct",
    "net_avg_ms",
    "net_jitter_ms",
    "net_p95_ms",
    "dns_avg_ms",
    "dns_failures",
    "dns_hijack",
    "vpn",
    "path_score",
    "link_score",
    "dns_score",
    "radio_score",
    "overall_score",
    "overall_grade",
    "verdict",
]

_V1_FIELDS = {"timestamp", "ssid", "gateway", "gw_loss_pct", "gw_avg_ms", "net_loss_pct",
              "net_avg_ms", "net_jitter_ms", "net_score", "net_verdict"}


def _needs_v2_migration() -> bool:
    if not LOG_FILE.exists():
        return False
    with open(LOG_FILE, encoding="utf-8") as f:
        try:
            header = next(csv.reader(f))
        except StopIteration:
            return False
    return set(header) == _V1_FIELDS


def append_row(data: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    if _needs_v2_migration():
        backup = LOG_FILE.with_name("netpilot_v1_backup.csv")
        shutil.move(str(LOG_FILE), str(backup))

    is_new = not LOG_FILE.exists()
    row = {k: data.get(k, "") for k in FIELDS}
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
