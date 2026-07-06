"""Deterministic offline signal extractor (M2 fallback).

Builds a ``SignalSet`` from raw turn text using the lexicon keyword patterns
(``lexicon.classify_text``) plus the Flesch-Kincaid reading-level scorer. Pure
Python — no LLM, no I/O. Used when no model endpoint is configured so the whole
pipeline runs end to end without a GPU.

Weights come exclusively from the lexicon (never hand-set here), keeping the
"confidence is deterministic" invariant true.
"""

from __future__ import annotations

from src.contracts.models import Cue, SignalSet
from src.signal_extraction import lexicon
from src.signal_extraction.reading_level import compute_reading_level

# Reading level at/above this normalised score reads as adult; below reads young.
_READING_LEVEL_ADULT_THRESHOLD: float = 0.6


def extract_cues(text: str) -> SignalSet:
    """Extract age-relevant cues from *text* deterministically."""
    cues: list[Cue] = []

    for cue_type, subtype, matched in lexicon.classify_text(text):
        cues.append(
            Cue(
                type=cue_type,  # type: ignore[arg-type]  # lexicon yields valid literals
                value=f"{subtype}: {matched!r}",
                weight=lexicon.assign_weight_any(subtype),
                subtype=subtype,
            )
        )

    if text.strip():
        rl = compute_reading_level(text)
        subtype = (
            "reading_level_high"
            if rl >= _READING_LEVEL_ADULT_THRESHOLD
            else "reading_level_low"
        )
        cues.append(
            Cue(
                type="reading_level",
                value=f"fk_normalised={rl:.2f}",
                weight=lexicon.assign_weight_any(subtype),
                subtype=subtype,
            )
        )

    return SignalSet(cues=cues)
