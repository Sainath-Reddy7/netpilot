"""Report v2: heatmap + schedule + incidents + availability + HTML export.

Generates:
  * reports/netpilot_report.png   — hour-of-day congestion heatmap per network
  * reports/netpilot_report.html  — standalone shareable report (embeds PNG)
  * console summary — healthy/dead hours per network, worst incidents
"""

from __future__ import annotations

import base64
import html as html_mod
from datetime import datetime
from pathlib import Path

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # render to file, never a GUI window
import matplotlib.pyplot as plt  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from events import EVENTS_FILE, availability_pct  # noqa: E402
from logger import LOG_FILE  # noqa: E402

console = Console()
REPORT_DIR = Path(__file__).resolve().parent / "reports"
MIN_ROWS = 10

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NetPilot Report</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 2rem auto; max-width: 1000px;
         background: #0d1117; color: #e6edf3; }}
  h1 {{ border-bottom: 2px solid #388bfd; padding-bottom: .4rem; }}
  h2 {{ color: #58a6ff; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #30363d; padding: .5rem .8rem; text-align: left; }}
  th {{ background: #161b22; }}
  .good {{ color: #3fb950; font-weight: 600; }} .bad {{ color: #f85149; font-weight: 600; }}
  .warn {{ color: #d29922; font-weight: 600; }}
  img {{ max-width: 100%; border: 1px solid #30363d; border-radius: 6px; }}
  .muted {{ color: #8b949e; }}
</style>
</head>
<body>
<h1>NetPilot — Network Report</h1>
<p class="muted">Generated {generated}</p>
<h2>Congestion heatmap</h2>
<img src="data:image/png;base64,{heatmap_b64}" alt="heatmap"/>
<h2>Network schedules</h2>
{schedules_html}
<h2>Incidents (worst {max_incidents})</h2>
{incidents_html}
<h2>Availability</h2>
<p>{availability_html}</p>
</body>
</html>
"""


def _hour_ranges(hours: list[int]) -> str:
    """Compress [9,10,11,14] into '09:00-12:00, 14:00-15:00'."""
    if not hours:
        return "none"
    hours = sorted(set(hours))
    ranges: list[str] = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        ranges.append(f"{start:02d}:00-{prev + 1:02d}:00")
        start = prev = h
    ranges.append(f"{start:02d}:00-{prev + 1:02d}:00")
    return ", ".join(ranges)


def _load(days: int) -> pd.DataFrame | None:
    if not LOG_FILE.exists():
        console.print(f"No log file yet at {LOG_FILE}. Run the monitor first.")
        return None
    df = pd.read_csv(LOG_FILE)
    if len(df) < MIN_ROWS:
        console.print(
            f"Only {len(df)} rows logged (need {MIN_ROWS}+). "
            "Keep the monitor running for a few hours to get a meaningful heatmap."
        )
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].copy()
    df["hour"] = df["timestamp"].dt.hour
    return df


def _incidents_table(days: int, max_rows: int = 12) -> Table | None:
    if not EVENTS_FILE.exists():
        return None
    try:
        ev = pd.read_csv(EVENTS_FILE)
        ev["timestamp"] = pd.to_datetime(ev["timestamp"], errors="coerce")
        ev = ev.dropna(subset=["timestamp"])
        cutoff = ev["timestamp"].max() - pd.Timedelta(days=days)
        ev = ev[ev["timestamp"] >= cutoff]
        ev = ev[ev["type"].isin(["OUTAGE", "WIFI_DOWN", "DNS_FAIL", "NETWORK_CHANGE", "AP_ROAM"])]
        if ev.empty:
            return None
        ev = ev.sort_values("timestamp", ascending=False).head(max_rows)
    except Exception:
        return None

    table = Table(title=f"Recent incidents (last {days} day(s))", show_lines=False)
    table.add_column("When", style="dim", width=19)
    table.add_column("Type", style="bold magenta", width=14)
    table.add_column("Detail", overflow="fold")
    style_map = {"OUTAGE": "red", "WIFI_DOWN": "red", "DNS_FAIL": "yellow", "AP_ROAM": "cyan", "NETWORK_CHANGE": "cyan"}
    for _, row in ev.iterrows():
        table.add_row(
            str(row["timestamp"].strftime("%d %b %H:%M:%S")),
            f"[{style_map.get(row['type'], 'white')}]{row['type']}[/{style_map.get(row['type'], 'white')}]",
            str(row["detail"]),
        )
    return table


def build_report(days: int = 7, html_export: bool = True) -> Path | None:
    df = _load(days)
    if df is None:
        return None

    lat = df.pivot_table(index="ssid", columns="hour", values="net_avg_ms", aggfunc="median")
    loss = df.pivot_table(index="ssid", columns="hour", values="net_loss_pct", aggfunc="mean")
    score = df.pivot_table(index="ssid", columns="hour", values="overall_score", aggfunc="mean") \
        if "overall_score" in df.columns else None

    lat = lat.reindex(columns=range(24))
    loss = loss.reindex(columns=range(24))
    score = score.reindex(columns=range(24)) if score is not None else None

    # ---------------- heatmap PNG ----------------
    fig, axes = plt.subplots(2, 1, figsize=(14, 2 + 2 * len(lat.index)), sharex=True)
    fig.suptitle(f"NetPilot — network congestion over the last {days} day(s)", fontsize=13)
    for ax, data, title, cmap, vmax in (
        (axes[0], lat, "Median latency (ms) — lower is better", "RdYlGn_r", 250),
        (axes[1], loss, "Mean packet loss (%) — lower is better", "Reds", 10),
    ):
        im = ax.imshow(data.values, aspect="auto", cmap=cmap, vmin=0, vmax=vmax)
        ax.set_yticks(range(len(data.index)))
        ax.set_yticklabels(data.index, fontsize=9)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                val = data.values[i, j]
                if pd.notna(val):
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=6)
        fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    axes[1].set_xlabel("Hour of day")
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    REPORT_DIR.mkdir(exist_ok=True)
    png_path = REPORT_DIR / "netpilot_report.png"
    fig.savefig(png_path, dpi=150)

    # ---------------- console summary ----------------
    schedules: dict[str, dict] = {}
    console.print()
    console.print(f"[bold]Network schedule summary (last {days} day(s))[/bold]")
    for ssid in lat.index:
        s = score.loc[ssid].dropna() if score is not None else pd.Series(dtype=float)
        if s.empty and "net_score" in df.columns:
            alt = df[df["ssid"] == ssid].groupby("hour")["net_score"].mean()
            s = alt
        good_hours = [h for h, v in s.items() if v >= 75]
        dead_hours = [h for h, v in s.items() if v < 40]
        med = s.median() if len(s) else 0
        rows_n = int((df["ssid"] == ssid).sum())
        schedules[ssid] = {
            "good": good_hours, "dead": dead_hours,
            "median": float(med) if len(s) else None, "rows": rows_n,
        }
        console.print(
            f"  [cyan]{ssid}[/cyan] ({rows_n} samples) — overall score "
            f"{med:.0f}/100\n"
            f"    healthy hours: [green]{_hour_ranges(good_hours)}[/green]\n"
            f"    dead hours:    [red]{_hour_ranges(dead_hours)}[/red]"
        )

    incidents = _incidents_table(days)
    if incidents is not None:
        console.print()
        console.print(incidents)

    # Week-over-week trend per network (needs 8+ days of history)
    if "overall_score" in df.columns and len(df) > 0:
        df["week"] = (df["timestamp"] - df["timestamp"].min()).dt.days // 7
        weekly = df.groupby(["ssid", "week"])["overall_score"].median()
        trend_lines: list[str] = []
        for ssid in weekly.index.get_level_values(0).unique():
            weeks = weekly[ssid].dropna()
            if len(weeks) >= 2:
                first, last = float(weeks.iloc[0]), float(weeks.iloc[-1])
                change = last - first
                arrow = "↑" if change >= 3 else ("↓" if change <= -3 else "→")
                color = "green" if change >= 3 else ("red" if change <= -3 else "yellow")
                trend_lines.append(
                    f"  [cyan]{ssid}[/cyan]: week 1 {first:.0f} → last week {last:.0f} "
                    f"[{color}]{arrow} {change:+.0f}[/{color}]"
                )
        if trend_lines:
            console.print("\n[bold]Week-over-week trend[/bold]")
            for line in trend_lines:
                console.print(line)

    avail = availability_pct(hours=days * 24)
    if avail is not None:
        style = "green" if avail >= 99 else ("yellow" if avail >= 95 else "red")
        console.print(f"\nAvailability (uptime while monitored, last {days}d): "
                      f"[{style}]{avail:.2f}%[/{style}]")

    # ---------------- HTML export ----------------
    html_path: Path | None = None
    if html_export:
        schedules_html = "<table><tr><th>Network</th><th>Samples</th><th>Score</th><th>Healthy hours</th><th>Dead hours</th></tr>"
        for ssid, info in schedules.items():
            med = info["median"]
            score_html = f"<span class='good'>{med:.0f}</span>" if med and med >= 75 else (
                f"<span class='warn'>{med:.0f}</span>" if med and med >= 40 else f"<span class='bad'>{med:.0f}</span>")
            schedules_html += (
                f"<tr><td>{html_mod.escape(ssid)}</td><td>{info['rows']}</td><td>{score_html}</td>"
                f"<td class='good'>{_hour_ranges(info['good'])}</td>"
                f"<td class='bad'>{_hour_ranges(info['dead'])}</td></tr>"
            )
        schedules_html += "</table>"

        incidents_html = "<p class='muted'>No incidents logged.</p>"
        if EVENTS_FILE.exists():
            try:
                ev = pd.read_csv(EVENTS_FILE)
                ev["timestamp"] = pd.to_datetime(ev["timestamp"], errors="coerce")
                ev = ev.dropna(subset=["timestamp"])
                ev = ev[ev["timestamp"] >= ev["timestamp"].max() - pd.Timedelta(days=days)]
                ev = ev[ev["type"].isin(["OUTAGE", "WIFI_DOWN", "DNS_FAIL", "NETWORK_CHANGE", "AP_ROAM"])]
                if not ev.empty:
                    incidents_html = "<table><tr><th>When</th><th>Type</th><th>Detail</th></tr>"
                    for _, row in ev.sort_values("timestamp", ascending=False).head(15).iterrows():
                        incidents_html += (
                            f"<tr><td>{row['timestamp'].strftime('%d %b %H:%M:%S')}</td>"
                            f"<td class='warn'>{html_mod.escape(str(row['type']))}</td>"
                            f"<td>{html_mod.escape(str(row['detail']))}</td></tr>"
                        )
                    incidents_html += "</table>"
            except Exception:
                pass

        availability_html = (
            f"{availability_pct(hours=days * 24):.2f}% uptime while monitored"
            if availability_pct(hours=days * 24) is not None else "not enough event data"
        )
        heatmap_b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
        html_path = REPORT_DIR / "netpilot_report.html"
        html_path.write_text(
            HTML_TEMPLATE.format(
                generated=datetime.now().strftime("%d %b %Y %H:%M"),
                heatmap_b64=heatmap_b64,
                schedules_html=schedules_html,
                max_incidents=15,
                incidents_html=incidents_html,
                availability_html=availability_html,
            ),
            encoding="utf-8",
        )
        console.print(f"\nSaved heatmap: [cyan]{png_path}[/cyan]")
        console.print(f"Saved HTML report: [cyan]{html_path}[/cyan]")

    return png_path


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    build_report(days)
