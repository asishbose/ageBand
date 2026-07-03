"""tinyagent / openai-agents function_tool for confirmed-band persistence."""

from __future__ import annotations

from agents import function_tool  # type: ignore[import-not-found]

from src.stepup_verification.persistence import persist_confirmed


@function_tool  # type: ignore[misc]
def persist_confirmed_tool(session_id: str, band: str, confirmed: bool) -> str:
    """Persist a confirmed age band.

    confirmed MUST be True. Returns '{"ok": true}' on success.
    Raises PermissionError if confirmed is False.
    """
    persist_confirmed(session_id, band, confirmed)
    return '{"ok": true}'
