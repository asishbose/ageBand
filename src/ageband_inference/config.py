"""Ageband-inference module configuration.

All weights are read from environment variables so they can be overridden
at deployment time without code changes.
"""

from __future__ import annotations

import os

CORROBORATION_WEIGHT: float = float(
    os.environ.get("INFERENCE_CORROBORATION_WEIGHT", "0.6")
)

EVASION_PENALTY: float = float(
    os.environ.get("INFERENCE_EVASION_PENALTY", "0.15")
)

CONTRADICTION_PENALTY: float = float(
    os.environ.get("INFERENCE_CONTRADICTION_PENALTY", "0.10")
)

MAX_CITED_CUES_BONUS: int = int(
    os.environ.get("INFERENCE_MAX_CITED_CUES_BONUS", "5")
)

CITED_CUES_WEIGHT: float = float(
    os.environ.get("INFERENCE_CITED_CUES_WEIGHT", "0.4")
)

# Maximum number of contradictions counted for the penalty calculation.
_MAX_CONTRADICTIONS_COUNTED: int = 3
