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
    return max(0.0, min(raw - penalty, 1.0))


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
