"""Module interface Protocols for AgeBand.

Every module in src/ implements one of these Protocols.
Depend on the Protocol, not the concrete class (Dependency Inversion).
All Protocols are runtime_checkable for smoke-test assertions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.contracts.models import (
    AgeBandContext,
    AgeBandEstimate,
    Decision,
    EvidenceSummary,
    GateResult,
    SignalSet,
    StepUpMessage,
    TurnEvent,
    safety_posture,
)


@runtime_checkable
class IGateway(Protocol):
    """M1 — TurnEvent intake, session management."""

    async def ingest(self, turn: TurnEvent) -> AgeBandContext:
        """Ingest a turn; return the current (or new) session context."""
        ...


@runtime_checkable
class IGate(Protocol):
    """M1.5 — Cheap deterministic gate (no LLM)."""

    def check(self, ctx: AgeBandContext) -> GateResult:
        """Return analyze or reuse_posture based on session state."""
        ...


@runtime_checkable
class ISignalExtractor(Protocol):
    """M2 — One structured LLM pass → SignalSet."""

    async def extract(self, turn: TurnEvent) -> SignalSet:
        """Extract age-relevant cues from a turn."""
        ...


@runtime_checkable
class IEvidenceFabric(Protocol):
    """M3 — Ephemeral session-scoped evidence store."""

    def read(self, session_id: str) -> EvidenceSummary:
        """Read current evidence for a session."""
        ...

    def update(self, session_id: str, signals: SignalSet) -> EvidenceSummary:
        """Merge new signals into session evidence; return updated summary."""
        ...

    def decay(self, session_id: str) -> None:
        """Apply time-based decay to session evidence weights."""
        ...


@runtime_checkable
class IAgeBandInference(Protocol):
    """M4 — LLM proposes band + cues + evasion flag (NO confidence)."""

    async def estimate(self, evidence: EvidenceSummary) -> AgeBandEstimate:
        """Propose an age band estimate from accumulated evidence."""
        ...


@runtime_checkable
class IPolicyDecision(Protocol):
    """M5 — Deterministic policy table: band × confidence → Decision."""

    def decide(self, estimate: AgeBandEstimate, confidence: float) -> Decision:
        """Map band + confidence to a safety Decision."""
        ...


@runtime_checkable
class IEnforcement(Protocol):
    """M6 — Emit safety_posture; host is the enforcer."""

    def emit(self, decision: Decision) -> safety_posture:
        """Build and emit the safety_posture for this decision."""
        ...


@runtime_checkable
class IStepupVerification(Protocol):
    """M7 — Step-up composition and confirmed-only persistence."""

    async def compose(self, ctx: AgeBandContext) -> StepUpMessage:
        """Compose a step-up message for the current session."""
        ...

    def persist_confirmed(self, session_id: str, band: str) -> None:
        """Persist an explicitly CONFIRMED age band. Never called for inferred bands."""
        ...


@runtime_checkable
class IAudit(Protocol):
    """M8 — Ephemeral decision/telemetry trace (minimal seam for lean build)."""

    def record(self, session_id: str, action: str, payload: dict[str, object]) -> None:
        """Record a decision event in the ephemeral trace."""
        ...


@runtime_checkable
class IOrchestration(Protocol):
    """M9/M10 — Top-level orchestration: run one turn through the planner loop."""

    async def run_turn(self, turn: TurnEvent) -> safety_posture:
        """Process a turn; return the resulting safety_posture."""
        ...
