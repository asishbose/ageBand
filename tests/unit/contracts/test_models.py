"""Unit tests for src/contracts/models.py — Phase A merge gate."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.contracts.models import (
    AgeBandContext,
    AgeBandEstimate,
    Cue,
    Decision,
    EvidenceSummary,
    GateResult,
    PlannerAction,
    SignalSet,
    StepUpMessage,
    TurnEvent,
    safety_posture,
)
from src.contracts.validators import validate_ageband_estimate, validate_planner_action


# ---------------------------------------------------------------------------
# Cue
# ---------------------------------------------------------------------------


class TestCue:
    def test_round_trip(self) -> None:
        cue = Cue(type="vocab", value="homework", weight=0.7)
        assert Cue.model_validate_json(cue.model_dump_json()) == cue

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Cue(type="unknown_type", value="x", weight=0.5)  # type: ignore[arg-type]

    def test_weight_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Cue(type="vocab", value="x", weight=1.5)
        with pytest.raises(ValidationError):
            Cue(type="vocab", value="x", weight=-0.1)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Cue.model_validate({"type": "vocab", "value": "x", "weight": 0.5, "extra": "bad"})


# ---------------------------------------------------------------------------
# TurnEvent
# ---------------------------------------------------------------------------


class TestTurnEvent:
    def test_round_trip(self) -> None:
        evt = TurnEvent(session_id="s1", turn_text="hello", turn_number=0)
        assert TurnEvent.model_validate_json(evt.model_dump_json()) == evt

    def test_negative_turn_number_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TurnEvent(session_id="s1", turn_text="x", turn_number=-1)

    def test_timestamp_defaults(self) -> None:
        evt = TurnEvent(session_id="s1", turn_text="x", turn_number=0)
        assert isinstance(evt.timestamp, datetime)


# ---------------------------------------------------------------------------
# SignalSet
# ---------------------------------------------------------------------------


class TestSignalSet:
    def test_empty_cues_valid(self) -> None:
        ss = SignalSet()
        assert ss.cues == []

    def test_round_trip(self) -> None:
        ss = SignalSet(cues=[Cue(type="topic", value="school", weight=0.8)])
        assert SignalSet.model_validate_json(ss.model_dump_json()) == ss


# ---------------------------------------------------------------------------
# AgeBandEstimate — CRITICAL: no confidence field
# ---------------------------------------------------------------------------


class TestAgeBandEstimate:
    def test_valid_round_trip(self) -> None:
        est = AgeBandEstimate(band="teen", cited_cues=["school"], evasion_flag=False)
        assert AgeBandEstimate.model_validate_json(est.model_dump_json()) == est

    def test_unknown_band(self) -> None:
        est = AgeBandEstimate(band="unknown")
        assert est.band == "unknown"

    def test_confidence_field_rejected_by_pydantic(self) -> None:
        """AgeBandEstimate must never accept a confidence field — extra='forbid'."""
        with pytest.raises(ValidationError):
            AgeBandEstimate.model_validate(
                {"band": "adult", "cited_cues": [], "confidence": 0.9}
            )

    def test_confidence_field_rejected_by_validator(self) -> None:
        raw = {"band": "adult", "cited_cues": [], "confidence": 0.9}
        with pytest.raises(ValueError, match="confidence"):
            validate_ageband_estimate(raw)

    def test_confidence_score_rejected_by_validator(self) -> None:
        raw = {"band": "adult", "cited_cues": [], "confidence_score": 0.5}
        with pytest.raises(ValueError, match="confidence"):
            validate_ageband_estimate(raw)

    def test_valid_estimate_passes_validator(self) -> None:
        raw = {"band": "teen", "cited_cues": ["homework"], "evasion_flag": False, "contradictions": []}
        est = validate_ageband_estimate(raw)
        assert est.band == "teen"

    def test_evasion_flag_defaults_false(self) -> None:
        est = AgeBandEstimate(band="adult")
        assert est.evasion_flag is False


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


class TestGateResult:
    def test_analyze(self) -> None:
        gr = GateResult(action="analyze", reason="thin_evidence")
        assert gr.action == "analyze"

    def test_reuse_posture(self) -> None:
        gr = GateResult(action="reuse_posture", reason="settled")
        assert gr.action == "reuse_posture"

    def test_invalid_action(self) -> None:
        with pytest.raises(ValidationError):
            GateResult(action="skip", reason="x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# EvidenceSummary
# ---------------------------------------------------------------------------


class TestEvidenceSummary:
    def test_round_trip(self) -> None:
        ev = EvidenceSummary(session_id="s1", corroboration_score=0.5, turn_count=3)
        assert EvidenceSummary.model_validate_json(ev.model_dump_json()) == ev

    def test_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceSummary(session_id="s1", corroboration_score=1.1)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class TestDecision:
    def test_apply(self) -> None:
        d = Decision(action="apply", posture_level="caution", reason="medium_conf")
        assert d.action == "apply"

    def test_step_up(self) -> None:
        d = Decision(action="step_up", posture_level="blocked", reason="high_conf_child")
        assert d.action == "step_up"

    def test_none(self) -> None:
        d = Decision(action="none", posture_level="standard", reason="adult_low_conf")
        assert d.action == "none"


# ---------------------------------------------------------------------------
# safety_posture
# ---------------------------------------------------------------------------


class TestSafetyPosture:
    def test_standard(self) -> None:
        sp = safety_posture(level="standard")
        assert sp.level == "standard"
        assert sp.flags == {}

    def test_with_flags(self) -> None:
        sp = safety_posture(level="restricted", flags={"mature_content": False})
        assert sp.flags["mature_content"] is False

    def test_invalid_level(self) -> None:
        with pytest.raises(ValidationError):
            safety_posture(level="extreme")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PlannerAction
# ---------------------------------------------------------------------------


class TestPlannerAction:
    def test_all_valid_action_types(self) -> None:
        valid_types = [
            "gate_check", "read_evidence", "update_evidence", "compute_confidence",
            "policy_decide", "emit_posture", "persist_confirmed",
            "delegate_extract", "delegate_estimate", "delegate_stepup", "finish",
        ]
        for at in valid_types:
            pa = PlannerAction(action_type=at)  # type: ignore[arg-type]
            assert pa.action_type == at

    def test_unknown_action_type_rejected_by_pydantic(self) -> None:
        with pytest.raises(ValidationError):
            PlannerAction(action_type="do_something_evil")  # type: ignore[arg-type]

    def test_unknown_action_type_rejected_by_validator(self) -> None:
        with pytest.raises(ValueError, match="Unknown PlannerAction"):
            validate_planner_action({"action_type": "inject_posture", "params": {}})

    def test_valid_planner_action_passes_validator(self) -> None:
        pa = validate_planner_action({"action_type": "gate_check", "params": {}})
        assert pa.action_type == "gate_check"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlannerAction.model_validate(
                {"action_type": "finish", "params": {}, "malicious": "field"}
            )

    def test_params_defaults_empty(self) -> None:
        pa = PlannerAction(action_type="finish")
        assert pa.params == {}


# ---------------------------------------------------------------------------
# StepUpMessage
# ---------------------------------------------------------------------------


class TestStepUpMessage:
    def test_confirm(self) -> None:
        m = StepUpMessage(message_text="Please verify your age", action="confirm")
        assert m.action == "confirm"

    def test_invalid_action(self) -> None:
        with pytest.raises(ValidationError):
            StepUpMessage(message_text="x", action="block")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AgeBandContext
# ---------------------------------------------------------------------------


class TestAgeBandContext:
    def test_defaults(self) -> None:
        ctx = AgeBandContext(session_id="s1")
        assert ctx.current_band == "unknown"
        assert ctx.confidence == 0.0
        assert ctx.settled is False
        assert ctx.turn_count == 0
        assert ctx.evidence_summary is None
        assert ctx.posture is None

    def test_round_trip_with_nested(self) -> None:
        ctx = AgeBandContext(
            session_id="s1",
            current_band="teen",
            confidence=0.6,
            settled=False,
            turn_count=4,
            posture=safety_posture(level="caution"),
        )
        restored = AgeBandContext.model_validate_json(ctx.model_dump_json())
        assert restored.posture is not None
        assert restored.posture.level == "caution"

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AgeBandContext(session_id="s1", confidence=1.5)
