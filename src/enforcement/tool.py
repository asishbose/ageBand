"""tinyagent / openai-agents function_tool wrapper for emit_posture."""

from __future__ import annotations

from agents import function_tool  # type: ignore[import-not-found]  # openai-agents SDK

from src.contracts.models import Decision
from src.enforcement.service import EnforcementService


@function_tool  # type: ignore[misc]
def emit_posture(decision_json: str) -> str:
    """Emit safety_posture for a Decision.

    Input: Decision as JSON.
    Output: safety_posture as JSON.
    """
    decision = Decision.model_validate_json(decision_json)
    posture = EnforcementService().emit(decision)
    return posture.model_dump_json()
