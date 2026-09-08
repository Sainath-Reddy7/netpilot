"""NetPilot — personal network health monitor for Windows.

Answers two questions:
  1. Is my current network good RIGHT NOW?  (live dashboard / --once)
  2. WHEN is each of my networks actually usable?  (--report heatmap)

Uses only Python stdlib + rich (+ pandas/matplotlib for reports).
No admin rights required.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

import logger as logmod
from health import DEAD, GO, HealthSnapshot, RollingHealth, diagnose
from prober import get_gateway, get_visible_networks, get_wifi_info, probe_cycle, try_switch_to_ssid

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
console = Console()

VERDICT_STYLE = {GO: "green", "WARN": "yellow", DEAD: "red bold"}


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def notify(title: str, message: str) -> None:
    """Windows toast via plyer if installed; console panel otherwise."""
    try:
        from plyer import notification  # optional dependency

        notification.notify(title=title, message=message, app_name="NetPilot", timeout=8)
    except Exception:
        console.print(Panel(f"[bold]{title}[/bold]\n{message}", style="red bold"))
        print("\a")  # terminal bell


@dataclass
class Cycle:
    wifi: dict
    gateway_ip: str | None
    gateway_snap: HealthSnapshot | None
    gateway_blocked: bool
    net_snap: HealthSnapshot
    diagnosis: str
    when: datetime


def run_cycle(cfg: dict, gw_health: RollingHealth, net_health: RollingHealth) -> Cycle:
    wifi = get_wifi_info()
    gateway_ip = get_gateway()

    cycle = probe_cycle(
        cfg["targets"], gateway_ip, cfg["pings_per_probe"], cfg["ping_timeout_ms"]
    )

    gw_result = cycle["gateway"]
    target_results = list(cycle["targets"].values())

    # Some APs/campuses ignore ICMP to the gateway: if every gateway ping dies
    # but the internet answers, the local link is actually fine.
    gw_blocked = bool(
        gw_result
        and gw_result.received == 0
        and any(r.received > 0 for r in target_results)
    )

    if gw_result is not None:
        gw_health.add_cycle([gw_result])
    net_health.add_cycle(target_results)

    gw_snap = None if gw_result is None else gw_health.snapshot()
    net_snap = net_health.snapshot()
    diag = diagnose(gw_snap if not gw_blocked else None, net_snap, gateway_icmp_blocked=gw_blocked)

    return Cycle(
        wifi=wifi,
        gateway_ip=gateway_ip,
        gateway_snap=gw_snap,
        gateway_blocked=gw_blocked,
        net_snap=net_snap,
        diagnosis=diag,
        when=datetime.now(),
    )


def _fmt_ms(value: float | None) -> str:
    return f"{value:.0f} ms" if value is not None else "n/a"


def build_table(c: Cycle) -> Table:
    table = Table(title=f"NetPilot — {c.when.strftime('%Y-%m-%d %H:%M:%S')}", show_header=False)
    table.add_column("Section", style="cyan", width=10)
    table.add_column("Value", overflow="fold")

    style = VERDICT_STYLE.get(c.net_snap.verdict, "")

    ssid = c.wifi.get("ssid") or "wired / unknown"
    extras = []
    if c.wifi.get("band"):
        extras.append(c.wifi["band"])
    if c.wifi.get("signal"):
        extras.append(f"{c.wifi['signal']} signal")
    table.add_row("Network", ssid + (f" ({', '.join(extras)})" if extras else ""))

    if c.gateway_ip is None:
        table.add_row("Gateway", "not found (VPN or no default route?)")
    elif c.gateway_blocked:
        table.add_row("Gateway", f"{c.gateway_ip} — no reply (ICMP blocked, link assumed fine)")
    else:
        gw = c.gateway_snap
        table.add_row(
            "Gateway",
            f"{c.gateway_ip} — {_fmt_ms(gw.avg_ms)} avg, {gw.loss_pct:.0f}% loss",
        )

    n = c.net_snap
    table.add_row(
        "Internet",
        f"{_fmt_ms(n.avg_ms)} avg | {_fmt_ms(n.jitter_ms)} jitter | p95 {_fmt_ms(n.p95_ms)} | {n.loss_pct:.0f}% loss",
    )
    table.add_row("Score", f"[{style}]{n.score:.0f}/100 — {n.verdict}[/{style}]")
    table.add_row("Verdict", f"[{style}]{c.diagnosis}[/{style}]")
    return table


def log_cycle(c: Cycle) -> None:
    logmod.append_row(c.wifi.get("ssid"), c.gateway_ip, c.gateway_snap, c.net_snap)


def once(cfg: dict) -> int:
    gw_health = RollingHealth("gateway", 1, cfg["score_weights"], cfg["thresholds"])
    net_health = RollingHealth("internet", 1, cfg["score_weights"], cfg["thresholds"])
    c = run_cycle(cfg, gw_health, net_health)
    console.print(build_table(c))
    if cfg.get("log_enabled", True):
        log_cycle(c)
        console.print(f"[dim]logged to {logmod.log_path()}[/dim]")
    return {GO: 0, "WARN": 1, DEAD: 2}.get(c.net_snap.verdict, 2)


def monitor(cfg: dict, auto_ssid: str | None, log_enabled: bool) -> None:
    weights, thresholds = cfg["score_weights"], cfg["thresholds"]
    gw_health = RollingHealth("gateway", cfg["window_cycles"], weights, thresholds)
    net_health = RollingHealth("internet", cfg["window_cycles"], weights, thresholds)

    state = "OK"
    dead_since: float | None = None
    alerted_dead = False
    last_switch = 0.0
    started = time.time()
    min_score = 100.0
    cycles = 0

    console.print(
        Panel(
            "Monitoring continuously — Ctrl+C to stop.\n"
            + (f"Auto-switch to [bold]{auto_ssid}[/bold] is [green]ARMED[/green] after "
               f"{cfg['dead_sustain_s']}s of DEAD." if auto_ssid else
               "Alert-only mode (no automatic switching)."),
            title="NetPilot",
        )
    )

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                c = run_cycle(cfg, gw_health, net_health)
                cycles += 1
                min_score = min(min_score, c.net_snap.score)
                if log_enabled:
                    log_cycle(c)
                live.update(build_table(c))

                now = time.time()
                if c.net_snap.verdict == DEAD:
                    if dead_since is None:
                        dead_since = now
                    sustained = now - dead_since >= cfg["dead_sustain_s"]
                    if sustained and not alerted_dead:
                        notify(
                            "NetPilot: network is DEAD",
                            f"{c.wifi.get('ssid') or 'current network'} — "
                            f"{c.net_snap.loss_pct:.0f}% loss, {_fmt_ms(c.net_snap.avg_ms)} avg. {c.diagnosis}",
                        )
                        alerted_dead = True
                        state = "DEAD"

                    if (
                        sustained
                        and auto_ssid
                        and now - last_switch >= cfg["auto_switch_cooldown_s"]
                        and auto_ssid in get_visible_networks()
                    ):
                        console.print(
                            f"[yellow]Attempting auto-switch to '{auto_ssid}'...[/yellow]"
                        )
                        if try_switch_to_ssid(auto_ssid):
                            last_switch = now
                            dead_since = None
                            alerted_dead = False
                            notify("NetPilot: switched network", f"Connected to {auto_ssid}.")
                        else:
                            last_switch = now  # don't retry every cycle
                else:
                    if alerted_dead and c.net_snap.verdict != DEAD:
                        notify(
                            "NetPilot: network recovered",
                            f"{c.wifi.get('ssid') or 'network'} back to "
                            f"{c.net_snap.verdict} ({c.net_snap.score:.0f}/100).",
                        )
                    alerted_dead = False
                    dead_since = None
                    state = c.net_snap.verdict

                time.sleep(cfg["interval_s"])
    except KeyboardInterrupt:
        pass

    mins = (time.time() - started) / 60
    console.print(
        f"\n[bold]Session summary:[/bold] {cycles} cycles over {mins:.0f} min, "
        f"worst score {min_score:.0f}/100, {logmod.row_count()} rows logged."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="netpilot",
        description="Personal network health monitor: is my network good right now, and when is it ever good?",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="single check, then exit (exit code: 0 GO / 1 WARN / 2 DEAD)")
    mode.add_argument("--report", action="store_true", help="build congestion heatmap from logs")
    parser.add_argument("--days", type=int, default=7, help="days of history for --report (default 7)")
    parser.add_argument("--auto", metavar="SSID", help="auto-switch to this saved Wi-Fi when network is DEAD")
    parser.add_argument("--interval", type=int, help="seconds between probe cycles (default from config)")
    parser.add_argument("--no-log", action="store_true", help="don't append results to CSV")
    args = parser.parse_args()

    cfg = load_config()
    if args.interval:
        cfg["interval_s"] = args.interval
    if args.no_log:
        cfg["log_enabled"] = False

    if args.report:
        from report import build_report

        path = build_report(args.days)
        return 0 if path else 1

    if args.once:
        return once(cfg)

    monitor(cfg, args.auto, not args.no_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
