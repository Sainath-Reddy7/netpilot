"""Report: turns logged CSV history into a congestion heatmap + summary.

The heatmap answers the real question: *WHEN is each of my networks usable?*
Rows are networks (SSIDs), columns are hours of the day.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # render to file, never a GUI window
import matplotlib.pyplot as plt  # noqa: E402
from rich.console import Console  # noqa: E402

from logger import LOG_FILE  # noqa: E402

console = Console()

REPORT_DIR = Path(__file__).resolve().parent / "reports"
MIN_ROWS = 10


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


def build_report(days: int = 7) -> Path | None:
    """Generate reports/netpilot_report.png from the CSV log. Returns path or None."""
    if not LOG_FILE.exists():
        print(f"No log file yet at {LOG_FILE}. Run the monitor first.")
        return None

    df = pd.read_csv(LOG_FILE)
    if len(df) < MIN_ROWS:
        print(
            f"Only {len(df)} rows logged (need {MIN_ROWS}+). "
            "Keep the monitor running for a few hours to get a meaningful heatmap."
        )
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].copy()
    df["hour"] = df["timestamp"].dt.hour

    # Hourly aggregates per network
    lat = df.pivot_table(index="ssid", columns="hour", values="net_avg_ms", aggfunc="median")
    loss = df.pivot_table(index="ssid", columns="hour", values="net_loss_pct", aggfunc="mean")
    score = df.pivot_table(index="ssid", columns="hour", values="net_score", aggfunc="mean")

    lat = lat.reindex(columns=range(24))
    loss = loss.reindex(columns=range(24))
    score = score.reindex(columns=range(24))

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
    out = REPORT_DIR / "netpilot_report.png"
    fig.savefig(out, dpi=150)

    # Text summary
    console.print()
    console.print(f"[bold]Network schedule summary (last {days} day(s))[/bold]")
    for ssid in lat.index:
        s = score.loc[ssid].dropna()
        good_hours = [h for h, v in s.items() if v >= 75]
        dead_hours = [h for h, v in s.items() if v < 40]
        med = s.median() if len(s) else 0
        console.print(
            f"  [cyan]{ssid}[/cyan] — overall score {med:.0f}/100\n"
            f"    healthy hours: [green]{_hour_ranges(good_hours)}[/green]\n"
            f"    dead hours:    [red]{_hour_ranges(dead_hours)}[/red]"
        )
    console.print(f"\nSaved heatmap: [cyan]{out}[/cyan]")
    return out


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    build_report(days)
