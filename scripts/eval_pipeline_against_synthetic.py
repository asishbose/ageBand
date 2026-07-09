#!/usr/bin/env python3
"""Evaluate the AgeBand pipeline against synthetic chat fixtures.

Replays each fixture in tests/fixtures/synthetic/ turn-by-turn through the
REAL production pipeline (gate → signal_extraction → evidence_fabric →
ageband_inference → policy_decision), then computes:

  - A confusion matrix (band × band counts)
  - Precision / recall / F1 per band
  - False-positive rate broken down by difficulty tier
  - Evasion-flag raise rate (how often the pipeline correctly flagged evasion)

Writes a timestamped JSON report to scripts/eval_results/<timestamp>.json
AND prints a human-readable summary table to stdout.

The eval model (EVAL_MODEL) is deliberately separate from the generator
(GENERATOR_MODEL): same model for both would let the evaluator recognise its
own writing style, inflating accuracy.

Usage:
    EVAL_API_BASE=http://localhost:8001/v1 \\
    EVAL_MODEL=Qwen/Qwen2.5-7B-Instruct \\
        python scripts/eval_pipeline_against_synthetic.py

    # Filter to a specific band / difficulty:
    EVAL_API_BASE=http://localhost:8001/v1 \\
    EVAL_MODEL=Qwen/Qwen2.5-7B-Instruct \\
        python scripts/eval_pipeline_against_synthetic.py \\
        --band child teen --difficulty clear evasive

Environment:
    EVAL_API_BASE        Base URL for the eval/production model endpoint.
                         Mapped to LOCAL_API_BASE for the pipeline.
                         (default: value of LOCAL_API_BASE)
    EVAL_MODEL           Model ID used by the pipeline during eval.
                         Mapped to LOCAL_MODEL for the pipeline.
                         (required)
    EVAL_API_KEY         Bearer token (default: value of LOCAL_API_KEY or EMPTY)
    EVAL_SETTLE_CONFIDENCE  Confidence threshold to count a band as settled
                         (default: 0.6)
    SKIP_AMD_CHECK       Automatically set to 'true' — skips vLLM startup check.

This script is NOT part of pytest/CI — it calls real LLM endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Must be set before importing anything that reads these env vars.
os.environ.setdefault("SKIP_AMD_CHECK", "true")

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "synthetic"
_RESULTS_DIR = Path(__file__).parent / "eval_results"

BANDS = ["child", "teen", "adult"]
SETTLE_CONFIDENCE = float(os.environ.get("EVAL_SETTLE_CONFIDENCE", "0.6"))


# ---------------------------------------------------------------------------
# Environment setup — map EVAL_* → LOCAL_* before importing the pipeline
# ---------------------------------------------------------------------------

def _configure_eval_env() -> tuple[str, str]:
    """Point the pipeline's env vars at the eval endpoint; return (model, mode)."""
    eval_base = os.environ.get("EVAL_API_BASE", "")
    eval_model = os.environ.get("EVAL_MODEL", "")
    eval_key = os.environ.get("EVAL_API_KEY", "")

    if not eval_model:
        sys.exit(
            "Error: EVAL_MODEL env var is required.\n"
            "Example: export EVAL_MODEL=Qwen/Qwen2.5-7B-Instruct\n\n"
            "Do NOT fall back to the offline deterministic estimator here — "
            "this harness is designed to test the LLM inference path. "
            "Set EVAL_MODEL and EVAL_API_BASE, then re-run."
        )

    if eval_base:
        os.environ["LOCAL_API_BASE"] = eval_base
    if eval_key:
        os.environ["LOCAL_API_KEY"] = eval_key
    os.environ["LOCAL_MODEL"] = eval_model

    # Force LLM path — fixtures are designed for the LLM estimator, not the
    # offline rule_estimator.  Offline mode would give artificially clean
    # results on carefully-crafted lexicon-keyword transcripts.
    os.environ["AGEBAND_INFERENCE_MODE"] = "llm"

    return eval_model, "llm"


# NOTE: env is configured inside main()/run_eval (via _configure_eval_env), NOT
# at import time — importing this module must be side-effect-free so the API
# process can reuse evaluate_fixtures() without _configure_eval_env's sys.exit.
from src.audit_fairness.service import AuditFairnessService  # noqa: E402
from src.contracts.models import TurnEvent  # noqa: E402
from src.orchestration.runner import OrchestrationService  # noqa: E402


