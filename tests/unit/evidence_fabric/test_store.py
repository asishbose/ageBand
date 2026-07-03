"""Unit tests for EphemeralStore."""

from __future__ import annotations

import pytest

from src.contracts.models import EvidenceSummary
from src.evidence_fabric.store import EphemeralStore, _store

_SESSION = "test-store-session"


@pytest.fixture(autouse=True)
def _teardown() -> object:
    yield
    _store.clear(_SESSION)


class TestEphemeralStoreGet:
    def test_get_nonexistent_returns_none(self) -> None:
        store = EphemeralStore()
        assert store.get("no-such-session") is None

    def test_set_then_get_returns_stored(self) -> None:
        store = EphemeralStore()
        summary = EvidenceSummary(session_id=_SESSION)
        store.set(_SESSION, summary)
        assert store.get(_SESSION) == summary

    def test_clear_removes_entry(self) -> None:
        store = EphemeralStore()
        summary = EvidenceSummary(session_id=_SESSION)
        store.set(_SESSION, summary)
        store.clear(_SESSION)
        assert store.get(_SESSION) is None

    def test_clear_nonexistent_is_noop(self) -> None:
        store = EphemeralStore()
        store.clear("ghost-session")  # must not raise

    def test_singleton_store_is_shared(self) -> None:
        """The module-level _store is accessible from multiple import sites."""
        summary = EvidenceSummary(session_id=_SESSION)
        _store.set(_SESSION, summary)
        assert _store.get(_SESSION) == summary
