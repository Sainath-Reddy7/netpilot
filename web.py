"""Web publishing: live-updating shareable dashboard.

Two data paths, both served by one self-contained HTML file:

  1. LIVE:   the page fetches web/data.json from the repo's `data` branch
             (raw.githubusercontent.com) every 60 s. The collector on the
             laptop pushes fresh data there via the GitHub API — no rebuilds,
             no deploy limits.
  2. FALLBACK: a snapshot embedded at publish time, used until the first
             successful fetch (or if GitHub is unreachable).

`python netpilot.py --publish`     real data snapshot embedded + live fetch
`python netpilot.py --publish --demo`  synthetic demo payload
`python netpilot.py --publish --anon`  pseudonymized network names
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from logger import LOG_FILE
from sync import build_payload, raw_data_url

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
MIN_ROWS = 1

DEFAULT_SYNC_CFG = {
    "repo": "Sainath-Reddy7/netpilot",
    "branch": "data",
    "path": "web/data.json",
}


def generate_demo_data() -> dict:
    """Synthetic but realistic one-week dataset (evening congestion included)."""
    import random

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
                {"lat": round(lat, 1), "loss": round(max(0.0, loss), 1),
                 "score": round(score, 1), "n": rng.randint(8, 30)}
            )
        networks.append(
            {
                "ssid": p["ssid"],
                "samples": sum(x["n"] for x in hourly) * 7,
                "median_score": round(sorted(x["score"] for x in hourly)[len(hourly) // 2], 1),
                "hourly": hourly,
            }
        )
    incidents = [
        {"when": "08 Sep 21:34", "type": "OUTAGE", "detail": "Network unusable for 242s (21:30-21:34). Upstream congested."},
        {"when": "08 Sep 20:58", "type": "AP_ROAM", "detail": "Roamed between access points of Campus-5G."},
        {"when": "07 Sep 22:41", "type": "DNS_FAIL", "detail": "DNS resolution failing (2 hosts this cycle)."},
        {"when": "07 Sep 21:02", "type": "OUTAGE", "detail": "Network unusable for 96s (21:00-21:02). Upstream congested."},
        {"when": "06 Sep 19:47", "type": "WIFI_DOWN", "detail": "WiFi dropped (state: disconnected)."},
    ]
    return {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "now": {"ssid": "Campus-5G", "verdict": "GO", "score": 91, "avg_ms": 44,
                "loss_pct": 0.0, "jitter_ms": 5, "vpn": "", "band": "5 GHz", "signal": 100},
        "networks": networks,
        "incidents": incidents,
        "availability": 96.4,
        "demo": True,
    }


HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetPilot — Live Network Health</title>
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
  .badge { display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: 1px;
           padding: .15rem .5rem; border-radius: 4px; vertical-align: middle; margin-left: .5rem; }
  .badge.live { background: rgba(63,185,80,.2); color: var(--good); }
  .badge.cached { background: rgba(210,156,34,.2); color: var(--warn); }
  .pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
           background: var(--good); margin-right: 4px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% {opacity: 1} 50% {opacity: .3} }
  .hero { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
          padding: 1.4rem; margin-bottom: 1.5rem; display: flex; flex-wrap: wrap; gap: 1.5rem;
          align-items: center; justify-content: space-between; }
  .hero .net { font-size: 1.25rem; font-weight: 700; }
  .hero .sub { color: var(--muted); font-size: .85rem; margin-top: .2rem; }
  .hero .verdict { font-size: 2.2rem; font-weight: 800; letter-spacing: 1px; }
  .stats { display: flex; gap: 1.5rem; flex-wrap: wrap; }
  .stat { text-align: center; }
  .stat .k { color: var(--muted); font-size: .7rem; text-transform: uppercase; letter-spacing: .5px; }
  .stat .v { font-size: 1.3rem; font-weight: 700; margin-top: .15rem; }
  .v.GO { color: var(--good); } .v.WARN { color: var(--warn); } .v.DEAD { color: var(--bad); }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
  .card .k { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .5px; }
  .card .v { font-size: 1.4rem; font-weight: 700; margin-top: .3rem; }
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
    <h1><span class="logo">📡 NetPilot</span> — Live Network Health
        <span class="badge" id="badge"><span class="pulse"></span>LIVE</span></h1>
    <div class="meta" id="meta"></div>
  </header>
  <div class="hero" id="hero"></div>
  <div class="cards" id="cards"></div>
  <div id="nets"></div>
  <section class="net">
    <h2>Recent incidents</h2>
    <div class="sub">Outages, drops, roaming and DNS failures</div>
    <table id="incidents"></table>
  </section>
  <footer>Collected locally by <a href="https://github.com/Sainath-Reddy7/netpilot">NetPilot</a> · auto-refreshes every 60 s · data: <span id="src"></span></footer>
</div>
<script>
const DATA_URL = "__DATA_URL__";
const EMBEDDED = __DATA__;
let DATA = EMBEDDED;

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function gradeOf(score) { return score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 60 ? 'C' : score >= 40 ? 'D' : 'F'; }
function latColor(ms) {
  if (ms === null || ms === undefined) return '#21262d';
  if (ms < 50) return '#2ea043'; if (ms < 80) return '#9ac51e';
  if (ms < 120) return '#d29922'; if (ms < 200) return '#db6d28';
  return '#f85149';
}
function ago(iso) {
  try {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return Math.round(s) + ' s ago';
    if (s < 5400) return Math.round(s/60) + ' min ago';
    return Math.round(s/3600) + ' h ago';
  } catch (e) { return '?'; }
}

function render() {
  const demo = DATA.demo ? ' · DEMO DATA' : '';
  document.getElementById('meta').textContent =
    'Updated ' + ago(DATA.updated) + demo;

  // hero: right now
  const n = DATA.now;
  const hero = document.getElementById('hero');
  if (n) {
    const band = n.band ? ' · ' + esc(n.band) : '';
    const vpn = n.vpn && n.vpn !== 'none' ? ' · VPN: ' + esc(n.vpn) : '';
    const note = n.note ? `<div class="sub" style="color:var(--warn)">⚠ ${esc(n.note)}</div>` : '';
    let extra = '';
    if (n.bloat) extra += `<div class="stat"><div class="k">bloat ↓/↑</div><div class="v" style="font-size:1rem">${esc(n.bloat.down || '–')} / ${esc(n.bloat.up || '–')}</div></div>`;
    if (n.mtu) extra += `<div class="stat"><div class="k">path MTU</div><div class="v" style="font-size:1rem">${esc(n.mtu)}</div></div>`;
    hero.innerHTML = `
      <div>
        <div class="net">${esc(n.ssid || 'unknown')}${band}${vpn}</div>
        <div class="sub">measured continuously from the collector machine</div>
        ${note}
      </div>
      <div class="stats">
        <div class="stat"><div class="k">verdict</div><div class="verdict v-${esc(n.verdict)}">${esc(n.verdict)}</div></div>
        <div class="stat"><div class="k">score</div><div class="v">${esc(n.score)}</div></div>
        <div class="stat"><div class="k">latency</div><div class="v">${n.avg_ms !== null && n.avg_ms !== undefined ? esc(n.avg_ms) + ' ms' : '–'}</div></div>
        <div class="stat"><div class="k">loss</div><div class="v">${n.loss_pct !== null && n.loss_pct !== undefined ? esc(n.loss_pct) + '%' : '–'}</div></div>
        <div class="stat"><div class="k">jitter</div><div class="v">${n.jitter_ms !== null && n.jitter_ms !== undefined ? esc(n.jitter_ms) + ' ms' : '–'}</div></div>
        ${extra}
      </div>`;
  }

  // summary cards
  const scores = DATA.networks.map(x => x.median_score);
  const avg = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : 0;
  document.getElementById('cards').innerHTML = [
    ['Networks monitored', DATA.networks.length],
    ['Median overall score', avg + '/100'],
    ['Availability', DATA.availability !== null && DATA.availability !== undefined ? DATA.availability.toFixed(2) + '%' : 'n/a'],
    ['Incidents (recent)', DATA.incidents.length],
  ].map(([k,v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

  // network sections
  document.getElementById('nets').innerHTML = DATA.networks.map(net => {
    const grade = gradeOf(net.median_score);
    const heat = net.hourly.map((x, h) => {
      const tip = x.lat === null || x.lat === undefined ? 'no data' :
        `${String(h).padStart(2,'0')}:00 — ${x.lat} ms · ${x.loss}% loss · score ${x.score}`;
      return `<div class="cell" style="background:${latColor(x.lat)}" data-tip="${esc(tip)}"></div>`;
    }).join('');
    const hours = net.hourly.map((x, h) => ({h, x}));
    const good = hours.filter(o => o.x.score !== null && o.x.score !== undefined && o.x.score >= 75).map(o => o.h);
    const dead = hours.filter(o => o.x.score !== null && o.x.score !== undefined && o.x.score < 40).map(o => o.h);
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
  document.getElementById('incidents').innerHTML = DATA.incidents.length
    ? '<tr><th>When</th><th>Type</th><th>Detail</th></tr>' +
      DATA.incidents.map(e => `<tr><td>${esc(e.when)}</td><td class="type-${esc(e.type)}">${esc(e.type)}</td><td>${esc(e.detail)}</td></tr>`).join('')
    : '<tr><td style="color:var(--muted)">No incidents logged — that\\'s a good thing.</td></tr>';
}

function setBadge(live) {
  const b = document.getElementById('badge');
  b.className = 'badge ' + (live ? 'live' : 'cached');
  b.innerHTML = live ? '<span class="pulse"></span>LIVE' : 'CACHED';
}

async function loadLive() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now(), {cache: 'no-store'});
    if (!res.ok) throw new Error(res.status);
    const fresh = await res.json();
    DATA = fresh;
    setBadge(true);
    document.getElementById('src').textContent = 'live from collector';
  } catch (e) {
    setBadge(false);
    document.getElementById('src').textContent = 'embedded snapshot';
  }
  render();
}

render();
loadLive();
setInterval(loadLive, 60000);
</script>
</body>
</html>
"""


def publish(days: int = 7, demo: bool = False, anon: bool = False, sync_cfg: dict | None = None) -> Path:
    if demo:
        data = generate_demo_data()
    else:
        if not LOG_FILE.exists():
            raise SystemExit(f"No logs at {LOG_FILE} — run the monitor first, or use --demo.")
        data = build_payload(days=days, anonymize=anon, now_state=None)
        if not data["networks"]:
            raise SystemExit("No log rows in range — run the monitor first, or use --demo.")

    cfg = sync_cfg or DEFAULT_SYNC_CFG
    url = raw_data_url(cfg)

    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = HTML_SHELL.replace("__DATA_URL__", url).replace("__DATA__", payload)

    WEB_DIR.mkdir(exist_ok=True)
    out = WEB_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys

    demo = "--demo" in sys.argv
    print(publish(demo=demo))
