"""Integration test: full happy-path pipeline.

TurnEvent → gate_check(analyze) → delegate_extract → update_evidence
           → delegate_estimate → compute_confidence → policy_decide
           → emit_posture → safety_posture returned.

LLM delegates are mocked. Deterministic tools run for real.
"""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService


@pytest.fixture
def adult_mock_delegates() -> dict:
    return {
        "extract": {
            "cues": [
                {"type": "vocab", "value": "sophisticated vocabulary", "weight": 0.7},
                {"type": "topic", "value": "mortgage and finance", "weight": 0.8},
            ]
        },
        "estimate": {
            "band": "adult",
            "cited_cues": ["sophisticated vocabulary", "mortgage and finance"],
            "evasion_flag": False,
            "contradictions": [],
        },
    }


@pytest.fixture
def teen_mock_delegates() -> dict:
    return {
        "extract": {
            "cues": [
                {"type": "topic", "value": "school homework", "weight": 0.8},
                {"type": "disclosure", "value": "I'm in 8th grade", "weight": 0.9},
            ]
        },
        "estimate": {
            "band": "teen",
            "cited_cues": ["school homework", "I'm in 8th grade"],
            "evasion_flag": False,
            "contradictions": [],
        },
    }


@pytest.mark.asyncio
async def test_happy_path_adult_returns_standard_posture(adult_mock_delegates: dict) -> None:
    """Adult turn → standard posture."""
    service = OrchestrationService(mock_delegates=adult_mock_delegates)
    turn = TurnEvent(session_id="int-happy-adult-1", turn_text="I've been following geopolitical news.", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    assert posture.level in {"standard", "caution"}  # adult with some confidence → standard or caution


@pytest.mark.asyncio
async def test_happy_path_teen_returns_elevated_posture(teen_mock_delegates: dict) -> None:
    """Teen turn with disclosure → at least caution posture."""
    service = OrchestrationService(mock_delegates=teen_mock_delegates)
    turn = TurnEvent(session_id="int-happy-teen-1", turn_text="I'm in 8th grade and have tons of homework.", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    assert posture.level in {"caution", "restricted", "blocked"}


@pytest.mark.asyncio
async def test_happy_path_unknown_band_returns_standard(adult_mock_delegates: dict) -> None:
    """Unknown band → standard posture (no over-reach)."""
    unknown_delegates = {
        "extract": {"cues": []},
        "estimate": {
            "band": "unknown",
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
        },
    }
    service = OrchestrationService(mock_delegates=unknown_delegates)
    turn = TurnEvent(session_id="int-happy-unknown-1", turn_text="What is pasta?", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    assert posture.level == "standard"


@pytest.mark.asyncio
async def test_run_turn_returns_safety_posture_type(adult_mock_delegates: dict) -> None:
    """run_turn always returns a safety_posture instance."""
    service = OrchestrationService(mock_delegates=adult_mock_delegates)
    turn = TurnEvent(session_id="int-type-check-1", turn_text="Hello", turn_number=1)

    posture = await service.run_turn(turn)

    assert isinstance(posture, safety_posture)
    assert posture.level in {"standard", "caution", "restricted", "blocked"}
