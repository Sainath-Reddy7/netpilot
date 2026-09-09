"""Dashboard v2: the professional rich layout.

Pure rendering — takes a `state` dict assembled by netpilot.py and returns
rich renderables. Two flavors:

  * build_dashboard(state)  -> full live Layout (used with rich.live.Live)
  * build_full_report(state) -> one-shot deep diagnostic report (--full)
"""

from __future__ import annotations

from datetime import datetime

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from health import DEAD, GO, Overall

_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline_text(data: list[float], width: int = 44, style: str = "green") -> Text:
    """Portable unicode sparkline (no rich.sparkline dependency)."""
    if not data:
        return Text("—", style="dim")
    data = data[-width:]
    lo, hi = min(data), max(data)
    span = (hi - lo) or 1.0
    chars = "".join(_BLOCKS[min(7, int((v - lo) / span * 7.999))] for v in data)
    return Text(chars, style=style)

GRADE_STYLE = {
    "A": "bold green",
    "B": "bold cyan",
    "C": "bold yellow",
    "D": "bold dark_orange",
    "F": "bold red",
    "n/a": "dim",
}
VERDICT_STYLE = {GO: "bold green", "WARN": "bold yellow", DEAD: "bold red"}


def _grade_txt(score: float | None, grades_thresholds: dict | None = None) -> Text:
    if score is None:
        return Text("n/a", style=GRADE_STYLE["n/a"])
    from health import letter_grade

    g = letter_grade(score, grades_thresholds)
    return Text(f"{g} {score:.0f}", style=GRADE_STYLE.get(g, "bold white"))


def _fmt(ms: float | None, suffix: str = " ms") -> str:
    return f"{ms:.0f}{suffix}" if ms is not None else "n/a"


def _kv(pairs: list[tuple[str, object]]) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan bold", justify="right", no_wrap=True)
    table.add_column(overflow="fold")
    for k, v in pairs:
        table.add_row(k, str(v))
    return table


def _header(state: dict) -> Panel:
    ov: Overall = state["overall"]
    verdict_style = VERDICT_STYLE.get(ov.verdict, "bold white")
    when = state.get("when") or datetime.now()

    title = Text()
    title.append(" NetPilot ", style="bold reverse cyan")
    title.append(f" {when.strftime('%Y-%m-%d %H:%M:%S')} ", style="dim")
    title.append(f" {ov.verdict} ", style=f"reverse {verdict_style}")

    # Domain grade strip: PATH A · LINK A · DNS B · RADIO A · BLOAT C
    gt = state.get("grade_thresholds")
    labels = {"path": "PATH", "link": "LINK", "dns": "DNS", "radio": "RADIO", "bloat": "BLOAT"}
    strip = Text()
    for i, (key, label) in enumerate(labels.items()):
        if i:
            strip.append("  ·  ", style="dim")
        strip.append(f"{label} ", style="dim")
        strip.append_text(_grade_txt(ov.domains.get(key), gt))
    overall_line = Text()
    overall_line.append(" OVERALL  ", style="cyan bold")
    overall_line.append_text(_grade_txt(ov.overall_score, gt))
    overall_line.append(f" — {ov.verdict}", style=verdict_style)

    net_line = state.get("header_line", "")
    grid = Table.grid(padding=(0, 1))
    grid.add_column()
    grid.add_row(title)
    grid.add_row("")
    grid.add_row(overall_line)
    grid.add_row(strip)
    if net_line:
        grid.add_row(Text(f" {net_line}", style="dim"))
    return Panel(grid, border_style=verdict_style)


def _link_panel(state: dict) -> Panel:
    wifi = state.get("wifi") or {}
    gw = state.get("gw_snap")
    gw_ip = state.get("gateway_ip")

    if state.get("gateway_blocked"):
        gw_line = f"{gw_ip} — no reply (ICMP blocked, link assumed fine)"
    elif gw is not None:
        gw_line = f"{gw_ip} — {_fmt(gw.avg_ms)} avg · {gw.loss_pct:.0f}% loss"
    elif gw_ip:
        gw_line = f"{gw_ip} — unmeasured"
    else:
        gw_line = "no default gateway (VPN full-tunnel or offline?)"

    rows = [
        ("SSID", wifi.get("ssid") or "wired/unknown"),
        ("Band", f"{wifi.get('band') or '?'} · ch {wifi.get('channel') or '?'} · {wifi.get('radio') or '?'}"),
        ("Signal", f"{wifi.get('signal') or '?'}% · {wifi.get('tx_rate') or '?'} Mbps link"),
        ("Gateway", gw_line),
        ("Grade", _grade_txt(gw.score if gw else None, state.get("grade_thresholds"))),
    ]
    return Panel(_kv(rows), title="LOCAL LINK", border_style="cyan")


def _wifi_env_panel(state: dict) -> Panel:
    env = state.get("wifi_env")
    if env is None:
        return Panel(Text("run --full for a channel scan", style="dim"), title="WIFI ENVIRONMENT", border_style="cyan")
    rows = [
        ("APs visible", env.total_aps),
        ("My channel", f"ch {env.current_channel} ({env.current_band}) — {env.cochannel_strong} strong, {env.cochannel_aps} total co-channel"),
        ("5 GHz twin", "yes — switch to it!" if env.has_5ghz_variant else ("no" if env.current_band and env.current_band.startswith("2.4") else "n/a")),
        ("Grade", _grade_txt(env.score(), state.get("grade_thresholds"))),
    ]
    panel = Panel(_kv(rows), title="WIFI ENVIRONMENT", border_style="cyan")
    return panel


