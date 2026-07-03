"""Minimal FastAPI application — exposes the AgeBand agent as an OpenAI-compatible
HTTP endpoint for the UI and tinyagent to call.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.contracts.models import TurnEvent, safety_posture
from src.orchestration.runner import OrchestrationService

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/turn")
async def process_turn(req: TurnRequest) -> dict[str, Any]:
    """Process one user turn and return the resulting safety_posture."""
    assert _service is not None, "Service not initialised"
    turn = TurnEvent(
        session_id=req.session_id,
        turn_text=req.turn_text,
        turn_number=req.turn_number,
    )
    posture = await _service.run_turn(turn)
    return {"posture": posture.model_dump()}


@app.exception_handler(Exception)
async def _global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_server_error"})
