"""Prober: low-level network measurements on Windows.

Uses only built-in tools (ping, netsh, route) — no admin rights, no extra
packages. Also exposes the raw radio/environment data used by wifi_env.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

IPV4_RE = r"\d+\.\d+\.\d+\.\d+"


@dataclass
class PingResult:
    """Outcome of one ping burst at a single host."""

    host: str
    sent: int = 0
    received: int = 0
    times_ms: list[float] = field(default_factory=list)
    df_blocked: bool = False  # "Packet needs to be fragmented but DF set"

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


def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def ping(host: str, count: int = 4, timeout_ms: int = 1500, df: bool = False, size: int | None = None) -> PingResult:
    """Ping `host` `count` times using Windows ping and parse the reply.

    df/size are used by the path-MTU probe (ping -f -l <size>).
    """
    result = PingResult(host=host)
    cmd = ["ping", "-n", str(count), "-w", str(timeout_ms)]
    if df:
        cmd.append("-f")
    if size is not None:
        cmd += ["-l", str(size)]
    cmd.append(host)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=count * (timeout_ms / 1000.0) + 10,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        result.sent = count
        return result

    times = re.findall(r"time[=<](\d+)ms", output)
    result.times_ms = [float(t) for t in times]

    m = re.search(r"Sent = (\d+), Received = (\d+)", output)
    if m:
        result.sent = int(m.group(1))
        result.received = int(m.group(2))
    else:
        result.sent = count
        result.received = len(times)

    # "Packet needs to be fragmented but DF set" — treated as full loss by
    # the stats above; the MTU module reads this case itself.
    result.df_blocked = bool(re.search(r"needs to be fragmented", output, re.IGNORECASE))
    return result


def get_wifi_info() -> dict:
    """Current Wi-Fi adapter state from `netsh wlan show interfaces`."""
    info = {
        "state": "unknown",
        "ssid": None,
        "bssid": None,
        "band": None,
        "channel": None,
        "radio": None,
        "signal": None,
        "rx_rate": None,
        "tx_rate": None,
    }
    output = _run(["netsh", "wlan", "show", "interfaces"])

    patterns = [
        ("state", r"\s*State\s+:\s*(.+?)\s*$", str),
        # "SSID" but not "BSSID"
        ("ssid", r"\s*SSID\s+:\s*(.+?)\s*$", str),
        ("bssid", r"\s*BSSID\s+:\s*(.+?)\s*$", str),
        ("band", r"\s*Band\s+:\s*(.+?)\s*$", str),
        ("channel", r"\s*Channel\s+:\s*(\d+)", int),
        ("radio", r"\s*Radio type\s+:\s*(.+?)\s*$", str),
        ("signal", r"\s*Signal\s+:\s*(\d+)%", int),
        ("rx_rate", r"\s*Receive rate \(Mbps\)\s+:\s*(\d+\.?\d*)", float),
        ("tx_rate", r"\s*Transmit rate \(Mbps\)\s+:\s*(\d+\.?\d*)", float),
    ]
    for line in output.splitlines():
        for key, pattern, cast in patterns:
            m = re.match(pattern, line)
            if m:
                info[key] = cast(m.group(1))
    if info["state"] != "unknown":
        info["state"] = str(info["state"]).lower()
    return info


def get_gateway() -> str | None:
    """Default gateway IP from the IPv4 routing table (lowest metric wins)."""
    output = _run(["route", "print", "-4", "0.0.0.0"])
    best: tuple[int, str] | None = None
    for m in re.finditer(
        rf"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+({IPV4_RE})\s+\S+\s+(\d+)\s",
        output,
        re.MULTILINE,
    ):
        gateway, metric = m.group(1), int(m.group(2))
        if best is None or metric < best[0]:
            best = (metric, gateway)
    return best[1] if best else None


def get_visible_networks() -> list[str]:
    """SSIDs currently in range (used before attempting an auto-switch)."""
    output = _run(["netsh", "wlan", "show", "networks"])
    return [
        m.group(1).strip()
        for m in re.finditer(r"^\s*SSID\s+\d+\s*:\s*(.+?)\s*$", output, re.MULTILINE)
    ]


def scan_wifi_environment() -> list[dict]:
    """All visible APs with BSSID/signal/channel/band.

    Output of `netsh wlan show networks mode=bssid` looks like:

        SSID 1 : Sai
            Network type         : Infrastructure
            Authentication       : WPA3-Personal
            BSSID 1             : 3e:20:ed:75:89:25
                 Signal          : 100%
                 Radio type      : 802.11n
                 Channel         : 10
                 Band            : 2.4 GHz
            BSSID 2             : ...
    """
    output = _run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=20)
    aps: list[dict] = []
    current_ssid: str | None = None
    current: dict | None = None

    for line in output.splitlines():
        m = re.match(r"^\s*SSID\s+\d+\s*:\s*(.+?)\s*$", line)
        if m:
            current_ssid = m.group(1)
            continue
        m = re.match(r"^\s*BSSID\s+\d+\s*:\s*([0-9a-fA-F:]+)\s*$", line)
        if m:
            current = {
                "ssid": current_ssid,
                "bssid": m.group(1).lower(),
                "signal": None,
                "channel": None,
                "band": None,
            }
            aps.append(current)
            continue
        if current is not None:
            m = re.match(r"^\s*Signal\s+:\s*(\d+)%", line)
            if m:
                current["signal"] = int(m.group(1))
                continue
            m = re.match(r"^\s*Channel\s+:\s*(\d+)", line)
            if m:
                current["channel"] = int(m.group(1))
                continue
            m = re.match(r"^\s*Band\s+:\s*(.+?)\s*$", line)
            if m:
                current["band"] = m.group(1)
    return aps


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
    """One light measurement cycle: gateway (local link) + internet targets."""
    cycle: dict = {"gateway": None, "targets": {}}
    if gateway:
        cycle["gateway"] = ping(gateway, count, timeout_ms)
    for target in targets:
        cycle["targets"][target] = ping(target, count, timeout_ms)
    return cycle
