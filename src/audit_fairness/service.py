"""AuditFairnessService (M8) — ephemeral decision trace adapter."""

from __future__ import annotations

import logging

from src.audit_fairness.trace import _trace
from src.contracts.protocols import IAudit

logger = logging.getLogger(__name__)


class AuditFairnessService:
    """Implements IAudit.

    Lean build: records events in-process only (EphemeralTrace).
    Future: swap _trace for a durable adapter without touching callers.
    """

    def record(
        self,
        session_id: str,
        action: str,
        payload: dict[str, object],
    ) -> None:
        """Record a decision event in the ephemeral trace."""
        _trace.append({"session_id": session_id, "action": action, **payload})
        logger.info("audit_record session=%s action=%s", session_id, action)


# Verify protocol satisfaction at import time (fail closed).
assert isinstance(AuditFairnessService(), IAudit), (
    "AuditFairnessService must satisfy IAudit protocol"
)
