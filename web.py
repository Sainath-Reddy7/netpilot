"""Web publishing: live-updating shareable dashboard (UI v5 — editorial premium).

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
<meta name="theme-color" content="#141519">
<meta name="description" content="Live network health — latency, loss and congestion, measured locally and published continuously.">
<meta property="og:title" content="NetPilot — live network health">
<meta property="og:description" content="Latency, packet loss and hour-by-hour congestion, measured on the machine itself.">
<meta property="og:type" content="website">
<title>NetPilot — live network health</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📡</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #141519; --panel: #191B20; --panel2: #1E2026;
    --line: #262931; --line2: #333742;
    --ink: #E8EAEE; --dim: #9094A0; --faint: #5E6270;
    --ok: #45D483; --warn: #FFB224; --bad: #FF5D5D;
    --mono: 'IBM Plex Mono', ui-monospace, monospace;
    --sans: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { scrollbar-color: var(--line2) var(--bg); }
  body { background: var(--bg); color: var(--ink); font-family: var(--sans);
         font-size: 14.5px; line-height: 1.55; padding-bottom: 4rem; }
  .wrap { max-width: 1060px; margin: 0 auto; padding: 0 1.25rem; }

  /* ---- header ---- */
  header { border-bottom: 1px solid var(--line); }
  .hbar { display: flex; align-items: baseline; justify-content: space-between;
          gap: 1rem; flex-wrap: wrap; padding: 1.1rem 0 .9rem; }
  .brand { display: flex; align-items: baseline; gap: .6rem; }
  .brand .name { font-family: var(--mono); font-weight: 600; font-size: 1.05rem; letter-spacing: .01em; }
  .brand .tag { color: var(--dim); font-size: .85rem; }
  .hstatus { display: flex; align-items: baseline; gap: .9rem; font-family: var(--mono); font-size: .78rem; color: var(--dim); }
  .live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
              background: var(--ok); margin-right: .45rem; vertical-align: 1px; }
  .live-dot.cached { background: var(--warn); }
  .live-dot.pulse { animation: dot 2.2s ease-in-out infinite; }
  @keyframes dot { 50% { opacity: .35; } }

  /* ---- the scope (hero) ---- */
  .scope { position: relative; margin-top: 1.4rem; border: 1px solid var(--line);
           background: var(--panel); overflow: hidden; }
  .graticule { position: absolute; inset: 0;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size: 100% 25%, 8.3333% 100%;
    opacity: .38; pointer-events: none; }
  .sweep { position: absolute; top: 0; bottom: 0; width: 90px; pointer-events: none;
    background: linear-gradient(90deg, transparent, rgba(232,234,238,.05), transparent);
    animation: sweep 7s linear infinite; }
  @keyframes sweep { from { left: -12%; } to { left: 104%; } }
  .scope-inner { position: relative; padding: 1.6rem 1.8rem 1.4rem; }
  .readout-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  .verdict-word { font-family: var(--mono); font-weight: 600; font-size: clamp(2.6rem, 6vw, 4rem);
                  line-height: 1; letter-spacing: .02em; }
  .score-block { text-align: right; font-family: var(--mono); }
  .score-block .n { font-size: 2rem; font-weight: 500; line-height: 1; }
  .score-block .g { color: var(--dim); font-size: .78rem; margin-top: .3rem; }
  .trace-wrap { margin: 1.2rem 0 .9rem; }
  .trace-wrap svg { width: 100%; height: 120px; display: block; }
  .trace { animation: draw 1.6s .15s ease-out forwards; }
  @keyframes draw { to { stroke-dashoffset: 0; } }
  .subject { font-size: .95rem; }
  .subject .dim { color: var(--dim); }
  .scope-note { margin-top: .35rem; font-size: .84rem; color: var(--warn); max-width: 62ch; }
  .readouts { display: flex; flex-wrap: wrap; gap: .4rem 2.2rem; margin-top: 1rem;
              padding-top: .95rem; border-top: 1px solid var(--line); }
  .ro .k { font-size: .78rem; color: var(--dim); }
  .ro .v { font-family: var(--mono); font-size: 1.22rem; font-weight: 500; margin-top: .1rem;
           font-variant-numeric: tabular-nums; }
  .ro .v small { font-size: .72rem; color: var(--faint); font-weight: 400; }
  .standby { padding: 3rem 1.8rem; font-family: var(--mono); color: var(--dim); position: relative; }

  /* ---- summary readouts ---- */
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
             border: 1px solid var(--line); border-top: 0; background: var(--panel2); }
  .summary > div { padding: .95rem 1.3rem; border-right: 1px solid var(--line); }
  .summary > div:last-child { border-right: 0; }
  .summary .k { font-size: .78rem; color: var(--dim); }
  .summary .v { font-family: var(--mono); font-size: 1.45rem; font-weight: 500; margin-top: .15rem;
                font-variant-numeric: tabular-nums; }
  .summary .d { font-size: .74rem; color: var(--faint); }

  /* ---- sections ---- */
  .sec-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem;
              flex-wrap: wrap; padding: 2.2rem 0 .9rem; }
  .sec-head h2 { font-size: 1.05rem; font-weight: 600; }
  .sec-head .right { font-family: var(--mono); font-size: .95rem; color: var(--dim); font-variant-numeric: tabular-nums; }
  .sec-sub { color: var(--faint); font-size: .8rem; margin: -.4rem 0 .9rem; }

  /* spectrogram */
  .spec-scroll { overflow-x: auto; }
  .spec { display: grid; grid-template-columns: repeat(24, 40px); gap: 2px; min-width: 1010px; }
  .spec .h { font-family: var(--mono); font-size: .64rem; color: var(--dim); text-align: center; padding-top: 3px; }
  .cell { height: 40px; background: var(--panel2); position: relative; cursor: default; }
  .cell.nodata { opacity: .55;
    background-image: repeating-linear-gradient(45deg, transparent 0 4px, var(--line) 4px 5px); }
  .cell.now { outline: 1.5px solid var(--ink); outline-offset: -1.5px; }
  .cell:hover { outline: 1.5px solid var(--ink); outline-offset: -1.5px; }
  .cell[data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: 118%;
    left: 50%; transform: translateX(-50%); background: #0B0C0F; color: var(--ink);
    border: 1px solid var(--line2); padding: .4rem .65rem; font-family: var(--mono);
    font-size: .68rem; white-space: nowrap; z-index: 9; }
  .spec-legend { display: flex; align-items: center; gap: .5rem; margin-top: .6rem;
                 font-size: .72rem; color: var(--faint); }
  .spec-legend .bar { height: 6px; width: 130px;
    background: linear-gradient(90deg, #45D483, #A3D04C, #FFB224, #FF5D5D); }

  .hours-line { margin-top: .7rem; font-size: .8rem; color: var(--dim);
                font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .hours-line b.good { color: var(--ok); font-weight: 500; }
  .hours-line b.bad { color: var(--bad); font-weight: 500; }

  /* curves */
  .curve { margin: 1rem 0 .2rem; }
  .curve svg { width: 100%; height: 110px; display: block; }
  .curve-empty { color: var(--faint); font-family: var(--mono); font-size: .75rem;
                 padding: 1.4rem 0 1rem; text-align: center; }

  /* incident log */
  .log { border: 1px solid var(--line); background: var(--panel); }
  .log-row { display: flex; gap: 1.1rem; padding: .7rem 1.2rem; border-bottom: 1px solid var(--line);
             font-size: .86rem; align-items: baseline; }
  .log-row:last-child { border-bottom: 0; }
  .log-when { font-family: var(--mono); font-size: .75rem; color: var(--faint); min-width: 92px; }
  .log-type { font-family: var(--mono); font-size: .75rem; font-weight: 600; min-width: 120px; }
  .log-what { color: var(--dim); flex: 1; }
  .log-empty { padding: 1.2rem; color: var(--faint); font-size: .85rem; }

  footer { margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid var(--line);
           font-size: .78rem; color: var(--faint); display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  footer a { color: var(--dim); }

  @media (max-width: 640px) {
    .scope-inner { padding: 1.2rem 1rem; }
    .readouts { gap: .35rem 1.4rem; }
    .summary > div { border-right: 0; border-bottom: 1px solid var(--line); }
    .summary > div:last-child { border-bottom: 0; }
    .log-row { flex-wrap: wrap; gap: .3rem 1rem; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sweep, .live-dot.pulse, .trace { animation: none !important; }
    .trace { stroke-dashoffset: 0 !important; }
  }
  .shot .sweep, .shot .live-dot.pulse, .shot .trace { animation: none !important; }
  .shot .trace { stroke-dashoffset: 0 !important; }
</style>
</head>
<body>
<div class="wrap">
  <header><div class="hbar">
    <div class="brand"><span class="name">NetPilot</span><span class="tag">live network health</span></div>
    <div class="hstatus">
      <span id="meta"></span>
      <span><span class="live-dot pulse" id="dot"></span><span id="badge">live</span></span>
    </div>
  </div></header>

  <div class="scope" id="scope"></div>
  <div class="summary" id="cards"></div>

  <div id="nets"></div>

  <div class="sec-head"><h2>Incident log</h2></div>
  <div class="log" id="incidents"></div>

  <footer>
    <span>Measured locally on the collector machine. No trackers.</span>
    <span>Updates every 60 s · <a href="https://github.com/Sainath-Reddy7/netpilot">source</a></span>
  </footer>
</div>

<script>
if (new URLSearchParams(location.search).get('shot') === '1')
  document.documentElement.classList.add('shot');
const DATA_URL = "__DATA_URL__";
const EMBEDDED = __DATA__;
let DATA = EMBEDDED;

const VC = { GO: 'var(--ok)', WARN: 'var(--warn)', DEAD: 'var(--bad)' };
const TCOL = { OUTAGE: 'var(--bad)', WIFI_DOWN: 'var(--bad)', DNS_FAIL: 'var(--warn)',
               AP_ROAM: 'var(--dim)', NETWORK_CHANGE: 'var(--dim)', WIFI_UP: 'var(--ok)' };
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gradeOf = sc => sc >= 90 ? 'A' : sc >= 75 ? 'B' : sc >= 60 ? 'C' : sc >= 40 ? 'D' : 'F';
const fmtInt = x => Number(x).toLocaleString();
function latColor(ms) {
  if (ms === null || ms === undefined) return null;
  if (ms < 50) return '#2FAE6B'; if (ms < 80) return '#7FB93E';
  if (ms < 120) return '#D99A1F'; if (ms < 200) return '#E4653C';
  return '#D94A4A';
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
function ro(k, v) { return `<div class="ro"><div class="k">${k}</div><div class="v">${v}</div></div>`; }

/* scope trace: smoothed median-latency curve on the graticule */
function traceSvg(hourly, verdict, id) {
  const W = 1000, H = 120, padB = 16, padT = 14;
  const pts = hourly.map((x, h) => ({ h, v: x.lat })).filter(p => p.v != null);
  const vc = VC[verdict] || 'var(--dim)';
  if (pts.length < 3) return '';
  const max = Math.max(...pts.map(p => p.v)) * 1.08 || 1;
  const min = Math.min(...pts.map(p => p.v)) * 0.92;
  const X = h => 8 + (h / 23) * (W - 16);
  const Y = v => H - padB - ((v - min) / (max - min || 1)) * (H - padB - padT);
  const segs = []; let seg = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].h === pts[i-1].h + 1) seg.push(pts[i]); else { segs.push(seg); seg = [pts[i]]; }
  }
  segs.push(seg);
  const path = ps => {
    let d = `M ${X(ps[0].h).toFixed(1)} ${Y(ps[0].v).toFixed(1)}`;
    for (let i = 0; i < ps.length - 1; i++) {
      const p0 = ps[Math.max(0,i-1)], p1 = ps[i], p2 = ps[i+1], p3 = ps[Math.min(ps.length-1,i+2)];
      d += ` C ${(X(p1.h)+(X(p2.h)-X(p0.h))/6).toFixed(1)} ${(Y(p1.v)+(Y(p2.v)-Y(p0.v))/6).toFixed(1)}, ${(X(p2.h)-(X(p3.h)-X(p1.h))/6).toFixed(1)} ${(Y(p2.v)-(Y(p3.v)-Y(p1.v))/6).toFixed(1)}, ${X(p2.h).toFixed(1)} ${Y(p2.v).toFixed(1)}`;
    }
    return d;
  };
  const lines = segs.filter(s => s.length > 1).map(path).join(' ');
  const peak = pts.reduce((a, p) => p.v > a.v ? p : a, pts[0]);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="latency over 24 hours">
    <path class="trace" d="${lines}" fill="none" stroke="${vc}" stroke-width="2" stroke-linecap="round"
      stroke-dasharray="3000" stroke-dashoffset="3000"
      style="filter: drop-shadow(0 0 5px ${vc})"/>
    <text x="${Math.min(W-150, X(peak.h)+10)}" y="${Math.max(15, Y(peak.v)-8)}" fill="var(--faint)"
      font-size="10" font-family="IBM Plex Mono, monospace">peak ${Math.round(peak.v)} ms at ${String(peak.h).padStart(2,'0')}:00</text>
    <text x="8" y="10" fill="var(--faint)" font-size="9" font-family="IBM Plex Mono, monospace">median latency per hour, last 24 h</text>
  </svg>`;
}

function render() {
  document.getElementById('meta').textContent = 'updated ' + ago(DATA.updated) + (DATA.demo ? ' (demo)' : '');

  const n = DATA.now;
  const scopeEl = document.getElementById('scope');
  const curNet = DATA.networks.length
    ? DATA.networks.reduce((a, x) => ((x.hourly[curHour()] || {}).n || 0) > ((a.hourly[curHour()] || {}).n || 0) ? x : a, DATA.networks[0])
    : null;

  if (n) {
    const vc = VC[n.verdict] || 'var(--dim)';
    const band = n.band ? `<span class="dim">, ${esc(n.band)}</span>` : '';
    const vpn = n.vpn && n.vpn !== 'none' ? `<span class="dim">, VPN ${esc(n.vpn)}</span>` : '';
    const note = n.note ? `<div class="scope-note">${esc(n.note)}</div>` : '';
    let extra = '';
    if (n.bloat) extra += ro('bloat down / up', `${esc(n.bloat.down || '–')} / ${esc(n.bloat.up || '–')}`);
    if (n.mtu) extra += ro('path MTU', esc(n.mtu));
    scopeEl.innerHTML = `
      <div class="graticule"></div><div class="sweep"></div>
      <div class="scope-inner">
        <div class="readout-top">
          <div class="verdict-word" style="color:${vc}">${esc(n.verdict)}</div>
          <div class="score-block"><div class="n" style="color:${vc}">${Math.round(n.score)}</div><div class="g">score, grade ${gradeOf(n.score)}</div></div>
        </div>
        <div class="trace-wrap">${curNet ? traceSvg(curNet.hourly, n.verdict) : ''}</div>
        <div class="subject">${esc(n.ssid || 'unknown network')}${band}${vpn}<span class="dim"> — signal ${n.signal != null ? esc(n.signal) : '–'}%</span></div>
        ${note}
        <div class="readouts">
          ${ro('latency', n.avg_ms != null ? esc(n.avg_ms) + ' <small>ms</small>' : '–')}
          ${ro('loss', n.loss_pct != null ? esc(n.loss_pct) + ' <small>%</small>' : '–')}
          ${ro('jitter', n.jitter_ms != null ? esc(n.jitter_ms) + ' <small>ms</small>' : '–')}
          ${extra}
        </div>
      </div>`;
    document.title = `NetPilot · ${n.verdict} ${Math.round(n.score)}`;
  } else {
    scopeEl.innerHTML = `<div class="graticule"></div><div class="standby">Waiting for the first reading from the collector.</div>`;
    document.title = 'NetPilot';
  }

  const scores = DATA.networks.map(x => x.median_score);
  const avg = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
  const totalSamples = DATA.networks.reduce((a, x) => a + (x.samples || 0), 0);
  document.getElementById('cards').innerHTML = [
    ['networks', DATA.networks.length, 'last 7 days'],
    ['median score', avg, 'all networks'],
    ['availability', DATA.availability != null ? DATA.availability.toFixed(2) + '%' : '–', 'while monitored'],
    ['readings', fmtInt(totalSamples), 'probe cycles'],
  ].map(([k, v, d]) => `<div><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');

  const H = curHour();
  document.getElementById('nets').innerHTML = DATA.networks.map(net => {
    const cells = net.hourly.map((x, h) => {
      const col = latColor(x.lat);
      const tip = col ? `${String(h).padStart(2,'0')}:00 — ${x.lat} ms, ${x.loss}% loss` : `${String(h).padStart(2,'0')}:00 — no data`;
      return `<div class="cell${col ? '' : ' nodata'}${h === H ? ' now' : ''}"${col ? ` style="background:${col}"` : ''} data-tip="${esc(tip)}"></div>`;
    }).join('');
    const good = net.hourly.map((x,h)=>({h,x})).filter(o=>o.x.score != null && o.x.score >= 75).map(o=>o.h);
    const dead = net.hourly.map((x,h)=>({h,x})).filter(o=>o.x.score != null && o.x.score < 40).map(o=>o.h);
    const hrs = a => a.length ? a.map(h => String(h).padStart(2,'0')).join(' ') : 'none';
    return `
      <div class="sec-head"><h2>${esc(net.ssid)}</h2><span class="right">${net.median_score} · ${gradeOf(net.median_score)}</span></div>
      <div class="sec-sub">${fmtInt(net.samples)} readings — hour-by-hour median latency, current hour boxed</div>
      <div class="spec-scroll"><div class="spec">
        ${Array.from({length:24},(_,h)=>`<div class="h">${String(h).padStart(2,'0')}</div>`).join('')}${cells}
      </div></div>
      <div class="spec-legend"><span>faster</span><div class="bar"></div><span>slower</span><span>· hatched means no data</span></div>
      <div class="hours-line">good hours <b class="good">${hrs(good)}</b> &nbsp; bad hours <b class="bad">${hrs(dead)}</b></div>
      <div class="curve">${traceSvg(net.hourly, net.median_score >= 75 ? 'GO' : net.median_score >= 40 ? 'WARN' : 'DEAD')}</div>`;
  }).join('');

  document.getElementById('incidents').innerHTML = DATA.incidents.length
    ? DATA.incidents.map(e => `
      <div class="log-row">
        <span class="log-when">${esc(e.when)}</span>
        <span class="log-type" style="color:${TCOL[e.type] || 'var(--dim)'}">${esc(e.type.replace(/_/g, ' '))}</span>
        <span class="log-what">${esc(e.detail)}</span>
      </div>`).join('')
    : '<div class="log-empty">No incidents on record.</div>';
}

function setBadge(live) {
  document.getElementById('badge').textContent = live ? 'live' : 'cached';
  document.getElementById('dot').className = 'live-dot' + (live ? ' pulse' : ' cached');
}

async function loadLive() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now(), {cache: 'no-store'});
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
    setBadge(true);
  } catch (e) { setBadge(false); }
  render();
}

render();
loadLive();
setInterval(loadLive, 60000);
</script>
</body>
</html>
"""

