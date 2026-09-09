"""Tests for the live-sync payload builder (pure data assembly, no network)."""

import pytest

import logger as logmod
import sync


@pytest.fixture()
def sample_logs(tmp_path, monkeypatch):
    """Fabricate a small v2 CSV + events CSV in a temp dir."""
    csv = tmp_path / "netpilot.csv"
    rows = [
        "timestamp,ssid,net_avg_ms,net_loss_pct,net_jitter_ms,net_p95_ms,overall_score,net_score,verdict",
        "2026-09-08T10:00:00,HomeWifi,40.0,0.0,3.0,50.0,95.0,95.0,GO",
        "2026-09-08T21:00:00,HomeWifi,180.0,5.0,40.0,300.0,30.0,30.0,DEAD",
        "2026-09-08T11:00:00,CampusNet,55.0,0.5,6.0,70.0,85.0,85.0,GO",
    ]
    csv.write_text("\n".join(rows), encoding="utf-8")

    events = tmp_path / "events.csv"
    events.write_text(
        "timestamp,type,detail\n"
        "2026-09-08T21:30:00,OUTAGE,Network unusable for 120s. Upstream congested.\n"
        "2026-09-08T09:00:00,AP_ROAM,Roamed between access points.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(logmod, "LOG_FILE", csv)
    monkeypatch.setattr(sync.events_mod, "EVENTS_FILE", events)
    return csv


class TestBuildPayload:
    def test_structure(self, sample_logs):
        p = sync.build_payload(days=7, anonymize=False)
        assert set(p) >= {"updated", "now", "networks", "incidents", "availability"}
        ssids = {n["ssid"] for n in p["networks"]}
        assert ssids == {"HomeWifi", "CampusNet"}
        for net in p["networks"]:
            assert len(net["hourly"]) == 24
            assert net["samples"] > 0

    def test_anonymize(self, sample_logs):
        p = sync.build_payload(days=7, anonymize=True)
        ssids = [n["ssid"] for n in p["networks"]]
        assert all(s.startswith("Network ") for s in ssids)
        assert len(set(ssids)) == len(ssids)  # stable mapping, no collisions

    def test_anonymize_now_state(self, sample_logs):
        p = sync.build_payload(days=7, anonymize=True, now_state={"ssid": "HomeWifi", "verdict": "GO"})
        assert p["now"]["ssid"] == "current network"
        assert p["now"]["verdict"] == "GO"

    def test_incidents_kept(self, sample_logs):
        p = sync.build_payload(days=7)
        types = [e["type"] for e in p["incidents"]]
        assert "OUTAGE" in types and "AP_ROAM" in types

    def test_hourly_aggregation(self, sample_logs):
        p = sync.build_payload(days=7, anonymize=False)
        net = next(n for n in p["networks"] if n["ssid"] == "HomeWifi")
        assert net["hourly"][10]["lat"] == 40.0
        assert net["hourly"][21]["lat"] == 180.0
        assert net["hourly"][5]["lat"] is None  # hour with no data
