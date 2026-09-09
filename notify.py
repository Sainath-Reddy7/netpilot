"""Notifications: Windows toast (plyer), Discord webhook, console fallback.

Priority: Discord webhook (if configured) + desktop toast (if plyer is
installed); console panel + bell always fires as the local floor.
"""

from __future__ import annotations

import json
import urllib.request

from rich.console import Console
from rich.panel import Panel

console = Console()

# Set by netpilot.py at startup from config: {"alerts": {"webhook_url": ...}}
WEBHOOK_URL: str | None = None


def _send_webhook(title: str, message: str) -> bool:
    """POST to a Discord-compatible webhook. Returns True on success."""
    if not WEBHOOK_URL:
        return False
    try:
        payload = json.dumps({"content": f"**{title}**\n{message}"}).encode()
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "NetPilot/2.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def notify(title: str, message: str, style: str = "red bold") -> None:
    """Discord webhook + desktop toast (if available) + console panel."""
    _send_webhook(title, message)
    delivered = False
    try:
        from plyer import notification  # optional dependency

        notification.notify(title=title, message=message, app_name="NetPilot", timeout=8)
        delivered = True
    except Exception:
        pass
    if not delivered:
        print("\a")  # terminal bell
    console.print(Panel(f"[bold]{title}[/bold]\n{message}", style=style))
