"""Deterministic corroboration score computation for accumulated cues."""

from __future__ import annotations

from src.contracts.models import Cue

_MAX_CORROBORATION_SUM: float = 5.0


def compute_corroboration(cues: list[Cue]) -> float:
    """Weighted sum of cue weights normalised to [0.0, 1.0].

    Formula: min(sum(c.weight for c in cues) / MAX_CORROBORATION_SUM, 1.0)
    Empty cues → 0.0.
    """
    if not cues:
        return 0.0
    raw = sum(c.weight for c in cues)
    return min(raw / _MAX_CORROBORATION_SUM, 1.0)
