"""Process-local ephemeral store for EvidenceSummary objects.

Never persisted. One instance per process; tests clear state via `_store.clear()`.
"""

from __future__ import annotations

from src.contracts.models import EvidenceSummary


class EphemeralStore:
    """In-memory dict-backed store; never written to disk or any external sink."""

    def __init__(self) -> None:
        self._data: dict[str, EvidenceSummary] = {}

    def get(self, session_id: str) -> EvidenceSummary | None:
        """Return stored evidence or None if session is unknown."""
        return self._data.get(session_id)

    def set(self, session_id: str, evidence: EvidenceSummary) -> None:
        """Overwrite (or create) the stored evidence for a session."""
        self._data[session_id] = evidence

    def clear(self, session_id: str) -> None:
        """Remove the entry for a session. No-op if it does not exist."""
        self._data.pop(session_id, None)


# Module-level singleton — imported by service.py and used in tests for teardown.
_store = EphemeralStore()
