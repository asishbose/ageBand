"""tinyagent / openai-agents function_tool wrapper for deterministic reading-level computation."""

from __future__ import annotations

import json

from agents import function_tool  # openai-agents SDK


@function_tool
def compute_reading_level_tool(text: str) -> str:
    """Compute reading level for text.

    Input:
        text: The user turn text to score.
    Output:
        JSON object {"reading_level": float} where float is in [0.0, 1.0].
        Higher = harder / more adult-like text.
    """
    from src.signal_extraction.reading_level import compute_reading_level

    return json.dumps({"reading_level": compute_reading_level(text)})
