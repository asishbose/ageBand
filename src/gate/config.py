"""Gate module configuration.

All thresholds are read from environment variables so they can be overridden
at deployment time without code changes.
"""

from __future__ import annotations

import os

CONFIDENCE_REUSE_THRESHOLD: float = float(
    os.environ.get("GATE_CONFIDENCE_THRESHOLD", "0.85")
)

MIN_TURNS_FOR_ANALYSIS: int = int(os.environ.get("GATE_MIN_TURNS", "2"))
