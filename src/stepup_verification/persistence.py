"""Confirmed-band persistence for stepup_verification (M7).

INVARIANT: Only explicitly CONFIRMED age bands are ever stored.
Inferred bands MUST NOT be persisted — the confirmed flag enforces this at the
function boundary so callers cannot accidentally bypass the guard.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_confirmed: dict[str, str] = {}  # session_id -> band (module-level singleton)


def persist_confirmed(session_id: str, band: str, confirmed: bool) -> None:
    """Persist an explicitly CONFIRMED age band.

    Raises PermissionError if confirmed is not True.
    NEVER called for inferred bands — confirmed must be True.
    """
    if not confirmed:
        raise PermissionError(
            "persist_confirmed called without confirmed=True. "
            "Inferred bands must never be persisted."
        )
    _confirmed[session_id] = band
    logger.info("persist_confirmed session=%s band=%s", session_id, band)


def get_confirmed(session_id: str) -> str | None:
    """Return the confirmed band for a session, or None if not stored."""
    return _confirmed.get(session_id)


def clear_confirmed(session_id: str) -> None:
    """Remove a session's confirmed band. For test teardown only."""
    _confirmed.pop(session_id, None)
