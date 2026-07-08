"""tinyagent / openai-agents function_tool wrapper for policy_decide."""

from __future__ import annotations

from agents import function_tool  # openai-agents SDK

from src.contracts.models import AgeBandEstimate
from src.policy_decision.service import PolicyDecisionService


@function_tool
def policy_decide(estimate_json: str, confidence: float) -> str:
    """Deterministic policy decision.

    Input: AgeBandEstimate as JSON, plus confidence float [0, 1].
    Output: Decision as JSON.
    """
    estimate = AgeBandEstimate.model_validate_json(estimate_json)
    decision = PolicyDecisionService().decide(estimate, confidence)
    return decision.model_dump_json()
