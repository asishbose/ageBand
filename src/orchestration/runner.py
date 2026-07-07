"""AgeBand orchestration service — wires tinyagent + planner loop + guardrails."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, cast, get_args

from src.ageband_inference.confidence import compute_confidence
from src.ageband_inference.service import AgeBandInferenceService
from src.audit_fairness.service import AuditFairnessService
from src.contracts.models import (
    AgeBandContext,
    AgeBandEstimate,
    Decision,
    PlannerAction,
    SignalSet,
    StepUpMessage,
    TurnEvent,
    safety_posture,
)
from src.enforcement.service import EnforcementService
from src.evidence_fabric.service import EvidenceFabricService
from src.gate import config as gate_config
from src.gate.gate_service import GateService
from src.gateway_session.service import GatewaySessionService
from src.orchestration.guardrails import (
    SAFE_DEFAULT_POSTURE,
    GuardrailViolation,
    PlannerState,
    check_iteration_cap,
    enforce_preconditions,
    record_action_completed,
)
from src.policy_decision.service import PolicyDecisionService
from src.signal_extraction.service import SignalExtractorService
from src.stepup_verification.persistence import get_confirmed

logger = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.environ.get("PLANNER_MAX_ITERATIONS", "8"))

# Mirror of PlannerAction.action_type — used for runtime validation + cast in
# _resolve_route so the planner can never silently pass a bad action_type to
# PlannerAction (fail closed: ValueError rather than a Pydantic ValidationError
# that might be swallowed higher up).
_ActionType = Literal[
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
_VALID_ACTION_TYPES: frozenset[str] = frozenset(get_args(_ActionType))

# Ordered routing sequence: (PlannerState flag attr, action_type or special token).
# Checked in order — first incomplete flag yields the next action.
_ROUTE_SEQUENCE = [
    ("gate_checked", "gate_check"),
    ("extract_done", "_gate_or_finish"),
    ("evidence_read", "update_evidence"),
    ("estimate_done", "delegate_estimate"),
    ("confidence_computed", "compute_confidence"),
    ("policy_decided", "policy_decide"),
    ("posture_emitted", "emit_posture"),
    ("step_up_requested", "_stepup_if_needed"),
]


# ---------------------------------------------------------------------------
# Turn-scoped mutable state
# ---------------------------------------------------------------------------


class _TurnState:
    """Mutable state for a single turn's planner run."""

    __slots__ = (
        "ctx", "posture", "signals", "estimate",
        "confidence", "decision", "planner", "stepup", "trace",
    )

    def __init__(self, ctx: AgeBandContext) -> None:
        self.ctx = ctx
        self.posture: safety_posture = ctx.posture or SAFE_DEFAULT_POSTURE
        self.signals: SignalSet | None = None
        self.estimate: AgeBandEstimate | None = None
        self.confidence: float = ctx.confidence
        self.decision: Decision | None = None
        self.planner: PlannerState = PlannerState()
        self.stepup: StepUpMessage | None = None
        self.trace: list[dict[str, Any]] = []


