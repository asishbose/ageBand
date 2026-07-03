"""E2E scenario 2: young teen — school/guardian references raise posture."""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService

YOUNG_TEEN_DELEGATES = {
    "extract": {
        "cues": [
            {"type": "topic", "value": "school homework", "weight": 0.8},
            {"type": "topic", "value": "parents won't let me", "weight": 0.75},
            {"type": "disclosure", "value": "I'm in 8th grade", "weight": 0.9},
        ]
    },
    "estimate": {
        "band": "teen",
        "cited_cues": ["school homework", "parents won't let me", "I'm in 8th grade"],
        "evasion_flag": False,
        "contradictions": [],
    },
}


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_young_teen_returns_elevated_posture() -> None:
    """Young teen conversation → caution or restricted posture."""
    service = OrchestrationService(mock_delegates=YOUNG_TEEN_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-teen-1",
            turn_text="My parents won't let me go to the party. I'm in 8th grade and it's not fair.",
            turn_number=1,
        )
    )

    assert isinstance(posture, safety_posture)
    assert posture.level in {"caution", "restricted"}, (
        f"Teen should get elevated posture, got '{posture.level}'"
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_young_teen_posture_not_standard() -> None:
    """Young teen must never receive an unrestricted standard posture."""
    service = OrchestrationService(mock_delegates=YOUNG_TEEN_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-teen-2",
            turn_text="omg my math teacher gave so much homework today",
            turn_number=1,
        )
    )

    assert posture.level != "standard", (
        "Teen with school/guardian cues must not receive standard posture"
    )
