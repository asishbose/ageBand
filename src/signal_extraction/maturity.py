"""Maturity signal scorers — weak, mismatch-only nudge cues (Phase 2).

Provides two maturity signal detectors:
1. Linguistic maturity scorer — sentence complexity, vocabulary diversity.
2. Interaction-style maturity scorer — meta-communicative patterns (hedging,
   asking clarifying questions, structured argumentation vs. reactive styles).

These produce weak ``_SPECIAL_META`` cues with fixed weight 0.3 — the same
weight as lexical style signals. They are intentionally weak because:
- Maturity scores alone cannot establish a band (they are excluded from
  ``STRONG_CUE_TYPES`` / ``_STRONG_TYPES`` in ``src.contracts.models``).
- Their primary purpose is mismatch detection: when a session's maturity
  signals strongly disagree with the declared/estimated band, that disagreement
  is a fairness signal (potential mis-classification or evasion), NOT a
  confident band assignment.

**Critical guard (must never be violated):**
These subtypes are registered in ``_SPECIAL_META`` but NEVER in ``_STRONG_TYPES``.
Maturity cues must never be able to establish a band on their own — doing so
would silently reintroduce the "lexical-only → child" false-positive bug that
PR #2 fixed. The ``assert`` at the bottom of this module enforces this at
import time.

Placement rationale: maturity detection is a cue-detection concern (it reads
the incoming text and produces a signal) rather than a band-estimation concern.
It lives here in ``signal_extraction/`` alongside the other cue producers
(``reading_level.py``, ``keyword_extractor.py``).
"""

from __future__ import annotations

import re
import statistics

from src.contracts.models import Cue

# Fixed weight for all maturity cues — deliberately low (same as reading_level).
MATURITY_CUE_WEIGHT: float = 0.3

# Maturity subtype names (registered in lexicon._SPECIAL_META, never _STRONG_TYPES).
SUBTYPE_HIGH_MATURITY: str = "maturity_high"   # adult-leaning maturity signal
SUBTYPE_LOW_MATURITY: str = "maturity_low"     # child/teen-leaning maturity signal

# Band hints used for mismatch detection (not for band establishment).
_BAND_HINT: dict[str, str] = {
    SUBTYPE_HIGH_MATURITY: "adult",
    SUBTYPE_LOW_MATURITY: "child",
}


# ---------------------------------------------------------------------------
# 1. Linguistic maturity scorer
# ---------------------------------------------------------------------------

# Vocabulary indicative of mature reflection / analytical writing (by frequency
# and register — these are not age-discriminatory in themselves, but their
# co-occurrence with simple structure is a mismatch signal).
_MATURE_VOCAB_RE = re.compile(
    r"\b(therefore|consequently|furthermore|moreover|nonetheless|whereas|albeit|"
    r"perspective|implications|framework|paradigm|nuanced|substantiate|"
    r"corroborate|nonetheless|particularly|specifically|significantly)\b",
    re.IGNORECASE,
)

_IMMATURE_VOCAB_RE = re.compile(
    r"\b(omg|lol|idk|tbh|ngl|bruh|bestie|lowkey|highkey|slay|literally|basically|"
    r"like like|super super|sooooo|soooo|kinda kinda)\b",
    re.IGNORECASE,
)


def _avg_words_per_sentence(text: str) -> float:
    """Rough words-per-sentence proxy (split on terminal punctuation)."""
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return 0.0
    word_counts = [len(s.split()) for s in sentences]
    return statistics.mean(word_counts)


def score_linguistic_maturity(text: str) -> float | None:
    """Compute a rough linguistic maturity score in [-1.0, 1.0].

    Positive → mature; negative → immature; None → insufficient text.
    Does NOT return a band or confidence; the score is only used for
    mismatch detection and weak-cue generation.
    """
    stripped = text.strip()
    if len(stripped.split()) < 5:  # not enough text to score
        return None

    mature_hits = len(_MATURE_VOCAB_RE.findall(stripped))
    immature_hits = len(_IMMATURE_VOCAB_RE.findall(stripped))
    avg_wps = _avg_words_per_sentence(stripped)

    # Composite: vocabulary + sentence length (longer → more mature)
    vocab_score = (mature_hits - immature_hits) / max(1, mature_hits + immature_hits + 1)
    length_score = min(1.0, (avg_wps - 5) / 15)  # 20+ wps → 1.0; <5 wps → negative

    return 0.6 * vocab_score + 0.4 * length_score


