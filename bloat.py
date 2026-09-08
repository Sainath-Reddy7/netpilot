"""Bufferbloat + throughput: latency UNDER load.

The classic home/dorm problem: everything is fine until a download starts,
then every ping explodes because the router's buffers fill up. Speedtests
miss this completely — NetPilot measures it directly:

  1. Take a baseline latency reading.
  2. Saturate the downlink with a HTTP download (default ~16 MB).
  3. Ping during the transfer.
  4. Grade = added latency under load (Waveform-style).

Also reports the achieved download throughput from the same transfer.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from dataclasses import dataclass

from prober import ping

BLOAT_GRADES = ["A+", "A", "B", "C", "F"]


@dataclass
class BloatSnapshot:
    baseline_ms: float | None = None
    loaded_ms: float | None = None
    delta_ms: float | None = None
    throughput_mbps: float | None = None
    grade: str = "n/a"
    note: str = ""

    @property
    def tested(self) -> bool:
        return self.delta_ms is not None

    def score(self) -> float:
        """Convert bloat delta to a 0-100 score (also used for the grade)."""
        if not self.tested:
            return 100.0  # untested shouldn't penalize light-mode cycles
        delta = self.delta_ms
        if delta <= 5:
            return 100.0
        if delta <= 150:
            # linear 100 -> 40 between 5 and 150 ms of added latency
            return round(100 - (delta - 5) * (60 / 145), 1)
        return max(10.0, round(40 - (delta - 150) * 0.15, 1))


class _Downloader(threading.Thread):
    def __init__(self, url: str, min_bytes: int):
        super().__init__(daemon=True)
        self.url = url
        self.min_bytes = min_bytes
        self.bytes_read = 0
        self.elapsed = 0.0
        self.error: str | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                self.url,
                headers={
                    # Cloudflare 403s bare Python requests; a normal-looking
                    # Accept header + UA gets through fine.
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetPilot/2.0",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                while not self._stop.is_set():
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    self.bytes_read += len(chunk)
        except Exception as exc:  # network blocks, TLS, timeouts — all fine
            self.error = str(exc)[:120]
        finally:
            self.elapsed = time.perf_counter() - start


def measure_bloat(url: str, target: str, load_pings: int, min_download_mb: int) -> BloatSnapshot:
    snap = BloatSnapshot()

    # 1. Baseline: 3 quick single pings.
    base_times: list[float] = []
    for _ in range(3):
        r = ping(target, 1, 1000)
        base_times += r.times_ms
        if not r.received:
            snap.note = f"No baseline connectivity to {target} — bloat test skipped."
            return snap
    snap.baseline_ms = sum(base_times) / len(base_times)

    # 2. Download while pinging.
    dl = _Downloader(url, min_download_mb * 1_000_000)
    dl.start()
    loaded_times: list[float] = []
    deadline = time.perf_counter() + 25
    while len(loaded_times) < load_pings and time.perf_counter() < deadline:
        if not dl.is_alive() and dl.bytes_read >= dl.min_bytes:
            break
        r = ping(target, 1, 1500)
        loaded_times += r.times_ms  # timeouts simply contribute no sample
        time.sleep(0.3)
    dl.stop()
    dl.join(timeout=5)

    if dl.error and dl.bytes_read == 0:
        snap.note = f"Download test blocked/failed ({dl.error})."
        return snap

    if dl.bytes_read >= dl.min_bytes and dl.elapsed > 0:
        snap.throughput_mbps = (dl.bytes_read * 8 / 1_000_000) / dl.elapsed

    if loaded_times:
        snap.loaded_ms = sum(loaded_times) / len(loaded_times)
        snap.delta_ms = max(0.0, snap.loaded_ms - snap.baseline_ms)

        if snap.delta_ms <= 5:
            snap.grade = "A+"
        elif snap.delta_ms <= 30:
            snap.grade = "A"
        elif snap.delta_ms <= 60:
            snap.grade = "B"
        elif snap.delta_ms <= 150:
            snap.grade = "C"
        else:
            snap.grade = "F"

    if snap.delta_ms and snap.delta_ms > 60:
        snap.note = (
            f"+{snap.delta_ms:.0f} ms of added latency under load — downloads/uploads "
            "will lag everything on this network (bufferbloat)."
        )
    elif snap.tested:
        snap.note = "Latency stays healthy under load."
    return snap
