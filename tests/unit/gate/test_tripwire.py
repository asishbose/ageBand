"""Unit tests for the always-on gate tripwire (M1.5)."""

from __future__ import annotations

from src.contracts.models import AgeBandContext, safety_posture
from src.gate.gate_service import GateService


def _settled_adult(last_turn_text: str) -> AgeBandContext:
    return AgeBandContext(
        session_id="trip",
        current_band="adult",
        confidence=0.9,
        settled=True,
        turn_count=5,
        posture=safety_posture(level="standard", flags={}),
        last_turn_text=last_turn_text,
    )


class TestTripwire:
    def test_child_cue_on_settled_adult_forces_reanalyse(self) -> None:
        ctx = _settled_adult("my mom said i cant do homework before school")
        result = GateService().check(ctx)
        assert result.action == "analyze"
        assert result.reason == "tripwire_contradiction"

    def test_adult_cue_on_settled_adult_reuses(self) -> None:
        ctx = _settled_adult("the quarterly forecast looks strong")
        result = GateService().check(ctx)
        assert result.action == "reuse_posture"
        assert result.reason == "settled_session"

    def test_no_turn_text_reuses(self) -> None:
        ctx = _settled_adult("")
        assert GateService().check(ctx).action == "reuse_posture"

    def test_adult_cue_on_settled_child_forces_reanalyse(self) -> None:
        ctx = AgeBandContext(
            session_id="trip2",
            current_band="child",
            confidence=0.9,
            settled=True,
            turn_count=5,
            posture=safety_posture(level="restricted", flags={}),
            last_turn_text="my mortgage renewal is coming up",
        )
        result = GateService().check(ctx)
        assert result.action == "analyze"
        assert result.reason == "tripwire_contradiction"
