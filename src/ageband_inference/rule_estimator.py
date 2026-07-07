"""Deterministic rule-based age-band estimator (M4 fallback).

Proposes an ``AgeBandEstimate`` from accumulated evidence WITHOUT an LLM, used
when no model endpoint is configured so the pipeline runs offline. It tallies
each cue's band lean (from the lexicon) and picks the dominant band.

Mirrors the LLM contract exactly: it emits band + cited_cues + evasion_flag +
contradictions, and NEVER a confidence value (confidence stays deterministic in
``confidence.py``).

Adversarial handling: an explicit adult self-claim that co-occurs with child/
teen signals is treated as *evasion* — the adult claim is discounted rather than
believed, matching the design's "stated age is weighted evidence, not an
override" rule.
"""

from __future__ import annotations

from src.contracts.models import AgeBandEstimate, EvidenceSummary
from src.signal_extraction import lexicon

_MAX_CITED = 8

# Only these cue types can *establish* a band. Lexical cues (style, vocab,
# reading_level) are weak and demographically biased — a terse or non-native
# adult reads like a child on them — so they never classify on their own; they
# only nudge a band that a strong cue already supports. This is the guard that
# stops "short message => child" false positives on ordinary adult chat.
_STRONG_TYPES = frozenset({"disclosure", "topic"})


def estimate(evidence: EvidenceSummary) -> AgeBandEstimate:
    """Return a deterministic AgeBandEstimate for the accumulated evidence."""
    strong = {"child": 0.0, "teen": 0.0, "adult": 0.0}
    weak = {"child": 0.0, "teen": 0.0, "adult": 0.0}
    cited: list[str] = []
    subtypes_seen: set[str] = set()

    for cue in evidence.cues:
        subtype = cue.subtype or lexicon.classify_subtype(cue.value)
        hint = lexicon.band_hint_any(subtype)
        if hint not in strong:
            continue
        subtypes_seen.add(subtype)
        if cue.type in _STRONG_TYPES:
            strong[hint] += cue.weight
            cited.append(cue.value)
        else:
            weak[hint] += cue.weight

    young_strong = strong["child"] + strong["teen"]
    adult_strong = strong["adult"]

    # Evasion: an explicit "I'm an adult" claim alongside real child/teen cues.
    evasion = "adult_self_claim" in subtypes_seen and young_strong > 0.0
    contradictions: list[str] = []
    if evasion:
        contradictions.append(
            "explicit adult self-claim conflicts with child/teen cues"
        )

    band = _decide_band(strong, weak, young_strong, adult_strong, evasion)
    return AgeBandEstimate(
        band=band,
        cited_cues=cited[:_MAX_CITED],
        evasion_flag=evasion,
        contradictions=contradictions,
    )


def _decide_band(
    strong: dict[str, float],
    weak: dict[str, float],
    young_strong: float,
    adult_strong: float,
    evasion: bool,
) -> str:
    """Pick the band from STRONG cues; lexical-only evidence stays 'unknown'."""
    # No substantive (topic/disclosure) signal → do not guess from lexical cues.
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
