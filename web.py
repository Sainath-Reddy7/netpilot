"""Web publishing: live-updating shareable dashboard (UI v4 — aurora glass).

Data contract (data.json in the secret gist, pushed by the collector):
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
    --bg: #070a10; --fg: #eef2f8; --muted: #93a0b4; --muted2: #5d6a7e;
    --accent: #58a6ff; --accent2: #a371f7;
    --good: #3fb950; --warn: #e3b341; --bad: #f85149;
    --glass: rgba(18, 24, 34, .58); --stroke: rgba(255,255,255,.07);
    --r: 18px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { scrollbar-color: #2b3444 var(--bg); }
  body {
    background: var(--bg); color: var(--fg); min-height: 100vh;
    font-family: ui-sans-serif, 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif;
    padding: 0 0 3.5rem; overflow-x: hidden;
  }
  /* faint blueprint grid */
  body::before { content: ''; position: fixed; inset: 0; z-index: -2; opacity: .05;
    background-image: linear-gradient(rgba(255,255,255,.5) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(255,255,255,.5) 1px, transparent 1px);
    background-size: 44px 44px; }
  /* aurora blobs */
  .aurora { position: fixed; inset: -25%; z-index: -1; filter: blur(110px); pointer-events: none; }
  .aurora i { position: absolute; border-radius: 50%; opacity: .5; }
  .aurora i:nth-child(1) { width: 44vw; height: 44vw; left: -8%; top: -12%;
    background: radial-gradient(circle, rgba(88,166,255,.32), transparent 65%);
    animation: drift1 22s ease-in-out infinite alternate; }
  .aurora i:nth-child(2) { width: 38vw; height: 38vw; right: -6%; top: 6%;
    background: radial-gradient(circle, rgba(163,113,247,.26), transparent 65%);
    animation: drift2 26s ease-in-out infinite alternate; }
  .aurora i:nth-child(3) { width: 34vw; height: 34vw; left: 26%; bottom: -16%;
    background: radial-gradient(circle, rgba(63,185,80,.16), transparent 65%);
    animation: drift3 30s ease-in-out infinite alternate; }
  @keyframes drift1 { to { transform: translate(7vw, 5vh) scale(1.18); } }
  @keyframes drift2 { to { transform: translate(-6vw, 7vh) scale(1.12); } }
  @keyframes drift3 { to { transform: translate(5vw, -6vh) scale(1.2); } }

  .wrap { max-width: 1120px; margin: 0 auto; padding: 0 1rem; }

  /* ---------- header ---------- */
  header { position: sticky; top: 0; z-index: 60; backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px); background: rgba(7,10,16,.72);
    border-bottom: 1px solid var(--stroke); }
  .hbar { max-width: 1120px; margin: 0 auto; padding: .85rem 1rem;
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: .65rem; text-decoration: none; }
  .brand .icon { font-size: 1.45rem; filter: drop-shadow(0 0 10px rgba(88,166,255,.5)); }
  .brand .t { font-size: 1.06rem; font-weight: 800; letter-spacing: .2px; }
  .brand .t .grad { background: linear-gradient(92deg, #58a6ff 10%, #a371f7 90%);
    -webkit-background-clip: text; background-clip: text; color: transparent; }
  .brand .sub { color: var(--muted2); font-size: .72rem; margin-top: .05rem; }
  .hright { display: flex; align-items: center; gap: .7rem; }
  .when { color: var(--muted); font-size: .8rem; font-variant-numeric: tabular-nums; }
  .badge { display: inline-flex; align-items: center; gap: .4rem; font-size: .68rem;
    font-weight: 800; letter-spacing: 1.6px; padding: .32rem .75rem; border-radius: 999px; }
  .badge.live { color: #49d97a; background: rgba(63,185,80,.1); border: 1px solid rgba(63,185,80,.35);
    box-shadow: 0 0 18px rgba(63,185,80,.15); }
  .badge.cached { color: var(--warn); background: rgba(227,179,65,.1); border: 1px solid rgba(227,179,65,.35); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: currentColor;
    animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; box-shadow: 0 0 0 0 rgba(73,217,122,.5); }
                     50% { opacity: .5; box-shadow: 0 0 0 7px rgba(73,217,122,0); } }

  main { padding-top: 1.6rem; }
  .reveal { animation: rise .7s cubic-bezier(.2,.7,.3,1) both; }
  @keyframes rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }

  /* ---------- glass ---------- */
  .glass { background: var(--glass); border: 1px solid var(--stroke); border-radius: var(--r);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    box-shadow: 0 14px 44px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.045); }

  /* ---------- hero ---------- */
  .hero { display: flex; align-items: center; gap: 2.4rem; flex-wrap: wrap;
    padding: 1.9rem 2.1rem; margin-bottom: 1.1rem; position: relative; overflow: hidden; }
  .hero::after { content: ''; position: absolute; inset: 0 0 auto 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--vc, var(--accent)), transparent); opacity: .6; }
  .gauge { position: relative; width: 158px; height: 158px; flex-shrink: 0; }
  .gauge svg { transform: rotate(-90deg); display: block; }
  .gauge .track { fill: none; stroke: rgba(255,255,255,.07); stroke-width: 11; }
  .gauge .bar { fill: none; stroke-width: 11; stroke-linecap: round;
    transition: stroke-dashoffset 1.4s cubic-bezier(.25,.8,.3,1);
    filter: drop-shadow(0 0 9px var(--vc, var(--accent))); }
  .gauge .mid { position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; }
  .gauge .num { font-size: 2.5rem; font-weight: 800; letter-spacing: -1px;
    font-variant-numeric: tabular-nums; line-height: 1; }
  .gauge .lbl { font-size: .6rem; color: var(--muted2); text-transform: uppercase;
    letter-spacing: 2.2px; margin-top: .3rem; }
  .hero-info { flex: 1 1 240px; min-width: 230px; }
  .hero-info .net { font-size: 1.42rem; font-weight: 800; letter-spacing: -.2px; }
  .vchip { display: inline-block; margin: .55rem 0 .4rem; padding: .22rem 1rem; border-radius: 999px;
    font-weight: 800; font-size: .95rem; letter-spacing: 3px; }
  .vchip.GO { color: #49d97a; border: 1.5px solid rgba(63,185,80,.6); background: rgba(63,185,80,.1);
    box-shadow: 0 0 22px rgba(63,185,80,.18); }
  .vchip.WARN { color: #f0c24b; border: 1.5px solid rgba(227,179,65,.6); background: rgba(227,179,65,.1);
    box-shadow: 0 0 22px rgba(227,179,65,.15); }
  .vchip.DEAD { color: #ff6b63; border: 1.5px solid rgba(248,81,73,.65); background: rgba(248,81,73,.1);
    box-shadow: 0 0 26px rgba(248,81,73,.2); }
  .hero-info .sub { color: var(--muted); font-size: .84rem; line-height: 1.55; }
  .hero-info .note { color: var(--warn); font-size: .8rem; margin-top: .5rem; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
    gap: 1rem 1.5rem; flex: 1.3 1 300px; }
  .stat { padding: .8rem 1rem; border-radius: 14px; background: rgba(255,255,255,.028);
    border: 1px solid rgba(255,255,255,.05); }
  .stat .k { color: var(--muted2); font-size: .62rem; text-transform: uppercase; letter-spacing: 1.4px; }
  .stat .v { font-size: 1.32rem; font-weight: 800; margin-top: .28rem;
    font-variant-numeric: tabular-nums; }

  /* ---------- cards ---------- */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem; margin-bottom: 1.1rem; }
  .card { padding: 1.15rem 1.3rem; transition: transform .2s, border-color .2s, box-shadow .2s; }
  .card:hover { transform: translateY(-3px); border-color: rgba(88,166,255,.28);
    box-shadow: 0 18px 50px rgba(0,0,0,.5), 0 0 24px rgba(88,166,255,.07); }
  .card .k { color: var(--muted2); font-size: .66rem; text-transform: uppercase; letter-spacing: 1.3px; }
  .card .v { font-size: 1.7rem; font-weight: 800; margin-top: .4rem; font-variant-numeric: tabular-nums; }
  .card .v small { font-size: .85rem; color: var(--muted); font-weight: 600; }
  .card .d { color: var(--muted2); font-size: .74rem; margin-top: .25rem; }

  /* ---------- network sections ---------- */
  section.net { padding: 1.5rem 1.6rem 1.4rem; margin-bottom: 1.1rem; }
  .net-head { display: flex; align-items: baseline; justify-content: space-between;
    gap: 1rem; flex-wrap: wrap; margin-bottom: .35rem; }
  .net-head h2 { font-size: 1.06rem; font-weight: 800; letter-spacing: .1px; }
  .net-head .pill { font-size: 1rem; font-weight: 800; font-variant-numeric: tabular-nums; }
  .net .sub { color: var(--muted2); font-size: .78rem; margin-bottom: 1.1rem; }
  .gA { color: #49d97a; } .gB { color: #3fd0d9; } .gC { color: #f0c24b; }
  .gD { color: #ff8a4d; } .gF { color: #ff6b63; }

  .chart-wrap { margin-bottom: 1.15rem; }
  .chart-wrap svg { width: 100%; height: 132px; display: block; }
  .chart-empty { color: var(--muted2); font-size: .78rem; padding: 1.4rem 0 1rem; text-align: center; }

  .heat-scroll { overflow-x: auto; padding-bottom: .35rem; }
  .heat { display: grid; grid-template-columns: repeat(24, 36px); gap: 3px; min-width: 950px; }
  .heat .h { font-size: .58rem; color: var(--muted2); text-align: center; padding-top: 2px; }
  .cell { height: 36px; border-radius: 7px; position: relative; cursor: default;
    border: 1px solid rgba(255,255,255,.028); transition: transform .12s; }
  .cell:hover { transform: scale(1.16); z-index: 4; }
  .cell.nodata { background: #141924; background-image: repeating-linear-gradient(45deg,
    transparent 0 5px, rgba(255,255,255,.022) 5px 7px); }
  .cell.now { outline: 2px solid rgba(238,242,248,.6); outline-offset: 1.5px; }
  .cell[data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: 118%;
    left: 50%; transform: translateX(-50%); background: #05070b; color: var(--fg);
    border: 1px solid rgba(255,255,255,.14); padding: .45rem .7rem; border-radius: 9px;
    font-size: .72rem; white-space: nowrap; z-index: 9; box-shadow: 0 10px 26px rgba(0,0,0,.6); }
  .legend { display: flex; align-items: center; gap: .55rem; margin-top: .75rem;
    font-size: .68rem; color: var(--muted2); flex-wrap: wrap; }
  .gradbar { height: 8px; border-radius: 4px; width: 150px;
    background: linear-gradient(90deg, #2ea043, #9ac51e, #d29922, #db6d28, #f85149); }
  .chips { margin-top: .75rem; font-size: .76rem; line-height: 2.2; }
  .chip { display: inline-block; padding: .14rem .65rem; border-radius: 999px; margin-right: .4rem;
    font-variant-numeric: tabular-nums; }
  .chip.good { color: #49d97a; background: rgba(63,185,80,.09); border: 1px solid rgba(63,185,80,.25); }
  .chip.bad { color: #ff6b63; background: rgba(248,81,73,.09); border: 1px solid rgba(248,81,73,.25); }

  /* ---------- incidents ---------- */
  .tl-item { display: flex; gap: 1.05rem; padding: .75rem 0; border-left: 2px solid rgba(255,255,255,.07);
    margin-left: .5rem; padding-left: 1.25rem; position: relative; }
  .tl-item::before { content: ''; position: absolute; left: -6.5px; top: 1.2rem; width: 11px; height: 11px;
    border-radius: 50%; background: var(--tc); box-shadow: 0 0 0 3.5px var(--bg), 0 0 12px var(--tc); }
  .tl-when { color: var(--muted2); font-size: .74rem; min-width: 96px; padding-top: .2rem;
    font-variant-numeric: tabular-nums; }
  .tl-type { font-size: .72rem; font-weight: 800; letter-spacing: 1.2px; color: var(--tc); }
  .tl-detail { font-size: .86rem; margin-top: .18rem; opacity: .9; }
  .tl-empty { color: var(--muted2); padding: 1rem 0 .6rem 1.8rem; font-size: .88rem; }

  footer { color: var(--muted2); font-size: .74rem; margin-top: 2.6rem; text-align: center; line-height: 1.9; }
  footer a { color: var(--accent); text-decoration: none; }

  @media (max-width: 680px) {
    .hero { gap: 1.3rem; padding: 1.4rem; }
    .stats { flex-basis: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    .aurora i, .pulse, .reveal { animation: none; }
  }
</style>
</head>
<body>
<div class="aurora"><i></i><i></i><i></i></div>

<header><div class="hbar">
  <a class="brand" href="#">
    <div class="icon">📡</div>
    <div>
      <div class="t"><span class="grad">NetPilot</span>&nbsp;· Live Network Health</div>
      <div class="sub">measured locally · updated by the collector</div>
    </div>
  </a>
  <div class="hright">
    <span class="when" id="meta"></span>
    <span class="badge live" id="badge"><span class="pulse"></span>LIVE</span>
  </div>
</div></header>

<main class="wrap">
  <div class="hero glass reveal" id="hero"></div>
  <div class="cards reveal" id="cards" style="animation-delay:.08s"></div>
  <div id="nets"></div>

  <section class="net glass reveal">
    <div class="net-head"><h2>Recent incidents</h2></div>
    <div class="sub">outages · drops · roaming · DNS failures — only real state changes are logged</div>
    <div class="timeline" id="incidents"></div>
  </section>

  <footer>
    collected by <a href="https://github.com/Sainath-Reddy7/netpilot">NetPilot</a> — local, private, no trackers<br>
    auto-refresh 60 s · source: <span id="src"></span>
  </footer>
</main>

<script>
const DATA_URL = "__DATA_URL__";
const EMBEDDED = __DATA__;
let DATA = EMBEDDED;

const VC = { GO: '#3fb950', WARN: '#e3b341', DEAD: '#f85149' };
const VC2 = { GO: '#3fd0d9', WARN: '#ff8a4d', DEAD: '#ff8a9b' };
const TC = { OUTAGE: '#f85149', WIFI_DOWN: '#f85149', DNS_FAIL: '#e3b341',
             AP_ROAM: '#58a6ff', NETWORK_CHANGE: '#58a6ff', WIFI_UP: '#3fb950' };

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gradeOf = sc => sc >= 90 ? 'A' : sc >= 75 ? 'B' : sc >= 60 ? 'C' : sc >= 40 ? 'D' : 'F';
const gcls = sc => 'g' + gradeOf(sc);
const fmtInt = x => Number(x).toLocaleString();

function latColor(ms) {
  if (ms === null || ms === undefined) return null;
  if (ms < 50) return '#2ea043'; if (ms < 80) return '#9ac51e';
  if (ms < 120) return '#d29922'; if (ms < 200) return '#db6d28';
  return '#f85149';
}
function ago(iso) {
  try {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return Math.round(s) + 's ago';
    if (s < 5400) return Math.round(s/60) + ' min ago';
    return Math.round(s/3600) + ' h ago';
  } catch (e) { return '?'; }
}
const curHour = () => new Date().getHours();

function countUp(el, target, suffix = '', dur = 950) {
  const t0 = performance.now();
  const step = t => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(target * e) + suffix;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function stat(k, v) { return `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`; }

/* smooth 24h latency curve (Catmull-Rom -> bezier) */
function areaChart(hourly, id) {
  const W = 860, H = 132, padL = 10, padR = 10, padT = 14, padB = 22;
  const pts = hourly.map((x, h) => ({ h, v: x.lat })).filter(p => p.v !== null && p.v !== undefined);
  if (pts.length < 3) return '<div class="chart-empty">curve appears as data accumulates…</div>';
  const max = Math.max(...pts.map(p => p.v)) * 1.08 || 1;
  const min = Math.min(...pts.map(p => p.v)) * 0.92;
  const X = h => padL + (h / 23) * (W - padL - padR);
  const Y = v => H - padB - ((v - min) / (max - min || 1)) * (H - padT - padB);

  // split into contiguous segments (hours without data break the line)
  const segs = [];
  let seg = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].h === pts[i - 1].h + 1) seg.push(pts[i]);
    else { segs.push(seg); seg = [pts[i]]; }
  }
  segs.push(seg);

  const path = ps => {
    let d = `M ${X(ps[0].h).toFixed(1)} ${Y(ps[0].v).toFixed(1)}`;
    for (let i = 0; i < ps.length - 1; i++) {
      const p0 = ps[Math.max(0, i - 1)], p1 = ps[i], p2 = ps[i + 1], p3 = ps[Math.min(ps.length - 1, i + 2)];
      const c1x = X(p1.h) + (X(p2.h) - X(p0.h)) / 6, c1y = Y(p1.v) + (Y(p2.v) - Y(p0.v)) / 6;
      const c2x = X(p2.h) - (X(p3.h) - X(p1.h)) / 6, c2y = Y(p2.v) - (Y(p3.v) - Y(p1.v)) / 6;
      d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${X(p2.h).toFixed(1)} ${Y(p2.v).toFixed(1)}`;
    }
    return d;
  };
  const lines = segs.filter(s => s.length > 1).map(path).join(' ');
  const main = segs.reduce((a, s) => s.length > a.length ? s : a, []);
  const area = path(main) +
    ` L ${X(main[main.length - 1].h).toFixed(1)} ${H - padB} L ${X(main[0].h).toFixed(1)} ${H - padB} Z`;
  const grid = [0.25, 0.5, 0.75].map(k => {
    const y = padT + k * (H - padT - padB);
    return `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,.05)" stroke-dasharray="3 6"/>`;
  }).join('');
  const labels = [0, 6, 12, 18, 23].map(h =>
    `<text x="${X(h)}" y="${H - 6}" fill="#5d6a7e" font-size="9" text-anchor="${h === 0 ? 'start' : h === 23 ? 'end' : 'middle'}">${String(h).padStart(2,'0')}</text>`).join('');
  const peak = pts.reduce((a, p) => p.v > a.v ? p : a, pts[0]);
  const dot = `<circle cx="${X(peak.h)}" cy="${Y(peak.v)}" r="4" fill="#f85149" opacity=".9"/>
    <text x="${Math.min(W - 90, X(peak.h) + 8)}" y="${Math.max(12, Y(peak.v) - 7)}" fill="#8b95a5" font-size="9">peak ${Math.round(peak.v)} ms @ ${String(peak.h).padStart(2,'0')}:00</text>`;

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="24 hour latency curve">
    <defs><linearGradient id="ag${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#58a6ff" stop-opacity=".33"/>
      <stop offset="1" stop-color="#58a6ff" stop-opacity="0"/></linearGradient></defs>
    ${grid}${labels}
    <path d="${area}" fill="url(#ag${id})"/>
    <path d="${lines}" fill="none" stroke="#58a6ff" stroke-width="2.6" stroke-linecap="round" style="filter:drop-shadow(0 0 6px rgba(88,166,255,.45))"/>
    ${dot}
  </svg>`;
}

function gaugeSvg(score, verdict) {
  const C = 2 * Math.PI * 62;
  const off = C * (1 - Math.max(0, Math.min(100, score)) / 100);
  const c1 = VC[verdict] || '#58a6ff', c2 = VC2[verdict] || '#a371f7';
  return `<div class="gauge" style="--vc:${c1}">
    <svg width="158" height="158" viewBox="0 0 158 158">
      <defs><linearGradient id="ringg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient></defs>
      <circle class="track" cx="79" cy="79" r="62"></circle>
      <circle class="bar" cx="79" cy="79" r="62" stroke="url(#ringg)"
              stroke-dasharray="${C}" stroke-dashoffset="${C}" data-off="${off}"></circle>
    </svg>
    <div class="mid"><div class="num" id="scoreNum">0</div><div class="lbl">score</div></div>
  </div>`;
}

function render() {
  document.getElementById('meta').textContent =
    'updated ' + ago(DATA.updated) + (DATA.demo ? ' · DEMO' : '');

  const n = DATA.now;
  const heroEl = document.getElementById('hero');
  if (n) {
    const vc = VC[n.verdict] || '#58a6ff';
    const band = n.band ? ' · ' + esc(n.band) : '';
    const sig = n.signal ? ' · ' + esc(n.signal) + '% signal' : '';
    const vpn = n.vpn && n.vpn !== 'none' ? ' · VPN: ' + esc(n.vpn) : '';
    const note = n.note ? `<div class="note">⚠ ${esc(n.note)}</div>` : '';
    let extra = '';
    if (n.bloat) extra += stat('bloat ↓ / ↑', `${esc(n.bloat.down || '–')}<br>${esc(n.bloat.up || '–')}`);
    if (n.mtu) extra += stat('path MTU', esc(n.mtu));
    heroEl.style.setProperty('--vc', vc);
    heroEl.innerHTML = `
      ${gaugeSvg(n.score, n.verdict)}
      <div class="hero-info">
        <div class="net">${esc(n.ssid || 'unknown')}${band}${sig}${vpn}</div>
        <div class="vchip ${esc(n.verdict)}">${esc(n.verdict)}</div>
        <div class="sub">grade ${gradeOf(n.score)} · measured continuously from the collector machine</div>
        ${note}
      </div>
      <div class="stats">
        ${stat('latency', n.avg_ms != null ? esc(n.avg_ms) + ' ms' : '–')}
        ${stat('loss', n.loss_pct != null ? esc(n.loss_pct) + '%' : '–')}
        ${stat('jitter', n.jitter_ms != null ? esc(n.jitter_ms) + ' ms' : '–')}
        ${extra}
      </div>`;
    countUp(heroEl.querySelector('#scoreNum'), n.score);
    requestAnimationFrame(() => {
      const bar = heroEl.querySelector('.bar');
      if (bar) setTimeout(() => { bar.style.strokeDashoffset = bar.dataset.off; }, 80);
    });
  }

  const scores = DATA.networks.map(x => x.median_score);
  const avg = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
  const totalSamples = DATA.networks.reduce((a, x) => a + (x.samples || 0), 0);
  document.getElementById('cards').innerHTML = [
    ['Networks monitored', DATA.networks.length, 'last 7 days'],
    ['Median score', avg, 'across all networks'],
    ['Availability', DATA.availability != null ? DATA.availability.toFixed(2) : '–', '% uptime while monitored'],
    ['Measurements', fmtInt(totalSamples), 'probe cycles logged'],
  ].map(([k, v, d]) => `<div class="card glass"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');

  const H = curHour();
  document.getElementById('nets').innerHTML = DATA.networks.map((net, i) => {
    const g = gradeOf(net.median_score);
    const heat = net.hourly.map((x, h) => {
      const col = latColor(x.lat);
      const cls = col ? '' : ' nodata';
      const tip = col ? `${String(h).padStart(2,'0')}:00 — ${x.lat} ms · ${x.loss}% loss · score ${x.score}` : `${String(h).padStart(2,'0')}:00 — no data yet`;
      return `<div class="cell${cls}${h === H ? ' now' : ''}"${col ? ` style="background:${col}"` : ''} data-tip="${esc(tip)}"></div>`;
    }).join('');
    const good = net.hourly.map((x, h) => ({h, x})).filter(o => o.x.score != null && o.x.score >= 75).map(o => o.h);
    const dead = net.hourly.map((x, h) => ({h, x})).filter(o => o.x.score != null && o.x.score < 40).map(o => o.h);
    const fmt = hs => hs.length ? hs.map(h => String(h).padStart(2,'0')).join(', ') : 'none';
    return `<section class="net glass reveal" style="animation-delay:${.12 + i * .07}s">
      <div class="net-head">
        <h2>${esc(net.ssid)}</h2>
        <span class="pill ${gcls(net.median_score)}">${net.median_score} · ${g}</span>
      </div>
      <div class="sub">${fmtInt(net.samples)} samples · 24 h latency curve · per-hour heatmap (current hour outlined)</div>
      <div class="chart-wrap">${areaChart(net.hourly, i)}</div>
      <div class="heat-scroll"><div class="heat">
        ${Array.from({length: 24}, (_, h) => `<div class="h">${String(h).padStart(2,'0')}</div>`).join('')}${heat}
      </div></div>
      <div class="legend"><span>fast</span><div class="gradbar"></div><span>slow / lossy</span>
        <span style="opacity:.7">▨&nbsp;= no data yet</span></div>
      <div class="chips">
        <span class="chip good">healthy: ${fmt(good)}</span>
        <span class="chip bad">dead: ${fmt(dead)}</span>
      </div>
    </section>`;
  }).join('');

  document.getElementById('incidents').innerHTML = DATA.incidents.length
    ? DATA.incidents.map(e => `
      <div class="tl-item" style="--tc: ${TC[e.type] || '#93a0b4'}">
        <div class="tl-when">${esc(e.when)}</div>
        <div>
          <div class="tl-type">${esc(e.type.replace(/_/g, ' '))}</div>
          <div class="tl-detail">${esc(e.detail)}</div>
        </div>
      </div>`).join('')
    : '<div class="tl-empty">No incidents logged — that\'s a good thing.</div>';
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
