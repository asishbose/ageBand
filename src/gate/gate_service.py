"""Deterministic gate service (M1.5).

Decides whether a session needs re-analysis or can reuse its current posture.
No LLM calls; no external I/O.
"""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandContext, GateResult
from src.contracts.protocols import IGate
from src.gate import config

logger = logging.getLogger(__name__)


class GateService:
    """Cheap deterministic tripwire — implements IGate."""

    def check(self, ctx: AgeBandContext) -> GateResult:  # noqa: D102
        result = self._evaluate(ctx)
        logger.info(
            "gate_check session=%s action=%s reason=%s",
            ctx.session_id,
            result.action,
            result.reason,
        )
        return result

    def _evaluate(self, ctx: AgeBandContext) -> GateResult:
        if ctx.settled:
            return GateResult(action="reuse_posture", reason="settled_session")

        if ctx.confidence >= config.CONFIDENCE_REUSE_THRESHOLD:
            return GateResult(action="reuse_posture", reason="high_confidence")

        # Only short-circuit for insufficient data if there is already a posture to reuse.
        # On first turn (no posture), we must always analyze — evidence-gathering starts immediately.
        if ctx.turn_count < config.MIN_TURNS_FOR_ANALYSIS and ctx.posture is not None:
            return GateResult(action="reuse_posture", reason="insufficient_data")

        return GateResult(action="analyze", reason="proceed")


# Verify GateService satisfies IGate at import time (fail closed).
assert isinstance(GateService(), IGate), "GateService must satisfy IGate protocol"
