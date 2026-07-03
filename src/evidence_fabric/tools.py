"""tinyagent / openai-agents function_tool wrappers for the evidence fabric (M3)."""

from __future__ import annotations

from agents import function_tool  # openai-agents SDK

from src.contracts.models import SignalSet
from src.evidence_fabric.service import EvidenceFabricService

_svc = EvidenceFabricService()


@function_tool
def read_evidence(session_id: str) -> str:
    """Read current evidence for a session. Returns EvidenceSummary as JSON."""
    return _svc.read(session_id).model_dump_json()


@function_tool
def update_evidence(session_id: str, signals_json: str) -> str:
    """Merge new SignalSet into evidence.

    signals_json: SignalSet as JSON.
    Returns EvidenceSummary as JSON.
    """
    signals = SignalSet.model_validate_json(signals_json)
    return _svc.update(session_id, signals).model_dump_json()


@function_tool
def decay_evidence(session_id: str) -> str:
    """Apply decay to session evidence. Returns {"ok": true}."""
    _svc.decay(session_id)
    return '{"ok": true}'