def _path_panel(state: dict) -> Panel:
    net = state.get("net_snap")
    history = state.get("latency_history") or []

    body = Table.grid(padding=(0, 1))
    body.add_column(style="cyan bold", justify="right")
    body.add_column()

    if net:
        body.add_row("Latency", f"{_fmt(net.avg_ms)} avg · {_fmt(net.p95_ms)} p95")
        body.add_row("Jitter", _fmt(net.jitter_ms))
        body.add_row("Loss", f"{net.loss_pct:.1f}%")
        body.add_row("Grade", _grade_txt(net.score, state.get("grade_thresholds")))
    if len(history) >= 4:
        body.add_row("Trend", _sparkline_text(history))
    if net:
        style = VERDICT_STYLE.get(net.verdict, "white")
        body.add_row("Diagnosis", Text(state.get("diagnosis", ""), style=style))
    return Panel(body, title="INTERNET PATH", border_style="green")


def _dns_panel(state: dict) -> Panel:
    dns = state.get("dns")
    if dns is None:
        return Panel(Text("pending…", style="dim"), title="DNS", border_style="magenta")
    resolvers = ", ".join(dns.resolvers) or "unknown"
    rows = [
        ("Resolvers", resolvers),
        ("Lookup", _fmt(dns.avg_ms) if dns.avg_ms is not None else f"FAILING ({dns.failures})"),
        ("Hijack", Text("DETECTED", style="bold red") if dns.hijacked else Text("no", style="green")),
        ("Grade", _grade_txt(dns.score(), state.get("grade_thresholds"))),
    ]
    if dns.hijack_note:
        rows.append(("Note", dns.hijack_note))
    return Panel(_kv(rows), title="DNS", border_style="magenta")


def _deep_panel(state: dict) -> Panel:
    bloat = state.get("bloat")
    mtu = state.get("mtu")
    path = state.get("path_trace")

    rows: list[tuple[str, object]] = []
    if bloat and bloat.tested:
        if bloat.delta_ms is not None:
            rows.append(("Bloat ↓", f"+{bloat.delta_ms:.0f} ms under load → {bloat.grade}"))
        if bloat.up_delta_ms is not None:
            rows.append(("Bloat ↑", f"+{bloat.up_delta_ms:.0f} ms under load → {bloat.up_grade}"))
        if bloat.throughput_mbps:
            rows.append(("Download", f"{bloat.throughput_mbps:.1f} Mbps"))
        if bloat.up_mbps:
            rows.append(("Upload", f"{bloat.up_mbps:.1f} Mbps"))
    elif bloat and bloat.note:
        rows.append(("Bloat", bloat.note))
    else:
        rows.append(("Bloat", "run --full (deep test)"))
    if mtu:
        rows.append(("Path MTU", f"{mtu.path_mtu or '?'} {'⚠ blackhole' if mtu.blackhole else 'ok'}"))
    if path:
        rows.append(("Route", path.summary()))
    if not rows:
        rows.append(("Status", "no deep data yet"))
    return Panel(_kv(rows), title="DEEP DIAGNOSTICS", border_style="yellow")


def _events_panel(state: dict) -> Panel:
    evts = state.get("events") or []
    if not evts:
        return Panel(Text("no events yet — that's a good thing", style="dim"), title="EVENTS (recent)", border_style="blue")
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold magenta", no_wrap=True)
    table.add_column(overflow="fold")
    for e in evts[:6]:
        ts = e["timestamp"].split("T")[-1] if "T" in e["timestamp"] else e["timestamp"]
        table.add_row(ts, e["type"], e["detail"])
    return Panel(table, title="EVENTS (recent)", border_style="blue")


def build_dashboard(state: dict) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=10),
        Layout(name="body", ratio=1),
        Layout(name="events", size=9),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=45),
        Layout(name="right", ratio=55),
    )
    layout["left"].split_column(Layout(name="link", ratio=1), Layout(name="wifienv", ratio=1))
    layout["right"].split_column(
        Layout(name="path", ratio=2), Layout(name="dns", ratio=1), Layout(name="deep", ratio=1)
    )

    layout["header"].update(_header(state))
    layout["link"].update(_link_panel(state))
    layout["wifienv"].update(_wifi_env_panel(state))
    layout["path"].update(_path_panel(state))
    layout["dns"].update(_dns_panel(state))
    layout["deep"].update(_deep_panel(state))
    layout["events"].update(_events_panel(state))
    return layout


def build_full_report(state: dict) -> list:
    """Sequential panels for --full (console, not Live)."""
    vpn = state.get("vpn")
    extra = []
    if vpn:
        line = f"active: {vpn.label}"
        if vpn.warp_cli:
            line += f" · warp app: {vpn.warp_cli}"
        if vpn.default_interface:
            line += f" · default route via {vpn.default_interface}"
        extra.append(Panel(Text(line), title="VPN / TUNNELS", border_style="bright_red"))
    if state.get("wifi_env"):
        advice = state["wifi_env"].advice
        extra.append(Panel(Text(advice), title="WIFI ADVICE", border_style="cyan"))

    return [
        _header(state),
        _link_panel(state),
        _path_panel(state),
        _dns_panel(state),
        _wifi_env_panel(state),
        _deep_panel(state),
        *extra,
        _events_panel(state),
    ]
