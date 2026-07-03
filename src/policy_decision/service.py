"""PolicyDecisionService — M5 implementation of IPolicyDecision."""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandEstimate, Decision
from src.contracts.protocols import IPolicyDecision
from src.policy_decision import table as _table

logger = logging.getLogger(__name__)


class PolicyDecisionService:
    """Pure-Python policy engine; no LLM interaction."""

    def decide(self, estimate: AgeBandEstimate, confidence: float) -> Decision:
        """Map band + confidence to a safety Decision via the deterministic table."""
        decision = _table.lookup(estimate.band, confidence)
        logger.info(
            "policy_decide band=%s confidence=%.3f → action=%s posture=%s",
            estimate.band,
            confidence,
            decision.action,
            decision.posture_level,
        )
        return decision


# Runtime-checkable assertion: class satisfies the protocol.
assert isinstance(PolicyDecisionService(), IPolicyDecision)
