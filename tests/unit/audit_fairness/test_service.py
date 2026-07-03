"""Unit tests for AuditFairnessService."""

from __future__ import annotations

import pytest

from src.audit_fairness.service import AuditFairnessService
from src.audit_fairness.trace import _trace

_SID_A = "sess-audit-a"
_SID_B = "sess-audit-b"


@pytest.fixture(autouse=True)
def _cleanup() -> None:  # type: ignore[return]
    yield
    _trace.clear(_SID_A)
    _trace.clear(_SID_B)


class TestAuditFairnessServiceRecord:
    def test_record_stores_entry(self) -> None:
        svc = AuditFairnessService()
        svc.record(_SID_A, "policy_decide", {"band": "teen", "confidence": 0.7})
        entries = _trace.get_trace(_SID_A)
        assert len(entries) == 1
        assert entries[0]["session_id"] == _SID_A
        assert entries[0]["action"] == "policy_decide"
        assert entries[0]["band"] == "teen"

    def test_two_records_for_same_session_both_appear(self) -> None:
        svc = AuditFairnessService()
        svc.record(_SID_A, "gate_check", {"result": "analyze"})
        svc.record(_SID_A, "emit_posture", {"level": "caution"})
        entries = _trace.get_trace(_SID_A)
        assert len(entries) == 2
        actions = {e["action"] for e in entries}
        assert actions == {"gate_check", "emit_posture"}

    def test_sessions_are_isolated(self) -> None:
        svc = AuditFairnessService()
        svc.record(_SID_A, "gate_check", {"result": "analyze"})
        svc.record(_SID_B, "emit_posture", {"level": "standard"})
        entries_a = _trace.get_trace(_SID_A)
        entries_b = _trace.get_trace(_SID_B)
        assert len(entries_a) == 1
        assert len(entries_b) == 1
        assert entries_a[0]["action"] == "gate_check"
        assert entries_b[0]["action"] == "emit_posture"

    def test_unknown_session_returns_empty_trace(self) -> None:
        entries = _trace.get_trace("sess-unknown")
        assert entries == []

    def test_payload_fields_merged_into_entry(self) -> None:
        svc = AuditFairnessService()
        svc.record(_SID_A, "persist_confirmed", {"band": "adult", "confirmed": True})
        entry = _trace.get_trace(_SID_A)[0]
        assert entry["band"] == "adult"
        assert entry["confirmed"] is True
