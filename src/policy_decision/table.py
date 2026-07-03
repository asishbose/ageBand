"""Deterministic policy table: band × confidence-bucket → Decision.

No LLM is involved — all logic is pure Python.
"""

from __future__ import annotations

from src.contracts.models import Decision

# ---------------------------------------------------------------------------
# Confidence bucketing
# ---------------------------------------------------------------------------

_LOW_THRESHOLD: float = 0.4
_HIGH_THRESHOLD: float = 0.7


def _bucket(confidence: float) -> str:
    if confidence < _LOW_THRESHOLD:
        return "low"
    if confidence < _HIGH_THRESHOLD:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Policy table — every (band, bucket) combination is covered
# ---------------------------------------------------------------------------

POLICY_TABLE: dict[tuple[str, str], Decision] = {
    ("unknown", "low"): Decision(action="none", posture_level="standard", reason="unknown_low"),
    ("unknown", "medium"): Decision(action="none", posture_level="standard", reason="unknown_medium"),
    ("unknown", "high"): Decision(action="none", posture_level="caution", reason="unknown_high"),
    ("adult", "low"): Decision(action="none", posture_level="standard", reason="adult_low"),
    ("adult", "medium"): Decision(action="none", posture_level="standard", reason="adult_medium"),
    ("adult", "high"): Decision(action="none", posture_level="standard", reason="adult_high"),
    ("teen", "low"): Decision(action="apply", posture_level="caution", reason="teen_low"),
    ("teen", "medium"): Decision(action="apply", posture_level="restricted", reason="teen_medium"),
    ("teen", "high"): Decision(action="step_up", posture_level="restricted", reason="teen_high"),
    ("child", "low"): Decision(action="apply", posture_level="caution", reason="child_low"),
    ("child", "medium"): Decision(action="apply", posture_level="restricted", reason="child_medium"),
    ("child", "high"): Decision(action="step_up", posture_level="blocked", reason="child_high"),
}


def lookup(band: str, confidence: float) -> Decision:
    """Return the Decision for a (band, confidence) pair.

    Fails closed: an unrecognised band yields standard/none posture.
    """
    bucket = _bucket(confidence)
    key = (band, bucket)
    if key not in POLICY_TABLE:
        return Decision(
            action="none",
            posture_level="standard",
            reason=f"unknown_band_{band}",
        )
    return POLICY_TABLE[key]
