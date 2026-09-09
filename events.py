"""Events: incident detection & a persistent timeline.

The live monitor feeds every cycle here; this module turns raw cycles into
human incidents — "WiFi disconnected for 40s", "roamed to another AP",
"network DEAD 21:34-21:39 (upstream congestion)" — keeps them for the
dashboard panel and appends them to logs/events.csv.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
EVENTS_FILE = BASE_DIR / "logs" / "events.csv"

EVENT_FIELDS = ["timestamp", "type", "detail"]

# Kept for the dashboard panel (most recent first).
RECENT: deque[dict] = deque(maxlen=200)


@dataclass
class EventState:
    """Tracks transitions between cycles to emit clean events."""

    prev_state: str | None = None
    dead_started: datetime | None = None
    prev_bssid: str | None = None
    prev_ssid: str | None = None
    dns_fail_streak: int = 0


def emit(etype: str, detail: str) -> dict:
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "type": etype,
        "detail": detail,
    }
    RECENT.appendleft(event)
    EVENTS_FILE.parent.mkdir(exist_ok=True)
    is_new = not EVENTS_FILE.exists()
    with open(EVENTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(event)
    return event


def process_cycle(
    state: EventState,
    *,
    wifi_state: str,
    ssid: str | None,
    bssid: str | None,
    net_verdict: str,
    diagnosis: str,
    dns_failures: int = 0,
) -> list[dict]:
    """Feed one cycle; returns events emitted this cycle."""
    fired: list[dict] = []
    now = datetime.now()

    # --- WiFi disconnect / reconnect ---
    # Only an explicit "disconnected" counts — "unknown" means netsh
    # hiccuped (e.g. during sleep/wake), which is not a real drop.
    if state.prev_state and state.prev_state == "connected" and wifi_state == "disconnected":
        fired.append(emit("WIFI_DOWN", "WiFi dropped."))
    if state.prev_state and state.prev_state != "connected" and wifi_state == "connected":
        fired.append(emit("WIFI_UP", f"WiFi reconnected to {ssid or 'network'}."))

    # --- SSID/BSSID switch = roaming or manual network change ---
    if wifi_state == "connected":
        if state.prev_ssid and ssid and state.prev_ssid != ssid:
            fired.append(emit("NETWORK_CHANGE", f"{state.prev_ssid} -> {ssid}."))
        elif state.prev_bssid and bssid and state.prev_bssid != bssid and ssid == state.prev_ssid:
            fired.append(
                emit("AP_ROAM", f"Roamed between access points of {ssid or 'network'} "
                                f"({state.prev_bssid} -> {bssid}).")
            )

    # --- DEAD period begin/end ---
    if net_verdict == "DEAD":
        if state.dead_started is None:
            state.dead_started = now
    else:
        if state.dead_started is not None:
            duration = (now - state.dead_started).total_seconds()
            fired.append(
                emit(
                    "OUTAGE",
                    f"Network unusable for {duration:.0f}s "
                    f"({state.dead_started.strftime('%H:%M:%S')}-{now.strftime('%H:%M:%S')}). {diagnosis}",
                )
            )
            state.dead_started = None

    # --- DNS failures ---
    if dns_failures > 0:
        state.dns_fail_streak += 1
        if state.dns_fail_streak == 2:
            fired.append(emit("DNS_FAIL", f"DNS resolution failing ({dns_failures} hosts this cycle)."))
    else:
        state.dns_fail_streak = 0

    # --- bookkeeping ---
    state.prev_state = wifi_state
    state.prev_ssid = ssid
    state.prev_bssid = bssid
    return fired


def availability_pct(hours: float = 24) -> float | None:
    """% of time (recent window) the network wasn't DEAD, from events.csv."""
    import pandas as pd

    if not EVENTS_FILE.exists():
        return None
    try:
        df = pd.read_csv(EVENTS_FILE)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        cutoff = df["timestamp"].max() - pd.Timedelta(hours=hours)
        df = df[df["timestamp"] >= cutoff]
        if df.empty:
            return None
        outages = df[df["type"] == "OUTAGE"]
        total_outage_s = 0.0
        for _, row in outages.iterrows():
            import re

            m = re.search(r"for (\d+)s", str(row["detail"]))
            if m:
                total_outage_s += int(m.group(1))
        window_s = min(hours * 3600, (df["timestamp"].max() - df["timestamp"].min()).total_seconds())
        if window_s <= 0:
            return None
        return max(0.0, 100.0 * (1 - total_outage_s / window_s))
    except Exception:
        return None


def recent_events(limit: int = 8) -> list[dict]:
    return list(RECENT)[:limit]
