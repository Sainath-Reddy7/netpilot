# NetPilot 📡

[![CI](https://github.com/Sainath-Reddy7/netpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Sainath-Reddy7/netpilot/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-36%20passing-brightgreen)](#tests)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-windows-blueviolet)](https://github.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A comprehensive network health monitor for Windows** — built after two days of
fighting hostel Wi-Fi and mobile hotspot congestion. NetPilot measures everything
that actually makes a network *feel* bad, tells you exactly **which layer is the
problem**, learns **when your networks are usable** over time, and can publish a
**shareable web dashboard** of it all.

> Speedtests measure Mbps. NetPilot measures what hurts: latency, jitter, packet
> loss, bufferbloat (both directions), DNS behavior, radio congestion — layer by layer.

**Jump to:** [Screenshots](#screenshots) · [Features](#what-it-measures-and-why) · [Install](#install) · [Usage](#usage) · [Web dashboard & Vercel](#web-dashboard--vercel-deployment) · [Scoring](#scoring) · [Tests](#tests) · [Architecture](#project-layout)

## Screenshots

**Live dashboard** (`python netpilot.py`):

![live dashboard](docs/screenshots/dashboard.svg)

**Full diagnostics** (`python netpilot.py --full` — traceroute, bidirectional
bufferbloat, throughput, path MTU, channel scan, VPN detection):

![full report](docs/screenshots/full-report.svg)

**Web dashboard** (`python netpilot.py --publish` → deploy anywhere, e.g. Vercel):
dark-themed, self-contained HTML with per-network hour-of-day heatmaps,
healthy/dead hour chips, incident timeline and availability — zero external
requests, zero tracking.

## What it measures (and why)

| Domain | What | Why it matters |
|---|---|---|
| **Local link** | latency/loss to your gateway | isolates "laptop ↔ router" problems (distance, interference, adapter sleep) |
| **Internet path** | latency, jitter, p95, loss to multiple targets | the core "is my network usable" signal |
| **Route** | hop-by-hop traceroute analysis | pinpoints *where* on the path the pain starts (e.g. carrier CGNAT) |
| **Bufferbloat ↓↑** | latency under download **and upload** load | "everything lags when someone downloads" — and uploads wreck video calls |
| **Throughput ↓↑** | download & upload Mbps | measured during the bloat tests, free of charge |
| **DNS** | resolver identification, lookup latency, **hijack detection** | campus/captive portals intercepting DNS cause mystery redirects and stalls |
| **Radio environment** | channel scan of all nearby APs, co-channel congestion, 5 GHz availability | "your channel has 11 strong neighbours" and "your SSID also has a 5 GHz twin — switch" |
| **Path MTU** | DF-ping binary search | detects silent large-packet blackholes (common with VPNs/firewalls) |
| **VPN awareness** | detects WARP / WireGuard / Tailscale / OpenVPN | measurements are interpreted differently when tunneled |
| **Events** | disconnects, AP roaming, outages, DNS failures | a timeline of *incidents*, with availability % and week-over-week trends |

**Alerts** when things go wrong: desktop toast (optional) **+ Discord webhook**
(set `alerts.webhook_url` in the config) + console. Optional auto-switching to a
backup Wi-Fi when the network is DEAD.

Everything runs with **no admin rights** and only uses built-in Windows tools
(`ping`, `netsh`, `route`, `tracert`) — nothing sketchy, nothing phoning home.

## Install

Python 3.10+ on Windows.

```bash
pip install -r requirements.txt   # rich, pandas, matplotlib
pip install plyer pytest          # optional: toast notifications / dev tests
```

## Usage

```bash
python netpilot.py                    # live dashboard (Ctrl+C to stop)
python netpilot.py --once             # quick check → exit code 0 GO / 1 WARN / 2 DEAD
python netpilot.py --full             # deep diagnostics (~2 min: traceroute, bidirectional
                                      #   bloat, throughput, path MTU, channel scan, VPN)
python netpilot.py --report           # heatmap + schedules + incidents + trends + HTML
python netpilot.py --report --days 14
python netpilot.py --publish          # web dashboard -> web/index.html (real data)
python netpilot.py --publish --demo   # web dashboard with synthetic demo data
python netpilot.py --publish --anon   # real data, network names pseudonymized
python netpilot.py --auto "MyHotspot" # auto-switch to a saved Wi-Fi after 30s of DEAD
python netpilot.py --deep-interval 15 # live mode: deep diagnostics every 15 min
```

**The routine:** run `--full` once per network to meet it, keep the live monitor
running when you care, check `--report` after a few days, and `--publish` when
you want receipts.

## Web dashboard & Vercel deployment

The web dashboard is a **single self-contained HTML file** — inline CSS/JS,
no CDNs, no trackers, works offline. Hosting it on Vercel takes ~2 minutes:

1. `python netpilot.py --publish` (or `--demo` / `--anon`) — generates `web/index.html`
2. Commit & push to GitHub (this repo)
3. Go to [vercel.com](https://vercel.com) → **Add New → Project** → import this repo
4. Framework preset: **Other** — `vercel.json` already points Vercel at `web/`
5. Deploy. Done — every push redeploys automatically.

**Privacy:** logs stay in `logs/` (git-ignored) and never leave your machine.
Only what you explicitly `--publish` goes to the web. Use `--demo` for a public
showcase, `--anon` to hide network names, or publish real data only to private
deployments.

## Scoring

Each domain gets a 0–100 score and a letter grade (A ≥90, B ≥75, C ≥60, D ≥40, else F).
The overall score is a weighted roll-up (path 45%, link 25%, DNS 15%, radio 15%,
+20% bufferbloat when tested); untested domains are dropped and weights
renormalized, so a light cycle still scores fairly.

| Verdict | Meaning | Real-world anchor |
|---|---|---|
| **GO** (≥75) | do your thing | 48 ms / 0% loss ≈ 93 |
| **WARN** (40–74) | usable, expect stutters | ~6% loss |
| **DEAD** (<40) | switch networks or wait | 217 ms avg, wild jitter |

Loss is punished deliberately hard: for real-time anything (games, calls), a few
percent of lost packets matters more than raw latency.

Some campus APs ignore pings to the gateway — NetPilot detects this and refuses
to blame your local link for it.

## Reports

`python netpilot.py --report` produces:

- `reports/netpilot_report.png` — hour-of-day congestion heatmap per network
- `reports/netpilot_report.html` — standalone shareable report: embedded heatmap,
  per-network healthy/dead hour schedules, recent incidents, week-over-week
  trends, availability %
- console summary, e.g.

```
Campus-5G (3810 samples) — overall 71/100
  healthy hours: 09:00-18:00
  dead hours:    19:00-23:00
Phone    (922 samples)  — overall 88/100
  healthy hours: 07:00-09:00, 23:00-07:00
  dead hours:    20:00-22:00

Week-over-week trend
  Campus-5G: week 1 74 → last week 68 [↓ -6]
  Phone:     week 1 85 → last week 87 [↑ +2]

Availability (uptime while monitored): 96.42%
```

## Tests

```bash
python -m pytest tests/ -q      # 36 tests
```

The suite unit-tests the parsers (ping / netsh / route / tracert output against
real captured samples), the scoring math (anchored to real-world measurements),
traceroute hop parsing, diagnosis logic and report helpers. CI runs the full
suite on every push — on a Windows runner, because that's the platform.

## Project layout

```
netpilot.py     CLI + monitoring engine (light cycles, deep cycles, alerts, auto-switch)
prober.py       subprocess wrappers + PURE parsers (unit-testable)
health.py       rolling stats, per-domain scores, grades, roll-up, diagnosis
dashboard.py    the rich layout (live dashboard + full report rendering)
wifi_env.py     channel congestion analysis from BSSID scans
dnscheck.py     resolver detection, lookup latency, NXDOMAIN hijack test
bloat.py        bidirectional bufferbloat + throughput
traceroute.py   hop-by-hop path analysis, loss localization
mtu.py          path MTU / blackhole detection via DF pings
vpndetect.py    WARP/WireGuard/Tailscale/OpenVPN detection
events.py       incident detection (outages, roaming, DNS fails) + timeline
logger.py       CSV logging (schema v2, auto-migrates v1 files)
report.py       heatmap, schedules, incidents, trends, availability, HTML export
notify.py       Discord webhook + toast + console alerts
web.py          --publish: self-contained shareable web dashboard
scripts/        maintenance (README screenshot generation)
tests/          pytest suite (real captured tool output)
web/            published dashboard (what Vercel serves)
```

## Notes & limits

- Windows-only for now (the probe layer parses `ping`/`netsh`/`route`/`tracert` output).
- Deep diagnostics transfer ~10 MB down + ~8 MB up — skip on metered connections
  or tune `bloat` in the config.
- Logs and reports stay in `logs/` and `reports/` — they contain your SSIDs, and
  both folders are git-ignored by default.
- Auto-switch connects only to **saved** Wi-Fi profiles, only if visible, and backs
  off for 5 minutes after each attempt.

## Roadmap

- System-tray mode (pystray) · Linux/macOS support (probe abstraction)
- Week-over-week network quality charts in the web dashboard
- Auto toggle VPN (WireGuard/WARP) on verdict changes

## License

[MIT](LICENSE) © 2026 Sainath Reddy

---

Born from a real situation: campus Wi-Fi that needs a VPN, a WireGuard box on AWS
Mumbai, a phone hotspot that dies at 8 pm, and way too many teleports in Valorant.