def _now_from_last_row(anonymize: bool) -> dict | None:
    """Approximate the current state from the most recent logged cycle, so the
    embedded snapshot has a complete hero even before the first live fetch."""
    try:
        import math

        import pandas as pd

        df = pd.read_csv(LOG_FILE)
        row = df.iloc[-1]

        def num(v):
            try:
                f = float(v)
                return None if math.isnan(f) else round(f, 1)
            except Exception:
                return None

        return {
            "ssid": "current network" if anonymize else str(row.get("ssid") or "unknown"),
            "band": None if pd.isna(row.get("band")) else str(row.get("band")),
            "signal": num(row.get("signal_pct")),
            "verdict": str(row.get("verdict") or "GO"),
            "score": num(row.get("overall_score")) or 0,
            "avg_ms": num(row.get("net_avg_ms")),
            "loss_pct": num(row.get("net_loss_pct")),
            "jitter_ms": num(row.get("net_jitter_ms")),
            "vpn": "" if pd.isna(row.get("vpn")) else str(row.get("vpn")),
        }
    except Exception:
        return None


def publish(days: int = 7, demo: bool = False, anon: bool = False, sync_cfg: dict | None = None) -> Path:
    if demo:
        data = generate_demo_data()
    else:
        if not LOG_FILE.exists():
            raise SystemExit(f"No logs at {LOG_FILE} — run the monitor first, or use --demo.")
        data = build_payload(days=days, anonymize=anon, now_state=_now_from_last_row(anon))
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
