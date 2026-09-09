"""Prober: low-level network measurements on Windows.

Two layers:
  * PURE PARSERS (parse_*) — take raw text from Windows tools and return
    structured data. No subprocess, fully unit-testable.
  * SUBPROCESS WRAPPERS (ping, get_wifi_info, ...) — run the real commands
    and feed their output to the parsers.

Uses only built-in tools (ping, netsh, route) — no admin rights, no extra
packages.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

IPV4_RE = r"\d+\.\d+\.\d+\.\d+"

# Console subprocesses (ping/netsh/route) must not flash a window when the
# collector runs in the background (pythonw) — CREATE_NO_WINDOW stops that.
CREATE_NO_WINDOW = 0x08000000


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


# -----------------------------------------------------------------------
# PURE PARSERS
# -----------------------------------------------------------------------

def parse_ping_output(text: str, host: str, count: int) -> PingResult:
    result = PingResult(host=host)

    times = re.findall(r"time[=<](\d+)ms", text)
    result.times_ms = [float(t) for t in times]

    m = re.search(r"Sent = (\d+), Received = (\d+)", text)
    if m:
        result.sent = int(m.group(1))
        result.received = int(m.group(2))
    else:
        result.sent = count
        result.received = len(times)

    result.df_blocked = bool(re.search(r"needs to be fragmented", text, re.IGNORECASE))
    return result


def parse_wifi_interfaces(text: str) -> dict:
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
    for line in text.splitlines():
        for key, pattern, cast in patterns:
            m = re.match(pattern, line)
            if m:
                info[key] = cast(m.group(1))
    if info["state"] != "unknown":
        info["state"] = str(info["state"]).lower()
    return info


def parse_gateway_from_routes(text: str) -> str | None:
    """Default gateway IP from `route print -4 0.0.0.0` output (lowest metric)."""
    best: tuple[int, str] | None = None
    for m in re.finditer(
        rf"^[ \t]*0\.0\.0\.0[ \t]+0\.0\.0\.0[ \t]+({IPV4_RE})[ \t]+\S+[ \t]+(\d+)(?:[ \t]+[^\r\n]+)?[ \t]*$",
        text,
        re.MULTILINE,
    ):
        gateway, metric = m.group(1), int(m.group(2))
        if best is None or metric < best[0]:
            best = (metric, gateway)
    return best[1] if best else None


def parse_visible_networks(text: str) -> list[str]:
    return [
        m.group(1).strip()
        for m in re.finditer(r"^\s*SSID\s+\d+\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    ]


def parse_bssid_scan(text: str) -> list[dict]:
    """Parse `netsh wlan show networks mode=bssid` output:

        SSID 1 : Sai
            Network type         : Infrastructure
            Authentication       : WPA3-Personal
            BSSID 1             : 3e:20:ed:75:89:25
                 Signal          : 100%
                 Radio type      : 802.11n
                 Channel         : 10
                 Band            : 2.4 GHz
    """
    aps: list[dict] = []
    current_ssid: str | None = None
    current: dict | None = None

    for line in text.splitlines():
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


# -----------------------------------------------------------------------
# SUBPROCESS WRAPPERS
# -----------------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def ping(host: str, count: int = 4, timeout_ms: int = 1500, df: bool = False, size: int | None = None) -> PingResult:
    """Ping `host` `count` times using Windows ping and parse the reply.

    df/size are used by the path-MTU probe (ping -f -l <size>).
    """
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
            creationflags=CREATE_NO_WINDOW,
        )
        output = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return PingResult(host=host, sent=count)

    return parse_ping_output(output, host, count)


def get_wifi_info() -> dict:
    return parse_wifi_interfaces(_run(["netsh", "wlan", "show", "interfaces"]))


def get_gateway() -> str | None:
    return parse_gateway_from_routes(_run(["route", "print", "-4", "0.0.0.0"]))


def get_visible_networks() -> list[str]:
    return parse_visible_networks(_run(["netsh", "wlan", "show", "networks"]))


def scan_wifi_environment() -> list[dict]:
    return parse_bssid_scan(_run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=20))


def try_switch_to_ssid(ssid: str) -> bool:
    """Connect to a saved Wi-Fi profile by SSID. Returns True on success."""
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "connect", f"name={ssid}"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
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
