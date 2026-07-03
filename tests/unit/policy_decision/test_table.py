"""Unit tests for policy_decision.table (M5).

Coverage:
- Every (band, bucket) combination returns a valid Decision
- Specific high-severity outcomes: child+high, adult+high, unknown+low, teen+medium
- Boundary confidence values: 0.0, 0.399, 0.4, 0.699, 0.7, 1.0
- Unknown band string fails closed → standard/none
"""

from __future__ import annotations

import pytest

from src.contracts.models import Decision
from src.policy_decision.table import POLICY_TABLE, _bucket, lookup

# ---------------------------------------------------------------------------
# _bucket boundaries
# ---------------------------------------------------------------------------


class TestBucket:
    def test_zero_is_low(self) -> None:
        assert _bucket(0.0) == "low"

    def test_just_below_low_threshold_is_low(self) -> None:
        assert _bucket(0.399) == "low"

    def test_at_low_threshold_is_medium(self) -> None:
        assert _bucket(0.4) == "medium"

    def test_just_below_high_threshold_is_medium(self) -> None:
        assert _bucket(0.699) == "medium"

    def test_at_high_threshold_is_high(self) -> None:
        assert _bucket(0.7) == "high"

    def test_one_is_high(self) -> None:
        assert _bucket(1.0) == "high"


# ---------------------------------------------------------------------------
# Full table coverage — all (band, bucket) pairs
# ---------------------------------------------------------------------------


class TestPolicyTableCoverage:
    @pytest.mark.parametrize(
        "band,bucket,expected_action,expected_posture",
        [
            ("unknown", "low", "none", "standard"),
            ("unknown", "medium", "none", "standard"),
            ("unknown", "high", "none", "caution"),
            ("adult", "low", "none", "standard"),
            ("adult", "medium", "none", "standard"),
            ("adult", "high", "none", "standard"),
            ("teen", "low", "apply", "caution"),
            ("teen", "medium", "apply", "restricted"),
            ("teen", "high", "step_up", "restricted"),
            ("child", "low", "apply", "caution"),
            ("child", "medium", "apply", "restricted"),
            ("child", "high", "step_up", "blocked"),
        ],
    )
    def test_table_entry(
        self, band: str, bucket: str, expected_action: str, expected_posture: str
    ) -> None:
        decision = POLICY_TABLE[(band, bucket)]
        assert isinstance(decision, Decision)
        assert decision.action == expected_action
        assert decision.posture_level == expected_posture


# ---------------------------------------------------------------------------
# lookup() — spot checks with confidence values
# ---------------------------------------------------------------------------


class TestLookupHighSeverity:
    def test_child_high_confidence_step_up_blocked(self) -> None:
        d = lookup("child", 0.9)
        assert d.action == "step_up"
        assert d.posture_level == "blocked"

    def test_adult_high_confidence_none_standard(self) -> None:
        d = lookup("adult", 0.9)
        assert d.action == "none"
        assert d.posture_level == "standard"

    def test_unknown_low_confidence_none_standard(self) -> None:
        d = lookup("unknown", 0.0)
        assert d.action == "none"
        assert d.posture_level == "standard"

    def test_teen_medium_apply_restricted(self) -> None:
        d = lookup("teen", 0.5)
        assert d.action == "apply"
        assert d.posture_level == "restricted"


class TestLookupBoundaryConfidence:
    def test_confidence_0_0_maps_to_low(self) -> None:
        d = lookup("child", 0.0)
        assert d.posture_level == "caution"

    def test_confidence_0_399_maps_to_low(self) -> None:
        d = lookup("teen", 0.399)
        assert d.posture_level == "caution"

    def test_confidence_0_4_maps_to_medium(self) -> None:
        d = lookup("teen", 0.4)
        assert d.posture_level == "restricted"

    def test_confidence_0_699_maps_to_medium(self) -> None:
        d = lookup("child", 0.699)
        assert d.posture_level == "restricted"

    def test_confidence_0_7_maps_to_high(self) -> None:
        d = lookup("child", 0.7)
        assert d.posture_level == "blocked"

    def test_confidence_1_0_maps_to_high(self) -> None:
        d = lookup("adult", 1.0)
        assert d.posture_level == "standard"


# ---------------------------------------------------------------------------
# Unknown band — fail closed
# ---------------------------------------------------------------------------


class TestLookupUnknownBand:
    def test_unknown_band_string_fails_closed_standard(self) -> None:
        d = lookup("robot", 0.9)
        assert d.action == "none"
        assert d.posture_level == "standard"

    def test_unknown_band_reason_contains_band_name(self) -> None:
        d = lookup("alien", 0.5)
        assert "alien" in d.reason

    def test_empty_band_fails_closed(self) -> None:
        d = lookup("", 0.8)
        assert d.action == "none"
        assert d.posture_level == "standard"
