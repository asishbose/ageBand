"""tinyagent / openai-agents function_tool wrapper for deterministic confidence computation."""

from __future__ import annotations

import json

from agents import function_tool  # openai-agents SDK

from src.ageband_inference.confidence import compute_confidence
from src.contracts.models import AgeBandEstimate, EvidenceSummary


@function_tool
def compute_confidence_tool(evidence_json: str, estimate_json: str) -> str:
    """Compute deterministic confidence from evidence and an age-band estimate.

    Input:
        evidence_json: EvidenceSummary as JSON.
        estimate_json: AgeBandEstimate as JSON (must NOT contain a confidence key).
    Output:
        JSON object {"confidence": float}.

    Never reads a confidence value from the LLM — confidence is always
    computed deterministically from the evidence and estimate shape.
    """
    evidence = EvidenceSummary.model_validate_json(evidence_json)
    estimate = AgeBandEstimate.model_validate_json(estimate_json)
    conf = compute_confidence(evidence, estimate)
    return json.dumps({"confidence": conf})
