"""Evidence weight decay — reduces all cue weights by a fixed rate per call."""

from __future__ import annotations

import os

from src.contracts.models import Cue, EvidenceSummary
from src.evidence_fabric.corroboration import compute_corroboration

DECAY_RATE: float = float(os.environ.get("EVIDENCE_DECAY_RATE", "0.1"))


def apply_decay(
    evidence: EvidenceSummary,
    decay_rate: float = DECAY_RATE,
) -> EvidenceSummary:
    """Reduce all cue weights by *decay_rate*; discard cues with weight ≤ 0.

    Returns a new EvidenceSummary (input is treated as immutable).
    Corroboration score is recomputed from the surviving cues.
    """
    surviving: list[Cue] = []
    for cue in evidence.cues:
        new_weight = cue.weight - decay_rate
        if new_weight > 0.0:
            # Preserve subtype — dropping it here would cause the lexicon
            # re-stamp in service.py to lose subtype context on decayed cues.
            surviving.append(
                Cue(
                    type=cue.type,
                    value=cue.value,
                    subtype=cue.subtype,
                    weight=new_weight,
                )
            )

    return EvidenceSummary(
        session_id=evidence.session_id,
        cues=surviving,
        corroboration_score=compute_corroboration(surviving),
        turn_count=evidence.turn_count,
    )
