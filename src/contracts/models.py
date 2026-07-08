"""Shared Pydantic v2 models for the AgeBand system.

INVARIANT: AgeBandEstimate has NO confidence field.
Confidence is computed deterministically in src/ageband_inference/confidence.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared cue-type constants
# ---------------------------------------------------------------------------

# Cue types that are strong enough to steer the rule estimator's band lean
# independently.  "reading_level", "style", and all _SPECIAL_META subtypes
# (maturity_high / maturity_low) are deliberately excluded — see rule_estimator
# docstring for the fairness rationale.  Declared here so both rule_estimator
# (M4) and signal_extraction/maturity (M2) can import from contracts without
# creating an M2 → M4 cross-module dependency.
STRONG_CUE_TYPES: frozenset[str] = frozenset({"disclosure", "topic"})

# ---------------------------------------------------------------------------
# Building-block types
# ---------------------------------------------------------------------------


class Cue(BaseModel):
    """A single age-relevant signal extracted from a turn."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["vocab", "topic", "disclosure", "style", "reading_level"]
    value: str
    weight: float = Field(ge=0.0, le=1.0)
    # Deterministic cue subtype (e.g. "guardian_reference"); drives lexicon
    # weighting. Optional so LLM/legacy cues without a subtype still validate.
    subtype: str = ""


# ---------------------------------------------------------------------------
# Gateway / session
# ---------------------------------------------------------------------------


class TurnEvent(BaseModel):
    """A single user turn arriving at the system boundary."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_text: str
    turn_number: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Signal extraction (M2)
# ---------------------------------------------------------------------------


class SignalSet(BaseModel):
    """All age-relevant cues extracted from a single turn."""

    model_config = ConfigDict(extra="forbid")

    cues: list[Cue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Age-band inference (M4)
# CRITICAL: NO confidence field — confidence is deterministic Python only.
# ---------------------------------------------------------------------------


class AgeBandEstimate(BaseModel):
    """LLM's proposed age-band estimation.

    Does NOT contain a confidence value — confidence is computed deterministically
    in src/ageband_inference/confidence.py.
    """

    model_config = ConfigDict(extra="forbid")

    band: Literal["child", "teen", "adult", "unknown"]
    cited_cues: list[str] = Field(default_factory=list)
    evasion_flag: bool = False
    contradictions: list[str] = Field(default_factory=list)
    # Additive fields (Phase 4) — richer masking pattern detail.
    # evasion_patterns: which of the four masking patterns fired. Empty list
    # when evasion_flag=False. Backward-compatible: existing callers checking
    # only evasion_flag continue to work; the richer pattern detail is opt-in.
    # Patterns: "mismatch", "deflection", "register_switching", "over_insistence"
    evasion_patterns: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gate (M1.5)
# ---------------------------------------------------------------------------


class GateResult(BaseModel):
    """Output of the cheap gate check."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["analyze", "reuse_posture"]
    reason: str


# ---------------------------------------------------------------------------
# Evidence fabric (M3)
# ---------------------------------------------------------------------------


class EvidenceSummary(BaseModel):
    """Accumulated session-scoped evidence (ephemeral, never persisted as profile)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    cues: list[Cue] = Field(default_factory=list)
    corroboration_score: float = Field(default=0.0, ge=0.0, le=1.0)
    turn_count: int = Field(default=0, ge=0)
    # Additive field (Phase 3) — record of candidate band per turn for
    # conversation-level uncertainty penalty. Existing code that doesn't
    # populate this field defaults to an empty list (no volatility penalty).
    # Format: list of band strings ("child"|"teen"|"adult"|"unknown"), one per turn.
    band_history: list[str] = Field(default_factory=list)
    # Additive field (Phase 5) — cosine similarity between the most recent
    # turn's embedding and the session centroid. None when no embedding model
    # is configured (offline / deterministic mode) — treated as "no penalty"
    # by _compute_uncertainty() in confidence.py.
    embedding_similarity: float | None = None


# ---------------------------------------------------------------------------
# Policy decision (M5)
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """Output of the deterministic policy engine."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["apply", "step_up", "none"]
    posture_level: Literal["standard", "caution", "restricted", "blocked"]
    flags: dict[str, bool] = Field(default_factory=dict)
    reason: str


# ---------------------------------------------------------------------------
# Enforcement (M6)
# ---------------------------------------------------------------------------


class safety_posture(BaseModel):  # noqa: N801 — canonical name from glossary
    """The posture AgeBand emits; the host assistant is responsible for honouring it."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["standard", "caution", "restricted", "blocked"]
    flags: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Orchestration / planner (M9/M10)
# ---------------------------------------------------------------------------

_VALID_ACTION_TYPES = frozenset(
    {
        "gate_check",
        "read_evidence",
        "update_evidence",
        "compute_confidence",
        "policy_decide",
        "emit_posture",
        "persist_confirmed",
        "delegate_extract",
        "delegate_estimate",
        "delegate_stepup",
        "finish",
    }
)


class PlannerAction(BaseModel):
    """Typed action request emitted by the planner_supervisor LLM.

    Validated by validate_planner_action() before execution.
    Unknown action_type values are rejected (fail closed).
    """

    model_config = ConfigDict(extra="forbid")

    action_type: Literal[
        "gate_check",
        "read_evidence",
        "update_evidence",
        "compute_confidence",
        "policy_decide",
        "emit_posture",
        "persist_confirmed",
        "delegate_extract",
        "delegate_estimate",
        "delegate_stepup",
        "finish",
    ]
    params: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step-up verification (M7)
# ---------------------------------------------------------------------------


class StepUpMessage(BaseModel):
    """Composed step-up message from the stepup_composer delegate."""

    model_config = ConfigDict(extra="forbid")

    message_text: str
    action: Literal["confirm", "restrict", "handoff"]


# ---------------------------------------------------------------------------
# Session context (shared across modules via orchestration)
# ---------------------------------------------------------------------------


class AgeBandContext(BaseModel):
    """Live per-session state carried through the planner loop."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    current_band: Literal["child", "teen", "adult", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    settled: bool = False
    turn_count: int = Field(default=0, ge=0)
    evidence_summary: EvidenceSummary | None = None
    posture: safety_posture | None = None
    # Most recent user turn text — transient, in-memory only (never persisted to
    # disk). Used by the gate tripwire to re-analyse settled sessions.
    last_turn_text: str = ""
