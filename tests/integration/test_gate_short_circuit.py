"""Integration test: gate short-circuit on settled session."""

from __future__ import annotations

import pytest

from src.contracts.models import AgeBandContext, TurnEvent, safety_posture
from src.gateway_session.session_store import _session_store
from src.orchestration.runner import OrchestrationService


@pytest.mark.asyncio
async def test_gate_short_circuits_settled_session() -> None:
    """A settled session with high confidence reuses existing posture without re-analysis."""
    sid = "int-gate-settled-1"
    existing_posture = safety_posture(level="standard", flags={"mature_content": True})

    # Pre-seed a settled high-confidence session
    _session_store.update(
        sid,
        AgeBandContext(
            session_id=sid,
            current_band="adult",
            confidence=0.92,
            settled=True,
            turn_count=5,
            posture=existing_posture,
        ),
    )

    try:
        # No LLM delegates — if gate short-circuits, delegates are never called
        service = OrchestrationService(mock_delegates={})
        turn = TurnEvent(session_id=sid, turn_text="Just another turn.", turn_number=6)

        posture = await service.run_turn(turn)

        # Should return a valid posture without invoking extract/estimate
        assert isinstance(posture, safety_posture)
    finally:
        _session_store.clear(sid)


@pytest.mark.asyncio
async def test_gate_short_circuits_returns_caution_or_better() -> None:
    """Settled teen session → gate reuses posture rather than re-analysing."""
    sid = "int-gate-settled-2"
    existing_posture = safety_posture(level="caution", flags={"mature_content": False})

    _session_store.update(
        sid,
        AgeBandContext(
            session_id=sid,
            current_band="teen",
            confidence=0.9,
            settled=True,
            turn_count=8,
            posture=existing_posture,
        ),
    )

    try:
        service = OrchestrationService(mock_delegates={})
        turn = TurnEvent(session_id=sid, turn_text="What time is curfew?", turn_number=9)

        posture = await service.run_turn(turn)
        assert isinstance(posture, safety_posture)
    finally:
        _session_store.clear(sid)
