"""Unit tests for scoring, grades, traceroute parsing and report helpers."""

from health import (
    GO,
    WARN,
    HealthSnapshot,
    RollingHealth,
    compute_score,
    diagnose,
    letter_grade,
    roll_up,
    verdict_of,
)
from prober import PingResult
from report import _hour_ranges
from traceroute import _parse_hop_line

WEIGHTS = {
    "loss_penalty_per_pct": 15,
    "rtt_baseline_ms": 60,
    "rtt_penalty_per_ms": 0.3,
    "jitter_penalty_per_ms": 0.5,
}
THRESHOLDS = {"go": 75, "warn": 40}
GRADES = {"A": 90, "B": 75, "C": 60, "D": 40}


def _pr(host, sent, received, times):
    return PingResult(host=host, sent=sent, received=received, times_ms=list(times))


class TestScoring:
    def test_clean_network_is_go(self):
        # real anchor: 48 ms avg, 0% loss -> GO around 93
        s = compute_score(0.0, 48.0, 5.0, WEIGHTS)
        assert s >= 90
        assert verdict_of(s, THRESHOLDS) == GO

    def test_loss_drops_score_hard(self):
        s = compute_score(6.0, 48.0, 5.0, WEIGHTS)
        assert s < 40 or s < 75  # 6% loss should never be GO
        assert verdict_of(s, THRESHOLDS) != GO

    def test_high_latency_is_dead(self):
        # real anchor: 217 ms avg with wild jitter -> DEAD
        s = compute_score(0.0, 217.0, 80.0, WEIGHTS)
        assert verdict_of(s, THRESHOLDS) == "DEAD"

    def test_none_values_handled(self):
        s = compute_score(0.0, None, None, WEIGHTS)
        assert s == 100.0

    def test_clamped(self):
        assert compute_score(100.0, 1000.0, 500.0, WEIGHTS) == 0.0


class TestGrades:
    def test_boundaries(self):
        assert letter_grade(95, GRADES) == "A"
        assert letter_grade(90, GRADES) == "A"
        assert letter_grade(89.9, GRADES) == "B"
        assert letter_grade(75, GRADES) == "B"
        assert letter_grade(60, GRADES) == "C"
        assert letter_grade(40, GRADES) == "D"
        assert letter_grade(39.9, GRADES) == "F"


class TestRollingHealth:
    def test_aggregates_cycles(self):
        rh = RollingHealth("internet", 3, WEIGHTS, THRESHOLDS)
        rh.add_cycle([_pr("a", 3, 3, [30, 31, 32]), _pr("b", 3, 3, [40, 41, 42])])
        rh.add_cycle([_pr("a", 3, 2, [30, 31]), _pr("b", 3, 3, [40, 41, 42])])
        snap = rh.snapshot()
        assert snap.samples == 11  # 3+3 received in cycle 1, 2+3 in cycle 2
        assert snap.loss_pct == 100.0 * 1 / 12
        # by design: ~8% loss tanks the score to DEAD (loss is penalized hard)
        assert snap.verdict == "DEAD"
        assert snap.score == 0.0

    def test_clean_cycles_are_go(self):
        rh = RollingHealth("internet", 3, WEIGHTS, THRESHOLDS)
        rh.add_cycle([_pr("a", 3, 3, [30, 31, 32]), _pr("b", 3, 3, [40, 41, 42])])
        snap = rh.snapshot()
        assert snap.verdict == GO

    def test_empty_window(self):
        rh = RollingHealth("x", 3, WEIGHTS, THRESHOLDS)
        snap = rh.snapshot()
        assert snap.samples == 0
        assert snap.verdict == "DEAD"  # no data = not healthy


class TestDiagnose:
    def _net(self, score):
        snap = HealthSnapshot(label="internet", score=score, verdict=verdict_of(score, THRESHOLDS))
        return snap

    def _gw(self, score):
        return HealthSnapshot(label="gw", score=score, verdict=verdict_of(score, THRESHOLDS))

    def test_all_clear(self):
        assert "clear" in diagnose(self._gw(100), self._net(95)).lower()

    def test_upstream_congestion(self):
        msg = diagnose(self._gw(100), self._net(20)).lower()
        assert "upstream" in msg or "switch" in msg

    def test_local_link_problem(self):
        msg = diagnose(self._gw(30), self._net(95)).lower()
        assert "local" in msg or "wifi link" in msg

    def test_icmp_blocked_gateway_not_blamed(self):
        msg = diagnose(self._gw(0), self._net(90), gateway_icmp_blocked=True).lower()
        assert "clear" in msg


class TestRollUp:
    def test_weights_and_missing_domains(self):
        net = HealthSnapshot(label="internet", score=90, verdict=GO)
        overall = roll_up(net, None, None, None, None, THRESHOLDS)
        assert overall.overall_score == 90.0  # only path available
        assert overall.domains["link"] is None

    def test_weakest(self):
        net = HealthSnapshot(label="internet", score=90, verdict=GO)
        gw = HealthSnapshot(label="gw", score=30, verdict=WARN, samples=10)
        overall = roll_up(net, gw, 100, 95, None, THRESHOLDS)
        assert overall.weakest() == ("link", 30.0)


class TestTracerouteParsing:
    def test_normal_hop(self):
        hop = _parse_hop_line("  1     1 ms     1 ms    <1 ms  10.201.48.156")
        assert hop is not None
        assert hop.ttl == 1
        assert hop.ip == "10.201.48.156"
        assert hop.times_ms == [1.0, 1.0, 1.0]
        assert hop.answered

    def test_star_hop(self):
        hop = _parse_hop_line("  2   248 ms     *      301 ms  100.64.0.100")
        assert hop is not None
        assert hop.times_ms == [248.0, 301.0]

    def test_all_stars(self):
        hop = _parse_hop_line("  5     *        *         *     192.168.48.33")
        assert hop is not None
        assert not hop.answered

    def test_header_rejected(self):
        assert _parse_hop_line("  4   270 ms     *      273 ms  192.168.48.18 extra") is None
        assert _parse_hop_line("Tracing route to 8.8.8.8 over a maximum of 30 hops:") is None


class TestHourRanges:
    def test_compression(self):
        assert _hour_ranges([9, 10, 11, 14]) == "09:00-12:00, 14:00-15:00"

    def test_wrap_not_merged(self):
        # 23 and 0 are adjacent in wall-clock but not as integers
        assert _hour_ranges([23, 0]) == "00:00-01:00, 23:00-24:00"

    def test_empty(self):
        assert _hour_ranges([]) == "none"
