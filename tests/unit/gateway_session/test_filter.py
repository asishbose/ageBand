"""Unit tests for gateway_session.filter."""

from __future__ import annotations

from src.contracts.models import TurnEvent
from src.gateway_session.filter import is_user_turn


def _turn(session_id: str = "sess-filter-test", turn_number: int = 1) -> TurnEvent:
    return TurnEvent(session_id=session_id, turn_text="hello", turn_number=turn_number)


class TestIsUserTurn:
    def test_always_true_for_normal_turn(self) -> None:
        """Lean build: is_user_turn always returns True."""
        assert is_user_turn(_turn()) is True

    def test_true_for_any_turn_number(self) -> None:
        for n in range(5):
            assert is_user_turn(_turn(turn_number=n)) is True

    def test_true_for_different_sessions(self) -> None:
        for sid in ["sess-a", "sess-b", "sess-c"]:
            assert is_user_turn(_turn(session_id=sid)) is True
