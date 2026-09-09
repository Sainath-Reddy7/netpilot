"""Generate README terminal screenshots as SVGs (rich save_svg).

Runs one light cycle + one deep cycle against the live network, renders the
dashboard and the full report into docs/screenshots/*.svg.

Usage:  python scripts/generate_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable when run from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402

from dashboard import build_dashboard, build_full_report  # noqa: E402
from health import roll_up  # noqa: E402
from netpilot import load_config, make_engine, run_deep, run_light  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main() -> None:
    engine = make_engine(load_config())
    state = run_light(engine)
    run_deep(engine)
    state.update(engine.deep)

    # Re-roll the overall score now that deep data exists
    env = engine.deep.get("wifi_env")
    radio = env.score() if env else None
    bloat = engine.deep.get("bloat")
    bloat_s = bloat.score() if bloat and bloat.tested else None
    state["overall"] = roll_up(
        state["net_snap"], state["gw_snap"], state["dns"].score(), radio, bloat_s, engine.cfg["thresholds"]
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    c1 = Console(record=True, width=112, height=40, force_terminal=True)
    c1.print(build_dashboard(state))
    c1.save_svg(str(OUT_DIR / "dashboard.svg"), title="NetPilot — live dashboard")

    c2 = Console(record=True, width=96, force_terminal=True)
    for panel in build_full_report(state):
        c2.print(panel)
    c2.save_svg(str(OUT_DIR / "full-report.svg"), title="NetPilot — full diagnostics (--full)")

    print(f"saved: {OUT_DIR / 'dashboard.svg'}")
    print(f"saved: {OUT_DIR / 'full-report.svg'}")


if __name__ == "__main__":
    main()
