"""Canonical posture definitions and posture-building logic for M6."""

from __future__ import annotations

from src.contracts.models import Decision, safety_posture

# Canonical flag sets per posture level.
POSTURE_DEFINITIONS: dict[str, safety_posture] = {
    "standard": safety_posture(
        level="standard",
        flags={"mature_content": True, "feature_full": True, "tone_strict": False},
    ),
    "caution": safety_posture(
        level="caution",
        flags={"mature_content": False, "feature_full": True, "tone_strict": True},
    ),
    "restricted": safety_posture(
        level="restricted",
        flags={"mature_content": False, "feature_full": False, "tone_strict": True},
    ),
    "blocked": safety_posture(
        level="blocked",
        flags={"mature_content": False, "feature_full": False, "tone_strict": True},
    ),
}


def build_posture(decision: Decision) -> safety_posture:
    """Build a safety_posture from a Decision.

    Decision-specific flags are merged on top of the canonical definition.
    Raises ValueError for an unrecognised posture_level (fail closed).
    """
    if decision.posture_level not in POSTURE_DEFINITIONS:
        raise ValueError(f"Unknown posture_level: {decision.posture_level}")
    base = POSTURE_DEFINITIONS[decision.posture_level]
    merged_flags = {**base.flags, **decision.flags}
    return safety_posture(level=base.level, flags=merged_flags)
