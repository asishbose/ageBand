"""Minimal FastAPI application — exposes the AgeBand agent as an OpenAI-compatible
HTTP endpoint for the UI and tinyagent to call.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.contracts.models import TurnEvent
from src.orchestration.runner import OrchestrationService
from src.stepup_verification.persistence import persist_confirmed

logger = logging.getLogger(__name__)

_service: OrchestrationService | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: verify AMD endpoint; Shutdown: nothing to clean up."""
    global _service

    skip_amd_check = os.environ.get("SKIP_AMD_CHECK", "").lower() in ("1", "true", "yes")
    if not skip_amd_check:
        from src.orchestration.amd_check import verify_amd_endpoint
        try:
            verify_amd_endpoint()
        except RuntimeError as exc:
            logger.warning("AMD endpoint check failed (continuing in degraded mode): %s", exc)

    _service = OrchestrationService()
    logger.info("AgeBand service started")
    yield
    logger.info("AgeBand service stopped")


app = FastAPI(
    title="AgeBand Agent Service",
    description="Passive age-band inference — emits safety_posture per turn.",
    version="1.0.0",
    lifespan=_lifespan,
)


class TurnRequest(BaseModel):
    session_id: str
    turn_text: str
    turn_number: int = 0


class ConfirmRequest(BaseModel):
    session_id: str
    band: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible request shape used by the UI's agentClient."""

    model: str = "ageband"
    messages: list[ChatMessage]
    user: str = "anonymous"
    stream: bool = False


class EvalRequest(BaseModel):
    """Optional filters for the /v1/eval accuracy run (defaults = all 15 fixtures)."""

    band: list[str] | None = None
    difficulty: list[str] | None = None


class BenchmarkRequest(BaseModel):
    """Parameters for the /v1/benchmark per-turn latency + throughput sweep."""

    concurrency: list[int] = [1, 5, 10]
    samples: int = 20
    gpu_hourly_cost: float = 1.99


@app.get("/health")
async def health() -> dict[str, object]:
    """Liveness check. Includes AMD telemetry when running on a GPU endpoint.

    The ``telemetry`` block is additive — existing callers checking only
    ``status`` are unaffected. When running in deterministic/offline mode
    or without an AMD GPU, ``telemetry.available`` is False and all GPU
    fields show "unavailable" / "N/A" — never raises, never fabricates.
    """
    from src.orchestration.amd_check import collect_amd_telemetry
    return {"status": "ok", "telemetry": collect_amd_telemetry()}


@app.post("/v1/turn")
async def process_turn(req: TurnRequest) -> dict[str, Any]:
    """Process one user turn; return the full session state (posture + signal)."""
    assert _service is not None, "Service not initialised"
    turn = TurnEvent(
        session_id=req.session_id,
        turn_text=req.turn_text,
        turn_number=req.turn_number,
    )
    state = await _service.run_turn_verbose(turn)
    # Keep the legacy "posture" key for back-compat with existing callers.
    return {"posture": state["posture"], **state}


@app.post("/v1/confirm")
async def confirm_age(req: ConfirmRequest) -> dict[str, Any]:
    """Persist an explicitly CONFIRMED age band; overrides inference next turn."""
    persist_confirmed(req.session_id, req.band, confirmed=True)
    return {"ok": True, "session_id": req.session_id, "band": req.band}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
    """OpenAI-compatible endpoint the UI calls.

    Runs the last user message through the pipeline and returns the AgeBand
    SessionState as JSON in ``choices[0].message.content`` (what agentClient.ts
    parses). ``user`` carries the session id.
    """
    assert _service is not None, "Service not initialised"
    user_msgs = [m for m in req.messages if m.role == "user"]
    text = user_msgs[-1].content if user_msgs else ""
    turn = TurnEvent(session_id=req.user, turn_text=text, turn_number=0)
    state = await _service.run_turn_verbose(turn)
    return {
        "id": f"ageband-{req.user}",
        "object": "chat.completion",
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(state)},
                "finish_reason": "stop",
            }
        ],
    }


_SAMPLE_EXPORT = Path(__file__).resolve().parent.parent / "roster" / "sample_export.json"


