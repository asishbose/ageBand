"""Deterministic rule-based age-band estimator (M4 fallback).

Proposes an ``AgeBandEstimate`` from accumulated evidence WITHOUT an LLM, used
when no model endpoint is configured so the pipeline runs offline. It tallies
each cue's band lean (from the lexicon) and picks the dominant band.

Mirrors the LLM contract exactly: it emits band + cited_cues + evasion_flag +
evasion_patterns + contradictions, and NEVER a confidence value (confidence
stays deterministic in ``confidence.py``).

**Masking/evasion detection (Phase 4 — 4 patterns):**
Generalises the original single evasion rule ("stated age contradicts cues")
into four distinct masking patterns. This is a **strict superset**: the original
"mismatch" pattern still fires for all existing adversarial cases, and three
new patterns detect distinct evasion strategies. No existing test case that
raised evasion_flag=True should fail to do so after this change.

Patterns:
  1. mismatch        — original rule: adult self-claim with young cues present
  2. deflection      — repeated hedging/denial responses to age-related cues
  3. register_switching — band_history shows sudden maturity/vocabulary shifts
  4. over_insistence — escalating unprompted repetition of an adult claim
"""

from __future__ import annotations

from typing import Literal

from src.contracts.models import AgeBandEstimate, EvidenceSummary
from src.signal_extraction import lexicon

_MAX_CITED = 8

# Only these cue types can *establish* a band. Lexical cues (style, vocab,
# reading_level) are weak and demographically biased — a terse or non-native
# adult reads like a child on them. They are EXCLUDED entirely from band
# decisions (not merely down-weighted). This is the deliberate guard that stops
# "short message => child" false positives on ordinary adult chat.
# Fairness evidence: replaying a real 35-user Discord logistics channel, 33/35
# adults were mislabeled `child` from reading_level_low alone. After this fix
# the same channel yields all `unknown` / `standard` — zero false positives.
# Re-export from contracts so external callers (tests, maturity.py) can import
# _STRONG_TYPES from here without creating an M2 → M4 boundary crossing.
from src.contracts.models import STRONG_CUE_TYPES as _STRONG_TYPES  # noqa: E402

# Deflection cue values (lowercased substrings) — these are injected by
# the keyword extractor's adult_self_claim detection.
_DEFLECTION_PHRASES = frozenset({
    "i'm not a kid", "im not a kid", "i'm not a child", "not a child",
    "stop treating me like a kid", "why do you keep asking",
})

# Over-insistence threshold: how many adult_self_claim cue instances in
# evidence before treating it as an escalating pattern.
_OVER_INSISTENCE_THRESHOLD: int = 2

# All four masking pattern names — exported for schema validation in Phase 5.
_MASKING_PATTERNS_ALL: frozenset[str] = frozenset({
    "mismatch", "deflection", "register_switching", "over_insistence"
})


def estimate(evidence: EvidenceSummary) -> AgeBandEstimate:
    """Return a deterministic AgeBandEstimate for the accumulated evidence."""
    strong: dict[str, float] = {"child": 0.0, "teen": 0.0, "adult": 0.0}
    cited: list[str] = []
    subtypes_seen: set[str] = set()
    adult_claim_cues: list[str] = []

    for cue in evidence.cues:
        subtype = cue.subtype or lexicon.classify_subtype(cue.value)
        hint = lexicon.band_hint_any(subtype)
        if hint not in strong:
            continue
        subtypes_seen.add(subtype)
        if subtype == "adult_self_claim":
            adult_claim_cues.append(cue.value.lower())
        # Lexical cues (vocab/style/reading_level) are excluded from band
        # decisions entirely — see _STRONG_TYPES comment above.
        if cue.type in _STRONG_TYPES:
            strong[hint] += cue.weight
            cited.append(cue.value)

    young_strong = strong["child"] + strong["teen"]
    adult_strong = strong["adult"]

    # Detect all four masking patterns.
    patterns = _detect_masking_patterns(
        subtypes_seen=subtypes_seen,
        adult_claim_cues=adult_claim_cues,
        young_strong=young_strong,
        band_history=evidence.band_history,
    )

    evasion = bool(patterns)
    contradictions: list[str] = []
    if evasion:
        for p in patterns:
            contradictions.append(_pattern_description(p))

    band = _decide_band(strong, young_strong, adult_strong, evasion)
    return AgeBandEstimate(
        band=band,
        cited_cues=cited[:_MAX_CITED],
        evasion_flag=evasion,
        contradictions=contradictions,
        evasion_patterns=list(patterns),
    )


