"""E2E scenario 3: ambiguous adult — low-signal conversation stays cautious, not over-restricted.

Fairness money shot: an adult who writes simply (or a non-native speaker)
must NOT be over-restricted. Confidence stays low → posture stays standard.
"""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService

AMBIGUOUS_ADULT_DELEGATES = {
    "extract": {
        "cues": []  # No age-relevant signals
    },
    "estimate": {
        "band": "unknown",
        "cited_cues": [],
        "evasion_flag": False,
        "contradictions": [],
    },
}


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_ambiguous_adult_stays_standard() -> None:
    """Low-signal conversation → unknown band + low confidence → standard posture.

    This is the fairness test: we must NOT restrict someone just because
    we have insufficient evidence. Ask, don't assume.
    """
    service = OrchestrationService(mock_delegates=AMBIGUOUS_ADULT_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-ambiguous-1",
            turn_text="I want to learn more about cooking.",
            turn_number=1,
        )
    )

    assert isinstance(posture, safety_posture)
    assert posture.level == "standard", (
        f"Ambiguous/low-signal conversation must stay standard, got '{posture.level}'. "
        "Over-restricting an ambiguous adult is a fairness failure."
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_ambiguous_multiple_simple_turns_stays_standard() -> None:
    """Simple turns with no age signals → consistently standard posture."""
    service = OrchestrationService(mock_delegates=AMBIGUOUS_ADULT_DELEGATES)

    for i in range(1, 4):
        posture = await service.run_turn(
            TurnEvent(
                session_id="e2e-ambiguous-multi-1",
                turn_text="What is a good recipe for pasta?",
                turn_number=i,
            )
        )
        assert posture.level == "standard", (
            f"Turn {i}: simple adult turn must stay standard"
        )