@app.post("/v1/roster")
async def roster(export: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:  # noqa: B008
    """Build a per-user age-band roster from a DiscordChatExporter JSON export.

    POST the export JSON as the body; if omitted (or missing "messages"), the
    bundled synthetic sample is used. Returns one row per non-bot author.

    INTENDED USE — consent boundary
    --------------------------------
    This endpoint replays message text through the AgeBand age-band inference
    pipeline and returns inferred age bands per author. It is intended ONLY for:
      • A channel you own or operate (e.g. a customer-service bot's own log)
      • An export of consenting participants (e.g. a research study with IRB)
      • Fully synthetic / anonymised data (e.g. the bundled sample_export.json)

    DO NOT upload real chat exports of users who have not consented to age-band
    inference. Inferring age from private non-consenting chat is precisely what
    AgeBand is designed to avoid — using this endpoint for that purpose
    contradicts the system's stated ethics and may violate applicable privacy law.

    The endpoint does not persist uploaded exports to disk; all processing is
    in-memory and ephemeral. Session state is cleared before and after each
    user's replay pass.
    """
    assert _service is not None, "Service not initialised"
    from src.roster import build_roster

    if not export or "messages" not in export:
        export = json.loads(_SAMPLE_EXPORT.read_text())
    rows = await build_roster(export, _service)
    return {"rows": rows, "user_count": len(rows)}


# Sample turns for the throughput benchmark — a mix of child/teen/adult signals
# so each turn exercises the full extract → estimate → policy pipeline.
_BENCH_TURNS = [
    "I just refinanced my mortgage and reviewed the Q3 earnings report.",
    "omg the homework tonight is so much, my teacher is being unfair",
    "we had recess today and i lost a tooth, it was so cool!",
    "The quarterly strategy review ran long at the office again.",
    "my mom said i have to finish my chores before i can play the game",
]


@app.post("/v1/eval")
async def run_eval_endpoint(
    req: EvalRequest | None = Body(default=None),  # noqa: B008
) -> dict[str, Any]:
    """Run the synthetic accuracy eval (15 bundled fixtures) in-process.

    Reuses ``evaluate_fixtures`` from the eval script against the shared service.
    Returns accuracy, settled rate, confusion matrix, and per-band metrics.
    """
    assert _service is not None, "Service not initialised"
    from scripts.eval_pipeline_against_synthetic import evaluate_fixtures
    from src.audit_fairness.service import AuditFairnessService

    band = req.band if req else None
    difficulty = req.difficulty if req else None
    report = await evaluate_fixtures(
        _service,
        AuditFairnessService(),
        band_filter=band,
        difficulty_filter=difficulty,
    )
    return {
        "eval_model": report["eval_model"],
        "inference_mode": report["inference_mode"],
        "settle_confidence_threshold": report["settle_confidence_threshold"],
        "metrics": report["metrics"],
        "per_sample": report["per_sample"],
    }


@app.post("/v1/benchmark")
async def run_benchmark_endpoint(
    req: BenchmarkRequest | None = Body(default=None),  # noqa: B008
) -> dict[str, Any]:
    """Per-turn latency + throughput sweep driven in-process (fast; not the
    roster benchmark, which times out replaying whole exports).

    For each concurrency level, fires ``samples`` turns through the pipeline via
    asyncio.gather, records p50/p95 latency + success, and derives tok/s from the
    vLLM ``/metrics`` generation-token delta over the sweep and $/1k turns.
    """
    import asyncio
    import statistics
    import time

    from scripts.benchmark_roster import _cost_per_1k_turns
    from src.contracts.models import TurnEvent
    from src.orchestration.amd_check import _scrape_vllm_metrics

    assert _service is not None, "Service not initialised"
    cfg = req or BenchmarkRequest()
    base_url = os.environ.get("LOCAL_API_BASE", "http://localhost:8000/v1")

    async def _one(i: int) -> tuple[float, bool]:
        t0 = time.perf_counter()
        try:
            await _service.run_turn_verbose(
                TurnEvent(
                    session_id=f"bench-{i}",
                    turn_text=_BENCH_TURNS[i % len(_BENCH_TURNS)],
                    turn_number=1,
                )
            )
            return (time.perf_counter() - t0) * 1000.0, True
        except Exception:  # noqa: BLE001 — count as failure, keep sweeping
            return (time.perf_counter() - t0) * 1000.0, False

    rows: list[dict[str, Any]] = []
    idx = 0
    for c in cfg.concurrency:
        conc = max(1, c)
        metrics_before = _scrape_vllm_metrics(base_url)
        t_start = time.perf_counter()
        latencies: list[float] = []
        successes = 0
        remaining = max(1, cfg.samples)
        while remaining > 0:
            batch = min(conc, remaining)
            res = await asyncio.gather(*[_one(idx + j) for j in range(batch)])
            idx += batch
            latencies += [r[0] for r in res]
            successes += sum(1 for r in res if r[1])
            remaining -= batch
        elapsed = time.perf_counter() - t_start
        metrics_after = _scrape_vllm_metrics(base_url)

        p50 = statistics.median(latencies) if latencies else 0.0
        if len(latencies) >= 2:
            p95 = statistics.quantiles(latencies, n=20)[18]
        else:
            p95 = latencies[0] if latencies else 0.0
        d_gen = float(metrics_after.get("gen_tokens_total", 0.0)) - float(
            metrics_before.get("gen_tokens_total", 0.0)
        )
        tok_s = d_gen / elapsed if elapsed > 0 and d_gen > 0 else 0.0
        cost = _cost_per_1k_turns(cfg.gpu_hourly_cost, tok_s)
        rows.append({
            "concurrency": c,
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "success": successes,
            "total": len(latencies),
            "tok_per_sec": round(tok_s, 1),
            "cost_per_1k_turns": round(cost, 4) if cost is not None else None,
        })

    best = max(rows, key=lambda r: r["tok_per_sec"]) if rows else {}
    return {
        "rows": rows,
        "headline": {
            "sessions_per_gpu": best.get("concurrency"),
            "p95_ms": best.get("p95_ms"),
            "tok_per_sec": best.get("tok_per_sec"),
            "cost_per_1k_turns": best.get("cost_per_1k_turns"),
        },
        "gpu_hourly_cost": cfg.gpu_hourly_cost,
    }


@app.exception_handler(Exception)
async def _global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_server_error"})


# ---------------------------------------------------------------------------
# Optional: serve the built UI from this same process (single-origin, single
# port). Enabled by AGEBAND_SERVE_UI=1 when src/ui/dist exists — lets a single
# `uvicorn` on one public port serve both the API and the UI, so the UI's
# root-relative /v1 and /health calls resolve without CORS or a reverse proxy.
# The Helm/nginx deploy path leaves this off (nginx serves the UI separately),
# and this mount is added LAST so the explicit API routes above take precedence.
# ---------------------------------------------------------------------------
if os.environ.get("AGEBAND_SERVE_UI", "").lower() in ("1", "true", "yes"):
    _UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
    if _UI_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
        logger.info("Serving UI from %s at /", _UI_DIST)
    else:
        logger.warning(
            "AGEBAND_SERVE_UI set but %s missing — run `npm run build` in src/ui",
            _UI_DIST,
        )