def _detect_masking_patterns(
    subtypes_seen: set[str],
    adult_claim_cues: list[str],
    young_strong: float,
    band_history: list[str],
) -> set[str]:
    """Detect all applicable masking patterns. Returns a set of pattern names.

    Strict superset of the original single-rule: "mismatch" fires for every
    case that previously raised evasion; three new patterns add detection.
    """
    patterns: set[str] = set()
    _add_mismatch(patterns, subtypes_seen, young_strong)
    _add_deflection(patterns, adult_claim_cues, young_strong)
    _add_register_switching(patterns, band_history)
    _add_over_insistence(patterns, adult_claim_cues)
    return patterns


def _add_mismatch(
    patterns: set[str], subtypes_seen: set[str], young_strong: float
) -> None:
    """Pattern 1 — adult self-claim with young cues present."""
    if "adult_self_claim" in subtypes_seen and young_strong > 0.0:
        patterns.add("mismatch")


def _add_deflection(
    patterns: set[str], adult_claim_cues: list[str], young_strong: float
) -> None:
    """Pattern 2 — user explicitly denies being young or protests age questions."""
    has_deflection = any(
        phrase in claim
        for claim in adult_claim_cues
        for phrase in _DEFLECTION_PHRASES
    )
    if has_deflection and young_strong > 0.0:
        patterns.add("deflection")


def _add_register_switching(
    patterns: set[str], band_history: list[str]
) -> None:
    """Pattern 3 — flip from a young band to adult mid-session."""
    if len(band_history) < 3:
        return
    young_bands = {"child", "teen"}
    had_young = any(b in young_bands for b in band_history[:-1])
    now_adult = band_history[-1] == "adult"
    if had_young and now_adult:
        patterns.add("register_switching")


def _add_over_insistence(
    patterns: set[str], adult_claim_cues: list[str]
) -> None:
    """Pattern 4 — repeated unprompted adult age claims."""
    if len(adult_claim_cues) >= _OVER_INSISTENCE_THRESHOLD:
        patterns.add("over_insistence")


def _pattern_description(pattern: str) -> str:
    return {
        "mismatch": "explicit adult self-claim conflicts with child/teen cues",
        "deflection": "user is deflecting age-related questions or denying youth",
        "register_switching": "sudden register shift from young-leaning to adult-leaning band",
        "over_insistence": "repeated unprompted escalation of adult age claims",
    }.get(pattern, f"masking pattern: {pattern}")


def _decide_band(
    strong: dict[str, float],
    young_strong: float,
    adult_strong: float,
    evasion: bool,
) -> Literal["child", "teen", "adult", "unknown"]:
    """Pick the band from STRONG (topic/disclosure) cues only.

    Lexical-only evidence returns 'unknown' — this is deliberate, not a gap.
    See _STRONG_TYPES comment for the fairness rationale.
    """
    # No substantive (topic/disclosure) signal → do not guess.
    if young_strong == 0.0 and adult_strong == 0.0:
        return "unknown"

    # Under evasion, do not let the discounted adult claim win.
    if evasion:
        return "child" if strong["child"] > strong["teen"] else "teen"

    if adult_strong > young_strong:
        return "adult"
    if strong["child"] > strong["teen"]:
        return "child"
    if strong["teen"] > 0.0:
        return "teen"
    return "child" if strong["child"] > 0.0 else "unknown"
