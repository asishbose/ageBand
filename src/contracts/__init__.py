"""AgeBand contracts package — shared Pydantic models and module interface protocols.

All modules in src/ import from here. No module depends on another module's internals.
This package is frozen after Phase A and must not be modified without a new ADR.
"""

from src.contracts.models import (
    AgeBandContext,
    AgeBandEstimate,
    Cue,
    Decision,
    EvidenceSummary,
    GateResult,
    PlannerAction,
    SignalSet,
    StepUpMessage,
    TurnEvent,
    safety_posture,
)
from src.contracts.protocols import (
    IAgeBandInference,
    IAudit,
    IEnforcement,
    IEvidenceFabric,
    IGate,
    IGateway,
    IOrchestration,
    IPolicyDecision,
    ISignalExtractor,
    IStepupVerification,
)
from src.contracts.validators import validate_ageband_estimate, validate_planner_action

__all__ = [
    # Models
    "Cue",
    "TurnEvent",
    "SignalSet",
    "AgeBandEstimate",
    "GateResult",
    "EvidenceSummary",
    "Decision",
    "safety_posture",
    "PlannerAction",
    "StepUpMessage",
    "AgeBandContext",
    # Protocols
    "IGateway",
    "IGate",
    "ISignalExtractor",
    "IEvidenceFabric",
    "IAgeBandInference",
    "IPolicyDecision",
    "IEnforcement",
    "IStepupVerification",
    "IAudit",
    "IOrchestration",
    # Validators
    "validate_ageband_estimate",
    "validate_planner_action",
]
