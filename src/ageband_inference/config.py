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

# --- Conversation-level uncertainty penalty constants (Phase 3) ---
# All are deliberately small — individually they are nudges, not dominators.
# The CAP (MAX_UNCERTAINTY_PENALTY) prevents accumulated penalties from
# driving confidence negative on their own.

# Penalty when band_history contains conflicting bands.
UNCERTAINTY_CONFLICT_PENALTY: float = float(
    os.environ.get("INFERENCE_UNCERTAINTY_CONFLICT_PENALTY", "0.08")
)

# Penalty when band flips ≥ 3 times across the history (high volatility).
UNCERTAINTY_VOLATILITY_PENALTY: float = float(
    os.environ.get("INFERENCE_UNCERTAINTY_VOLATILITY_PENALTY", "0.08")
)

# Penalty when maturity cues (Phase 2) disagree with the candidate band.
UNCERTAINTY_MATURITY_MISMATCH_PENALTY: float = float(
    os.environ.get("INFERENCE_UNCERTAINTY_MATURITY_MISMATCH_PENALTY", "0.05")
)

# Penalty when there are fewer turns than this threshold (thin evidence).
UNCERTAINTY_SPARSITY_PENALTY: float = float(
    os.environ.get("INFERENCE_UNCERTAINTY_SPARSITY_PENALTY", "0.05")
)

# Minimum turn count before confidence is considered well-founded.
MIN_TURNS_FOR_CONFIDENCE: int = int(
    os.environ.get("INFERENCE_MIN_TURNS_FOR_CONFIDENCE", "3")
)

# Hard cap: total uncertainty penalty never exceeds this value.
MAX_UNCERTAINTY_PENALTY: float = float(
    os.environ.get("INFERENCE_MAX_UNCERTAINTY_PENALTY", "0.20")
)

# --- Embedding drift factor constants (Phase 5) ---
# Only applies when EMBEDDING_MODEL is configured (offline: sim=None → 0 penalty).

# Cosine similarity threshold below which a turn is flagged as a drift outlier.
EMBEDDING_DRIFT_THRESHOLD: float = float(
    os.environ.get("INFERENCE_EMBEDDING_DRIFT_THRESHOLD", "0.65")
)

# Penalty added to the uncertainty score when similarity falls below the threshold.
UNCERTAINTY_EMBEDDING_DRIFT_PENALTY: float = float(
    os.environ.get("INFERENCE_UNCERTAINTY_EMBEDDING_DRIFT_PENALTY", "0.05")
)
