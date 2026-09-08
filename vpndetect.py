"""VPN/tunnel detection: know when WARP, WireGuard or friends are active.

A VPN changes EVERYTHING about the measurements (different gateway, different
path, encapsulated UDP) — a monitor that doesn't notice this misdiagnoses.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field

from prober import _run

TUNNEL_NAME_HINTS = {
    "CloudflareWARP": "Cloudflare WARP",
    "WireGuard": "WireGuard",
    "wg-": "WireGuard",
    "Tailscale": "Tailscale",
    "OpenVPN": "OpenVPN",
    "Wintun": "wintun tunnel",
    "ZeroTier": "ZeroTier",
    "NordLynx": "NordVPN",
    "ProtonVPN": "Proton VPN",
}


@dataclass
class VpnSnapshot:
    tunnels: list[str] = field(default_factory=list)
    warp_cli: str | None = None     # warp-cli status line if available
    default_interface: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.tunnels)

    @property
    def label(self) -> str:
        if not self.tunnels:
            return "none"
        return ", ".join(self.tunnels)


def snapshot_vpn() -> VpnSnapshot:
    snap = VpnSnapshot()

    # Connected (non-admin) adapters from netsh; tunnels that are merely
    # installed but idle show up as Disconnected and are skipped.
    output = _run(["netsh", "interface", "show", "interface"])
    for line in output.splitlines():
        # Admin State    State          Type        Interface Name
        m = re.match(r"^(Enabled|Disabled)\s+(\S+)\s+(\S+)\s+(.+?)\s*$", line)
        if not m:
            continue
        admin, link_state, _kind, name = m.groups()
        for hint, label in TUNNEL_NAME_HINTS.items():
            if hint.lower() in name.lower():
                if link_state == "Connected":
                    entry = f"{label} (up)"
                elif admin == "Enabled":
                    entry = f"{label} (idle)"
                else:
                    entry = f"{label} (disabled)"
                if entry not in snap.tunnels:
                    snap.tunnels.append(entry)
                break

    # The default-route interface: first connected adapter that isn't a tunnel
    for line in output.splitlines():
        m = re.match(r"^Enabled\s+Connected\s+\S+\s+(.+?)\s*$", line)
        if not m:
            continue
        name = m.group(1)
        if not any(h.lower() in name.lower() for h in TUNNEL_NAME_HINTS):
            snap.default_interface = name
            break

    # Cloudflare WARP via CLI if installed
    warp = shutil.which("warp-cli")
    if warp:
        out = _run([warp, "status"], timeout=8)
        m = re.search(r"Status update:\s*(.+)", out)
        if m:
            snap.warp_cli = m.group(1).strip()
            # exact match: "Connected", not "Disconnected" (substring trap!)
            if snap.warp_cli.strip().lower() == "connected":
                entry = "Cloudflare WARP (up)"
                if entry not in snap.tunnels:
                    snap.tunnels.append(entry)

    return snap
