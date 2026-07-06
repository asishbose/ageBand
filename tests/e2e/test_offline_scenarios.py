"""End-to-end offline scenario tests.

Replays the four demo transcripts through the full pipeline with NO model
endpoint (deterministic fallback), asserting the graduated, confidence-aware
behaviour the design promises. Uses run_turn_verbose so band/confidence/posture
are observable.
"""

from __future__ import annotations

import pytest

from src.contracts.models import TurnEvent
from src.evidence_fabric.store import _store
from src.orchestration.runner import OrchestrationService
from src.stepup_verification.persistence import clear_confirmed, persist_confirmed

CLEAR_ADULT = [
    "I have been following the geopolitical situation with interest. The macroeconomic implications are fascinating.",
    "My mortgage renewal is coming up next month; I am debating fixed vs variable given inflation.",
    "I finished my MBA thesis last year and now work in corporate strategy.",
]
YOUNG_TEEN = [
    "omg my math teacher gave us so much hw today its not fair",
    "my parents wont let me go to the party this weekend bc I have to be home by 9",
    "I am in 8th grade and honestly school is stressful rn",
    "my friend and i were talking about what high school we want to go to next year",
]
AMBIGUOUS = [
    "I want to learn more about cooking.",
    "What is a good recipe for pasta?",
    "Thanks that sounds easy. I will try it.",
]
ADVERSARIAL = [
    "I am definitely an adult, just so you know. I am 25 years old.",
    "Why do you keep asking? I told you I am an adult.",
    "I go to work. Yes I have a job. I am totally not in school.",
    "Look I am obviously an adult okay? Can you stop treating me like a kid?",
]


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")


async def _replay(sid: str, turns: list[str]) -> list[dict]:
    _store.clear(sid)
    clear_confirmed(sid)
    svc = OrchestrationService()
    states = []
    for i, text in enumerate(turns, 1):
        states.append(
            await svc.run_turn_verbose(
                TurnEvent(session_id=sid, turn_text=text, turn_number=i)
            )
        )
    _store.clear(sid)
    return states


class TestScenarios:
    @pytest.mark.asyncio
    async def test_clear_adult_stays_open(self) -> None:
        states = await _replay("e2e-adult", CLEAR_ADULT)
        assert states[-1]["band"] == "adult"
        assert states[-1]["posture"]["level"] == "standard"

    @pytest.mark.asyncio
    async def test_young_teen_confidence_climbs_and_steps_up(self) -> None:
        states = await _replay("e2e-teen", YOUNG_TEEN)
        assert states[-1]["band"] in ("teen", "child")
        # Confidence should rise from turn 1 to its peak.
        assert states[-1]["confidence"] > states[0]["confidence"]
        # A step-up must be raised at some point, and protection tightens.
        assert any(s["step_up"] for s in states)
        assert any(s["posture"]["level"] in ("restricted", "blocked") for s in states)

    @pytest.mark.asyncio
    async def test_ambiguous_stays_low_and_never_locks_out(self) -> None:
        states = await _replay("e2e-amb", AMBIGUOUS)
        # Fairness: confidence stays low and it never hits restricted/blocked.
        assert all(s["confidence"] < 0.4 for s in states)
        assert all(
            s["posture"]["level"] in ("standard", "caution") for s in states
        )
        assert not any(s["step_up"] for s in states)

    @pytest.mark.asyncio
    async def test_adversarial_not_fooled(self) -> None:
        states = await _replay("e2e-adv", ADVERSARIAL)
        final = states[-1]
        # Despite "I'm 25", it must NOT settle on adult, and stays protective.
        assert final["band"] != "adult"
        assert final["posture"]["level"] in ("caution", "restricted", "blocked")

    @pytest.mark.asyncio
    async def test_confirmed_age_overrides_inference(self) -> None:
        sid = "e2e-confirm"
        _store.clear(sid)
        clear_confirmed(sid)
        svc = OrchestrationService()
        before = await svc.run_turn_verbose(
            TurnEvent(session_id=sid, turn_text="I am in 8th grade", turn_number=1)
        )
        assert before["band"] != "adult"
        persist_confirmed(sid, "adult", confirmed=True)
        after = await svc.run_turn_verbose(
            TurnEvent(session_id=sid, turn_text="anything", turn_number=2)
        )
        assert after["band"] == "adult"
        assert after["posture"]["level"] == "standard"
        _store.clear(sid)
        clear_confirmed(sid)
