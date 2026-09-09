"""NetPilot v2 — comprehensive personal network health monitor for Windows.

Four modes:
  live      python netpilot.py               — professional live dashboard
  once      python netpilot.py --once        — quick check (also does light DNS)
  full      python netpilot.py --full        — deep diagnostics: traceroute,
                                              bufferbloat, throughput, path MTU,
                                              channel scan, VPN detect
  report    python netpilot.py --report      — heatmap + schedule + incidents + HTML

No admin rights required. Logs stay local (logs/), never leave the machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

import events as events_mod
import logger as logmod
import notify as notify_mod
from bloat import measure_bloat
from dashboard import build_dashboard, build_full_report
from dnscheck import snapshot_dns
from health import DEAD, GO, RollingHealth, diagnose, roll_up
from mtu import measure_mtu
from notify import notify
from prober import get_gateway, get_visible_networks, get_wifi_info, probe_cycle, try_switch_to_ssid
from traceroute import measure_path
from vpndetect import snapshot_vpn
from wifi_env import snapshot_wifi_env

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
__version__ = "2.2.0"
console = Console()


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    # Discord-compatible webhook for alerts (optional)
    notify_mod.WEBHOOK_URL = (cfg.get("alerts") or {}).get("webhook_url") or None
    return cfg


@dataclass
class Engine:
    """Holds rolling state for the monitoring loops."""

    cfg: dict
    gw_health: RollingHealth
    net_health: RollingHealth
    latency_history: deque = None  # type: ignore[assignment]
    deep: dict = None  # type: ignore[assignment]   # cached deep results
    last_deep_ts: float = 0.0
    event_state: events_mod.EventState = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.latency_history is None:
            self.latency_history = deque(maxlen=120)
        if self.deep is None:
            self.deep = {}
        if self.event_state is None:
            self.event_state = events_mod.EventState()


def make_engine(cfg: dict) -> Engine:
    return Engine(
        cfg=cfg,
        gw_health=RollingHealth("gateway", cfg["window_cycles"], cfg["score_weights"], cfg["thresholds"]),
        net_health=RollingHealth("internet", cfg["window_cycles"], cfg["score_weights"], cfg["thresholds"]),
    )


def run_light(engine: Engine) -> dict:
    """One light cycle: wifi + gateway + pings + DNS. Returns dashboard state."""
    cfg = engine.cfg
    wifi = get_wifi_info()
    gateway_ip = get_gateway()

    cycle = probe_cycle(cfg["targets"], gateway_ip, cfg["pings_per_probe"], cfg["ping_timeout_ms"])
    gw_result = cycle["gateway"]
    target_results = list(cycle["targets"].values())

    gw_blocked = bool(
        gw_result and gw_result.received == 0
        and any(r.received > 0 for r in target_results)
    )
    if gw_result is not None:
        engine.gw_health.add_cycle([gw_result])
    engine.net_health.add_cycle(target_results)

    gw_snap = None if gw_result is None else engine.gw_health.snapshot()
    net_snap = engine.net_health.snapshot()
    diagnosis = diagnose(gw_snap if not gw_blocked else None, net_snap, gateway_icmp_blocked=gw_blocked)

    # DNS every cycle (cheap, and hijack detection is valuable)
    dcfg = cfg.get("dns", {})
    dns = snapshot_dns(
        dcfg.get("test_hosts", ["cloudflare.com"]),
        dcfg.get("hijack_probe_prefix", "netpilot-nxd"),
        dcfg.get("hijack_probe_suffix", ".invalid"),
    )
    dns_score = dns.score()

    # Radio score: from the last full scan if we have one; else from wifi info alone
    env = engine.deep.get("wifi_env")
    if env is not None:
        radio_score = env.score(
            cfg.get("wifi_env", {}).get("crowded_channel_aps", 6),
            cfg.get("wifi_env", {}).get("strong_signal_threshold_pct", 55),
        )
    else:
        radio_score = None

    bloat = engine.deep.get("bloat")
    bloat_score = bloat.score() if bloat and bloat.tested else None

    overall = roll_up(net_snap, gw_snap, dns_score, radio_score, bloat_score, cfg["thresholds"])

    if net_snap.avg_ms is not None:
        engine.latency_history.append(net_snap.avg_ms)

    vpn = engine.deep.get("vpn")
    header_bits = [wifi.get("ssid") or "wired"]
    if wifi.get("band"):
        header_bits.append(f"{wifi['band']} ch{wifi.get('channel')}")
    if vpn:
        header_bits.append(f"VPN: {vpn.label}")

    state = {
        "when": datetime.now(),
        "wifi": wifi,
        "gateway_ip": gateway_ip,
        "gw_snap": gw_snap,
        "gateway_blocked": gw_blocked,
        "net_snap": net_snap,
        "diagnosis": diagnosis,
        "overall": overall,
        "dns": dns,
        "latency_history": list(engine.latency_history),
        "header_line": " · ".join(str(b) for b in header_bits),
        "grade_thresholds": cfg.get("grades"),
        **engine.deep,  # wifi_env, bloat, mtu, path_trace, vpn
    }

    # Events + logging
    fired = events_mod.process_cycle(
        engine.event_state,
        wifi_state=wifi.get("state", "unknown"),
        ssid=wifi.get("ssid"),
        bssid=wifi.get("bssid"),
        net_verdict=net_snap.verdict,
        diagnosis=diagnosis,
        dns_failures=dns.failures,
    )
    state["events"] = events_mod.recent_events()

    if cfg.get("log_enabled", True):
        logmod.append_row(
            {
                "timestamp": state["when"].isoformat(timespec="seconds"),
                "ssid": wifi.get("ssid") or "unknown",
                "bssid": wifi.get("bssid") or "",
                "band": wifi.get("band") or "",
                "channel": wifi.get("channel") or "",
                "signal_pct": wifi.get("signal") or "",
                "tx_rate_mbps": wifi.get("tx_rate") or "",
                "cochannel_aps": env.cochannel_aps if env else "",
                "gateway": gateway_ip or "",
                "gw_loss_pct": f"{gw_snap.loss_pct:.1f}" if gw_snap else "",
                "gw_avg_ms": f"{gw_snap.avg_ms:.1f}" if gw_snap and gw_snap.avg_ms is not None else "",
                "net_loss_pct": f"{net_snap.loss_pct:.1f}",
                "net_avg_ms": f"{net_snap.avg_ms:.1f}" if net_snap.avg_ms is not None else "",
                "net_jitter_ms": f"{net_snap.jitter_ms:.1f}" if net_snap.jitter_ms is not None else "",
                "net_p95_ms": f"{net_snap.p95_ms:.1f}" if net_snap.p95_ms is not None else "",
                "dns_avg_ms": f"{dns.avg_ms:.1f}" if dns.avg_ms is not None else "",
                "dns_failures": dns.failures,
                "dns_hijack": int(dns.hijacked),
                "vpn": vpn.label if vpn else "",
                "path_score": net_snap.score,
                "link_score": gw_snap.score if gw_snap else "",
                "dns_score": dns_score,
                "radio_score": radio_score if radio_score is not None else "",
                "overall_score": overall.overall_score,
                "overall_grade": overall.grade(cfg.get("grades")),
                "verdict": overall.verdict,
            }
        )
    return state


def run_deep(engine: Engine) -> dict:
    """Deep diagnostics: channel scan, VPN, traceroute, bloat, MTU."""
    cfg = engine.cfg
    results: dict = {}

    results["vpn"] = snapshot_vpn()
    results["wifi_env"] = snapshot_wifi_env(
        strong_pct=cfg.get("wifi_env", {}).get("strong_signal_threshold_pct", 55),
        crowded_aps=cfg.get("wifi_env", {}).get("crowded_channel_aps", 6),
    )
    results["path_trace"] = measure_path(
        cfg["targets"][0],
        max_hops=cfg.get("traceroute", {}).get("max_hops", 15),
        timeout_ms=cfg.get("traceroute", {}).get("timeout_ms", 800),
    )

    bcfg = cfg.get("bloat", {})
    results["bloat"] = measure_bloat(
        bcfg.get("url", "https://speed.cloudflare.com/__down?bytes=16000000"),
        cfg["targets"][0],
        bcfg.get("load_pings", 10),
        bcfg.get("min_download_mb", 1),
    )

    mcfg = cfg.get("mtu", {})
    results["mtu"] = measure_mtu(cfg["targets"][0], mcfg.get("min", 1200), mcfg.get("max", 1472))

    engine.deep.update(results)
    engine.last_deep_ts = time.time()
    return results


def once(engine: Engine, deep: bool = False) -> int:
    state = run_light(engine)
    if deep:
        console.print("[dim]Running deep diagnostics (this takes ~1 minute)...[/dim]")
        run_deep(engine)
        state.update(engine.deep)
        # Re-roll overall with deep data included
        env = engine.deep.get("wifi_env")
        radio = env.score() if env else None
        bloat = engine.deep.get("bloat")
        bloat_s = bloat.score() if bloat and bloat.tested else None
        state["overall"] = roll_up(state["net_snap"], state["gw_snap"], state["dns"].score(), radio, bloat_s, engine.cfg["thresholds"])
        for panel in build_full_report(state):
            console.print(panel)
    else:
        for panel in build_full_report(state):
            console.print(panel)
    if engine.cfg.get("log_enabled", True):
        console.print(f"[dim]logged to {logmod.log_path()}[/dim]")
    return {GO: 0, "WARN": 1, DEAD: 2}.get(state["overall"].verdict, 2)


def monitor(engine: Engine, auto_ssid: str | None, deep_interval_min: float) -> None:
    cfg = engine.cfg
    alert_state = {"alerted_dead": False}
    dead_since: float | None = None
    last_switch = 0.0
    started = time.time()
    min_score = 100.0
    cycles = 0

    console.print(
        Panel(
            "Monitoring continuously — Ctrl+C to stop.\n"
            + (
                f"Auto-switch to [bold]{auto_ssid}[/bold] [green]ARMED[/green] after "
                f"{cfg['dead_sustain_s']}s of DEAD. "
                if auto_ssid
                else "Alert-only mode (no automatic switching). "
            )
            + f"Deep diagnostics every {deep_interval_min:.0f} min.",
            title="NetPilot v2",
        )
    )

    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                state = run_light(engine)
                cycles += 1
                min_score = min(min_score, state["overall"].overall_score)
                live.update(build_dashboard(state))

                now = time.time()
                # ---- alerts (tied to the internet path, the switch-worthy signal)
                path_verdict = state["net_snap"].verdict
                if path_verdict == DEAD:
                    if dead_since is None:
                        dead_since = now
                    sustained = now - dead_since >= cfg["dead_sustain_s"]
                    if sustained and not alert_state["alerted_dead"]:
                        avg_txt = f"{state['net_snap'].avg_ms:.0f}ms" if state["net_snap"].avg_ms is not None else "n/a"
                        notify(
                            "NetPilot: network is DEAD",
                            f"{state['wifi'].get('ssid') or 'network'} — "
                            f"{state['net_snap'].loss_pct:.0f}% loss, "
                            f"{avg_txt} avg. {state['diagnosis']}",
                        )
                        alert_state["alerted_dead"] = True
                    if (
                        sustained
                        and auto_ssid
                        and now - last_switch >= cfg["auto_switch_cooldown_s"]
                        and auto_ssid in get_visible_networks()
                    ):
                        console.print(f"[yellow]Attempting auto-switch to '{auto_ssid}'...[/yellow]")
                        if try_switch_to_ssid(auto_ssid):
                            last_switch = now
                            dead_since = None
                            alert_state["alerted_dead"] = False
                            notify("NetPilot: switched network", f"Connected to {auto_ssid}.", style="green")
                        else:
                            last_switch = now
                else:
                    if alert_state["alerted_dead"]:
                        notify(
                            "NetPilot: network recovered",
                            f"{state['wifi'].get('ssid') or 'network'} back to "
                            f"{path_verdict} ({state['net_snap'].score:.0f}/100).",
                            style="green",
                        )
                    alert_state["alerted_dead"] = False
                    dead_since = None

                # ---- periodic deep diagnostics (blocks the loop ~1 min)
                if now - engine.last_deep_ts >= deep_interval_min * 60:
                    state["header_line"] += " · [deep diagnostics running…]"
                    live.update(build_dashboard(state))
                    run_deep(engine)

                time.sleep(cfg["interval_s"])
    except KeyboardInterrupt:
        pass

    mins = (time.time() - started) / 60
    console.print(
        f"\n[bold]Session summary:[/bold] {cycles} cycles over {mins:.0f} min, "
        f"worst overall score {min_score:.0f}/100, {logmod.row_count()} rows logged."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="netpilot",
        description="NetPilot v2 — is my network good right now, and when is it ever good?",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="single light check, then exit")
    mode.add_argument("--full", action="store_true", help="single DEEP check (traceroute, bloat, MTU, channel scan)")
    mode.add_argument("--report", action="store_true", help="build report from logs")
    mode.add_argument("--publish", action="store_true", help="generate shareable web dashboard (web/index.html)")
    parser.add_argument("--version", action="version", version=f"netpilot {__version__}")
    parser.add_argument("--days", type=int, default=7, help="days of history for --report/--publish (default 7)")
    parser.add_argument("--demo", action="store_true", help="with --publish: use synthetic demo data (no real SSIDs)")
    parser.add_argument("--anon", action="store_true", help="with --publish: pseudonymize network names")
    parser.add_argument("--no-html", action="store_true", help="skip HTML report export")
    parser.add_argument("--auto", metavar="SSID", help="auto-switch to this saved Wi-Fi when path is DEAD")
    parser.add_argument("--deep-interval", type=float, default=None, metavar="MIN", help="minutes between deep diagnostics in live mode")
    parser.add_argument("--interval", type=int, help="seconds between light cycles (default from config)")
    parser.add_argument("--no-log", action="store_true", help="don't append results to CSV")
    args = parser.parse_args()

    cfg = load_config()
    if args.interval:
        cfg["interval_s"] = args.interval
    if args.no_log:
        cfg["log_enabled"] = False

    if args.report:
        from report import build_report

        path = build_report(args.days, html_export=not args.no_html)
        return 0 if path else 1

    if args.publish:
        from web import publish

        try:
            path = publish(days=args.days, demo=args.demo, anon=args.anon)
        except SystemExit as e:
            console.print(f"[red]{e}[/red]")
            return 1
        console.print(f"[green]Web dashboard written:[/green] {path}")
        console.print("Deploy: push to GitHub → vercel.com → Import repo (web/ is already configured).")
        return 0

    engine = make_engine(cfg)
    deep_interval = args.deep_interval if args.deep_interval is not None else cfg.get("deep_interval_min", 30)

    if args.once:
        return once(engine, deep=False)
    if args.full:
        return once(engine, deep=True)

    monitor(engine, args.auto, deep_interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
