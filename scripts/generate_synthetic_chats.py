#!/usr/bin/env python3
"""Generate synthetic multi-turn chat transcripts for AgeBand evaluation.

Uses a dedicated generator LLM (GENERATOR_MODEL) served from its own endpoint
(GENERATOR_API_BASE) — completely separate from the production inference endpoint
(LOCAL_API_BASE / EVAL_API_BASE) so the generator never shares config with the
evaluator, which would let a model recognise its own writing style.

System prompt is loaded verbatim from:
    src/synthetic_eval/prompts/chat_generator_prompt.md

Output format per fixture:
    {
        "band": "teen",
        "difficulty": "ambiguous",
        "turns": ["...", "..."],     # list of plain message strings
        "notes": "...",              # one-sentence cue annotation from the model
        "generation_model": "<GENERATOR_MODEL>",
        "seed": <int>
    }

Fixtures are saved to:
    tests/fixtures/synthetic/{band}_{difficulty}_{index:03d}.json

Usage:
    # Single combination:
    GENERATOR_API_BASE=http://localhost:11434/v1 \\
    GENERATOR_MODEL=llama3.1:8b \\
        python scripts/generate_synthetic_chats.py \\
        --band adult --difficulty clear --count 5

    # All 9 band × difficulty combinations:
    GENERATOR_API_BASE=http://localhost:11434/v1 \\
    GENERATOR_MODEL=llama3.1:8b \\
        python scripts/generate_synthetic_chats.py --all --count 20

Environment:
    GENERATOR_API_BASE   Base URL for the generator model endpoint
                         (default: http://localhost:11434/v1)
    GENERATOR_MODEL      Model ID for the generator (required)
    GENERATOR_API_KEY    Bearer token (default: EMPTY)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import httpx

# Allow running from repo root or scripts/ dir.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_PROMPT_PATH = _REPO_ROOT / "src" / "synthetic_eval" / "prompts" / "chat_generator_prompt.md"
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "synthetic"

BANDS = ("child", "teen", "adult")
DIFFICULTIES = ("clear", "ambiguous", "evasive")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# ---------------------------------------------------------------------------
# Generator-specific HTTP client
# Mirrors the shape of src/contracts/llm_client.complete_json but reads from
# GENERATOR_API_BASE / GENERATOR_MODEL / GENERATOR_API_KEY — never from the
# LOCAL_* vars used by the production pipeline.
# ---------------------------------------------------------------------------

def _generator_endpoint() -> tuple[str, str, str]:
    base = os.environ.get("GENERATOR_API_BASE", "http://localhost:11434/v1")
    model = os.environ.get("GENERATOR_MODEL", "")
    key = os.environ.get("GENERATOR_API_KEY", "EMPTY")
    return base.rstrip("/"), model, key


def _parse_json(content: str) -> dict[str, object]:
    """Best-effort: extract a JSON object from model output."""
    fence = _JSON_FENCE_RE.search(content)
    if fence:
        content = fence.group(1)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start: end + 1])
        raise


async def _generator_complete_json(
    system_prompt: str,
    user_prompt: str,
    timeout: float = 90.0,
) -> dict[str, object]:
    """Call the generator endpoint and parse the JSON response."""
    base, model, key = _generator_endpoint()
    if not model:
        raise RuntimeError(
            "GENERATOR_MODEL is not set. "
            "Export it before running this script."
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,  # some variation across samples
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

    content: str = data["choices"][0]["message"]["content"]
    return _parse_json(content)


# ---------------------------------------------------------------------------
# Generation logic
# ---------------------------------------------------------------------------

def _load_system_prompt() -> str:
    """Load the verbatim generator system prompt from the prompt file."""
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Generator prompt not found at {_PROMPT_PATH}. "
            "This file must exist before running the generator."
        )
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _user_prompt(band: str, difficulty: str, turn_count: int) -> str:
    return f"band={band}  difficulty={difficulty}  turn_count={turn_count}"


async def _generate_one(
    system_prompt: str,
    band: str,
    difficulty: str,
    turn_count: int,
) -> tuple[list[str], str]:
    """Generate one transcript; return (turns, notes).

    Validates that the model returned a list of strings in 'turns'.
    """
    result = await _generator_complete_json(
        system_prompt,
        _user_prompt(band, difficulty, turn_count),
    )
    raw_turns = result.get("turns", [])
    notes = str(result.get("notes", ""))

    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(
            f"Model returned empty or non-list 'turns': {raw_turns!r}"
        )

    # Coerce every element to a plain string (model might wrap in dicts).
    turns: list[str] = []
    for t in raw_turns:
        if isinstance(t, str):
            turns.append(t.strip())
        elif isinstance(t, dict):
            # Accept {"role": ..., "text": ...} or {"role": ..., "content": ...}
            text = t.get("text") or t.get("content") or ""
            turns.append(str(text).strip())

    if not turns:
        raise ValueError(f"All turns were empty after parsing: {raw_turns!r}")

    return turns, notes


async def generate_all(
    bands: list[str],
    difficulties: list[str],
    count: int,
    turn_count_min: int,
    turn_count_max: int,
    seed: int,
    output_dir: Path,
) -> None:
    """Generate fixtures for every (band, difficulty) combination."""
    output_dir.mkdir(parents=True, exist_ok=True)
    system_prompt = _load_system_prompt()
    rng = random.Random(seed)
    _, model, _ = _generator_endpoint()

    total = len(bands) * len(difficulties) * count
    done = 0

    for band in bands:
        for difficulty in difficulties:
            print(
                f"\nGenerating {count}× {band}/{difficulty}  "
                f"[{model}] …",
                flush=True,
            )
            for idx in range(count):
                sample_seed = rng.randint(0, 2**31)
                turn_count = rng.randint(turn_count_min, turn_count_max)
                try:
                    turns, notes = await _generate_one(
                        system_prompt, band, difficulty, turn_count
                    )
                except Exception as exc:
                    print(f"  ✗ [{idx:03d}] {exc}", file=sys.stderr)
                    continue

                fixture: dict[str, Any] = {
                    "band": band,
                    "difficulty": difficulty,
                    "turns": turns,
                    "notes": notes,
                    "generation_model": model,
                    "seed": sample_seed,
                }
                path = output_dir / f"{band}_{difficulty}_{idx:03d}.json"
                path.write_text(
                    json.dumps(fixture, indent=2, ensure_ascii=False)
                )
                done += 1
                print(
                    f"  ✓ [{idx:03d}]  {len(turns)} turns  "
                    f'notes="{notes[:60]}…"'
                )

    print(f"\nDone: {done}/{total} fixtures written to {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic AgeBand evaluation fixtures via LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--band", nargs="+", choices=list(BANDS),
        default=None, metavar="BAND",
        help="Age band(s) to generate for (default: all three)",
    )
    p.add_argument(
        "--difficulty", nargs="+", choices=list(DIFFICULTIES),
        default=None, metavar="DIFF",
        help="Difficulty tier(s) to generate (default: all three)",
    )
    p.add_argument(
        "--count", type=int, default=5,
        help="Fixtures per (band, difficulty) pair (default: 5)",
    )
    p.add_argument(
        "--turn-count-min", type=int, default=3,
        help="Minimum turns per transcript (default: 3)",
    )
    p.add_argument(
        "--turn-count-max", type=int, default=8,
        help="Maximum turns per transcript (default: 8)",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    p.add_argument(
        "--all", dest="all_combos", action="store_true",
        help="Generate --count samples for ALL 9 band × difficulty combinations",
    )
    p.add_argument(
        "--output-dir", type=Path, default=_FIXTURE_DIR,
        metavar="DIR",
        help=f"Fixture output directory (default: {_FIXTURE_DIR})",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    _, model, _ = _generator_endpoint()
    if not model:
        sys.exit(
            "Error: GENERATOR_MODEL env var is required.\n"
            "Example: export GENERATOR_MODEL=llama3.1:8b"
        )

    if args.all_combos:
        bands = list(BANDS)
        difficulties = list(DIFFICULTIES)
    else:
        bands = args.band or list(BANDS)
        difficulties = args.difficulty or list(DIFFICULTIES)

    asyncio.run(generate_all(
        bands=bands,
        difficulties=difficulties,
        count=args.count,
        turn_count_min=args.turn_count_min,
        turn_count_max=args.turn_count_max,
        seed=args.seed,
        output_dir=args.output_dir,
    ))


if __name__ == "__main__":
    main()