class OrchestrationService:
    """Top-level orchestration: runs the planner loop per turn.

    Implements IOrchestration. Deterministic tools run in-process.
    LLM delegate calls are injected via _mock_delegates for unit/integration tests.
    """

    def __init__(self, mock_delegates: dict[str, Any] | None = None) -> None:
        self._gate = GateService()
        self._evidence = EvidenceFabricService()
        self._policy = PolicyDecisionService()
        self._enforcement = EnforcementService()
        self._gateway = GatewaySessionService()
        self._audit = AuditFairnessService()
        self._extractor = SignalExtractorService()
        self._estimator = AgeBandInferenceService()
        self._mock_delegates: dict[str, Any] = mock_delegates or {}

    async def run_turn(self, turn: TurnEvent) -> safety_posture:
        """Process a turn through the planner loop; return the resulting safety_posture."""
        ts = await self._run(turn)
        return ts.posture

    async def run_turn_verbose(self, turn: TurnEvent) -> dict[str, Any]:
        """Process a turn and return the full session state (for the UI/API).

        Same pipeline as run_turn; additionally exposes band, confidence,
        evidence, the executed-action trace, and any step-up message.
        """
        ts = await self._run(turn)
        return self._session_state(turn, ts)

    async def _run(self, turn: TurnEvent) -> _TurnState:
        """Run one turn end-to-end: confirmed override → planner loop → persist."""
        ctx = await self._gateway.ingest(turn)
        ts = _TurnState(ctx)

        # Confirmed ground truth overrides inference (design invariant).
        confirmed = get_confirmed(turn.session_id)
        if confirmed:
            self._apply_confirmed(ts, confirmed)
            self._persist_state(turn, ts)
            return ts

        for iteration in range(MAX_ITERATIONS):
            if check_iteration_cap(iteration, MAX_ITERATIONS) is not None:
                logger.warning("Planner cap hit session=%s", turn.session_id)
                self._audit.record(turn.session_id, "cap_reached", {"iteration": iteration})
                ts.posture = SAFE_DEFAULT_POSTURE
                self._persist_state(turn, ts)
                return ts

            done = await self._step(turn, ts)
            if done:
                break

        self._persist_state(turn, ts)
        return ts

    def _apply_confirmed(self, ts: _TurnState, band: str) -> None:
        """Short-circuit: build posture directly from a CONFIRMED age band."""
        estimate = AgeBandEstimate(band=band)  # type: ignore[arg-type]
        decision = self._policy.decide(estimate, 1.0)
        ts.estimate = estimate
        ts.decision = decision
        ts.confidence = 1.0
        ts.posture = self._enforcement.emit(decision)
        ts.trace.append({"action_type": "confirmed_override", "params": {"band": band}})
        self._audit.record(ts.ctx.session_id, "confirmed_override", {"band": band})

    def _persist_state(self, turn: TurnEvent, ts: _TurnState) -> None:
        """Write end-of-turn state back to the session store (cross-turn memory)."""
        band = ts.estimate.band if ts.estimate else ts.ctx.current_band
        settled = (
            ts.confidence >= gate_config.CONFIDENCE_REUSE_THRESHOLD
            and band != "unknown"
        )
        evidence = self._evidence.read(turn.session_id)
        ctx = ts.ctx.model_copy(
            update={
                "confidence": ts.confidence,
                "posture": ts.posture,
                "current_band": band,
                "settled": settled,
                "evidence_summary": evidence,
            }
        )
        ts.ctx = ctx
        self._gateway.update_context(turn.session_id, ctx)

    def _session_state(self, turn: TurnEvent, ts: _TurnState) -> dict[str, Any]:
        """Build the UI-facing SessionState dict from turn state."""
        band = ts.estimate.band if ts.estimate else ts.ctx.current_band
        evidence = self._evidence.read(turn.session_id)
        return {
            "session_id": turn.session_id,
            "band": band,
            "confidence": ts.confidence,
            "posture": ts.posture.model_dump(),
            "evidence": evidence.model_dump(),
            "trace": ts.trace,
            "step_up": ts.stepup.model_dump() if ts.stepup else None,
            # Exposed for the eval harness; False when no estimate yet.
            "evasion_flag": ts.estimate.evasion_flag if ts.estimate else False,
        }

    async def _step(self, turn: TurnEvent, ts: _TurnState) -> bool:
        """Execute one planner step; return True when the turn is finished."""
        try:
            action = self._route(ts)
        except GuardrailViolation as exc:
            logger.error("Route error session=%s: %s", turn.session_id, exc)
            ts.posture = SAFE_DEFAULT_POSTURE
            return True

        if action.action_type == "finish":
            return True

        try:
            enforce_preconditions(action.action_type, action.params, ts.planner)
        except GuardrailViolation as exc:
            logger.error("Guardrail rejected %s: %s", action.action_type, exc)
            self._audit.record(
                turn.session_id, "guardrail_rejection",
                {"action": action.action_type, "reason": str(exc)},
            )
            ts.posture = SAFE_DEFAULT_POSTURE
            return True

        try:
            result = await self._execute(action, turn, ts)
        except Exception as exc:
            logger.error("Action %s failed: %s", action.action_type, exc)
            ts.posture = SAFE_DEFAULT_POSTURE
            return True

        record_action_completed(action.action_type, ts.planner)
        ts.trace.append({"action_type": action.action_type, "params": dict(action.params)})
        return self._apply_result(action.action_type, result, turn.session_id, ts)

    # ------------------------------------------------------------------
    # Result application — one handler per action type (dispatch table)
    # ------------------------------------------------------------------

    def _apply_result(
        self, action_type: str, result: Any, session_id: str, ts: _TurnState
    ) -> bool:
        """Dispatch result to the appropriate applier; return True when turn is done."""
        applier = _RESULT_APPLIERS.get(action_type)
        if applier is None:
            return False
        return bool(applier(self, result, session_id, ts))

    def _apply_extract(self, result: Any, _sid: str, ts: _TurnState) -> bool:
        if isinstance(result, SignalSet):
            ts.signals = result
        return False

    def _apply_estimate(self, result: Any, _sid: str, ts: _TurnState) -> bool:
        if isinstance(result, AgeBandEstimate):
            ts.estimate = result
        return False

    def _apply_confidence(self, result: Any, _sid: str, ts: _TurnState) -> bool:
        if isinstance(result, float):
            ts.confidence = result
            ts.ctx = ts.ctx.model_copy(update={"confidence": result})
        return False

    def _apply_decision(self, result: Any, _sid: str, ts: _TurnState) -> bool:
        if isinstance(result, Decision):
            ts.decision = result
        return False

    def _apply_posture(self, result: Any, session_id: str, ts: _TurnState) -> bool:
        if not isinstance(result, safety_posture):
            return False
        ts.posture = result
        ts.ctx = ts.ctx.model_copy(update={"posture": result})
        self._audit.record(session_id, "posture_emitted", {"level": result.level})
        return not (ts.decision and ts.decision.action == "step_up")

    def _apply_stepup(self, result: Any, _sid: str, ts: _TurnState) -> bool:
        if isinstance(result, StepUpMessage):
            ts.stepup = result
        return True

    # ------------------------------------------------------------------
    # Deterministic routing (replaces LLM planner in lean / test builds)
    # ------------------------------------------------------------------

    def _route(self, ts: _TurnState) -> PlannerAction:
        """Return the next PlannerAction by scanning the routing sequence."""
        for flag, action in _ROUTE_SEQUENCE:
            if not getattr(ts.planner, flag, True):
                return self._resolve_route(action, ts)
        return PlannerAction(action_type="finish", params={})

    def _resolve_route(self, action: str, ts: _TurnState) -> PlannerAction:
        """Resolve special route tokens to concrete PlannerActions."""
        if action == "_gate_or_finish":
            if self._gate.check(ts.ctx).action == "reuse_posture":
                return PlannerAction(action_type="finish", params={})
            return PlannerAction(action_type="delegate_extract", params={})
        if action == "_stepup_if_needed":
            if ts.decision and ts.decision.action == "step_up":
                return PlannerAction(action_type="delegate_stepup", params={})
            return PlannerAction(action_type="finish", params={})
        if action not in _VALID_ACTION_TYPES:
            raise ValueError(
                f"_resolve_route: unknown action_type {action!r}. "
                f"Valid values: {sorted(_VALID_ACTION_TYPES)}"
            )
        return PlannerAction(
            action_type=cast(_ActionType, action),
            params={"ctx_json": ts.ctx.model_dump_json()} if action == "gate_check" else {},
        )

    # ------------------------------------------------------------------
    # Action execution — dispatch dict + one handler per action type
    # ------------------------------------------------------------------

    async def _execute(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> Any:
        """Dispatch action_type to the appropriate handler."""
        handlers: dict[str, Any] = {
            "gate_check": self._handle_gate_check,
            "delegate_extract": self._handle_extract,
            "update_evidence": self._handle_update_evidence,
            "read_evidence": self._handle_read_evidence,
            "delegate_estimate": self._handle_estimate,
            "compute_confidence": self._handle_confidence,
            "policy_decide": self._handle_policy,
            "emit_posture": self._handle_emit_posture,
            "delegate_stepup": self._handle_stepup,
            "persist_confirmed": self._handle_persist,
        }
        handler = handlers.get(action.action_type)
        if handler is None:
            return None
        return await handler(action, turn, ts)

    async def _handle_gate_check(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> Any:
        return self._gate.check(ts.ctx)

    async def _handle_extract(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> SignalSet:
        mock = self._mock_delegates.get("extract")
        if mock:
            return SignalSet.model_validate(mock)
        return await self._extractor.extract(turn)

    async def _handle_update_evidence(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> Any:
        signals = ts.signals or SignalSet()
        # Age prior evidence so recent turns weigh more. Applied only once a few
        # turns of history exist, to keep early-turn behaviour stable.
        prior = self._evidence.read(turn.session_id)
        if prior.turn_count >= 2 and prior.cues:
            self._evidence.decay(turn.session_id)
        evidence = self._evidence.update(turn.session_id, signals)
        # Phase 5: embed this turn and record similarity to session centroid.
        # No-op when EMBEDDING_MODEL is unset (returns None → no penalty).
        from src.contracts.embeddings_client import update_session_similarity
        sim = await update_session_similarity(turn.session_id, turn.turn_text)
        if sim is not None:
            self._evidence.set_embedding_similarity(turn.session_id, sim)
            # Re-read to return the updated summary with embedding_similarity set.
            evidence = self._evidence.read(turn.session_id)
        return evidence

    async def _handle_read_evidence(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> Any:
        return self._evidence.read(turn.session_id)

    async def _handle_estimate(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> AgeBandEstimate:
        mock = self._mock_delegates.get("estimate")
        if mock:
            from src.contracts.validators import validate_ageband_estimate
            return validate_ageband_estimate(mock)
        evidence = self._evidence.read(turn.session_id)
        return await self._estimator.estimate(evidence)

    async def _handle_confidence(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> float:
        evidence = self._evidence.read(turn.session_id)
        estimate = ts.estimate or AgeBandEstimate(band="unknown")
        return compute_confidence(evidence, estimate)

    async def _handle_policy(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> Decision:
        estimate = ts.estimate or AgeBandEstimate(band="unknown")
        return self._policy.decide(estimate, ts.confidence)

    async def _handle_emit_posture(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> safety_posture:
        if ts.decision is None:
            return SAFE_DEFAULT_POSTURE
        return self._enforcement.emit(ts.decision)

    async def _handle_stepup(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> StepUpMessage:
        mock = self._mock_delegates.get("stepup")
        if mock:
            return StepUpMessage.model_validate(mock)
        return StepUpMessage(
            message_text="Could you please confirm your age to continue?",
            action="confirm",
        )

    async def _handle_persist(
        self, action: PlannerAction, turn: TurnEvent, ts: _TurnState
    ) -> dict[str, Any]:
        band = str(action.params.get("band", ""))
        confirmed = action.params.get("confirmed", False)
        if confirmed is not True:
            raise GuardrailViolation("persist_confirmed called without confirmed=True")
        from src.stepup_verification.persistence import persist_confirmed as _persist
        _persist(turn.session_id, band, confirmed=True)
        return {"ok": True}


# Module-level dispatch dict — defined after class so we can reference unbound methods.
_RESULT_APPLIERS: dict[str, Any] = {
    "delegate_extract": OrchestrationService._apply_extract,
    "delegate_estimate": OrchestrationService._apply_estimate,
    "compute_confidence": OrchestrationService._apply_confidence,
    "policy_decide": OrchestrationService._apply_decision,
    "emit_posture": OrchestrationService._apply_posture,
    "delegate_stepup": OrchestrationService._apply_stepup,
}
