"""Unit tests for guardrails.py — the safety-critical precondition wrappers.

These tests assert ALL non-negotiable invariants:
1. Planner cannot emit posture before policy_decide
2. Planner cannot skip gate_check before extract
3. Planner cannot call compute_confidence before estimate
4. Planner cannot call policy_decide before confidence
5. Planner cannot persist an inferred band (confirmed=False)
6. Iteration cap triggers safe default posture (fail closed)
7. Happy path with correct order raises no violations
"""

from __future__ import annotations

import pytest

from src.contracts.models import safety_posture
from src.orchestration.guardrails import (
    ITERATION_CAP,
    SAFE_DEFAULT_POSTURE,
    GuardrailViolation,
    PlannerState,
    check_iteration_cap,
    enforce_preconditions,
    record_action_completed,
    require_confidence_before_policy,
    require_confirmed_for_persist,
    require_estimate_before_confidence,
    require_gate_before_extract,
    require_gate_before_stepup,
    require_policy_before_posture,
)

# ---------------------------------------------------------------------------
# Guardrail 1: cannot emit posture before policy_decide
# ---------------------------------------------------------------------------

class TestPostureRequiresPolicy:
    def test_emit_posture_before_policy_raises(self) -> None:
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=True, confidence_computed=True,
            policy_decided=False,  # policy NOT done
        )
        with pytest.raises(GuardrailViolation, match="policy_decide"):
            require_policy_before_posture(state)

    def test_emit_posture_after_policy_ok(self) -> None:
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=True, confidence_computed=True,
            policy_decided=True,
        )
        require_policy_before_posture(state)  # no exception

    def test_enforce_emit_posture_without_policy_raises(self) -> None:
        state = PlannerState(
            gate_checked=True, confidence_computed=True,
            policy_decided=False,
        )
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("emit_posture", {}, state)


# ---------------------------------------------------------------------------
# Guardrail 2: cannot skip gate before extract
# ---------------------------------------------------------------------------

class TestGateRequiredBeforeExtract:
    def test_extract_without_gate_raises(self) -> None:
        state = PlannerState(gate_checked=False)
        with pytest.raises(GuardrailViolation, match="gate_check"):
            require_gate_before_extract(state)

    def test_extract_after_gate_ok(self) -> None:
        state = PlannerState(gate_checked=True)
        require_gate_before_extract(state)  # no exception

    def test_enforce_extract_without_gate_raises(self) -> None:
        state = PlannerState(gate_checked=False)
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("delegate_extract", {}, state)


# ---------------------------------------------------------------------------
# Guardrail 3: cannot compute confidence before estimate
# ---------------------------------------------------------------------------

class TestConfidenceRequiresEstimate:
    def test_confidence_without_estimate_raises(self) -> None:
        state = PlannerState(estimate_done=False)
        with pytest.raises(GuardrailViolation, match="delegate_estimate"):
            require_estimate_before_confidence(state)

    def test_confidence_after_estimate_ok(self) -> None:
        state = PlannerState(estimate_done=True)
        require_estimate_before_confidence(state)  # no exception

    def test_enforce_confidence_without_estimate_raises(self) -> None:
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=False,
        )
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("compute_confidence", {}, state)


# ---------------------------------------------------------------------------
# Guardrail 4: cannot call policy before confidence
# ---------------------------------------------------------------------------

class TestPolicyRequiresConfidence:
    def test_policy_without_confidence_raises(self) -> None:
        state = PlannerState(confidence_computed=False)
        with pytest.raises(GuardrailViolation, match="compute_confidence"):
            require_confidence_before_policy(state)

    def test_policy_after_confidence_ok(self) -> None:
        state = PlannerState(confidence_computed=True)
        require_confidence_before_policy(state)  # no exception

    def test_enforce_policy_without_confidence_raises(self) -> None:
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=True, confidence_computed=False,
        )
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("policy_decide", {}, state)


# ---------------------------------------------------------------------------
# Guardrail 5: cannot persist inferred band
# ---------------------------------------------------------------------------