def linguistic_maturity_cue(text: str) -> Cue | None:
    """Return a maturity Cue if linguistic maturity signals are strong enough.

    Returns None for neutral or weak signals — only fires on clear mismatch
    potential (score ≥ 0.4 or ≤ -0.4).
    """
    score = score_linguistic_maturity(text)
    if score is None:
        return None

    if score >= 0.4:
        return Cue(
            type="style",
            value=f"linguistic_maturity_score={score:.2f}",
            subtype=SUBTYPE_HIGH_MATURITY,
            weight=MATURITY_CUE_WEIGHT,
        )
    if score <= -0.4:
        return Cue(
            type="style",
            value=f"linguistic_maturity_score={score:.2f}",
            subtype=SUBTYPE_LOW_MATURITY,
            weight=MATURITY_CUE_WEIGHT,
        )
    return None


# ---------------------------------------------------------------------------
# 2. Interaction-style maturity scorer
# ---------------------------------------------------------------------------

_HEDGING_RE = re.compile(
    r"\b(I think|I believe|I suppose|arguably|perhaps|in my view|in my opinion|"
    r"it seems|one could argue|it could be|may be|might be)\b",
    re.IGNORECASE,
)

_REACTIVE_RE = re.compile(
    r"\b(that's so|this is so|you're so|why are you|stop|no way|whatever|"
    r"not fair|so unfair|hate this|hate when)\b",
    re.IGNORECASE,
)

_CLARIFYING_RE = re.compile(
    r"\b(what do you mean|could you clarify|can you explain|I'm confused about|"
    r"did you mean|to be clear)\b",
    re.IGNORECASE,
)


def score_interaction_maturity(text: str) -> float | None:
    """Score interaction-style maturity in [-1.0, 1.0].

    Hedging + clarification-seeking → mature.
    Reactive / emotionally charged short responses → immature.
    Returns None for insufficient text.
    """
    stripped = text.strip()
    if len(stripped.split()) < 4:
        return None

    hedging = len(_HEDGING_RE.findall(stripped))
    reactive = len(_REACTIVE_RE.findall(stripped))
    clarifying = len(_CLARIFYING_RE.findall(stripped))

    total = hedging + reactive + clarifying
    if total == 0:
        return None  # no interaction-style signal

    mature = hedging + clarifying
    score = (mature - reactive) / total
    return score


def interaction_style_cue(text: str) -> Cue | None:
    """Return an interaction-style maturity Cue if signal is strong (|score| ≥ 0.5)."""
    score = score_interaction_maturity(text)
    if score is None:
        return None

    if score >= 0.5:
        return Cue(
            type="style",
            value=f"interaction_style_maturity={score:.2f}",
            subtype=SUBTYPE_HIGH_MATURITY,
            weight=MATURITY_CUE_WEIGHT,
        )
    if score <= -0.5:
        return Cue(
            type="style",
            value=f"interaction_style_maturity={score:.2f}",
            subtype=SUBTYPE_LOW_MATURITY,
            weight=MATURITY_CUE_WEIGHT,
        )
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_maturity_cues(text: str) -> list[Cue]:
    """Extract maturity cues (linguistic + interaction-style) from *text*.

    Returns 0–2 Cue objects. Never returns more than one cue per scorer.
    All cues have weight MATURITY_CUE_WEIGHT (0.3) and type "style".
    """
    cues: list[Cue] = []
    ling = linguistic_maturity_cue(text)
    if ling is not None:
        cues.append(ling)
    interact = interaction_style_cue(text)
    if interact is not None:
        cues.append(interact)
    return cues


# ---------------------------------------------------------------------------
# Safety guard — enforced at import time
# ---------------------------------------------------------------------------

def assert_not_strong_type() -> None:
    """Confirm maturity subtypes are NEVER in _STRONG_TYPES.

    This is the fairness invariant: maturity cues must not be able to establish
    a band on their own. If this assertion fails, the lexicon has been
    accidentally changed in a way that would reintroduce the PR #2 regression.

    Called from tests (deferred to avoid a circular import at module level:
    maturity.py → rule_estimator.py → signal_extraction.__init__ → maturity.py).
    """
    from src.contracts.models import STRONG_CUE_TYPES as _STRONG_TYPES  # noqa: PLC0415
    for subtype in (SUBTYPE_HIGH_MATURITY, SUBTYPE_LOW_MATURITY):
        assert subtype not in _STRONG_TYPES, (
            f"CRITICAL: maturity subtype {subtype!r} is in _STRONG_TYPES. "
            "Maturity cues must never establish a band — this would re-introduce "
            "the lexical-only false-positive bug that PR #2 fixed. "
            "Remove the subtype from _STRONG_TYPES immediately."
        )
