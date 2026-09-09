"""Web publishing: live-updating shareable dashboard (UI v3).

Data contract (web/data.json, pushed by the collector):
  updated, demo, now{ssid,band,signal,verdict,score,avg_ms,loss_pct,
  jitter_ms,vpn,bloat,mtu,note}, networks[{ssid,samples,median_score,
  hourly[24]{lat,loss,score,n}}], incidents[{when,type,detail}], availability

`python netpilot.py --publish [--anon|--demo]` -> web/index.html
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
    "gist_id": "9242530888d662dcc51bc4cb5f89b6e7",
    "gist_owner": "Sainath-Reddy7",
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
        {"when": "06 Sep 19:47", "type": "WIFI_DOWN", "detail": "WiFi dropped."},
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


HTML_SHELL = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetPilot — Live Network Health</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📡</text></svg>">
<style>
  :root {
    --bg: #0a0e14; --panel: #11151d; --panel2: #161b26; --border: #232a37;
    --fg: #e8edf4; --muted: #8b95a5; --accent: #58a6ff; --accent2: #bc8cff;
    --good: #3fb950; --warn: #e3b341; --bad: #f85149;
    --radius: 14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { scrollbar-color: #2a3342 var(--bg); }
  body {
    background: var(--bg); color: var(--fg);
    font-family: ui-sans-serif, 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh; padding: 1.5rem 1rem 3rem;
    background-image:
      radial-gradient(1200px 500px at 70% -10%, rgba(88,166,255,.07), transparent 60%),
      radial-gradient(900px 400px at 10% 0%, rgba(188,140,255,.05), transparent 55%);
  }
  .wrap { max-width: 1100px; margin: 0 auto; }

  /* ---------- header ---------- */
  header { display: flex; align-items: center; justify-content: space-between;
           flex-wrap: wrap; gap: .8rem; margin-bottom: 1.4rem; }
  .brand { display: flex; align-items: center; gap: .7rem; }
  .brand .icon { font-size: 1.7rem; }
  .brand h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: .2px; }
  .brand h1 .grad {
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .brand .sub { color: var(--muted); font-size: .8rem; margin-top: .1rem; }
  .hright { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
  .badge { display: inline-flex; align-items: center; gap: .35rem; font-size: .72rem;
           font-weight: 700; letter-spacing: 1.2px; padding: .3rem .7rem;
           border-radius: 999px; border: 1px solid transparent; }
  .badge.live { color: var(--good); border-color: rgba(63,185,80,.35); background: rgba(63,185,80,.08); }
  .badge.cached { color: var(--warn); border-color: rgba(227,179,65,.35); background: rgba(227,179,65,.08); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: currentColor;
           animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% {opacity:1; box-shadow: 0 0 0 0 rgba(63,185,80,.4)}
                     50% {opacity:.55; box-shadow: 0 0 0 6px rgba(63,185,80,0)} }
  .when { color: var(--muted); font-size: .82rem; }

  /* ---------- hero ---------- */
  .hero { background: linear-gradient(180deg, var(--panel2), var(--panel));
          border: 1px solid var(--border); border-radius: var(--radius);
          padding: 1.6rem 1.8rem; margin-bottom: 1.2rem;
          display: flex; align-items: center; gap: 2.2rem; flex-wrap: wrap;
          box-shadow: 0 10px 40px rgba(0,0,0,.35); position: relative; overflow: hidden; }
  .hero::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 4px;
                  background: var(--vc, var(--accent)); }
  .gauge { position: relative; width: 132px; height: 132px; flex-shrink: 0; }
  .gauge svg { transform: rotate(-90deg); }
  .gauge .track { fill: none; stroke: #232a37; stroke-width: 10; }
  .gauge .bar { fill: none; stroke: var(--vc, var(--accent)); stroke-width: 10;
                stroke-linecap: round; transition: stroke-dashoffset 1.2s cubic-bezier(.2,.7,.3,1), stroke .4s;
                filter: drop-shadow(0 0 6px var(--vc, var(--accent))); }
  .gauge .mid { position: absolute; inset: 0; display: flex; flex-direction: column;
                align-items: center; justify-content: center; }
  .gauge .num { font-size: 1.9rem; font-weight: 800; letter-spacing: -.5px; }
  .gauge .lbl { font-size: .62rem; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; }
  .hero-info { flex: 1; min-width: 230px; }
  .hero-info .net { font-size: 1.3rem; font-weight: 700; }
  .hero-info .verdict-chip { display: inline-block; margin: .45rem 0 .3rem; padding: .18rem .8rem;
    border-radius: 999px; font-weight: 800; font-size: .95rem; letter-spacing: 2px;
    color: var(--vc); border: 1px solid var(--vc); background: color-mix(in srgb, var(--vc) 12%, transparent); }
  .hero-info .sub { color: var(--muted); font-size: .85rem; line-height: 1.5; }
  .hero-info .note { color: var(--warn); font-size: .82rem; margin-top: .4rem; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
           gap: .9rem 1.4rem; flex: 2; min-width: 280px; }
  .stat .k { color: var(--muted); font-size: .68rem; text-transform: uppercase; letter-spacing: 1px; }
  .stat .v { font-size: 1.25rem; font-weight: 700; margin-top: .15rem; font-variant-numeric: tabular-nums; }

  /* ---------- cards ---------- */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
           gap: 1rem; margin-bottom: 1.2rem; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
          padding: 1.1rem 1.2rem; transition: transform .18s, border-color .18s; }
  .card:hover { transform: translateY(-2px); border-color: #2f3949; }
  .card .k { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: 1px; }
  .card .v { font-size: 1.5rem; font-weight: 800; margin-top: .35rem; font-variant-numeric: tabular-nums; }
  .card .d { color: var(--muted); font-size: .78rem; margin-top: .15rem; }

  /* ---------- network sections ---------- */
  section.net { background: var(--panel); border: 1px solid var(--border);
                border-radius: var(--radius); padding: 1.4rem 1.5rem; margin-bottom: 1.2rem; }
  .net-head { display: flex; align-items: baseline; justify-content: space-between;
              gap: 1rem; flex-wrap: wrap; margin-bottom: .3rem; }
  .net-head h2 { font-size: 1.02rem; font-weight: 700; }
  .net-head .pill { font-size: .95rem; font-weight: 800; }
  .net .sub { color: var(--muted); font-size: .82rem; margin-bottom: 1rem; }
  .heat-scroll { overflow-x: auto; padding-bottom: .3rem; }
  .heat { display: grid; grid-template-columns: repeat(24, 34px); gap: 3px; min-width: 900px; }
  .heat .h { font-size: .58rem; color: var(--muted); text-align: center; padding-top: 2px; }
  .cell { height: 34px; border-radius: 6px; background: #1a2029; position: relative; cursor: default;
          border: 1px solid rgba(255,255,255,.02); }
  .cell.now { outline: 2px solid rgba(232,237,244,.55); outline-offset: 1px; }
  .cell[data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: 115%;
    left: 50%; transform: translateX(-50%); background: #000; color: var(--fg);
    border: 1px solid var(--border); padding: .4rem .65rem; border-radius: 7px;
    font-size: .72rem; white-space: nowrap; z-index: 9; box-shadow: 0 6px 18px rgba(0,0,0,.5); }
  .legend { display: flex; align-items: center; gap: .5rem; margin-top: .7rem;
            font-size: .7rem; color: var(--muted); }
  .gradbar { height: 8px; border-radius: 4px; width: 140px;
             background: linear-gradient(90deg, #2ea043, #9ac51e, #d29922, #db6d28, #f85149); }
  .chips { margin-top: .8rem; font-size: .78rem; line-height: 2.1; }
  .chip { display: inline-block; padding: .12rem .6rem; border-radius: 999px; margin-right: .35rem; }
  .chip.good { color: var(--good); background: rgba(63,185,80,.1); border: 1px solid rgba(63,185,80,.25); }
  .chip.bad { color: var(--bad); background: rgba(248,81,73,.1); border: 1px solid rgba(248,81,73,.25); }

  /* ---------- incident timeline ---------- */
  .timeline { position: relative; margin-top: .6rem; }
  .tl-item { display: flex; gap: 1rem; padding: .65rem 0; border-left: 2px solid var(--border);
             margin-left: .45rem; padding-left: 1.2rem; position: relative; }
  .tl-item::before { content: ''; position: absolute; left: -6px; top: 1.05rem; width: 10px; height: 10px;
             border-radius: 50%; background: var(--tc, var(--muted));
             box-shadow: 0 0 0 3px var(--bg), 0 0 8px var(--tc, transparent); }
  .tl-when { color: var(--muted); font-size: .78rem; min-width: 96px; padding-top: .12rem; }
  .tl-body .tl-type { font-size: .78rem; font-weight: 800; letter-spacing: .8px; color: var(--tc, var(--fg)); }
  .tl-body .tl-detail { font-size: .86rem; color: var(--fg); margin-top: .15rem; opacity: .92; }
  .tl-empty { color: var(--muted); padding: .8rem 0 .4rem 1.7rem; font-size: .88rem; }

  footer { color: var(--muted); font-size: .78rem; margin-top: 2.4rem; text-align: center; line-height: 1.8; }
  footer a { color: var(--accent); text-decoration: none; }
  .grade-A { color: var(--good); } .grade-B { color: #39c5cf; }
  .grade-C { color: var(--warn); } .grade-D { color: #db6d28; } .grade-F { color: var(--bad); }

  @media (max-width: 640px) {
    .hero { gap: 1.2rem; padding: 1.3rem; }
    .stats { min-width: 100%; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="icon">📡</div>
      <div>
        <h1><span class="grad">NetPilot</span> · Live Network Health</h1>
        <div class="sub">measured locally, updated by the collector</div>
      </div>
    </div>
    <div class="hright">
      <span class="when" id="meta"></span>
      <span class="badge live" id="badge"><span class="pulse"></span>LIVE</span>
    </div>
  </header>

  <div class="hero" id="hero"></div>
  <div class="cards" id="cards"></div>
  <div id="nets"></div>

  <section class="net">
    <div class="net-head"><h2>Recent incidents</h2></div>
    <div class="sub">outages · drops · roaming · DNS failures — only real state changes are logged</div>
    <div class="timeline" id="incidents"></div>
  </section>

  <footer>
    collected by <a href="https://github.com/Sainath-Reddy7/netpilot">NetPilot</a> — runs locally, no trackers ·
    auto-refresh 60 s · source: <span id="src"></span>
  </footer>
</div>

<script>
const DATA_URL = "__DATA_URL__";
const EMBEDDED = __DATA__;
let DATA = EMBEDDED;
const VC = { GO: '#3fb950', WARN: '#e3b341', DEAD: '#f85149' };
const TC = { OUTAGE: '#f85149', WIFI_DOWN: '#f85149', DNS_FAIL: '#e3b341',
             AP_ROAM: '#58a6ff', NETWORK_CHANGE: '#58a6ff', WIFI_UP: '#3fb950' };

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gradeOf = sc => sc >= 90 ? 'A' : sc >= 75 ? 'B' : sc >= 60 ? 'C' : sc >= 40 ? 'D' : 'F';
function latColor(ms) {
  if (ms === null || ms === undefined) return '#1a2029';
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
const curHour = () => new Date().getHours();

function gaugeSvg(score) {
  const C = 2 * Math.PI * 52;
  const off = C * (1 - Math.max(0, Math.min(100, score)) / 100);
  return `<div class="gauge" style="--vc: var(--vc, #58a6ff)">
    <svg width="132" height="132" viewBox="0 0 132 132">
      <circle class="track" cx="66" cy="66" r="52"></circle>
      <circle class="bar" cx="66" cy="66" r="52" stroke-dasharray="${C}"
              stroke-dashoffset="${C}" data-off="${off}"></circle>
    </svg>
    <div class="mid"><div class="num">${Math.round(score)}</div><div class="lbl">score</div></div>
  </div>`;
}

function render() {
  document.getElementById('meta').textContent =
    'updated ' + ago(DATA.updated) + (DATA.demo ? ' · DEMO DATA' : '');

  const n = DATA.now;
  const heroEl = document.getElementById('hero');
  if (n) {
    const vc = VC[n.verdict] || '#58a6ff';
    const band = n.band ? ' · ' + esc(n.band) : '';
    const sig = n.signal ? ' · ' + esc(n.signal) + '% signal' : '';
    const vpn = n.vpn && n.vpn !== 'none' ? ' · VPN: ' + esc(n.vpn) : '';
    const note = n.note ? `<div class="note">⚠ ${esc(n.note)}</div>` : '';
    let extra = '';
    if (n.bloat) extra += stat('bloat ↓ / ↑', `${esc(n.bloat.down || '–')} · ${esc(n.bloat.up || '–')}`);
    if (n.mtu) extra += stat('path MTU', esc(n.mtu));
    heroEl.style.setProperty('--vc', vc);
    heroEl.innerHTML = `
      ${gaugeSvg(n.score)}
      <div class="hero-info">
        <div class="net">${esc(n.ssid || 'unknown')}${band}${sig}${vpn}</div>
        <div class="verdict-chip">${esc(n.verdict)}</div>
        <div class="sub">grade ${gradeOf(n.score)} · measured continuously from the collector machine</div>
        ${note}
      </div>
      <div class="stats">
        ${stat('latency', n.avg_ms !== null && n.avg_ms !== undefined ? esc(n.avg_ms) + ' ms' : '–')}
        ${stat('loss', n.loss_pct !== null && n.loss_pct !== undefined ? esc(n.loss_pct) + '%' : '–')}
        ${stat('jitter', n.jitter_ms !== null && n.jitter_ms !== undefined ? esc(n.jitter_ms) + ' ms' : '–')}
        ${extra}
      </div>`;
    // animate the gauge ring after insertion
    requestAnimationFrame(() => {
      const bar = heroEl.querySelector('.bar');
      if (bar) setTimeout(() => { bar.style.strokeDashoffset = bar.dataset.off; }, 60);
    });
  }

  const scores = DATA.networks.map(x => x.median_score);
  const avg = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : 0;
  const totalSamples = DATA.networks.reduce((a,x)=>a+(x.samples||0),0);
  document.getElementById('cards').innerHTML = [
    ['Networks monitored', DATA.networks.length, 'in the last 7 days'],
    ['Median score', avg + '<span style="font-size:.9rem;color:var(--muted)">/100</span>', 'all networks'],
    ['Availability', DATA.availability != null ? DATA.availability.toFixed(2) + '%' : 'n/a', 'while monitored'],
    ['Measurements', totalSamples.toLocaleString(), 'probe cycles logged'],
  ].map(([k,v,d]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');

  const H = curHour();
  document.getElementById('nets').innerHTML = DATA.networks.map(net => {
    const grade = gradeOf(net.median_score);
    const heat = net.hourly.map((x, h) => {
      const tip = x.lat == null ? 'no data' :
        `${String(h).padStart(2,'0')}:00 — ${x.lat} ms · ${x.loss}% loss · score ${x.score}`;
      return `<div class="cell${h === H ? ' now' : ''}" style="background:${latColor(x.lat)}" data-tip="${esc(tip)}"></div>`;
    }).join('');
    const good = net.hourly.map((x,h)=>({h,x})).filter(o=>o.x.score != null && o.x.score >= 75).map(o=>o.h);
    const dead = net.hourly.map((x,h)=>({h,x})).filter(o=>o.x.score != null && o.x.score < 40).map(o=>o.h);
    const fmt = hs => hs.length ? hs.map(h=>String(h).padStart(2,'0')).join(', ') : 'none';
    return `<section class="net">
      <div class="net-head">
        <h2>${esc(net.ssid)}</h2>
        <span class="pill grade-${grade}">${net.median_score} · ${grade}</span>
      </div>
      <div class="sub">${net.samples.toLocaleString()} samples · per-hour median latency · current hour outlined</div>
      <div class="heat-scroll"><div class="heat">
        ${Array.from({length:24},(_,h)=>`<div class="h">${String(h).padStart(2,'0')}</div>`).join('')}${heat}
      </div></div>
      <div class="legend"><span>fast</span><div class="gradbar"></div><span>slow / lossy</span></div>
      <div class="chips">
        <span class="chip good">healthy: ${fmt(good)}</span>
        <span class="chip bad">dead: ${fmt(dead)}</span>
      </div>
    </section>`;
  }).join('');

  const incEl = document.getElementById('incidents');
  incEl.innerHTML = DATA.incidents.length
    ? DATA.incidents.map(e => `
      <div class="tl-item" style="--tc: ${TC[e.type] || '#8b95a5'}">
        <div class="tl-when">${esc(e.when)}</div>
        <div class="tl-body">
          <div class="tl-type">${esc(e.type.replace('_', ' '))}</div>
          <div class="tl-detail">${esc(e.detail)}</div>
        </div>
      </div>`).join('')
    : '<div class="tl-empty">No incidents logged — that\'s a good thing.</div>';
}

function stat(k, v) { return `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`; }

function setBadge(live) {
  const b = document.getElementById('badge');
  b.className = 'badge ' + (live ? 'live' : 'cached');
  b.innerHTML = live ? '<span class="pulse"></span>LIVE' : 'CACHED SNAPSHOT';
}

async function loadLive() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now(), {cache: 'no-store'});
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
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
