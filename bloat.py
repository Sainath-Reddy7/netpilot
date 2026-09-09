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


@dataclass
class BloatSnapshot:
    baseline_ms: float | None = None
    loaded_ms: float | None = None
    delta_ms: float | None = None
    throughput_mbps: float | None = None
    grade: str = "n/a"
    note: str = ""
    up_baseline_ms: float | None = None
    up_loaded_ms: float | None = None
    up_delta_ms: float | None = None
    up_grade: str = "n/a"
    up_mbps: float | None = None

    @property
    def tested(self) -> bool:
        return self.delta_ms is not None or self.up_delta_ms is not None

    @property
    def worst_delta_ms(self) -> float | None:
        deltas = [d for d in (self.delta_ms, self.up_delta_ms) if d is not None]
        return max(deltas) if deltas else None

    def score(self) -> float:
        """Convert worst-direction bloat delta to a 0-100 score."""
        delta = self.worst_delta_ms
        if delta is None:
            return 100.0  # untested shouldn't penalize light-mode cycles
        if delta <= 5:
            return 100.0
        if delta <= 150:
            # linear 100 -> 40 between 5 and 150 ms of added latency
            return round(100 - (delta - 5) * (60 / 145), 1)
        return max(10.0, round(40 - (delta - 150) * 0.15, 1))


def _grade_delta(delta_ms: float) -> str:
    if delta_ms <= 5:
        return "A+"
    if delta_ms <= 30:
        return "A"
    if delta_ms <= 60:
        return "B"
    if delta_ms <= 150:
        return "C"
    return "F"


_HEADERS = {
    # Cloudflare 403s bare Python requests; a normal-looking
    # Accept header + UA gets through fine.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetPilot/2.0",
    "Accept": "*/*",
}


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
            req = urllib.request.Request(self.url, headers=dict(_HEADERS))
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


class _Uploader(threading.Thread):
    """POSTs chunks to an endpoint (e.g. speed.cloudflare.com/__up) until stopped."""

    def __init__(self, url: str, chunk_bytes: int = 1_000_000, max_chunks: int = 8):
        super().__init__(daemon=True)
        self.url = url
        self.chunk_bytes = chunk_bytes
        self.max_chunks = max_chunks
        self.bytes_sent = 0
        self.elapsed = 0.0
        self.error: str | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        start = time.perf_counter()
        payload = b"n" * self.chunk_bytes
        try:
            while not self._stop.is_set() and (self.bytes_sent // self.chunk_bytes) < self.max_chunks:
                req = urllib.request.Request(
                    self.url, data=payload, method="POST", headers=dict(_HEADERS)
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
                self.bytes_sent += self.chunk_bytes
        except Exception as exc:
            self.error = str(exc)[:120]
        finally:
            self.elapsed = time.perf_counter() - start


def _ping_during_load(target: str, load_pings: int, deadline_s: float = 25) -> list[float]:
    """Ping while a load thread runs; returns the collected latency samples."""
    times: list[float] = []
    deadline = time.perf_counter() + deadline_s
    while len(times) < load_pings and time.perf_counter() < deadline:
        r = ping(target, 1, 1500)
        times += r.times_ms  # timeouts simply contribute no sample
        time.sleep(0.3)
    return times


def measure_bloat(
    url: str,
    target: str,
    load_pings: int,
    min_download_mb: int,
    up_url: str = "https://speed.cloudflare.com/__up",
) -> BloatSnapshot:
    snap = BloatSnapshot()

    # --- shared baseline ---
    base_times: list[float] = []
    for _ in range(3):
        r = ping(target, 1, 1000)
        base_times += r.times_ms
        if not r.received:
            snap.note = f"No baseline connectivity to {target} — bloat test skipped."
            return snap
    snap.baseline_ms = sum(base_times) / len(base_times)
    snap.up_baseline_ms = snap.baseline_ms

    # --- download direction ---
    dl = _Downloader(url, min_download_mb * 1_000_000)
    dl.start()
    dl_times = _ping_during_load(target, load_pings, deadline_s=25)
    dl.stop()
    dl.join(timeout=5)

    if not (dl.error and dl.bytes_read == 0):
        if dl.bytes_read >= dl.min_bytes and dl.elapsed > 0:
            snap.throughput_mbps = (dl.bytes_read * 8 / 1_000_000) / dl.elapsed
        if dl_times:
            snap.loaded_ms = sum(dl_times) / len(dl_times)
            snap.delta_ms = max(0.0, snap.loaded_ms - snap.baseline_ms)
            snap.grade = _grade_delta(snap.delta_ms)

    # --- upload direction (video calls suffer here) ---
    up = _Uploader(up_url)
    up.start()
    up_times = _ping_during_load(target, load_pings, deadline_s=30)
    up.stop()
    up.join(timeout=5)

    if not (up.error and up.bytes_sent == 0):
        if up.bytes_sent > 0 and up.elapsed > 0:
            snap.up_mbps = (up.bytes_sent * 8 / 1_000_000) / up.elapsed
        if up_times:
            snap.up_loaded_ms = sum(up_times) / len(up_times)
            snap.up_delta_ms = max(0.0, snap.up_loaded_ms - snap.up_baseline_ms)
            snap.up_grade = _grade_delta(snap.up_delta_ms)

    # --- verdict note ---
    worst = snap.worst_delta_ms
    if worst is not None and worst > 60:
        direction = "downloads" if snap.delta_ms == worst else "uploads"
        snap.note = (
            f"+{worst:.0f} ms of added latency during {direction} — transfers "
            "will lag everything on this network (bufferbloat)."
        )
    elif snap.tested:
        snap.note = "Latency stays healthy under load (both directions)."
    elif dl.error and dl.bytes_read == 0:
        snap.note = f"Download test blocked/failed ({dl.error})."
    return snap
