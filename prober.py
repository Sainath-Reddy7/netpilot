"""Prober: low-level network measurements on Windows.

Everything here uses built-in tools only (ping, netsh, route) so the app
needs no admin rights and no extra packages.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class PingResult:
    """Outcome of one ping burst at a single host."""

    host: str
    sent: int = 0
    received: int = 0
    times_ms: list[float] = field(default_factory=list)

    @property
    def loss_pct(self) -> float:
        if self.sent == 0:
            return 100.0
        return 100.0 * (self.sent - self.received) / self.sent

    @property
    def avg_ms(self) -> float | None:
        return sum(self.times_ms) / len(self.times_ms) if self.times_ms else None

    @property
    def min_ms(self) -> float | None:
        return min(self.times_ms) if self.times_ms else None

    @property
    def max_ms(self) -> float | None:
        return max(self.times_ms) if self.times_ms else None


def ping(host: str, count: int = 4, timeout_ms: int = 1500) -> PingResult:
    """Ping `host` `count` times using Windows ping and parse the reply."""
    result = PingResult(host=host)
    try:
        proc = subprocess.run(
            ["ping", "-n", str(count), "-w", str(timeout_ms), host],
            capture_output=True,
            text=True,
            timeout=count * (timeout_ms / 1000.0) + 10,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        result.sent = count
        return result

    # Individual reply latencies: "time=34ms" or "time<1ms"
    times = re.findall(r"time[=<](\d+)ms", output)
    result.times_ms = [float(t) for t in times]

    # Sent/received from the summary line: "Sent = 4, Received = 4, Lost = 0 (0% loss),"
    m = re.search(r"Sent = (\d+), Received = (\d+)", output)
    if m:
        result.sent = int(m.group(1))
        result.received = int(m.group(2))
    else:
        # No summary line (e.g. "General failure"): count replies ourselves.
        result.sent = count
        result.received = len(times)
    return result


def get_wifi_info() -> dict:
    """Current Wi-Fi adapter state from `netsh wlan show interfaces`."""
    info = {"state": "unknown", "ssid": None, "band": None, "signal": None}
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return info

    for line in output.splitlines():
        m = re.match(r"\s*State\s+:\s*(.+?)\s*$", line)
        if m:
            info["state"] = m.group(1).lower()
            continue
        # Careful to match "SSID" but not "BSSID"
        m = re.match(r"\s*SSID\s+:\s*(.+?)\s*$", line)
        if m:
            info["ssid"] = m.group(1)
            continue
        m = re.match(r"\s*Band\s+:\s*(.+?)\s*$", line)
        if m:
            info["band"] = m.group(1)
            continue
        m = re.match(r"\s*Signal\s+:\s*(.+?)\s*$", line)
        if m:
            info["signal"] = m.group(1)
    return info


def get_gateway() -> str | None:
    """Default gateway IP from the IPv4 routing table (lowest metric wins)."""
    try:
        proc = subprocess.run(
            ["route", "print", "-4", "0.0.0.0"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return None

    best: tuple[int, str] | None = None
    for m in re.finditer(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+(\d+)\s",
        output,
        re.MULTILINE,
    ):
        gateway, metric = m.group(1), int(m.group(2))
        if best is None or metric < best[0]:
            best = (metric, gateway)
    return best[1] if best else None


def get_visible_networks() -> list[str]:
    """SSIDs currently in range (used before attempting an auto-switch)."""
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "networks"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return []
    return [
        m.group(1).strip()
        for m in re.finditer(r"^\s*SSID\s+\d+\s*:\s*(.+?)\s*$", output, re.MULTILINE)
    ]


def try_switch_to_ssid(ssid: str) -> bool:
    """Connect to a saved Wi-Fi profile by SSID. Returns True on success."""
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "connect", f"name={ssid}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def probe_cycle(
    targets: list[str],
    gateway: str | None,
    count: int,
    timeout_ms: int,
) -> dict:
    """One full measurement cycle: gateway (local link) + internet targets."""
    cycle: dict = {"gateway": None, "targets": {}}
    if gateway:
        cycle["gateway"] = ping(gateway, count, timeout_ms)
    for target in targets:
        cycle["targets"][target] = ping(target, count, timeout_ms)
    return cycle
