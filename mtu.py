"""Path MTU discovery: are large packets being silently blackholed?

Some VPNs/firewalls drop large packets without the required "fragmentation
needed" reply — traffic then stalls mysteriously while small pings work fine
(the classic "internet works but pages half-load" bug). We binary-search the
largest ping payload that survives with DF set.
"""

from __future__ import annotations

from dataclasses import dataclass

from prober import ping

TYPICAL_ETHERNET_MTU = 1500  # payload 1472 + 28 bytes ICMP/IP headers


@dataclass
class MtuSnapshot:
    max_payload: int | None = None
    path_mtu: int | None = None
    blackhole: bool = False
    note: str = ""

    @property
    def healthy(self) -> bool:
        return self.path_mtu is not None and self.path_mtu >= 1400


def measure_mtu(target: str, lo: int = 1200, hi: int = 1472) -> MtuSnapshot:
    snap = MtuSnapshot()

    def survives(size: int) -> bool:
        r = ping(target, 2, 1200, df=True, size=size)
        return r.received > 0

    # Quick sanity: does the smallest size even pass?
    if not survives(lo):
        # DF pings may be blocked entirely on this network — don't misreport.
        snap.note = "DF pings appear blocked here; MTU probe inconclusive."
        return snap

    best = lo
    left, right = lo, hi
    while left <= right:
        mid = (left + right) // 2
        if survives(mid):
            best = mid
            left = mid + 1
        else:
            right = mid - 1

    snap.max_payload = best
    snap.path_mtu = best + 28

    if snap.path_mtu < TYPICAL_ETHERNET_MTU:
        snap.blackhole = True
        snap.note = (
            f"Path MTU is {snap.path_mtu} (typical is 1500) — large packets are being "
            "dropped/tunneled. VPN users: make sure your tunnel MTU is at or below this."
        )
    else:
        snap.note = f"Full-size packets pass (path MTU {snap.path_mtu})."
    return snap