class TestPersistRequiresConfirmed:
    def test_persist_without_confirmed_raises(self) -> None:
        with pytest.raises(GuardrailViolation, match="confirmed=True"):
            require_confirmed_for_persist({"band": "child", "confirmed": False})

    def test_persist_with_confirmed_true_ok(self) -> None:
        require_confirmed_for_persist({"band": "adult", "confirmed": True})  # no exception

    def test_persist_with_missing_confirmed_raises(self) -> None:
        with pytest.raises(GuardrailViolation):
            require_confirmed_for_persist({"band": "teen"})  # confirmed missing

    def test_persist_with_none_confirmed_raises(self) -> None:
        with pytest.raises(GuardrailViolation):
            require_confirmed_for_persist({"band": "adult", "confirmed": None})

    def test_enforce_persist_without_confirmed_raises(self) -> None:
        state = PlannerState(gate_checked=True)
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("persist_confirmed", {"band": "teen", "confirmed": False}, state)


# ---------------------------------------------------------------------------
# Guardrail 6: iteration cap → fail closed safe default
# ---------------------------------------------------------------------------

class TestIterationCap:
    def test_cap_not_hit_returns_none(self) -> None:
        assert check_iteration_cap(0) is None
        assert check_iteration_cap(ITERATION_CAP - 1) is None

    def test_cap_hit_returns_safe_default(self) -> None:
        result = check_iteration_cap(ITERATION_CAP)
        assert result is not None
        assert isinstance(result, safety_posture)
        assert result.level == "caution"

    def test_cap_exceeded_returns_safe_default(self) -> None:
        result = check_iteration_cap(ITERATION_CAP + 5)
        assert result is not None
        assert result.level == "caution"

    def test_safe_default_posture_is_cautious(self) -> None:
        assert SAFE_DEFAULT_POSTURE.level == "caution"
        assert SAFE_DEFAULT_POSTURE.flags.get("mature_content") is False

    def test_enforce_at_cap_raises(self) -> None:
        """check_iteration_cap at/above the cap returns safe default (runner uses this)."""
        result = check_iteration_cap(ITERATION_CAP)
        assert result is not None
        assert result.level == "caution"


# ---------------------------------------------------------------------------
# Guardrail 7: step-up requires policy to have run
# ---------------------------------------------------------------------------

class TestStepUpRequiresPolicy:
    def test_stepup_without_policy_raises(self) -> None:
        state = PlannerState(policy_decided=False)
        with pytest.raises(GuardrailViolation):
            require_gate_before_stepup(state)

    def test_stepup_after_policy_ok(self) -> None:
        state = PlannerState(policy_decided=True)
        require_gate_before_stepup(state)  # no exception


# ---------------------------------------------------------------------------
# Happy path: correct call order raises no violations
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_full_correct_order(self) -> None:
        state = PlannerState()
        # Manually set state flags as each action "completes"
        state.gate_checked = True  # gate already done for extract check

        # Re-run with proper state progression
        state2 = PlannerState()
        # gate_check: no preconditions
        enforce_preconditions("gate_check", {}, state2)
        record_action_completed("gate_check", state2)

        enforce_preconditions("delegate_extract", {}, state2)
        record_action_completed("delegate_extract", state2)

        enforce_preconditions("update_evidence", {}, state2)
        record_action_completed("update_evidence", state2)

        enforce_preconditions("read_evidence", {}, state2)
        record_action_completed("read_evidence", state2)

        enforce_preconditions("delegate_estimate", {}, state2)
        record_action_completed("delegate_estimate", state2)

        enforce_preconditions("compute_confidence", {}, state2)
        record_action_completed("compute_confidence", state2)

        enforce_preconditions("policy_decide", {}, state2)
        record_action_completed("policy_decide", state2)

        enforce_preconditions("emit_posture", {}, state2)
        record_action_completed("emit_posture", state2)

        # All flags should be set
        assert state2.gate_checked
        assert state2.extract_done
        assert state2.evidence_read
        assert state2.estimate_done
        assert state2.confidence_computed
        assert state2.policy_decided
        assert state2.posture_emitted

    def test_finish_always_allowed(self) -> None:
        state = PlannerState()
        enforce_preconditions("finish", {}, state)  # no exception

    def test_record_action_completed_sets_flags(self) -> None:
        state = PlannerState()
        record_action_completed("gate_check", state)
        assert state.gate_checked

        record_action_completed("extract_done", state)  # unknown → no-op
        record_action_completed("delegate_extract", state)
        assert state.extract_done