# ---------------------------------------------------------------------------
# Pipeline replay
# ---------------------------------------------------------------------------

async def replay_fixture(
    fixture: dict[str, Any],
    service: OrchestrationService,
    audit: AuditFairnessService,
) -> dict[str, Any]:
    """Replay one fixture through the pipeline; return a per-fixture result dict.

    Each fixture gets a unique UUID session so evidence never bleeds between
    fixtures even when sharing a single OrchestrationService instance.
    """
    session_id = f"eval-{uuid.uuid4().hex[:12]}"
    ground_truth: str = fixture["band"]
    difficulty: str = fixture.get("difficulty", "clear")
    raw_turns: list[Any] = fixture.get("turns", [])

    # Fixtures store turns as plain strings; legacy dicts are also handled.
    def _turn_text(t: Any) -> str:
        if isinstance(t, str):
            return t.strip()
        if isinstance(t, dict):
            return str(t.get("text") or t.get("content") or "").strip()
        return ""

    predicted_band = "unknown"
    final_confidence = 0.0
    evasion_flag_raised = False
    turns_to_settle: int | None = None  # 1-indexed first settled turn

    for i, raw_turn in enumerate(raw_turns):
        text = _turn_text(raw_turn)
        if not text:
            continue

        event = TurnEvent(
            session_id=session_id,
            turn_text=text,
            turn_number=i,
        )
        state: dict[str, Any] = await service.run_turn_verbose(event)

        band: str = str(state.get("band", "unknown"))
        confidence = float(state.get("confidence", 0.0))

        # Track if evasion_flag was ever raised across any turn.
        if state.get("evasion_flag", False):
            evasion_flag_raised = True

        # First turn where band is definite and confident enough = settled.
        if (
            turns_to_settle is None
            and band != "unknown"
            and confidence >= SETTLE_CONFIDENCE
        ):
            turns_to_settle = i + 1  # 1-indexed

        predicted_band = band
        final_confidence = confidence

    settled = predicted_band != "unknown" and final_confidence >= SETTLE_CONFIDENCE
    correct = predicted_band == ground_truth

    result: dict[str, Any] = {
        "session_id": session_id,
        "ground_truth": ground_truth,
        "predicted": predicted_band,
        "confidence": round(final_confidence, 4),
        "difficulty": difficulty,
        "turns_to_settle": turns_to_settle,
        "evasion_flag_raised": evasion_flag_raised,
        "settled": settled,
        "correct": correct,
        "generation_model": fixture.get("generation_model", ""),
        "notes": fixture.get("notes", ""),
    }

    # Feed into the audit trace using the existing EphemeralTrace shape:
    # {session_id, action, **payload}
    audit.record(session_id, "eval_result", {
        "ground_truth": ground_truth,
        "predicted": predicted_band,
        "confidence": round(final_confidence, 4),
        "difficulty": difficulty,
        "turns_to_settle": turns_to_settle,
        "evasion_flag_raised": evasion_flag_raised,
        "settled": settled,
        "correct": correct,
    })

    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute confusion matrix, per-band P/R/F1, and per-difficulty error rates."""
    pred_cols = BANDS + ["unknown"]

    # Confusion matrix: rows = ground truth, cols = predicted.
    conf_matrix: dict[str, dict[str, int]] = {
        b: {p: 0 for p in pred_cols} for b in BANDS
    }
    for r in results:
        gt: str = r["ground_truth"]
        pred: str = r["predicted"]
        if gt in conf_matrix:
            col = pred if pred in conf_matrix[gt] else "unknown"
            conf_matrix[gt][col] += 1

    # Per-band precision / recall / F1.
    per_band: dict[str, dict[str, float]] = {}
    for band in BANDS:
        tp = conf_matrix[band].get(band, 0)
        fp = sum(conf_matrix[b].get(band, 0) for b in BANDS if b != band)
        fn = sum(conf_matrix[band].get(p, 0) for p in pred_cols if p != band)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        per_band[band] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    # Error / unsettled / evasion-flag rates by difficulty tier.
    by_diff: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0, "incorrect": 0, "unsettled": 0, "evasion_flagged": 0,
        }
    )
    for r in results:
        d: str = r["difficulty"]
        by_diff[d]["total"] += 1
        if not r["correct"]:
            by_diff[d]["incorrect"] += 1
        if not r["settled"]:
            by_diff[d]["unsettled"] += 1
        if r.get("evasion_flag_raised"):
            by_diff[d]["evasion_flagged"] += 1

    for d in by_diff:
        n = by_diff[d]["total"]
        by_diff[d]["error_rate"] = round(by_diff[d]["incorrect"] / n, 3) if n else 0.0
        by_diff[d]["unsettled_rate"] = round(by_diff[d]["unsettled"] / n, 3) if n else 0.0
        by_diff[d]["evasion_flag_rate"] = (
            round(by_diff[d]["evasion_flagged"] / n, 3) if n else 0.0
        )

    total = len(results)
    overall_accuracy = (
        round(sum(1 for r in results if r["correct"]) / total, 3) if total else 0.0
    )
    settled_rate = (
        round(sum(1 for r in results if r["settled"]) / total, 3) if total else 0.0
    )

    return {
        "confusion_matrix": conf_matrix,
        "per_band": per_band,
        "by_difficulty": dict(by_diff),
        "overall_accuracy": overall_accuracy,
        "total_samples": total,
        "settled_rate": settled_rate,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def print_report(
    metrics: dict[str, Any],
    eval_model: str,
    inference_mode: str,
    report_path: Path,
) -> None:
    """Render a plain-text summary table to stdout."""
    cm = metrics["confusion_matrix"]
    pb = metrics["per_band"]
    diff = metrics["by_difficulty"]
    pred_cols = BANDS + ["unknown"]

    col_w = 11
    row_w = 10
    sep = "=" * 68

    print()
    print(sep)
    print("  AgeBand Synthetic Evaluation Report")
    print(f"  Eval model     : {eval_model}")
    print(f"  Inference mode : {inference_mode}")
    print(f"  Samples        : {metrics['total_samples']}")
    print(f"  Accuracy       : {metrics['overall_accuracy']:.1%}")
    print(f"  Settled rate   : {metrics['settled_rate']:.1%}")
    print(f"  Settle thresh  : {SETTLE_CONFIDENCE}")
    print(sep)

    # Confusion matrix
    print()
    print("Confusion matrix  (rows = ground truth, cols = predicted)")
    header = f"{'':>{row_w}}" + "".join(f"{p:>{col_w}}" for p in pred_cols)
    print(header)
    print("-" * len(header))
    for gt in BANDS:
        row = f"{gt:>{row_w}}"
        for pred in pred_cols:
            row += f"{cm.get(gt, {}).get(pred, 0):>{col_w}}"
        print(row)

    # Per-band P/R/F1
    print()
    print("Per-band metrics")
    print(f"  {'band':<10}  {'precision':>10}  {'recall':>8}  {'f1':>8}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}")
    macro_p = macro_r = macro_f = 0.0
    for band in BANDS:
        m = pb.get(band, {})
        p_, r_, f_ = m.get("precision", 0.0), m.get("recall", 0.0), m.get("f1", 0.0)
        print(f"  {band:<10}  {p_:>10.3f}  {r_:>8.3f}  {f_:>8.3f}")
        macro_p += p_; macro_r += r_; macro_f += f_
    n_b = len(BANDS)
    print(
        f"  {'macro avg':<10}  {macro_p/n_b:>10.3f}  "
        f"{macro_r/n_b:>8.3f}  {macro_f/n_b:>8.3f}"
    )

    # By-difficulty breakdown
    if diff:
        print()
        print("By difficulty tier")
        print(
            f"  {'difficulty':<12}  {'n':>5}  "
            f"{'error%':>8}  {'unsettled%':>11}  {'evasion_flag%':>14}"
        )
        print(
            f"  {'-'*12}  {'-'*5}  "
            f"{'-'*8}  {'-'*11}  {'-'*14}"
        )
        for d, stats in sorted(diff.items()):
            print(
                f"  {d:<12}  {stats['total']:>5}  "
                f"{stats['error_rate']:>8.1%}  "
                f"{stats['unsettled_rate']:>11.1%}  "
                f"{stats['evasion_flag_rate']:>14.1%}"
            )

    print()
    print(sep)
    print(f"\nFull report → {report_path}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def evaluate_fixtures(
    service: OrchestrationService,
    audit: AuditFairnessService,
    band_filter: list[str] | None = None,
    difficulty_filter: list[str] | None = None,
    fixture_dir: Path = _FIXTURE_DIR,
    eval_model: str | None = None,
    progress: "Callable[[Path, dict[str, Any]], None] | None" = None,
) -> dict[str, Any]:
    """Replay the synthetic fixtures via *service* and return the report dict.

    Side-effect-free w.r.t. process control: no sys.exit, no printing, no disk
    write — so it is safe to call from a long-running API process (``/v1/eval``)
    as well as the CLI. Raises RuntimeError when no fixtures are found/matched or
    all fail; the caller decides how to surface that. ``progress`` is an optional
    per-fixture callback (used by the CLI to stream ✓/✗ lines).
    """
    from src.contracts.runtime import use_llm

    model = eval_model or os.environ.get("LOCAL_MODEL") or os.environ.get("EVAL_MODEL", "")
    mode = "llm" if use_llm() else "deterministic"

    all_files = sorted(fixture_dir.glob("*.json"))
    if not all_files:
        raise RuntimeError(
            f"No fixtures found in {fixture_dir}. "
            "Run  python scripts/generate_synthetic_chats.py  first."
        )

    filtered: list[tuple[Path, dict[str, Any]]] = []
    for fp in all_files:
        data: dict[str, Any] = json.loads(fp.read_text())
        if band_filter and data.get("band") not in band_filter:
            continue
        if difficulty_filter and data.get("difficulty") not in difficulty_filter:
            continue
        filtered.append((fp, data))

    if not filtered:
        raise RuntimeError("No fixtures matched the requested band / difficulty filters.")

    results: list[dict[str, Any]] = []
    for fp, fixture in filtered:
        result = await replay_fixture(fixture, service, audit)
        results.append(result)
        if progress is not None:
            progress(fp, result)

    if not results:
        raise RuntimeError("All fixtures failed to evaluate.")

    return {
        "eval_model": model,
        "inference_mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settle_confidence_threshold": SETTLE_CONFIDENCE,
        "metrics": compute_metrics(results),
        "per_sample": results,
    }


async def run_eval(
    fixture_dir: Path,
    band_filter: list[str] | None,
    difficulty_filter: list[str] | None,
) -> None:
    eval_model, inference_mode = _configure_eval_env()
    service = OrchestrationService()
    audit = AuditFairnessService()

    print(
        f"\nEvaluating fixtures  "
        f"[EVAL_MODEL={eval_model!r}  mode={inference_mode}] …\n"
    )

    def _progress(fp: Path, result: dict[str, Any]) -> None:
        tick = "✓" if result["correct"] else "✗"
        ev = " [evasion]" if result["evasion_flag_raised"] else ""
        print(
            f"  {fp.name:<45} {tick}  gt={result['ground_truth']:<6} "
            f"pred={result['predicted']:<8} conf={result['confidence']:.2f}{ev}"
        )

    try:
        report = await evaluate_fixtures(
            service, audit, band_filter, difficulty_filter,
            fixture_dir=fixture_dir, eval_model=eval_model, progress=_progress,
        )
    except RuntimeError as exc:
        sys.exit(str(exc))

    # Write timestamped report.
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = _RESULTS_DIR / f"{ts}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print_report(report["metrics"], eval_model, inference_mode, report_path)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate AgeBand pipeline against synthetic chat fixtures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--fixtures", type=Path, default=_FIXTURE_DIR, metavar="DIR",
        help=f"Fixture directory (default: {_FIXTURE_DIR})",
    )
    p.add_argument(
        "--band", nargs="+", choices=BANDS, default=None, metavar="BAND",
        help="Only evaluate these bands",
    )
    p.add_argument(
        "--difficulty", nargs="+",
        choices=["clear", "ambiguous", "evasive"],
        default=None, metavar="DIFF",
        help="Only evaluate these difficulty tiers",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(run_eval(
        fixture_dir=args.fixtures,
        band_filter=args.band,
        difficulty_filter=args.difficulty,
    ))


if __name__ == "__main__":
    main()
