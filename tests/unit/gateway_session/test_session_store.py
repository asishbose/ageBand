"""Unit tests for gateway_session.SessionStore."""

from __future__ import annotations

import pytest

from src.contracts.models import AgeBandContext
from src.gateway_session.session_store import SessionStore

_SID = "sess-store-test"


@pytest.fixture
def store() -> SessionStore:
    """Fresh SessionStore for each test."""
    return SessionStore()


class TestSessionStoreCreate:
    def test_create_returns_context_with_defaults(self, store: SessionStore) -> None:
        ctx = store.create(_SID)
        assert ctx.session_id == _SID
        assert ctx.current_band == "unknown"
        assert ctx.confidence == 0.0
        assert ctx.settled is False
        assert ctx.turn_count == 0

    def test_create_then_get_round_trip(self, store: SessionStore) -> None:
        created = store.create(_SID)
        retrieved = store.get(_SID)
        assert retrieved == created


class TestSessionStoreGet:
    def test_get_nonexistent_returns_none(self, store: SessionStore) -> None:
        assert store.get("nonexistent") is None


class TestSessionStoreUpdate:
    def test_update_persists_changes(self, store: SessionStore) -> None:
        store.create(_SID)
        updated_ctx = AgeBandContext(
            session_id=_SID,
            current_band="adult",
            confidence=0.9,
            settled=True,
            turn_count=5,
        )
        store.update(_SID, updated_ctx)
        result = store.get(_SID)
        assert result is not None
        assert result.current_band == "adult"
        assert result.confidence == 0.9
        assert result.settled is True
        assert result.turn_count == 5


class TestSessionStoreClear:
    def test_clear_removes_session(self, store: SessionStore) -> None:
        store.create(_SID)
        store.clear(_SID)
        assert store.get(_SID) is None

    def test_clear_nonexistent_is_safe(self, store: SessionStore) -> None:
        store.clear("nonexistent")  # should not raise
