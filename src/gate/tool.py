"""tinyagent / openai-agents function_tool wrapper for the gate check."""

from __future__ import annotations

from agents import function_tool  # type: ignore[import-not-found]  # openai-agents SDK

from src.contracts.models import AgeBandContext
from src.gate.gate_service import GateService


@function_tool  # type: ignore[misc]
def gate_check(ctx_json: str) -> str:
    """Check the gate for a session.

    Input: AgeBandContext as JSON.
    Output: GateResult as JSON.
    """
    ctx = AgeBandContext.model_validate_json(ctx_json)
    result = GateService().check(ctx)
    return result.model_dump_json()
