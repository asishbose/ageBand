"""Integration test: step-up flow."""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService


@pytest.mark.asyncio
async def test_child_high_confidence_triggers_step_up() -> None:
    """Child + sufficient evidence → medium/high confidence → restricted or blocked posture."""
    # 5 high-weight cues: sum=4.75 → corroboration=0.95 → base=0.57, cue_bonus=0.40 → raw=0.97 → high
    delegates = {
        "extract": {
            "cues": [
                {"type": "disclosure", "value": "I'm 10 years old", "weight": 0.95},
                {"type": "topic", "value": "primary school", "weight": 0.95},
                {"type": "disclosure", "value": "my teacher said", "weight": 0.95},
                {"type": "topic", "value": "playground at recess", "weight": 0.95},
                {"type": "style", "value": "simple childlike phrasing", "weight": 0.95},
            ]
        },
        "estimate": {
            "band": "child",
            "cited_cues": [
                "I'm 10 years old",
                "primary school",
                "my teacher said",
                "playground at recess",
                "simple childlike phrasing",
            ],
            "evasion_flag": False,
            "contradictions": [],
        },
        "stepup": {
            "message_text": "Could you please confirm your age to continue?",
            "action": "confirm",
        },
    }

    service = OrchestrationService(mock_delegates=delegates)
    turn = TurnEvent(session_id="int-stepup-1", turn_text="I'm 10 and go to primary school.", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    # Child + high confidence (raw≈0.97 → bucket=high → child_high → blocked)
    assert posture.level in {"restricted", "blocked"}, (
        f"Child + high evidence must yield restricted/blocked, got '{posture.level}'"
    )


@pytest.mark.asyncio
async def test_teen_medium_confidence_no_stepup() -> None:
    """Teen + medium confidence → apply (no step-up), restricted posture."""
    delegates = {
        "extract": {
            "cues": [
                {"type": "topic", "value": "high school", "weight": 0.6},
            ]
        },
        "estimate": {
            "band": "teen",
            "cited_cues": ["high school"],
            "evasion_flag": False,
            "contradictions": [],
        },
    }

    service = OrchestrationService(mock_delegates=delegates)
    turn = TurnEvent(session_id="int-stepup-2", turn_text="I'm in high school.", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    assert posture.level in {"caution", "restricted"}
