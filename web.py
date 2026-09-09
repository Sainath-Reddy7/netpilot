"""Web publishing: turn NetPilot logs into a shareable static dashboard.

`python netpilot.py --publish` generates web/index.html — a single
self-contained file (inline CSS/JS, zero external requests, zero tracking)
that can be hosted anywhere. Deploy on Vercel:

  1. Push the repo (web/index.html included)
  2. vercel.com → Add New Project → import the repo → Deploy
     (vercel.json already points at web/)

Use `--demo` to publish realistic synthetic data (no SSIDs leaked) and
`--anon` to pseudonymize real network names before publishing.
"""

from __future__ import annotations

import html as html_mod
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from events import EVENTS_FILE
from logger import LOG_FILE

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
MIN_ROWS = 5


# ---------------------------------------------------------------- data

def _load_real(days: int) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(LOG_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].copy()
    df["hour"] = df["timestamp"].dt.hour

    networks = []
    score_col = "overall_score" if "overall_score" in df.columns else "net_score"
    for ssid, g in df.groupby("ssid"):
        hourly = []
        for h in range(24):
            rows = g[g["hour"] == h]
            hourly.append(
                {
                    "lat": round(float(rows["net_avg_ms"].median()), 1) if len(rows) else None,
                    "loss": round(float(rows["net_loss_pct"].mean()), 1) if len(rows) else None,
                    "score": round(float(rows[score_col].mean()), 1) if len(rows) else None,
                    "n": int(len(rows)),
                }
            )
        sampled = [x["score"] for x in hourly if x["score"] is not None]
        networks.append(
            {
                "ssid": str(ssid),
                "samples": int(len(g)),
                "median_score": round(float(g[score_col].median()), 1) if len(g) else 0,
                "hourly": hourly,
            }
        )
    return networks


def _load_incidents(days: int, limit: int = 15) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        import pandas as pd

        ev = pd.read_csv(EVENTS_FILE)
        ev["timestamp"] = pd.to_datetime(ev["timestamp"], errors="coerce")
        ev = ev.dropna(subset=["timestamp"])
        ev = ev[ev["timestamp"] >= ev["timestamp"].max() - pd.Timedelta(days=days)]
        ev = ev[ev["type"].isin(["OUTAGE", "WIFI_DOWN", "DNS_FAIL", "AP_ROAM", "NETWORK_CHANGE"])]
        return [
            {"when": row["timestamp"].strftime("%d %b %H:%M"), "type": str(row["type"]), "detail": str(row["detail"])}
            for _, row in ev.sort_values("timestamp", ascending=False).head(limit).iterrows()
        ]
    except Exception:
        return []


