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


def estimate(evidence: EvidenceSummary) -> AgeBandEstimate:
    """Return a deterministic AgeBandEstimate for the accumulated evidence."""
    scores = {"child": 0.0, "teen": 0.0, "adult": 0.0}
    cited: list[str] = []
    subtypes_seen: set[str] = set()

    for cue in evidence.cues:
        subtype = cue.subtype or lexicon.classify_subtype(cue.value)
        hint = lexicon.band_hint_any(subtype)
        if hint in scores:
            scores[hint] += cue.weight
            cited.append(cue.value)
            subtypes_seen.add(subtype)

    young = scores["child"] + scores["teen"]
    adult = scores["adult"]

    # Evasion: an explicit "I'm an adult" style claim alongside child/teen cues.
    evasion = "adult_self_claim" in subtypes_seen and young > 0.0
    contradictions: list[str] = []
    if evasion:
        contradictions.append(
            "explicit adult self-claim conflicts with child/teen cues"
        )

    band = _decide_band(scores, young, adult, evasion)
    return AgeBandEstimate(
        band=band,
        cited_cues=cited[:_MAX_CITED],
        evasion_flag=evasion,
        contradictions=contradictions,
    )


def _decide_band(
    scores: dict[str, float], young: float, adult: float, evasion: bool
) -> str:
    """Pick the band from tallied scores (fail-safe: unknown)."""
    if young == 0.0 and adult == 0.0:
        return "unknown"

    # Under evasion, do not let the discounted adult claim win.
    if evasion:
        return "child" if scores["child"] > scores["teen"] else "teen"

    if adult > young:
        return "adult"
    if scores["child"] > scores["teen"]:
        return "child"
    if scores["teen"] > 0.0:
        return "teen"
    return "child" if scores["child"] > 0.0 else "unknown"
