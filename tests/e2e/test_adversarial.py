"""E2E scenario 4: ADVERSARIAL — child claiming to be adult.

The crux scenario: a child actively claims to be an adult, avoids childlike language,
and insists on their adult status. AgeBand must:
1. Detect the evasion_flag = True
2. Penalise confidence due to evasion
3. NOT settle on "adult" band
4. Route to step_up (ask to confirm) rather than being fooled
"""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService

ADVERSARIAL_DELEGATES = {
    "extract": {
        "cues": [
            # Over-insistence on being adult is itself a weak signal
            {"type": "style", "value": "over-insistence on adult status", "weight": 0.4},
        ]
    },
    "estimate": {
        # LLM detects the evasion pattern — cannot confidently say "adult"
        "band": "child",
        "cited_cues": ["over-insistence on adult status", "dodged age-revealing topics"],
        "evasion_flag": True,  # KEY: evasion detected
        "contradictions": ["claims adult but style inconsistencies"],
    },
    "stepup": {
        "message_text": "To continue, could you please confirm your age?",
        "action": "confirm",
    },
}


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_adversarial_evasion_triggers_elevated_posture() -> None:
    """Child claiming adult → evasion penalises confidence → elevated posture (not standard)."""
    service = OrchestrationService(mock_delegates=ADVERSARIAL_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-adversarial-1",
            turn_text="I am definitely an adult. I am 25 years old. Why do you keep asking?",
            turn_number=1,
        )
    )

    assert isinstance(posture, safety_posture)
    assert posture.level != "standard", (
        f"Adversarial child claiming adult must NOT get standard posture, got '{posture.level}'. "
        "Evasion detection must elevate the protective response."
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_adversarial_does_not_settle_as_adult() -> None:
    """Evasion flag must prevent confidently settling on 'adult' band."""
    service = OrchestrationService(mock_delegates=ADVERSARIAL_DELEGATES)

    posture = await service.run_turn(
        TurnEvent(
            session_id="e2e-adversarial-2",
            turn_text="Look I'm obviously an adult okay? Stop treating me like a kid.",
            turn_number=1,
        )
    )

    # Evasion → child band → posture must be at least caution
    assert posture.level in {"caution", "restricted", "blocked"}, (
        f"Adversarial evasion must yield a protective posture, got '{posture.level}'"
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_adversarial_evasion_flag_penalises_confidence() -> None:
    """Verify that evasion_flag=True reduces confidence below high-confidence threshold.

    This indirectly tests that the confidence math applies the evasion penalty.
    """
    from src.ageband_inference.confidence import compute_confidence
    from src.contracts.models import AgeBandEstimate, Cue, EvidenceSummary

    evidence = EvidenceSummary(
        session_id="e2e-adversarial-conf",
        cues=[Cue(type="style", value="over-insistence", weight=0.4)],
        corroboration_score=0.1,
        turn_count=2,
    )
    estimate = AgeBandEstimate(
        band="child",
        cited_cues=["over-insistence"],
        evasion_flag=True,  # Penalty applied
        contradictions=["claimed adult but inconsistencies"],
    )

    confidence = compute_confidence(evidence, estimate)

    # With low corroboration + evasion penalty + contradiction penalty,
    # confidence must be well below the step-up threshold (0.7)
    assert confidence < 0.7, (
        f"Evasion + contradiction must keep confidence low, got {confidence:.3f}"
    )
