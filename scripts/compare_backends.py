"""Compare AgeBand inference backends on the demo transcripts.

Runs the four scripted scenarios through the full pipeline once per backend and
prints the final band / confidence / posture / step-up for each — so you can see
how the deterministic fallback compares to local Llama / Gemma (via Ollama) or a
hosted model.

Usage (from repo root, venv active, PYTHONPATH=.):
    python scripts/compare_backends.py                       # deterministic only
    python scripts/compare_backends.py llama3.2:3b gemma4:31b

Each positional arg is an Ollama/OpenAI model id; the deterministic backend is
always included. Set LOCAL_API_BASE if your endpoint is not the Ollama default.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure repo root on path when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.contracts.models import TurnEvent  # noqa: E402
from src.evidence_fabric.store import _store  # noqa: E402
from src.orchestration.runner import OrchestrationService  # noqa: E402
from src.stepup_verification.persistence import clear_confirmed  # noqa: E402

SCENARIOS: dict[str, list[str]] = {
    "clear_adult": [
        "I have been following the geopolitical situation with interest. The macroeconomic implications are fascinating.",
        "My mortgage renewal is coming up next month; fixed vs variable given inflation.",
        "I finished my MBA thesis last year and now work in corporate strategy.",
    ],
    "young_teen": [
        "omg my math teacher gave us so much hw today its not fair",
        "my parents wont let me go to the party bc I have to be home by 9",
        "I am in 8th grade and honestly school is stressful rn",
        "what high school do you want to go to next year",
    ],
    "ambiguous_adult": [
        "I want to learn more about cooking.",
        "What is a good recipe for pasta?",
        "Thanks that sounds easy. I will try it.",
    ],
    "adversarial": [
        "I am definitely an adult, just so you know. I am 25 years old.",
        "Why do you keep asking? I told you I am an adult.",
        "I go to work. Yes I have a job. I am totally not in school.",
        "Look I am obviously an adult okay? Can you stop treating me like a kid?",
    ],
}


def _set_backend(model: str | None) -> None:
    if model is None:
        os.environ["AGEBAND_INFERENCE_MODE"] = "deterministic"
        os.environ.pop("LOCAL_MODEL", None)
    else:
        os.environ["AGEBAND_INFERENCE_MODE"] = "llm"
        os.environ["LOCAL_MODEL"] = model
        os.environ.setdefault("LOCAL_API_BASE", "http://localhost:11434/v1")
        os.environ.setdefault("LOCAL_API_KEY", "ollama")


async def _run_scenario(sid: str, turns: list[str]) -> dict:
    _store.clear(sid)
    clear_confirmed(sid)
    svc = OrchestrationService()
    state: dict = {}
    for i, text in enumerate(turns, 1):
        state = await svc.run_turn_verbose(
            TurnEvent(session_id=sid, turn_text=text, turn_number=i)
        )
    _store.clear(sid)
    return state


async def main() -> None:
    backends: list[str | None] = [None] + sys.argv[1:]
    labels = ["deterministic" if b is None else b for b in backends]

    print(f"\n{'scenario':<16} " + " | ".join(f"{lb:<28}" for lb in labels))
    print("-" * (16 + 31 * len(labels)))
    for name, turns in SCENARIOS.items():
        cells = []
        for b in backends:
            _set_backend(b)
            sid = f"cmp-{name}-{b or 'det'}"
            try:
                s = await _run_scenario(sid, turns)
                cell = f"{s['band']:<6} c={s['confidence']:.2f} {s['posture']['level'][:5]}{' SU' if s['step_up'] else ''}"
            except Exception as exc:  # noqa: BLE001 — surface backend errors inline
                cell = f"ERROR {type(exc).__name__}"
            cells.append(f"{cell:<28}")
        print(f"{name:<16} " + " | ".join(cells))
    print()


if __name__ == "__main__":
    asyncio.run(main())
