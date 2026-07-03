"""Unit tests for stepup_verification.persistence."""

from __future__ import annotations

import pytest

from src.stepup_verification.persistence import (
    clear_confirmed,
    get_confirmed,
    persist_confirmed,
)

_SID = "sess-persist-test"
_UNKNOWN_SID = "sess-does-not-exist"


class TestPersistConfirmed:
    def teardown_method(self) -> None:
        clear_confirmed(_SID)

    def test_persist_and_retrieve(self) -> None:
        persist_confirmed(_SID, "adult", confirmed=True)
        assert get_confirmed(_SID) == "adult"

    def test_inferred_band_raises_permission_error(self) -> None:
        with pytest.raises(PermissionError, match="confirmed=True"):
            persist_confirmed(_SID, "child", confirmed=False)

    def test_inferred_band_not_stored_after_error(self) -> None:
        with pytest.raises(PermissionError):
            persist_confirmed(_SID, "child", confirmed=False)
        assert get_confirmed(_SID) is None

    def test_overwrite_updates_band(self) -> None:
        persist_confirmed(_SID, "teen", confirmed=True)
        persist_confirmed(_SID, "adult", confirmed=True)
        assert get_confirmed(_SID) == "adult"


class TestGetConfirmed:
    def test_unknown_session_returns_none(self) -> None:
        assert get_confirmed(_UNKNOWN_SID) is None


class TestClearConfirmed:
    def test_clear_removes_entry(self) -> None:
        persist_confirmed(_SID, "adult", confirmed=True)
        clear_confirmed(_SID)
        assert get_confirmed(_SID) is None

    def test_clear_nonexistent_is_safe(self) -> None:
        clear_confirmed(_UNKNOWN_SID)  # should not raise
