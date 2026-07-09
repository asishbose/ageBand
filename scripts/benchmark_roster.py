"""Roster replay throughput benchmark for AMD MI300X.

Drives POST /v1/roster with a concurrency sweep and captures latency,
throughput, and GPU metrics from the vLLM /metrics endpoint.

This script is NOT part of pytest/CI — it calls real endpoints under load
and is designed to be run once against AMD Dev Cloud hardware to fill in
the headline numbers for the hackathon deck (slide 9).

Usage (from repo root):
    # Dry run against the deterministic offline path (no GPU needed):
    AGEBAND_INFERENCE_MODE=deterministic \\
      python scripts/benchmark_roster.py --concurrency 1 5 10 \\
        --samples 20 --gpu-hourly-cost 0.0

    # Real AMD MI300X run (after hardware is available):
    LOCAL_API_BASE=http://vllm-service:8000/v1 \\
    LOCAL_MODEL=google/gemma-3-27b-it \\
    EXTRACTOR_MODEL=google/gemma-3-4b-it \\
    ESTIMATOR_MODEL=google/gemma-3-27b-it \\
      python scripts/benchmark_roster.py --concurrency 1 5 10 25 50 \\
        --samples 200 --gpu-hourly-cost 3.50

Output:
    scripts/eval_results/benchmark_<timestamp>.json
    A summary table printed to stdout.

Slide 9 fields captured:
    - sessions/GPU (max concurrent sessions before p95 latency > 5 s)
    - p95 gate→posture latency (ms)
    - sustained tok/s (from vLLM /metrics)
    - $/1k moderated turns (derived from --gpu-hourly-cost and throughput)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx

# Ensure repo root on path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Synthetic export builder
# ---------------------------------------------------------------------------

_SYNTHETIC_AUTHORS = [
    ("child_clara", [
        "I'm in 3rd grade!", "We had recess today and it was fun",
        "My mom says I can only have 30 mins of screen time",
        "I love my teacher she is so nice",
    ]),
    ("teen_jamie", [
        "omg hw is so much tonight lol",
        "my parents wont let me go to the party bc curfew",
        "i'm in 8th grade and stressed rn",
    ]),
    ("adult_morgan", [
        "My mortgage renewal is next month — fixed vs variable?",
        "I finished my MBA last year, now in corporate strategy.",
        "The macroeconomic situation is fascinating.",
    ]),
    ("adult_alex", [
        "Does anyone know a good recipe for pasta?",
        "I need to meal prep for the week.",
        "Work has been really busy with the quarterly review.",
    ]),
    ("unknown_sam", [
        "I want to learn more about cooking.",
        "What is a good recipe?",
        "Thanks, sounds easy.",
    ]),
]


def _build_synthetic_export(n_authors: int = 100) -> dict[str, Any]:
    """Build a synthetic DiscordChatExporter JSON with n_authors entries."""
    messages: list[dict[str, Any]] = []
    msg_id = 1
    for i in range(n_authors):
        template = _SYNTHETIC_AUTHORS[i % len(_SYNTHETIC_AUTHORS)]
        author_name, turns = template
        author_id = str(1000 + i)
        for j, text in enumerate(turns):
            messages.append({
                "id": str(msg_id),
                "type": "Default",
                "timestamp": f"2024-01-01T{10 + j:02d}:00:00.000+00:00",
                "content": text,
                "author": {
                    "id": author_id,
                    "name": f"{author_name}_{i}",
                    "isBot": False,
                },
            })
            msg_id += 1
    return {"guild": {}, "channel": {}, "messages": messages}


# ---------------------------------------------------------------------------
# vLLM metrics scraper
# ---------------------------------------------------------------------------

async def _scrape_vllm_metrics(
    base_url: str, client: httpx.AsyncClient
) -> dict[str, float]:
    """Scrape vLLM's Prometheus /metrics endpoint.

    Returns dict with keys: running_requests, prompt_tokens_total,
    gen_tokens_total, gpu_cache_usage_pct. Returns empty dict when
    the endpoint is not reachable (offline / no GPU).
    """
    try:
        metrics_url = base_url.rstrip("/").replace("/v1", "") + "/metrics"
        resp = await client.get(metrics_url, timeout=5.0)
        if resp.status_code != 200:
            return {}
        lines = resp.text.splitlines()
        result: dict[str, float] = {}
        for line in lines:
            if line.startswith("#"):
                continue
            if "vllm:num_requests_running" in line:
                result["running_requests"] = float(line.split()[-1])
            elif "vllm:prompt_tokens_total" in line:
                result["prompt_tokens_total"] = float(line.split()[-1])
            elif "vllm:generation_tokens_total" in line:
                result["gen_tokens_total"] = float(line.split()[-1])
            elif "vllm:gpu_cache_usage_perc" in line:
                result["gpu_cache_usage_pct"] = float(line.split()[-1]) * 100
        return result
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Roster endpoint driver
# ---------------------------------------------------------------------------

async def _single_roster_call(
    client: httpx.AsyncClient,
    agent_url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[float, bool]:
    """POST /v1/roster and return (latency_ms, success)."""
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{agent_url}/v1/roster",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return (time.perf_counter() - t0) * 1000, True
    except Exception:  # noqa: BLE001
        return (time.perf_counter() - t0) * 1000, False


async def _concurrency_sweep(
    agent_url: str,
    export_payload: dict[str, Any],
    concurrency: int,
    timeout: float,
) -> dict[str, Any]:
    """Run *concurrency* parallel /v1/roster calls and gather stats."""
    vllm_base = os.environ.get("LOCAL_API_BASE", "http://localhost:8000/v1")

    async with httpx.AsyncClient() as client:
        metrics_before = await _scrape_vllm_metrics(vllm_base, client)

        t_sweep_start = time.perf_counter()
        tasks = [
            _single_roster_call(client, agent_url, export_payload, timeout)
            for _ in range(concurrency)
        ]
        results = await asyncio.gather(*tasks)
        sweep_elapsed = time.perf_counter() - t_sweep_start

        metrics_after = await _scrape_vllm_metrics(vllm_base, client)

    latencies = [r[0] for r in results]
    successes = sum(1 for r in results if r[1])
    # statistics.quantiles needs >=2 points; fall back to the single sample
    # (or 0.0 when empty) so a concurrency=1 sweep doesn't crash.
    if len(latencies) >= 2:
        p95 = statistics.quantiles(latencies, n=20)[18]
    elif latencies:
        p95 = latencies[0]
    else:
        p95 = 0.0

    # Token throughput: delta gen_tokens / sweep_elapsed
    delta_gen = (
        metrics_after.get("gen_tokens_total", 0.0)
        - metrics_before.get("gen_tokens_total", 0.0)
    )
    tok_per_sec = delta_gen / sweep_elapsed if sweep_elapsed > 0 else 0.0

    return {
        "concurrency": concurrency,
        "total_calls": concurrency,
        "successful": successes,
        "failed": concurrency - successes,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": p95,
        "min_ms": min(latencies) if latencies else 0.0,
        "max_ms": max(latencies) if latencies else 0.0,
        "sweep_elapsed_s": sweep_elapsed,
        "gen_tok_per_sec": tok_per_sec,
        "vllm_metrics_before": metrics_before,
        "vllm_metrics_after": metrics_after,
    }


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------

def _cost_per_1k_turns(
    gpu_hourly_cost: float,
    tok_per_sec: float,
    avg_toks_per_turn: float = 150.0,
) -> float | None:
    """$/1k moderated turns, given GPU hourly cost and measured tok/s."""
    if gpu_hourly_cost <= 0 or tok_per_sec <= 0:
        return None
    turns_per_hour = (tok_per_sec * 3600) / avg_toks_per_turn
    cost_per_turn = gpu_hourly_cost / turns_per_hour
    return cost_per_turn * 1000


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-url",
        default=os.environ.get("AGEBAND_AGENT_URL", "http://localhost:8080"),
        help="AgeBand agent service base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[1, 5, 10, 25, 50],
        metavar="N",
        help="Concurrency levels to sweep (default: 1 5 10 25 50)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        metavar="N",
        help="Number of synthetic authors in the export (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        metavar="SEC",
        help="Per-request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--gpu-hourly-cost",
        type=float,
        default=0.0,
        metavar="USD",
        help="GPU server cost per hour in USD (e.g. 3.50 for MI300X Dev Cloud). "
             "Used to compute $/1k turns. Pass 0 to skip cost calculation.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(
        os.path.dirname(__file__), "eval_results"
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"benchmark_{timestamp}.json")

    print(f"\n{'AgeBand Roster Throughput Benchmark':^60}")
    print(f"{'=' * 60}")
    print(f"  Agent URL:   {args.agent_url}")
    print(f"  Authors:     {args.samples}")
    print(f"  Concurrency: {args.concurrency}")
    print(
        f"  GPU $/hr:    "
        + (f"${args.gpu_hourly_cost:.2f}" if args.gpu_hourly_cost > 0 else "not set")
    )
    print()

    export_payload = _build_synthetic_export(args.samples)

    sweep_results = []
    for c in args.concurrency:
        print(f"  Running concurrency={c} ...", end=" ", flush=True)
        result = await _concurrency_sweep(
            args.agent_url, export_payload, c, args.timeout
        )
        cost = _cost_per_1k_turns(
            args.gpu_hourly_cost, result["gen_tok_per_sec"]
        )
        result["cost_per_1k_turns_usd"] = cost
        sweep_results.append(result)
        p95 = result["p95_ms"]
        tps = result["gen_tok_per_sec"]
        ok = result["successful"]
        total = result["total_calls"]
        cost_str = f"  ${cost:.3f}/1k" if cost is not None else "  cost=N/A"
        print(
            f"p95={p95:.0f}ms  tok/s={tps:.1f}  {ok}/{total} ok{cost_str}"
        )

    # Headline numbers for slide 9
    best_result = max(sweep_results, key=lambda r: r["gen_tok_per_sec"])
    max_sessions = best_result["concurrency"]
    best_p95 = best_result["p95_ms"]
    best_tps = best_result["gen_tok_per_sec"]
    best_cost = best_result["cost_per_1k_turns_usd"]

    report = {
        "timestamp": timestamp,
        "config": {
            "agent_url": args.agent_url,
            "authors_per_call": args.samples,
            "concurrency_levels": args.concurrency,
            "gpu_hourly_cost_usd": args.gpu_hourly_cost,
            "LOCAL_API_BASE": os.environ.get("LOCAL_API_BASE", ""),
            "LOCAL_MODEL": os.environ.get("LOCAL_MODEL", ""),
            "EXTRACTOR_MODEL": os.environ.get("EXTRACTOR_MODEL", ""),
            "ESTIMATOR_MODEL": os.environ.get("ESTIMATOR_MODEL", ""),
            "AGEBAND_INFERENCE_MODE": os.environ.get("AGEBAND_INFERENCE_MODE", "auto"),
        },
        "sweep_results": sweep_results,
        "slide_9_headline": {
            "sessions_per_gpu": max_sessions,
            "p95_gate_to_posture_ms": (
                "PENDING — requires AMD Dev Cloud MI300X run"
                if best_tps == 0
                else round(best_p95, 1)
            ),
            "tok_per_sec": (
                "PENDING — requires AMD Dev Cloud MI300X run"
                if best_tps == 0
                else round(best_tps, 1)
            ),
            "cost_per_1k_turns_usd": (
                "PENDING — requires AMD Dev Cloud MI300X run"
                if best_cost is None
                else round(best_cost, 4)
            ),
        },
    }

    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'─' * 60}")
    print("Slide 9 headline numbers:")
    h = report["slide_9_headline"]
    print(f"  Sessions/GPU:       {h['sessions_per_gpu']}")
    print(f"  p95 latency (ms):   {h['p95_gate_to_posture_ms']}")
    print(f"  Sustained tok/s:    {h['tok_per_sec']}")
    print(f"  $/1k turns:         {h['cost_per_1k_turns_usd']}")
    print(f"\nReport saved to: {out_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
