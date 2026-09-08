"""WiFi environment analysis: is the air around you congested?

Answers questions like:
  * How many APs are fighting for MY channel right now?
  * Is a 5 GHz variant of my SSID available that I should switch to?
  * Which channels in my band are the cleanest?

Based on `netsh wlan show networks mode=bssid` (see prober.scan_wifi_environment).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prober import get_wifi_info, scan_wifi_environment


@dataclass
class ChannelInfo:
    channel: int
    band: str
    aps: int = 0
    strongest_signal_pct: int = 0

    @property
    def busy(self) -> bool:
        return self.aps > 0


@dataclass
class WifiEnvSnapshot:
    current_ssid: str | None = None
    current_band: str | None = None
    current_channel: int | None = None
    total_aps: int = 0
    cochannel_aps: int = 0              # APs on my channel, my band
    cochannel_strong: int = 0           # ...with strong signal (real competitors)
    channels: list[ChannelInfo] = field(default_factory=list)
    has_5ghz_variant: bool = False      # same SSID broadcasting on 5 GHz
    advice: str = ""

    @property
    def congested(self) -> bool:
        return self.cochannel_strong >= 4

    def score(self, crowded_aps: int = 6, strong_pct: int = 55) -> float:
        """0-100 radio-environment score."""
        s = 100.0
        # Strong same-channel neighbours are the real airtime competitors.
        s -= min(60.0, self.cochannel_strong * 8)
        # Weak same-channel APs add noise but matter less.
        s -= min(25.0, max(0, self.cochannel_aps - self.cochannel_strong) * 4)
        # Being stuck on 2.4 GHz in a crowded place is itself a penalty.
        if self.current_band and self.current_band.startswith("2.4") and self.total_aps > 10:
            s -= 15.0
        return max(0.0, min(100.0, round(s, 1)))

    def verdict_line(self, crowded_aps: int = 6, strong_pct: int = 55) -> str:
        if self.advice:
            return self.advice
        return "Radio environment looks clean."


def snapshot_wifi_env(strong_pct: int = 55, crowded_aps: int = 6) -> WifiEnvSnapshot:
    info = get_wifi_info()
    aps = scan_wifi_environment()

    snap = WifiEnvSnapshot(
        current_ssid=info.get("ssid"),
        current_band=info.get("band"),
        current_channel=info.get("channel"),
        total_aps=len(aps),
    )
    if not aps or snap.current_channel is None:
        snap.advice = "Wi-Fi scan unavailable (or on wired/VPN)."
        return snap

    # Group APs by channel for the current band (2.4/5 GHz).
    band_key = (snap.current_band or "")[:3]
    by_channel: dict[int, ChannelInfo] = {}
    for ap in aps:
        ch, band = ap.get("channel"), ap.get("band") or ""
        if ch is None or not band.startswith(band_key):
            continue
        ci = by_channel.setdefault(ch, ChannelInfo(channel=ch, band=band))
        ci.aps += 1
        sig = ap.get("signal") or 0
        if sig > ci.strongest_signal_pct:
            ci.strongest_signal_pct = sig
        if ch == snap.current_channel:
            snap.cochannel_aps += 1
            if sig >= strong_pct:
                snap.cochannel_strong += 1

    # The AP we're connected to counts itself; competitors are the rest.
    snap.cochannel_aps = max(0, snap.cochannel_aps - 1)
    snap.channels = sorted(by_channel.values(), key=lambda c: (-c.aps, c.channel))

    # Same SSID on 5 GHz while we're on 2.4?
    if snap.current_band and snap.current_band.startswith("2.4"):
        snap.has_5ghz_variant = any(
            ap.get("ssid") == snap.current_ssid
            and (ap.get("band") or "").startswith("5")
            for ap in aps
        )

    # Human advice
    bits: list[str] = []
    if snap.has_5ghz_variant:
        bits.append("your SSID also broadcasts on 5 GHz — switch to it, 2.4 GHz here is a warzone")
    if snap.cochannel_strong >= crowded_aps:
        bits.append(f"channel {snap.current_channel} is crowded ({snap.cochannel_strong} strong neighbours)")
    elif snap.cochannel_strong >= 3:
        bits.append(f"channel {snap.current_channel} has {snap.cochannel_strong} strong neighbours — usable but not clean")
    cleanest = [c for c in reversed(snap.channels) if c.aps == 0]
    if snap.cochannel_strong >= 3 and cleanest:
        bits.append(f"channels {[c.channel for c in cleanest[:3]]} look free on {snap.current_band}")
    snap.advice = "; ".join(bits).capitalize() + "." if bits else "Radio environment looks clean."
    return snap
