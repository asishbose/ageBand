"""EnforcementService — M6 implementation of IEnforcement."""

from __future__ import annotations

import logging

from src.contracts.models import Decision, safety_posture
from src.contracts.protocols import IEnforcement
from src.enforcement.posture_map import build_posture

logger = logging.getLogger(__name__)


class EnforcementService:
    """Emits safety_posture from a Decision.

    Does NOT touch the host model or reply path — the host is the enforcer.
    """

    def emit(self, decision: Decision) -> safety_posture:
        """Build and return the safety_posture for this decision."""
        posture = build_posture(decision)
        logger.info(
            "enforcement action=%s → posture_level=%s flags=%s",
            decision.action,
            posture.level,
            posture.flags,
        )
        return posture


# Runtime-checkable assertion: class satisfies the protocol.
assert isinstance(EnforcementService(), IEnforcement)
