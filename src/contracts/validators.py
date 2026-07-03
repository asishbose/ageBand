"""Shared validation helpers for AgeBand contracts.

These validators enforce invariants that cannot be expressed purely in Pydantic:
- AgeBandEstimate must never carry a confidence value (LLM must not produce one).
- PlannerAction must have a known action_type (fail-closed on unknown actions).
"""

from __future__ import annotations

from src.contracts.models import AgeBandEstimate, PlannerAction

_FORBIDDEN_ESTIMATE_KEYS = frozenset({"confidence", "confidence_score", "conf"})

_VALID_ACTION_TYPES = frozenset(
    {
        "gate_check",
        "read_evidence",
        "update_evidence",
        "compute_confidence",
        "policy_decide",
        "emit_posture",
        "persist_confirmed",
        "delegate_extract",
        "delegate_estimate",
        "delegate_stepup",
        "finish",
    }
)


def validate_ageband_estimate(raw: dict[str, object]) -> AgeBandEstimate:
    """Parse and validate an AgeBandEstimate from a raw dict.

    Raises ValueError if any forbidden key (confidence, confidence_score, conf)
    is present — this enforces the invariant that the LLM must NEVER emit a
    confidence value. Confidence is always computed deterministically in Python.
    """
    forbidden = _FORBIDDEN_ESTIMATE_KEYS & raw.keys()
    if forbidden:
        raise ValueError(
            f"AgeBandEstimate must not contain confidence key(s): {forbidden}. "
            "Confidence is computed deterministically in confidence.py — "
            "the LLM must not produce it."
        )
    return AgeBandEstimate.model_validate(raw)


def validate_planner_action(raw: dict[str, object]) -> PlannerAction:
    """Parse and validate a PlannerAction from a raw dict.

    Raises ValueError for unknown action_type values (fail closed).
    Also rejects extra fields via the model's ConfigDict(extra='forbid').
    """
    action_type = raw.get("action_type")
    if action_type not in _VALID_ACTION_TYPES:
        raise ValueError(
            f"Unknown PlannerAction.action_type: {action_type!r}. "
            f"Valid types: {sorted(_VALID_ACTION_TYPES)}"
        )
    return PlannerAction.model_validate(raw)
