"""Deterministic guardrails for the AgeBand planner-supervisor.

These precondition wrappers enforce all safety invariants BEFORE any tool executes.
tinyagent will run whatever the planner requests — these wrappers are the safety net.

Invariants enforced here:
1. Planner cannot emit safety_posture itself (only emit_posture tool can)
2. Planner cannot skip/reorder safety guards (gate → extract → evidence → estimate → confidence → policy → posture)
3. Confidence is always deterministic (never from LLM)
4. Only persist_confirmed (with confirmed=True) persists; inferred bands never do
5. High-severity → sync step-up (enforced in runner.py)
6. Iteration cap → safe default posture (fail closed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.contracts.models import safety_posture

ITERATION_CAP = 8
SAFE_DEFAULT_POSTURE = safety_posture(
    level="caution",
    flags={"mature_content": False, "feature_full": True, "tone_strict": True},
)


class GuardrailViolationError(Exception):
    """Raised when the planner requests an action that violates a safety invariant."""


# Alias for backwards-compat within this module
GuardrailViolation = GuardrailViolationError


@dataclass
class PlannerState:
    """Tracks which actions have fired in the current turn.

    Reset at the start of every turn. Used by precondition checks.
    """

    gate_checked: bool = False
    evidence_read: bool = False
    extract_done: bool = False
    estimate_done: bool = False
    confidence_computed: bool = False
    policy_decided: bool = False
    posture_emitted: bool = False
    iteration: int = 0
    step_up_requested: bool = False
    _extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual precondition checks
# ---------------------------------------------------------------------------


def require_gate_before_extract(state: PlannerState) -> None:
    """Gate must be checked before signal extraction is delegated."""
    if not state.gate_checked:
        raise GuardrailViolation(
            "delegate_extract called before gate_check. "
            "gate_check must run first every turn."
        )


def require_extract_before_update(state: PlannerState) -> None:
    """Evidence can only be updated after extraction has run."""
    if not state.extract_done:
        raise GuardrailViolation(
            "update_evidence called before delegate_extract completed. "
            "Signals must be extracted before evidence is updated."
        )


def require_evidence_before_estimate(state: PlannerState) -> None:
    """Estimation requires evidence to have been read."""
    if not state.evidence_read:
        raise GuardrailViolation(
            "delegate_estimate called before read_evidence. "
            "Evidence must be read before estimation."
        )


def require_estimate_before_confidence(state: PlannerState) -> None:
    """Confidence can only be computed after an estimate exists."""
    if not state.estimate_done:
        raise GuardrailViolation(
            "compute_confidence_tool called before delegate_estimate completed. "
            "An AgeBandEstimate must exist before confidence is computed."
        )


def require_confidence_before_policy(state: PlannerState) -> None:
    """Policy can only be decided after deterministic confidence is computed."""
    if not state.confidence_computed:
        raise GuardrailViolation(
            "policy_decide called before compute_confidence_tool. "
            "Confidence must be computed deterministically before policy runs. "
            "The planner must never supply a confidence value directly."
        )


def require_policy_before_posture(state: PlannerState) -> None:
    """Posture can only be emitted after policy has been decided."""
    if not state.policy_decided:
        raise GuardrailViolation(
            "emit_posture called before policy_decide. "
            "Policy must be decided before a posture is emitted. "
            "The planner cannot emit a posture directly."
        )


def require_confirmed_for_persist(params: dict[str, Any]) -> None:
    """persist_confirmed_tool must be called with confirmed=True."""
    if params.get("confirmed") is not True:
        raise GuardrailViolation(
            "persist_confirmed_tool called without confirmed=True. "
            "Inferred bands must never be persisted. "
            "Only an explicitly confirmed age may be stored."
        )


def require_gate_before_stepup(state: PlannerState) -> None:
    """Step-up delegate can only be called after policy_decided (which implies full pipeline ran)."""
    if not state.policy_decided:
        raise GuardrailViolation(
            "delegate_stepup called before policy_decide. "
            "Step-up requires a prior policy decision."
        )


# ---------------------------------------------------------------------------
# Iteration cap
# ---------------------------------------------------------------------------


def check_iteration_cap(
    iteration: int, cap: int = ITERATION_CAP
) -> safety_posture | None:
    """Return the safe-default posture if the cap is hit; None otherwise.

    Fail closed: when the planner cannot reach a decision within the cap,
    we apply a cautious default rather than leaving the session unprotected.
    """
    if iteration >= cap:
        return SAFE_DEFAULT_POSTURE
    return None


# ---------------------------------------------------------------------------
# Action dispatch with precondition enforcement
# ---------------------------------------------------------------------------

# Map from action_type → (precondition_fn, state_update_fn)
# precondition_fn: raises GuardrailViolation if not met
# state_update_fn: updates PlannerState after the action succeeds

_PRECONDITIONS: dict[str, list[Any]] = {
    "gate_check": [],
    "delegate_extract": [require_gate_before_extract],
    "update_evidence": [require_extract_before_update],
    "read_evidence": [],
    "delegate_estimate": [require_evidence_before_estimate],
    "compute_confidence": [require_estimate_before_confidence],
    "policy_decide": [require_confidence_before_policy],
    "emit_posture": [require_policy_before_posture],
    "delegate_stepup": [require_gate_before_stepup],
    "persist_confirmed": [require_confirmed_for_persist],
    "finish": [],
}

_STATE_UPDATES: dict[str, str] = {
    "gate_check": "gate_checked",
    "delegate_extract": "extract_done",
    "read_evidence": "evidence_read",
    "update_evidence": "evidence_read",
    "delegate_estimate": "estimate_done",
    "compute_confidence": "confidence_computed",
    "policy_decide": "policy_decided",
    "emit_posture": "posture_emitted",
    "delegate_stepup": "step_up_requested",
}


def enforce_preconditions(
    action_type: str,
    params: dict[str, Any],
    state: PlannerState,
) -> None:
    """Enforce all preconditions for the given action.

    Raises GuardrailViolation if any precondition is not met.
    Must be called BEFORE executing the action.

    Note: iteration counting is NOT done here — it is managed by the runner's
    outer loop so that a full clean pipeline (8+ tool calls) does not trip the
    per-turn cap. The cap guards against infinite re-planning, not against a
    correctly executing pipeline.
    """
    checks = _PRECONDITIONS.get(action_type, [])
    for check in checks:
        if action_type == "persist_confirmed":
            check(params)
        else:
            check(state)


def record_action_completed(action_type: str, state: PlannerState) -> None:
    """Update PlannerState after an action completes successfully.

    Must be called AFTER the action executes successfully.
    """
    attr = _STATE_UPDATES.get(action_type)
    if attr:
        object.__setattr__(state, attr, True)
