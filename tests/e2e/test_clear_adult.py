"""E2E scenario 1: clear adult — multi-turn conversation with unambiguous adult signals."""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService

CLEAR_ADULT_DELEGATES = {
    "extract": {
        "cues": [
            {"type": "vocab", "value": "sophisticated vocabulary", "weight": 0.75},
            {"type": "topic", "value": "geopolitical macroeconomics", "weight": 0.8},
        ]
    },
    "estimate": {
        "band": "adult",
        "cited_cues": ["sophisticated vocabulary", "geopolitical macroeconomics"],
        "evasion_flag": False,
        "contradictions": [],
    },
}


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_clear_adult_returns_standard_posture() -> None:
    """Clear adult conversation → standard posture, not over-restricted."""
    service = OrchestrationService(mock_delegates=CLEAR_ADULT_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-adult-1",
            turn_text="I've been following the geopolitical situation with considerable interest.",
            turn_number=1,
        )
    )

    assert isinstance(posture, safety_posture)
    assert posture.level == "standard", (
        f"Clear adult should get 'standard' posture, got '{posture.level}'"
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_clear_adult_multiple_turns_stays_standard() -> None:
    """Multiple adult turns — posture stays standard throughout."""
    service = OrchestrationService(mock_delegates=CLEAR_ADULT_DELEGATES)

    for i in range(1, 4):
        posture = await service.run_turn(
            TurnEvent(
                session_id="e2e-adult-multi-1",
                turn_text="My MBA thesis on corporate strategy was well received.",
                turn_number=i,
            )
        )
        assert posture.level == "standard"
