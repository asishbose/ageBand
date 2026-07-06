"""Unit tests for cross-turn context write-back (M1)."""

from __future__ import annotations

import pytest

from src.contracts.models import safety_posture
from src.gateway_session.service import GatewaySessionService
from src.gateway_session.session_store import _session_store


class TestUpdateContext:
    def teardown_method(self) -> None:
        _session_store.clear("wb-1")

    @pytest.mark.asyncio
    async def test_written_state_is_read_back_next_turn(self) -> None:
        from src.contracts.models import TurnEvent

        gw = GatewaySessionService()
        ctx = await gw.ingest(TurnEvent(session_id="wb-1", turn_text="hi", turn_number=1))
        updated = ctx.model_copy(
            update={
                "confidence": 0.9,
                "current_band": "adult",
                "settled": True,
                "posture": safety_posture(level="standard", flags={}),
            }
        )
        gw.update_context("wb-1", updated)

        # Next ingest should see the persisted confidence/band/settled.
        ctx2 = await gw.ingest(
            TurnEvent(session_id="wb-1", turn_text="again", turn_number=2)
        )
        assert ctx2.confidence == 0.9
        assert ctx2.current_band == "adult"
        assert ctx2.settled is True

    @pytest.mark.asyncio
    async def test_ingest_stashes_last_turn_text(self) -> None:
        from src.contracts.models import TurnEvent

        gw = GatewaySessionService()
        ctx = await gw.ingest(
            TurnEvent(session_id="wb-1", turn_text="my homework", turn_number=1)
        )
        assert ctx.last_turn_text == "my homework"
