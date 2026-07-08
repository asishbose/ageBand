"""Deterministic offline signal extractor (M2 fallback).

Builds a ``SignalSet`` from raw turn text using the lexicon keyword patterns
(``lexicon.classify_text``) plus the Flesch-Kincaid reading-level scorer. Pure
Python — no LLM, no I/O. Used when no model endpoint is configured so the whole
pipeline runs end to end without a GPU.

Weights come exclusively from the lexicon (never hand-set here), keeping the
"confidence is deterministic" invariant true.

Non-English abstention (Phase 1):
    This extractor's lexicon is English-only. Scanning non-English text produces
    false signals worse than "no evidence" (e.g. a Spanish sentence accidentally
    matching an English keyword). ``extract_cues`` therefore checks the language
    and returns an **empty SignalSet** for confidently non-English input, making
    the abstention explicit rather than an accidental side-effect.
    Undetermined / short text (language == "") is passed through normally.
"""

from __future__ import annotations

import logging

from src.contracts.models import Cue, SignalSet
from src.signal_extraction import lexicon
from src.signal_extraction.language_detect import is_english_or_unknown
from src.signal_extraction.maturity import extract_maturity_cues
from src.signal_extraction.reading_level import compute_reading_level

logger = logging.getLogger(__name__)

# Reading level at/above this normalised score reads as adult; below reads young.
_READING_LEVEL_ADULT_THRESHOLD: float = 0.6


def extract_cues(text: str) -> SignalSet:
    """Extract age-relevant cues from *text* deterministically.

    Returns an empty SignalSet for confidently non-English text — the English
    lexicon cannot reliably score non-English input and must not produce false
    age signals from it.
    """
    if not is_english_or_unknown(text):
        logger.debug(
            "keyword_extractor: non-English text detected — abstaining "
            "(returning empty SignalSet to avoid false signals from English lexicon)"
        )
        return SignalSet(cues=[])

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

    # Maturity cues: weak nudge (weight 0.3, excluded from _STRONG_TYPES).
    cues.extend(extract_maturity_cues(text))

    return SignalSet(cues=cues)
