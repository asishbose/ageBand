"""Unit tests for StepupVerificationService."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.contracts.models import AgeBandContext, StepUpMessage
from src.stepup_verification.persistence import clear_confirmed, get_confirmed
from src.stepup_verification.service import StepupVerificationService

_SID = "sess-svc-test"


def _ctx(session_id: str = _SID) -> AgeBandContext:
    return AgeBandContext(session_id=session_id)


class TestCompose:
    @pytest.mark.asyncio
    async def test_compose_with_valid_mock_returns_step_up_message(self) -> None:
        svc = StepupVerificationService()
        mock = {"message_text": "Please confirm your age.", "action": "confirm"}
        result = await svc.compose(_ctx(), _mock_response=mock)
        assert isinstance(result, StepUpMessage)
        assert result.action == "confirm"
        assert result.message_text == "Please confirm your age."

    @pytest.mark.asyncio
    async def test_compose_restrict_action(self) -> None:
        svc = StepupVerificationService()
        mock = {"message_text": "Feature limited.", "action": "restrict"}
        result = await svc.compose(_ctx(), _mock_response=mock)
        assert result.action == "restrict"

    @pytest.mark.asyncio
    async def test_compose_handoff_action(self) -> None:
        svc = StepupVerificationService()
        mock = {"message_text": "Escalating…", "action": "handoff"}
        result = await svc.compose(_ctx(), _mock_response=mock)
        assert result.action == "handoff"

    @pytest.mark.asyncio
    async def test_invalid_mock_raises_validation_error(self) -> None:
        svc = StepupVerificationService()
        bad_mock: dict[str, object] = {"message_text": "ok", "action": "unknown_action"}
        with pytest.raises(ValidationError):
            await svc.compose(_ctx(), _mock_response=bad_mock)

    @pytest.mark.asyncio
    async def test_missing_field_raises_validation_error(self) -> None:
        svc = StepupVerificationService()
        with pytest.raises(ValidationError):
            await svc.compose(_ctx(), _mock_response={"action": "confirm"})


class TestPersistConfirmed:
    def teardown_method(self) -> None:
        clear_confirmed(_SID)

    def test_persist_confirmed_stores_band(self) -> None:
        svc = StepupVerificationService()
        svc.persist_confirmed(_SID, "adult")
        assert get_confirmed(_SID) == "adult"

    def test_persist_confirmed_different_sessions_isolated(self) -> None:
        svc = StepupVerificationService()
        other_sid = "sess-other"
        svc.persist_confirmed(_SID, "teen")
        assert get_confirmed(other_sid) is None
        clear_confirmed(_SID)
