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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    """
    assert _service is not None, "Service not initialised"
    from src.roster import build_roster

    if not export or "messages" not in export:
        export = json.loads(_SAMPLE_EXPORT.read_text())
    rows = await build_roster(export, _service)
    return {"rows": rows, "user_count": len(rows)}


@app.exception_handler(Exception)
async def _global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_server_error"})
