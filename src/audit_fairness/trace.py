"""Ephemeral in-memory decision trace for audit_fairness (M8).

This is a minimal seam — a no-op for the lean build that can be replaced
with a real backend (e.g. structured log sink, time-series DB) by swapping
the adapter behind IAudit without touching callers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EphemeralTrace:
    """Append-only, session-keyed trace of decision events.

    Stored entirely in process memory; cleared on process restart.
    Only session_id-scoped reads are exposed — no cross-session leakage.
    """

    def __init__(self) -> None:
        self._log: list[dict[str, object]] = []

    def append(self, entry: dict[str, object]) -> None:
        """Append a decision entry to the trace."""
        self._log.append(entry)
        logger.debug("audit_trace_append action=%s", entry.get("action"))

    def get_trace(self, session_id: str) -> list[dict[str, object]]:
        """Return all entries recorded for a given session_id."""
        return [e for e in self._log if e.get("session_id") == session_id]

    def clear(self, session_id: str) -> None:
        """Remove all entries for a session. For test teardown only."""
        self._log = [e for e in self._log if e.get("session_id") != session_id]


# Module-level singleton.
_trace = EphemeralTrace()
