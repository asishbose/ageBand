"""Deterministic gate service (M1.5).

Decides whether a session needs re-analysis or can reuse its current posture.
No LLM calls; no external I/O.
"""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandContext, GateResult
from src.contracts.protocols import IGate
from src.gate import config
from src.signal_extraction import lexicon

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
        would_reuse = (
            ctx.settled or ctx.confidence >= config.CONFIDENCE_REUSE_THRESHOLD
        )
        # Always-on tripwire: even a settled/high-confidence session is re-analysed
        # the moment the current turn contradicts the established band (e.g. a
        # settled "adult" session where the device is handed to a child).
        if would_reuse and self._tripwire_fires(ctx):
            return GateResult(action="analyze", reason="tripwire_contradiction")

        if ctx.settled:
            return GateResult(action="reuse_posture", reason="settled_session")

        if ctx.confidence >= config.CONFIDENCE_REUSE_THRESHOLD:
            return GateResult(action="reuse_posture", reason="high_confidence")

        # Only short-circuit for insufficient data if there is already a posture to reuse.
        # On first turn (no posture), we must always analyze — evidence-gathering starts immediately.
        if ctx.turn_count < config.MIN_TURNS_FOR_ANALYSIS and ctx.posture is not None:
            return GateResult(action="reuse_posture", reason="insufficient_data")

        return GateResult(action="analyze", reason="proceed")

    @staticmethod
    def _tripwire_fires(ctx: AgeBandContext) -> bool:
        """Return True if the current turn contradicts the established band.

        Cheap keyword scan (no LLM) over the current turn text. Fires when a
        settled adult session shows child/teen cues, or a settled child/teen
        session shows adult cues.
        """
        text = ctx.last_turn_text or ""
        if not text:
            return False
        hints = {
            lexicon.band_hint_any(subtype)
            for _t, subtype, _m in lexicon.classify_text(text)
        }
        hints.discard("")
        if not hints:
            return False
        if ctx.current_band == "adult":
            return bool(hints & {"child", "teen"})
        if ctx.current_band in ("child", "teen"):
            return "adult" in hints
        return False


# Verify GateService satisfies IGate at import time (fail closed).
assert isinstance(GateService(), IGate), "GateService must satisfy IGate protocol"
