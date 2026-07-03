"""Unit tests for GatewaySessionService."""

from __future__ import annotations

import pytest

from src.contracts.models import AgeBandContext, TurnEvent
from src.gateway_session.service import GatewaySessionService
from src.gateway_session.session_store import _session_store

_SID = "sess-gw-test"


def _turn(session_id: str = _SID, turn_number: int = 1) -> TurnEvent:
    return TurnEvent(session_id=session_id, turn_text="hello world", turn_number=turn_number)


@pytest.fixture(autouse=True)
def _cleanup() -> None:  # type: ignore[return]
    yield
    _session_store.clear(_SID)
    _session_store.clear("sess-gw-b")


class TestGatewaySessionServiceIngest:
    @pytest.mark.asyncio
    async def test_ingest_creates_new_session(self) -> None:
        svc = GatewaySessionService()
        ctx = await svc.ingest(_turn())
        assert isinstance(ctx, AgeBandContext)
        assert ctx.session_id == _SID

    @pytest.mark.asyncio
    async def test_ingest_sets_correct_session_id(self) -> None:
        svc = GatewaySessionService()
        ctx = await svc.ingest(_turn(session_id=_SID))
        assert ctx.session_id == _SID

    @pytest.mark.asyncio
    async def test_ingest_increments_turn_count_on_second_call(self) -> None:
        svc = GatewaySessionService()
        ctx1 = await svc.ingest(_turn(turn_number=1))
        ctx2 = await svc.ingest(_turn(turn_number=2))
        assert ctx1.turn_count == 1
        assert ctx2.turn_count == 2

    @pytest.mark.asyncio
    async def test_ingest_different_sessions_are_independent(self) -> None:
        svc = GatewaySessionService()
        ctx_a = await svc.ingest(_turn(session_id=_SID, turn_number=1))
        ctx_b = await svc.ingest(_turn(session_id="sess-gw-b", turn_number=1))
        assert ctx_a.session_id == _SID
        assert ctx_b.session_id == "sess-gw-b"
        assert ctx_a.turn_count == 1
        assert ctx_b.turn_count == 1

    @pytest.mark.asyncio
    async def test_initial_band_is_unknown(self) -> None:
        svc = GatewaySessionService()
        ctx = await svc.ingest(_turn())
        assert ctx.current_band == "unknown"
