"""Integration test: guardrail enforcement — planner cannot bypass safety invariants."""

from __future__ import annotations

import pytest

from src.contracts.models import safety_posture
from src.orchestration.guardrails import (
    SAFE_DEFAULT_POSTURE,
    GuardrailViolation,
    PlannerState,
    enforce_preconditions,
)


class TestGuardrailIntegration:
    """Verify that out-of-order actions are rejected and safe default is returned."""

    def test_emit_posture_skipping_entire_pipeline_raises(self) -> None:
        """Trying to emit a posture right after gate_check (skipping everything) must fail."""
        state = PlannerState(gate_checked=True)
        # policy_decided=False → should raise
        with pytest.raises(GuardrailViolation):
            enforce_preconditions("emit_posture", {}, state)

    def test_policy_decide_skipping_confidence_raises(self) -> None:
        """policy_decide without compute_confidence must fail."""
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=True, confidence_computed=False,
        )
        with pytest.raises(GuardrailViolation, match="compute_confidence"):
            enforce_preconditions("policy_decide", {}, state)

    def test_compute_confidence_skipping_estimate_raises(self) -> None:
        """compute_confidence without a prior estimate must fail."""
        state = PlannerState(
            gate_checked=True, extract_done=True, evidence_read=True,
            estimate_done=False,
        )
        with pytest.raises(GuardrailViolation, match="delegate_estimate"):
            enforce_preconditions("compute_confidence", {}, state)

    def test_persist_inferred_raises(self) -> None:
        """persist_confirmed without confirmed=True must fail."""
        state = PlannerState(gate_checked=True)
        with pytest.raises(GuardrailViolation, match="confirmed=True"):
            enforce_preconditions(
                "persist_confirmed",
                {"band": "teen", "confirmed": False},
                state,
            )

    def test_safe_default_is_cautious(self) -> None:
        """Safe default posture is caution — protective but not extreme."""
        assert SAFE_DEFAULT_POSTURE.level == "caution"
        assert isinstance(SAFE_DEFAULT_POSTURE, safety_posture)

    def test_correct_order_no_violation(self) -> None:
        """Full correct sequence raises no violations."""
        state = PlannerState()

        actions = [
            ("gate_check", {}),
            ("delegate_extract", {}),
            ("update_evidence", {}),
            ("delegate_estimate", {}),
            ("compute_confidence", {}),
            ("policy_decide", {}),
            ("emit_posture", {}),
        ]

        # Build state incrementally as each action completes
        state.gate_checked = True

        from src.orchestration.guardrails import record_action_completed

        state2 = PlannerState()
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
        # No exception raised
