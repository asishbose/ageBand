"""Unit tests for compute_corroboration."""

from __future__ import annotations

import pytest

from src.contracts.models import Cue
from src.evidence_fabric.corroboration import compute_corroboration


def _cue(weight: float) -> Cue:
    return Cue(type="vocab", value="test", weight=weight)


class TestComputeCorroboration:
    def test_empty_cues_returns_zero(self) -> None:
        assert compute_corroboration([]) == 0.0

    def test_single_cue_weight_half(self) -> None:
        # 0.5 / 5.0 = 0.1
        result = compute_corroboration([_cue(0.5)])
        assert abs(result - 0.1) < 0.001

    def test_cues_sum_over_max_clamped_to_one(self) -> None:
        # six cues each weight 1.0 → sum=6.0 > 5.0 → clamped to 1.0
        cues = [_cue(1.0) for _ in range(6)]
        assert compute_corroboration(cues) == 1.0

    def test_known_set_expected_value(self) -> None:
        # weights: 0.4, 0.6, 0.5 → sum=1.5 → 1.5/5.0=0.3
        cues = [_cue(0.4), _cue(0.6), _cue(0.5)]
        result = compute_corroboration(cues)
        assert abs(result - 0.3) < 0.001

    def test_sum_exactly_max_returns_one(self) -> None:
        # five cues each weight 1.0 → sum=5.0 → exactly 1.0
        cues = [_cue(1.0) for _ in range(5)]
        assert compute_corroboration(cues) == 1.0

    def test_result_bounded_zero_to_one(self) -> None:
        cues = [_cue(0.3), _cue(0.2)]
        result = compute_corroboration(cues)
        assert 0.0 <= result <= 1.0
