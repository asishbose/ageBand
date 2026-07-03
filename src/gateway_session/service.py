"""GatewaySessionService (M1) — TurnEvent intake and session lifecycle."""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandContext, TurnEvent
from src.contracts.protocols import IGateway
from src.gateway_session.filter import is_user_turn
from src.gateway_session.session_store import _session_store

logger = logging.getLogger(__name__)


class GatewaySessionService:
    """Implements IGateway.

    Ingest a TurnEvent: get-or-create the session, increment turn_count for
    user turns, and return the current AgeBandContext.
    Non-user turns return the existing context unchanged.
    """

    async def ingest(self, turn: TurnEvent) -> AgeBandContext:
        """Get-or-create session context; increment turn_count for user turns."""
        ctx = _session_store.get(turn.session_id)

        if ctx is None:
            ctx = _session_store.create(turn.session_id)

        if not is_user_turn(turn):
            logger.debug("non_user_turn skipped session=%s", turn.session_id)
            return ctx

        updated = ctx.model_copy(update={"turn_count": ctx.turn_count + 1})
        _session_store.update(turn.session_id, updated)
        logger.info(
            "turn_ingested session=%s turn_count=%d",
            turn.session_id,
            updated.turn_count,
        )
        return updated


# Verify protocol satisfaction at import time (fail closed).
assert isinstance(GatewaySessionService(), IGateway), (
    "GatewaySessionService must satisfy IGateway protocol"
)
