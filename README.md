# NetPilot 📡

**Personal network health monitor for Windows** — born out of two days of fighting
hostel WiFi and mobile hotspot congestion while trying to play Valorant on campus.

It answers two questions:

1. **Is my network good RIGHT NOW?** — live dashboard with a health score, for
   anything you care about: classes, calls, downloads, gaming.
2. **WHEN is each of my networks actually usable?** — a congestion heatmap built
   from 24/7 logs that shows which hours each network (campus WiFi / phone
   hotspot / home WiFi) is healthy or dying.

## Why

Two networks, both flaky, both dying at *different times of day* — and Windows
gives you zero visibility into which one to be on. Speedtests are useless here:
they measure Mbps, but for calls and games what matters is **latency, jitter and
packet loss**. NetPilot measures exactly those, and separately for:

- **Local link** (laptop ↔ router/gateway) — catches WiFi distance/interference issues
- **Internet path** (router ↔ the world) — catches ISP/campus congestion

so it can tell you *which side* is the problem.

## Install

Python 3.10+ on Windows. Everything needed is stdlib + `rich`.

```bash
pip install rich            # required
pip install plyer           # optional: Windows toast notifications
pip install pandas matplotlib   # only needed for --report
```

## Usage

```bash
python netpilot.py                # live dashboard (Ctrl+C to stop)
python netpilot.py --once         # one-shot check; exit code 0 GO / 1 WARN / 2 DEAD
python netpilot.py --report       # congestion heatmap + best/worst hours per network
python netpilot.py --report --days 14
python netpilot.py --auto "MyHotspot"   # auto-switch to a saved Wi-Fi when DEAD 30s+
```

**The routine:** run the monitor (or `--once`) whenever you're about to do
something that matters. Trust the verdict, not the speedtest.

## Reading the dashboard

```
 Network   Campus-5G (5 GHz, 100% signal)
 Gateway   10.12.144.1 — no reply (ICMP blocked, link assumed fine)
 Internet  48 ms avg | 12 ms jitter | p95 61 ms | 6% loss
 Score     21/100 — DEAD
 Verdict   Internet path is congested (ISP/campus). Switch network or wait.
```

- **GO 🟢 (≥75)** — queue up, you're fine.
- **WARN 🟡 (40–74)** — usable, but unstable; expect occasional stutters.
- **DEAD 🔴 (<40)** — switch networks or wait. (Score anchors: 48 ms / 0% loss ≈ 93 → GO;
  6% loss ≈ WARN/DEAD; 217 ms with wild jitter ≈ DEAD.)

Some APs ignore ping to the gateway (common on campus networks) — NetPilot
detects this and doesn't count it against you.

## The heatmap

`python netpilot.py --report` renders `reports/netpilot_report.png`: rows are
your networks, columns are hours of the day, colored by median latency and mean
loss — plus a plain-English schedule like:

```
Campus-5G  — healthy hours: 09:00-18:00   dead hours: 19:00-23:00
Phone      — healthy hours: 07:00-09:00, 00:00-02:00   dead hours: 20:00-23:00
```

Leave the monitor running overnight (plugged in) to map your networks properly.

## Config

`config.json` — probe targets, interval, score weights and thresholds,
auto-switch cooldown. All tweakable without touching code.

## Notes & limits

- Windows-only for now (ping/netsh/route parsing).
- No admin rights needed. Everything runs locally; logs stay in `logs/`.
- Auto-switch connects to a **saved** Wi-Fi profile only, and only if the
  network is currently visible; it backs off for 5 minutes after each attempt.

## Roadmap ideas

- Throughput sanity test (small download), not just latency
- Auto toggle VPN (WireGuard/WARP) on network change
- Web dashboard + phone notification
