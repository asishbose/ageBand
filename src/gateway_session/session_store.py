"""In-memory session store for gateway_session (M1).

Ephemeral by design — only explicitly CONFIRMED ages may ever be persisted
(handled by stepup_verification, M7). Session state here is turn-scoped only.
"""

from __future__ import annotations

import logging
from typing import Literal

from src.contracts.models import AgeBandContext

logger = logging.getLogger(__name__)

_INITIAL_BAND: Literal["unknown"] = "unknown"
_INITIAL_CONFIDENCE = 0.0


class SessionStore:
    """In-memory store mapping session_id → AgeBandContext."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgeBandContext] = {}

    def get(self, session_id: str) -> AgeBandContext | None:
        """Return the context for a session, or None if not found."""
        return self._sessions.get(session_id)

    def create(self, session_id: str) -> AgeBandContext:
        """Initialise a new session with default values and store it."""
        ctx = AgeBandContext(
            session_id=session_id,
            current_band=_INITIAL_BAND,
            confidence=_INITIAL_CONFIDENCE,
            settled=False,
            turn_count=0,
        )
        self._sessions[session_id] = ctx
        logger.info("session_created session=%s", session_id)
        return ctx

    def update(self, session_id: str, ctx: AgeBandContext) -> None:
        """Overwrite the stored context for a session."""
        self._sessions[session_id] = ctx
        logger.debug("session_updated session=%s", session_id)

    def clear(self, session_id: str) -> None:
        """Remove a session from the store. For test teardown only."""
        self._sessions.pop(session_id, None)


# Module-level singleton — all services share one store per process.
_session_store = SessionStore()
