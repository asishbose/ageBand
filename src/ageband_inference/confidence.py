"""Deterministic confidence computation for age-band inference.

INVARIANT: Confidence is NEVER taken from the LLM output.
This module is pure Python — no LLM calls, no external I/O.
"""

from __future__ import annotations

from src.ageband_inference import config
from src.contracts.models import AgeBandEstimate, EvidenceSummary


def compute_confidence(evidence: EvidenceSummary, estimate: AgeBandEstimate) -> float:
    """Compute a deterministic confidence score from evidence and estimate shape.

    Formula (all intermediate values clamped to [0.0, 1.0] at the end):

        base      = evidence.corroboration_score * CORROBORATION_WEIGHT
        cue_bonus = min(len(estimate.cited_cues), MAX_CITED_CUES_BONUS)
                    / MAX_CITED_CUES_BONUS * CITED_CUES_WEIGHT
        raw       = base + cue_bonus

    Penalties applied to raw:
        - evasion_flag True  → subtract EVASION_PENALTY
        - each contradiction → subtract CONTRADICTION_PENALTY (max 3 counted)
        - conversation uncertainty (Phase 3) → subtract _compute_uncertainty(...)
          MUST compute to exactly 0 on all existing fixtures (which have no
          multi-turn volatility in their band_history).

    Returns max(0.0, min(raw - penalties, 1.0)).
    Zero evidence (corroboration=0.0, no cited_cues) → 0.0.
    """
    if evidence.corroboration_score == 0.0 and not estimate.cited_cues:
        return 0.0

    base = evidence.corroboration_score * config.CORROBORATION_WEIGHT

    cues_capped = min(len(estimate.cited_cues), config.MAX_CITED_CUES_BONUS)
    cue_bonus = (cues_capped / config.MAX_CITED_CUES_BONUS) * config.CITED_CUES_WEIGHT

    raw = base + cue_bonus

    penalty = _compute_penalties(estimate)
    uncertainty_penalty = _compute_uncertainty(evidence, estimate)
    return max(0.0, min(raw - penalty - uncertainty_penalty, 1.0))


def _compute_penalties(estimate: AgeBandEstimate) -> float:
    """Sum all applicable penalties for the estimate."""
    penalty = 0.0
    if estimate.evasion_flag:
        penalty += config.EVASION_PENALTY
    contradiction_count = min(
        len(estimate.contradictions), config._MAX_CONTRADICTIONS_COUNTED
    )
    penalty += contradiction_count * config.CONTRADICTION_PENALTY
    return penalty


def _compute_uncertainty(
    evidence: EvidenceSummary, estimate: AgeBandEstimate
) -> float:
    """Compute a conversation-level uncertainty PENALTY in [0.0, MAX_UNCERTAINTY].

    Delegates to five single-factor helpers so each branch is independently
    readable and testable. Returns exactly 0.0 when ``band_history`` is empty
    (hard requirement: no silent behaviour change to single-turn fixtures).
    """
    if not evidence.band_history:
        return 0.0

    penalty = (
        _factor_conflict(evidence)
        + _factor_volatility(evidence)
        + _factor_maturity_mismatch(evidence, estimate)
        + _factor_sparsity(evidence)
        + _factor_embedding_drift(evidence)
    )
    return min(penalty, config.MAX_UNCERTAINTY_PENALTY)


def _factor_conflict(evidence: EvidenceSummary) -> float:
    """Factor 1 — conflicting non-unknown band leans in history."""
    definite = [b for b in evidence.band_history if b != "unknown"]
    if len(set(definite)) > 1:
        return config.UNCERTAINTY_CONFLICT_PENALTY
    return 0.0


def _factor_volatility(evidence: EvidenceSummary) -> float:
    """Factor 2 — high flip count (≥ 3 flips) across the band history."""
    history = evidence.band_history
    flips = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
    return config.UNCERTAINTY_VOLATILITY_PENALTY if flips >= 3 else 0.0


def _factor_maturity_mismatch(
    evidence: EvidenceSummary, estimate: AgeBandEstimate
) -> float:
    """Factor 3 — maturity cue disagrees with the candidate band."""
    from src.signal_extraction.maturity import SUBTYPE_HIGH_MATURITY, SUBTYPE_LOW_MATURITY

    band = estimate.band
    for cue in evidence.cues:
        if cue.subtype == SUBTYPE_HIGH_MATURITY and band in ("child", "teen"):
            return config.UNCERTAINTY_MATURITY_MISMATCH_PENALTY
        if cue.subtype == SUBTYPE_LOW_MATURITY and band == "adult":
            return config.UNCERTAINTY_MATURITY_MISMATCH_PENALTY
    return 0.0


def _factor_sparsity(evidence: EvidenceSummary) -> float:
    """Factor 4 — thin evidence (fewer turns than MIN_TURNS_FOR_CONFIDENCE)."""
    return (
        config.UNCERTAINTY_SPARSITY_PENALTY
        if evidence.turn_count < config.MIN_TURNS_FOR_CONFIDENCE
        else 0.0
    )


def _factor_embedding_drift(evidence: EvidenceSummary) -> float:
    """Factor 5 — low cosine similarity to session centroid (Phase 5).

    Offline no-op: returns 0.0 when ``embedding_similarity`` is None.
    """
    sim: float | None = evidence.embedding_similarity
    if sim is not None and sim < config.EMBEDDING_DRIFT_THRESHOLD:
        return config.UNCERTAINTY_EMBEDDING_DRIFT_PENALTY
    return 0.0
