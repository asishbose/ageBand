"""Multilingual evaluation harness for AgeBand (Phase 1).

Replays multilingual synthetic fixtures through the REAL AgeBand pipeline
and reports per-language accuracy vs. ground truth band labels.

Output format is intentionally parallel to eval_pipeline_against_synthetic.py
so results are comparable across languages and against the English baseline.

Usage:
    # Deterministic path (tests non-English abstention in offline mode):
    AGEBAND_INFERENCE_MODE=deterministic \\
      python scripts/eval_multilang.py

    # LLM path (tests multilingual LLM extraction):
    EVAL_API_BASE=http://localhost:8001/v1 EVAL_MODEL=google/gemma-3-27b-it \\
      python scripts/eval_multilang.py --lang all

    # Specific language:
    EVAL_MODEL=google/gemma-3-4b-it python scripts/eval_multilang.py --lang es

Fixtures:
    tests/fixtures/synthetic_multilang/{lang}/*.json
    Each fixture: {"band": "child|teen|adult|unknown", "language": "XX",
                   "difficulty": "clear|ambiguous|evasive", "turns": [...]}

NOT wired into pytest or CI — calls real endpoints and is an offline analysis tool.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


SUPPORTED_LANGS = ("es", "hi", "fr", "ar", "zh")
FIXTURE_BASE = Path(__file__).parent.parent / "tests" / "fixtures" / "synthetic_multilang"
OUT_DIR = Path(__file__).parent / "eval_results"


def _configure_eval_env() -> str:
    """Set LOCAL_* from EVAL_* vars and force AGEBAND_INFERENCE_MODE.

    Returns the inference mode string for display.
    """
    eval_model = os.environ.get("EVAL_MODEL", "")
    eval_base = os.environ.get("EVAL_API_BASE", "")
    eval_key = os.environ.get("EVAL_API_KEY", "")

    mode = os.environ.get("AGEBAND_INFERENCE_MODE", "")
    if mode == "deterministic":
        return "deterministic"

    if not eval_model:
        print(
            "Info: EVAL_MODEL not set — using deterministic path.\n"
            "Set EVAL_MODEL + EVAL_API_BASE to test the LLM extraction path.",
            file=sys.stderr,
        )
        os.environ["AGEBAND_INFERENCE_MODE"] = "deterministic"
        return "deterministic"

    if eval_base:
        os.environ["LOCAL_API_BASE"] = eval_base
    if eval_key:
        os.environ["LOCAL_API_KEY"] = eval_key
    os.environ["LOCAL_MODEL"] = eval_model
    os.environ["AGEBAND_INFERENCE_MODE"] = "llm"
    return "llm"


def _load_fixtures(langs: list[str]) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for lang in langs:
        lang_dir = FIXTURE_BASE / lang
        if not lang_dir.exists():
            continue
        for fp in sorted(lang_dir.glob("*.json")):
            with fp.open() as f:
                data = json.load(f)
            data["_file"] = str(fp)
            data.setdefault("language", lang)
            fixtures.append(data)
    return fixtures


async def _run_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    from src.contracts.models import TurnEvent
    from src.evidence_fabric.store import _store
    from src.orchestration.runner import OrchestrationService
    from src.stepup_verification.persistence import clear_confirmed

    turns: list[str] = fixture.get("turns", [])
    session_id = f"multilang-{fixture['language']}-{os.urandom(4).hex()}"
    _store.clear(session_id)
    clear_confirmed(session_id)
    svc = OrchestrationService()
    final_state: dict[str, Any] = {}
    for i, text in enumerate(turns, 1):
        final_state = await svc.run_turn_verbose(
            TurnEvent(session_id=session_id, turn_text=text, turn_number=i)
        )
    _store.clear(session_id)
    return {
        "ground_truth": fixture.get("band", "unknown"),
        "predicted": final_state.get("band", "unknown"),
        "confidence": final_state.get("confidence", 0.0),
        "language": fixture.get("language", "?"),
        "difficulty": fixture.get("difficulty", "?"),
        "file": fixture.get("_file", ""),
    }


def _confusion_matrix(
    results: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    bands = ["child", "teen", "adult", "unknown"]
    matrix: dict[str, dict[str, int]] = {b: {b2: 0 for b2 in bands} for b in bands}
    for r in results:
        gt = r["ground_truth"]
        pred = r["predicted"]
        if gt in matrix and pred in matrix:
            matrix[gt][pred] += 1
    return matrix


def _per_band_metrics(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    bands = list(matrix.keys())
    metrics: dict[str, dict[str, float]] = {}
    for band in bands:
        tp = matrix[band][band]
        fp = sum(matrix[b][band] for b in bands if b != band)
        fn = sum(matrix[band][b] for b in bands if b != band)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        metrics[band] = {"precision": precision, "recall": recall, "f1": f1}
    return metrics


def _print_results(
    results: list[dict[str, Any]],
    mode: str,
    langs: list[str],
) -> None:
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_lang[r["language"]].append(r)

    print(f"\n{'AgeBand Multilingual Eval':^60}")
    print(f"{'Mode:':12} {mode}")
    print(f"{'Languages:':12} {', '.join(langs)}")
    print(f"{'Fixtures:':12} {len(results)}")
    print()

    for lang in langs:
        lang_results = by_lang.get(lang, [])
        if not lang_results:
            print(f"  {lang}: no fixtures found")
            continue
        correct = sum(1 for r in lang_results if r["ground_truth"] == r["predicted"])
        acc = correct / len(lang_results) if lang_results else 0.0
        print(f"  {lang.upper()}: {correct}/{len(lang_results)} correct ({acc:.0%})")
        for r in lang_results:
            status = "✓" if r["ground_truth"] == r["predicted"] else "✗"
            print(
                f"    {status} gt={r['ground_truth']:<7} pred={r['predicted']:<7} "
                f"c={r['confidence']:.2f} [{r['difficulty']}]"
            )

    if results:
        print()
        print("Overall confusion matrix (rows=ground_truth, cols=predicted):")
        matrix = _confusion_matrix(results)
        bands = ["child", "teen", "adult", "unknown"]
        header = "         " + "  ".join(f"{b:<7}" for b in bands)
        print(header)
        for gt in bands:
            row = f"  {gt:<7}" + "  ".join(f"{matrix[gt][pred]:<7}" for pred in bands)
            print(row)

        print()
        print("Per-band metrics:")
        metrics = _per_band_metrics(matrix)
        print(f"  {'band':<8} {'precision':>9} {'recall':>7} {'f1':>5}")
        for band, m in metrics.items():
            print(
                f"  {band:<8} {m['precision']:>9.2f} {m['recall']:>7.2f} {m['f1']:>5.2f}"
            )


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lang",
        nargs="+",
        default=list(SUPPORTED_LANGS),
        choices=list(SUPPORTED_LANGS) + ["all"],
        help=f"Languages to evaluate (default: all). Choices: {', '.join(SUPPORTED_LANGS)}",
    )
    args = parser.parse_args()
    langs = list(SUPPORTED_LANGS) if "all" in args.lang else args.lang

    mode = _configure_eval_env()
    fixtures = _load_fixtures(langs)
    if not fixtures:
        print(
            f"No fixtures found under {FIXTURE_BASE}/{{lang}}/ for languages: {langs}\n"
            "Generate them with scripts/generate_synthetic_chats.py --lang XX or\n"
            "add hand-authored fixtures (see tests/fixtures/synthetic_multilang/README).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loaded {len(fixtures)} fixtures across {langs}. Running pipeline...")
    results = []
    for fx in fixtures:
        r = await _run_fixture(fx)
        results.append(r)

    _print_results(results, mode, langs)

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"multilang_{ts}.json"
    report = {
        "timestamp": ts,
        "mode": mode,
        "languages": langs,
        "results": results,
        "confusion_matrix": _confusion_matrix(results),
        "per_band_metrics": _per_band_metrics(_confusion_matrix(results)),
    }
    with out_path.open("w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
