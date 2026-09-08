"""DNS health: which resolver am I using, how fast is it, is it lying to me?

Campus/captive networks love to hijack DNS. We detect it by resolving a name
that is GUARANTEED to not exist (RFC 2606 `.invalid` TLD) — if we get an
answer, something is intercepting queries (portal / hijack).
"""

from __future__ import annotations

import random
import re
import socket
import time
from dataclasses import dataclass, field

from prober import _run


@dataclass
class DnsSnapshot:
    resolvers: list[str] = field(default_factory=list)
    resolve_times_ms: dict[str, float | None] = field(default_factory=dict)
    avg_ms: float | None = None
    failures: int = 0
    hijacked: bool = False
    hijack_note: str = ""

    @property
    def ok(self) -> bool:
        return self.failures == 0 and not self.hijacked

    def score(self, slow_ms: float = 100) -> float:
        s = 100.0
        s -= self.failures * 25
        if self.hijacked:
            s -= 40
        if self.avg_ms is not None:
            s -= max(0.0, self.avg_ms - 40) * 0.5
        return max(0.0, min(100.0, round(s, 1)))


def get_resolvers(interface_hint: str = "Wi-Fi") -> list[str]:
    """DNS server IPs configured on the active adapter (via netsh)."""
    output = _run(["netsh", "interface", "ip", "show", "dns", f"name={interface_hint}"])
    found = re.findall(r"\d+\.\d+\.\d+\.\d+", output)
    if not found:
        output = _run(["netsh", "interface", "ip", "show", "dns"])
        found = re.findall(r"\d+\.\d+\.\d+\.\d+", output)
    return list(dict.fromkeys(found))


def _timed_resolve(host: str) -> float | None:
    """Resolve a hostname, return milliseconds (None = failure)."""
    start = time.perf_counter()
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo(host, None)
        return (time.perf_counter() - start) * 1000.0
    except (socket.gaierror, OSError):
        return None


def snapshot_dns(test_hosts: list[str], hijack_prefix: str, hijack_suffix: str) -> DnsSnapshot:
    snap = DnsSnapshot(resolvers=get_resolvers())

    for host in test_hosts:
        ms = _timed_resolve(host)
        snap.resolve_times_ms[host] = ms
        if ms is None:
            snap.failures += 1
    times = [t for t in snap.resolve_times_ms.values() if t is not None]
    snap.avg_ms = sum(times) / len(times) if times else None

    # Hijack check: something that MUST NOT resolve, resolving.
    probe = f"{hijack_prefix}-{random.randint(1000, 9999)}{hijack_suffix}"
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo(probe, None)
        snap.hijacked = True
        snap.hijack_note = (
            f"'{probe}' (guaranteed non-existent) resolved — DNS is being intercepted "
            "(captive portal / campus hijack). Expect surprise redirects."
        )
    except (socket.gaierror, OSError):
        pass

    return snap
