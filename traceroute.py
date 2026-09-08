"""Traceroute analysis: WHERE along the path does the pain start?

Runs `tracert -d` and grades each hop, so we can say things like
"loss begins at hop 3 (100.64.x.x — carrier CGNAT)" instead of just
"internet is bad".

Note: intermediate hops that rate-limit ICMP (showing * * *) while later
hops answer are NOT real loss — we only flag a hop when it and everything
behind it go dark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from prober import _run

IPV4ISH = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _parse_hop_line(line: str) -> Hop | None:
    """Parse lines like:

        1     1 ms     1 ms    <1 ms  10.201.48.156
        2   248 ms     *      301 ms  100.64.0.100
    """
    tokens = line.split()
    if len(tokens) < 5 or not tokens[0].isdigit():
        return None
    ip = tokens[-1]
    if not IPV4ISH.match(ip):
        return None
    ttl = int(tokens[0])
    middle = " ".join(tokens[1:-1])
    times = [float(t.lstrip("<")) for t in re.findall(r"<\d+|\d+", middle)]
    return Hop(ttl=ttl, ip=ip, times_ms=times)


@dataclass
class Hop:
    ttl: int
    ip: str
    times_ms: list[float] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return bool(self.times_ms)

    @property
    def avg_ms(self) -> float | None:
        return sum(self.times_ms) / len(self.times_ms) if self.times_ms else None


@dataclass
class PathSnapshot:
    hops: list[Hop] = field(default_factory=list)
    first_dark_hop: int | None = None   # first hop where the path goes silent
    worst_latency_hop: Hop | None = None
    note: str = ""

    @property
    def reachable(self) -> bool:
        return bool(self.hops) and self.hops[-1].answered

    def summary(self) -> str:
        if not self.hops:
            return "Traceroute unavailable."
        if self.first_dark_hop:
            hop = self.hops[self.first_dark_hop - 1] if self.first_dark_hop <= len(self.hops) else None
            ip = hop.ip if hop else "?"
            return f"Path goes dark at hop {self.first_dark_hop} ({ip}) — trouble starts there or before."
        if self.worst_latency_hop:
            return (
                f"Path complete ({len(self.hops)} hops). Biggest jump: "
                f"hop {self.worst_latency_hop.ttl} ({self.worst_latency_hop.ip}, "
                f"{self.worst_latency_hop.avg_ms:.0f} ms)."
            )
        return f"Path complete ({len(self.hops)} hops), no anomalies."


def measure_path(target: str, max_hops: int = 15, timeout_ms: int = 800) -> PathSnapshot:
    # tracert with -w <ms> per hop; -d skips DNS (faster, IPs only).
    output = _run(
        ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout_ms), target],
        timeout=max_hops * (timeout_ms / 1000.0) * 3 + 15,
    )

    snap = PathSnapshot()
    prev_avg: float | None = None
    biggest_jump: tuple[float, Hop] | None = None

    for line in output.splitlines():
        hop = _parse_hop_line(line)
        if hop is None:
            continue
        snap.hops.append(hop)

        if prev_avg is not None and hop.answered:
            jump = hop.avg_ms - prev_avg
            if biggest_jump is None or jump > biggest_jump[0]:
                biggest_jump = (jump, hop)
        if hop.answered:
            prev_avg = hop.avg_ms

    # First hop after which NOTHING answers (real blackout, not rate-limiting).
    last_answered = max((h.ttl for h in snap.hops if h.answered), default=0)
    tail_dark = [h for h in snap.hops if h.ttl > last_answered]
    if last_answered and tail_dark:
        snap.first_dark_hop = tail_dark[0].ttl

    if biggest_jump and biggest_jump[0] > 80:
        snap.worst_latency_hop = biggest_jump[1]

    if not snap.hops:
        snap.note = "Traceroute produced no parsable hops."
    return snap