def generate_demo_data() -> dict:
    """Synthetic but realistic one-week dataset (evening congestion included)."""
    rng = random.Random(42)
    networks = []
    profiles = [
        {"ssid": "Campus-5G", "base": 42.0, "evening": 130.0, "evening_loss": 7.0, "night": 55.0},
        {"ssid": "Phone-hotspot", "base": 34.0, "evening": 190.0, "evening_loss": 12.0, "night": 60.0},
    ]
    for p in profiles:
        hourly = []
        for h in range(24):
            if 19 <= h <= 23:
                lat = p["evening"] + rng.uniform(-25, 45)
                loss = p["evening_loss"] + rng.uniform(-3, 4)
                score = rng.uniform(18, 45)
            elif 0 <= h <= 2:
                lat = p["night"] + rng.uniform(-10, 20)
                loss = rng.uniform(0, 2)
                score = rng.uniform(55, 75)
            else:
                lat = p["base"] + rng.uniform(-6, 10)
                loss = rng.uniform(0, 0.6)
                score = rng.uniform(80, 97)
            hourly.append(
                {
                    "lat": round(lat, 1),
                    "loss": round(max(0.0, loss), 1),
                    "score": round(score, 1),
                    "n": rng.randint(8, 30),
                }
            )
        good = [h for h, x in enumerate(hourly) if x["score"] >= 75]
        networks.append(
            {
                "ssid": p["ssid"],
                "samples": sum(x["n"] for x in hourly) * 7,
                "median_score": round(sorted(x["score"] for x in hourly)[len(hourly) // 2], 1),
                "hourly": hourly,
                "good_hours": good,
            }
        )
    incidents = [
        {"when": "08 Sep 21:34", "type": "OUTAGE", "detail": "Network unusable for 242s (21:30-21:34). Upstream congested."},
        {"when": "08 Sep 20:58", "type": "AP_ROAM", "detail": "Roamed between access points of Campus-5G."},
        {"when": "07 Sep 22:41", "type": "DNS_FAIL", "detail": "DNS resolution failing (2 hosts this cycle)."},
        {"when": "07 Sep 21:02", "type": "OUTAGE", "detail": "Network unusable for 96s (21:00-21:02). Upstream congested."},
        {"when": "06 Sep 19:47", "type": "WIFI_DOWN", "detail": "WiFi dropped (state: disconnected)."},
    ]
    return {"networks": networks, "incidents": incidents, "availability": 96.4, "demo": True}


def _anon(networks: list[dict]) -> list[dict]:
    mapping: dict[str, str] = {}
    for net in networks:
        if net["ssid"] not in mapping:
            mapping[net["ssid"]] = f"Network {chr(ord('A') + len(mapping))}"
        net["ssid"] = mapping[net["ssid"]]
    return networks


# ---------------------------------------------------------------- render

HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetPilot — Network Health</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d; --fg: #e6edf3;
    --muted: #8b949e; --accent: #58a6ff; --good: #3fb950; --warn: #d29922; --bad: #f85149;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--fg);
         font-family: 'Segoe UI', system-ui, sans-serif; padding: 2rem 1rem; }
  .wrap { max-width: 1080px; margin: 0 auto; }
  header { border-bottom: 2px solid var(--accent); padding-bottom: 1rem; margin-bottom: 1.5rem; }
  h1 { font-size: 1.6rem; letter-spacing: .5px; }
  h1 .logo { color: var(--accent); }
  .meta { color: var(--muted); margin-top: .4rem; font-size: .9rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
  .card .k { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .5px; }
  .card .v { font-size: 1.5rem; font-weight: 700; margin-top: .3rem; }
  section.net { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
                padding: 1.2rem; margin-bottom: 1.2rem; }
  section.net h2 { font-size: 1.05rem; margin-bottom: .2rem; }
  section.net .sub { color: var(--muted); font-size: .85rem; margin-bottom: .9rem; }
  .score { float: right; font-size: 1.3rem; font-weight: 700; }
  .heat { display: grid; grid-template-columns: repeat(24, 1fr); gap: 2px; }
  .heat .h { font-size: .55rem; color: var(--muted); text-align: center; }
  .cell { height: 30px; border-radius: 3px; background: #21262d; position: relative; cursor: default; }
  .cell:hover { outline: 1px solid var(--fg); }
  .cell[data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: 110%;
    left: 50%; transform: translateX(-50%); background: #000; color: var(--fg);
    padding: .35rem .6rem; border-radius: 4px; font-size: .7rem; white-space: nowrap; z-index: 5; }
  .chips { margin-top: .8rem; font-size: .8rem; line-height: 1.9; }
  .chip { display: inline-block; padding: .1rem .55rem; border-radius: 999px; margin-right: .3rem; }
  .chip.good { background: rgba(63,185,80,.15); color: var(--good); }
  .chip.bad { background: rgba(248,81,73,.15); color: var(--bad); }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; }
  .type-OUTAGE, .type-WIFI_DOWN { color: var(--bad); font-weight: 600; }
  .type-DNS_FAIL { color: var(--warn); font-weight: 600; }
  .type-AP_ROAM, .type-NETWORK_CHANGE { color: var(--accent); font-weight: 600; }
  footer { color: var(--muted); font-size: .8rem; margin-top: 2rem; text-align: center; }
  footer a { color: var(--accent); text-decoration: none; }
  .grade-A { color: var(--good); } .grade-B { color: #39c5cf; }
  .grade-C { color: var(--warn); } .grade-D { color: #db6d28; } .grade-F { color: var(--bad); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="logo">📡 NetPilot</span> — Network Health</h1>
    <div class="meta" id="meta"></div>
  </header>
  <div class="cards" id="cards"></div>
  <div id="nets"></div>
  <section class="net">
    <h2>Recent incidents</h2>
    <div class="sub">Outages, drops, roaming and DNS failures</div>
    <table id="incidents"></table>
  </section>
  <footer>Generated by <a href="https://github.com/Sainath-Reddy7/netpilot">NetPilot</a> · all data measured locally</footer>
</div>
<script>
const DATA = __DATA__;

function latColor(ms) {
  if (ms === null) return '#21262d';
  if (ms < 50) return '#2ea043'; if (ms < 80) return '#9ac51e';
  if (ms < 120) return '#d29922'; if (ms < 200) return '#db6d28';
  return '#f85149';
}
function gradeOf(score) { return score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 60 ? 'C' : score >= 40 ? 'D' : 'F'; }
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

document.getElementById('meta').textContent =
  'Generated ' + DATA.generated + (DATA.demo ? ' · DEMO DATA' : ' · last ' + DATA.days + ' day(s)');

// summary cards
const allScores = DATA.networks.map(n => n.median_score);
const avg = allScores.length ? Math.round(allScores.reduce((a,b)=>a+b,0)/allScores.length) : 0;
const worstNet = DATA.networks.slice().sort((a,b)=>a.median_score-b.median_score)[0];
document.getElementById('cards').innerHTML = [
  ['Networks monitored', DATA.networks.length],
  ['Median overall score', avg + '/100'],
  ['Availability', DATA.availability !== null ? DATA.availability.toFixed(2) + '%' : 'n/a'],
  ['Incidents (recent)', DATA.incidents.length],
].map(([k,v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

// network sections
document.getElementById('nets').innerHTML = DATA.networks.map(net => {
  const grade = gradeOf(net.median_score);
  const heat = net.hourly.map((x, h) => {
    const tip = x.lat === null ? 'no data' :
      `${String(h).padStart(2,'0')}:00 — ${x.lat} ms · ${x.loss}% loss · score ${x.score}`;
    return `<div class="cell" style="background:${latColor(x.lat)}" data-tip="${tip}" title=""></div>`;
  }).join('');
  const hours = net.hourly.map((x, h) => ({h, x}));
  const good = hours.filter(o => o.x.score !== null && o.x.score >= 75).map(o => o.h);
  const dead = hours.filter(o => o.x.score !== null && o.x.score < 40).map(o => o.h);
  const fmt = hs => hs.length ? hs.map(h => String(h).padStart(2,'0')).join(', ') : 'none';
  return `<section class="net">
    <h2>${esc(net.ssid)} <span class="score grade-${grade}">${net.median_score} · ${grade}</span></h2>
    <div class="sub">${net.samples} samples · per-hour median latency (hover for detail)</div>
    <div class="heat">${Array.from({length:24},(_,h)=>`<div class="h">${String(h).padStart(2,'0')}</div>`).join('')}${heat}</div>
    <div class="chips">
      <span class="chip good">healthy: ${fmt(good)}</span>
      <span class="chip bad">dead: ${fmt(dead)}</span>
    </div>
  </section>`;
}).join('');

// incidents
const inc = document.getElementById('incidents');
inc.innerHTML = DATA.incidents.length
  ? '<tr><th>When</th><th>Type</th><th>Detail</th></tr>' +
    DATA.incidents.map(e => `<tr><td>${esc(e.when)}</td><td class="type-${esc(e.type)}">${esc(e.type)}</td><td>${esc(e.detail)}</td></tr>`).join('')
  : '<tr><td style="color:var(--muted)">No incidents logged — that\\'s a good thing.</td></tr>';
</script>
</body>
</html>
"""


def publish(days: int = 7, demo: bool = False, anon: bool = False) -> Path:
    if demo:
        data = generate_demo_data()
    else:
        if not LOG_FILE.exists():
            raise SystemExit(f"No logs at {LOG_FILE} — run the monitor first, or use --demo.")
        networks = _load_real(days)
        if len(networks) == 0:
            raise SystemExit("No log rows in range — run the monitor first, or use --demo.")
        if anon:
            networks = _anon(networks)
        incidents = _load_incidents(days)

        from events import availability_pct

        data = {
            "networks": networks,
            "incidents": incidents,
            "availability": availability_pct(hours=days * 24),
            "demo": False,
        }

    data["generated"] = datetime.now().strftime("%d %b %Y %H:%M")
    data["days"] = days
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    html = HTML_SHELL.replace("__DATA__", payload)
    # incident details are plain text from our own logger; escape for safety
    WEB_DIR.mkdir(exist_ok=True)
    out = WEB_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys

    demo = "--demo" in sys.argv
    print(publish(demo=demo))
