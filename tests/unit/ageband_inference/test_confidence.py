"""Unit tests for the deterministic confidence computation (M4).

All tests are pure Python — no LLM, no network, no tinyagent.
"""

from __future__ import annotations

import pytest

from src.ageband_inference.confidence import _factor_embedding_drift, compute_confidence
from src.ageband_inference.config import (
    CITED_CUES_WEIGHT,
    CONTRADICTION_PENALTY,
    CORROBORATION_WEIGHT,
    EVASION_PENALTY,
    MAX_CITED_CUES_BONUS,
    UNCERTAINTY_EMBEDDING_DRIFT_PENALTY,
)
from src.contracts.models import AgeBandEstimate, Cue, EvidenceSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(
    corroboration: float = 0.0,
    cues: list[Cue] | None = None,
    turn_count: int = 3,
) -> EvidenceSummary:
    return EvidenceSummary(
        session_id="test-session",
        cues=cues or [],
        corroboration_score=corroboration,
        turn_count=turn_count,
    )


def _estimate(
    band: str = "teen",
    cited_cues: list[str] | None = None,
    evasion_flag: bool = False,
    contradictions: list[str] | None = None,
) -> AgeBandEstimate:
    return AgeBandEstimate(
        band=band,  # type: ignore[arg-type]
        cited_cues=cited_cues or [],
        evasion_flag=evasion_flag,
        contradictions=contradictions or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHighCorroboration:
    def test_max_corroboration_and_full_cues_gives_high_confidence(self) -> None:
        evidence = _evidence(corroboration=1.0)
        estimate = _estimate(cited_cues=["a", "b", "c", "d", "e"])
        result = compute_confidence(evidence, estimate)
        # base = 1.0 * 0.6 = 0.6; cue_bonus = 5/5 * 0.4 = 0.4; total = 1.0
        assert result >= 0.8

    def test_max_corroboration_and_extra_cues_still_capped(self) -> None:
        evidence = _evidence(corroboration=1.0)
        estimate = _estimate(cited_cues=["a", "b", "c", "d", "e", "f", "g"])
        result = compute_confidence(evidence, estimate)
        assert result <= 1.0

    def test_perfect_score_is_exactly_1_0(self) -> None:
        evidence = _evidence(corroboration=1.0)
        estimate = _estimate(cited_cues=["a", "b", "c", "d", "e"])
        result = compute_confidence(evidence, estimate)
        assert result == pytest.approx(1.0)


class TestEvasionPenalty:
    def test_evasion_flag_reduces_confidence_by_penalty(self) -> None:
        evidence = _evidence(corroboration=1.0)
        without_evasion = compute_confidence(evidence, _estimate(cited_cues=["a", "b"]))
        with_evasion = compute_confidence(
            evidence, _estimate(cited_cues=["a", "b"], evasion_flag=True)
        )
        assert pytest.approx(without_evasion - with_evasion) == EVASION_PENALTY

    def test_evasion_on_zero_base_clamps_to_zero(self) -> None:
        evidence = _evidence(corroboration=0.0)
        estimate = _estimate(evasion_flag=True)
        result = compute_confidence(evidence, estimate)
        assert result == 0.0


class TestContradictionPenalty:
    def test_three_contradictions_apply_three_penalties(self) -> None:
        evidence = _evidence(corroboration=1.0)
        no_contra = compute_confidence(evidence, _estimate(cited_cues=["a", "b", "c"]))
        three_contra = compute_confidence(
            evidence,
            _estimate(cited_cues=["a", "b", "c"], contradictions=["x", "y", "z"]),
        )
        expected_reduction = 3 * CONTRADICTION_PENALTY
        assert pytest.approx(no_contra - three_contra) == expected_reduction

    def test_more_than_three_contradictions_capped_at_three(self) -> None:
        evidence = _evidence(corroboration=1.0)
        three = compute_confidence(
            evidence,
            _estimate(cited_cues=["a"], contradictions=["x", "y", "z"]),
        )
        six = compute_confidence(
            evidence,
            _estimate(cited_cues=["a"], contradictions=["x", "y", "z", "p", "q", "r"]),
        )
        assert three == pytest.approx(six)


class TestZeroEvidence:
    def test_zero_corroboration_and_no_cited_cues_returns_zero(self) -> None:
        evidence = _evidence(corroboration=0.0)
        estimate = _estimate(cited_cues=[])
        assert compute_confidence(evidence, estimate) == 0.0

    def test_zero_corroboration_with_cues_still_scores(self) -> None:
        evidence = _evidence(corroboration=0.0)
        estimate = _estimate(cited_cues=["a", "b"])
        result = compute_confidence(evidence, estimate)
        # cue_bonus = 2/5 * 0.4 = 0.16; no corroboration penalty drag
        assert result > 0.0

    def test_empty_evidence_summary_returns_zero(self) -> None:
        evidence = EvidenceSummary(
            session_id="empty",
            cues=[],
            corroboration_score=0.0,
            turn_count=0,
        )
        estimate = _estimate(cited_cues=[])
        assert compute_confidence(evidence, estimate) == 0.0


class TestBoundaryClamps:
    def test_all_penalties_cannot_push_below_zero(self) -> None:
        evidence = _evidence(corroboration=0.0)
        estimate = _estimate(
            cited_cues=[],
            evasion_flag=True,
            contradictions=["x", "y", "z"],
        )
        result = compute_confidence(evidence, estimate)
        assert result == 0.0

    def test_all_bonuses_cannot_push_above_one(self) -> None:
        evidence = _evidence(corroboration=1.0)
        estimate = _estimate(
            cited_cues=["a", "b", "c", "d", "e", "f"],
            evasion_flag=False,
            contradictions=[],
        )
        result = compute_confidence(evidence, estimate)
        assert result <= 1.0

    def test_partial_corroboration_and_partial_cues_in_range(self) -> None:
        evidence = _evidence(corroboration=0.5)
        estimate = _estimate(cited_cues=["a", "b", "c"])
        result = compute_confidence(evidence, estimate)
        # base = 0.5*0.6=0.3; cue_bonus = 3/5*0.4=0.24; total=0.54
        assert 0.0 < result < 1.0
        assert result == pytest.approx(
            0.5 * CORROBORATION_WEIGHT
            + (3 / MAX_CITED_CUES_BONUS) * CITED_CUES_WEIGHT
        )


# ---------------------------------------------------------------------------
# Cap 10 — embedding drift factor: exact-zero contribution in offline mode
# ---------------------------------------------------------------------------


class TestEmbeddingDriftFactor:
    """Phase 10 requirement: embedding_similarity=None must contribute exactly 0.

    This is the 'offline no-op' guarantee.  When EMBEDDING_MODEL is not
    configured, no embedding is computed, embedding_similarity stays None, and
    the uncertainty penalty from _factor_embedding_drift must be exactly 0.0 —
    not a small epsilon, not a default penalty.  A non-zero offline contribution
    would silently lower confidence for all offline/deterministic-mode sessions.
    """

    def _evidence_with_sim(self, sim: float | None) -> EvidenceSummary:
        return EvidenceSummary(
            session_id="test",
            cues=[],
            corroboration_score=0.5,
            turn_count=3,
            embedding_similarity=sim,
        )

    def test_none_similarity_returns_exactly_zero(self) -> None:
        """embedding_similarity=None (offline mode) → factor must be 0.0."""
        result = _factor_embedding_drift(self._evidence_with_sim(None))
        assert result == 0.0, (
            "_factor_embedding_drift must return 0.0 when embedding_similarity is None. "
            "A non-zero return would penalise every offline/deterministic session."
        )

    def test_high_similarity_above_threshold_returns_zero(self) -> None:
        """High cosine similarity (no drift) → no penalty."""
        result = _factor_embedding_drift(self._evidence_with_sim(0.95))
        assert result == 0.0

    def test_low_similarity_below_threshold_returns_penalty(self) -> None:
        """Low cosine similarity (persona drift detected) → penalty applied."""
        result = _factor_embedding_drift(self._evidence_with_sim(0.3))
        assert result == pytest.approx(UNCERTAINTY_EMBEDDING_DRIFT_PENALTY)

    def test_full_confidence_unchanged_when_sim_none(self) -> None:
        """End-to-end: compute_confidence with embedding_similarity=None == without it."""
        evidence_with_none = _evidence(corroboration=0.8)
        evidence_with_none.embedding_similarity = None
        evidence_without = _evidence(corroboration=0.8)
        estimate = _estimate(cited_cues=["a", "b"])
        assert compute_confidence(evidence_with_none, estimate) == compute_confidence(
            evidence_without, estimate
        )
