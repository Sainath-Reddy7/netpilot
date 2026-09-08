"""Notifications: Windows toast (plyer) with console fallback."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

console = Console()


def notify(title: str, message: str, style: str = "red bold") -> None:
    """Desktop notification if plyer is installed; always mirrors to console."""
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
