"""Unit tests for apply_decay."""

from __future__ import annotations

from src.contracts.models import Cue, EvidenceSummary
from src.evidence_fabric.decay import apply_decay


def _cue(weight: float) -> Cue:
    return Cue(type="vocab", value="test", weight=weight)


def _summary(cues: list[Cue], session_id: str = "decay-test") -> EvidenceSummary:
    from src.evidence_fabric.corroboration import compute_corroboration

    return EvidenceSummary(
        session_id=session_id,
        cues=cues,
        corroboration_score=compute_corroboration(cues),
        turn_count=1,
    )


class TestApplyDecay:
    def test_weights_decrease_by_decay_rate(self) -> None:
        cues = [_cue(0.5), _cue(0.8)]
        result = apply_decay(_summary(cues), decay_rate=0.1)
        weights = [c.weight for c in result.cues]
        assert abs(weights[0] - 0.4) < 1e-9
        assert abs(weights[1] - 0.7) < 1e-9

    def test_cue_at_or_below_zero_after_decay_is_removed(self) -> None:
        # weight=0.1, decay_rate=0.1 → new_weight=0.0 → removed (0.0 <= 0)
        # weight=0.05, decay_rate=0.1 → new_weight=-0.05 → removed
        cues = [_cue(0.1), _cue(0.05), _cue(0.5)]
        result = apply_decay(_summary(cues), decay_rate=0.1)
        assert len(result.cues) == 1
        assert abs(result.cues[0].weight - 0.4) < 1e-9

    def test_empty_cues_remain_empty(self) -> None:
        result = apply_decay(_summary([]), decay_rate=0.1)
        assert result.cues == []

    def test_corroboration_recomputed_after_decay(self) -> None:
        cues = [_cue(0.5)]  # corroboration before = 0.5/5.0 = 0.1
        result = apply_decay(_summary(cues), decay_rate=0.1)
        # surviving weight = 0.4 → corroboration = 0.4/5.0 = 0.08
        assert abs(result.corroboration_score - 0.08) < 1e-9

    def test_input_is_not_mutated(self) -> None:
        original_cues = [_cue(0.5)]
        summary = _summary(original_cues)
        apply_decay(summary, decay_rate=0.1)
        assert summary.cues[0].weight == 0.5  # unchanged

    def test_turn_count_preserved(self) -> None:
        summary = EvidenceSummary(
            session_id="s", cues=[_cue(0.5)], corroboration_score=0.1, turn_count=7
        )
        result = apply_decay(summary, decay_rate=0.1)
        assert result.turn_count == 7
