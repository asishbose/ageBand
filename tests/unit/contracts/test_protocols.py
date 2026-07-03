"""Unit tests for src/contracts/protocols.py — Protocol structural checks."""

from __future__ import annotations

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


class TestProtocolsAreRuntimeCheckable:
    """All Protocols must be @runtime_checkable so isinstance() works in tests."""

    def test_igw_checkable(self) -> None:
        assert hasattr(IGateway, "__protocol_attrs__")

    def test_igate_checkable(self) -> None:
        assert hasattr(IGate, "__protocol_attrs__")

    def test_isignal_extractor_checkable(self) -> None:
        assert hasattr(ISignalExtractor, "__protocol_attrs__")

    def test_ievidence_checkable(self) -> None:
        assert hasattr(IEvidenceFabric, "__protocol_attrs__")

    def test_iageband_checkable(self) -> None:
        assert hasattr(IAgeBandInference, "__protocol_attrs__")

    def test_ipolicy_checkable(self) -> None:
        assert hasattr(IPolicyDecision, "__protocol_attrs__")

    def test_ienforcement_checkable(self) -> None:
        assert hasattr(IEnforcement, "__protocol_attrs__")

    def test_istepup_checkable(self) -> None:
        assert hasattr(IStepupVerification, "__protocol_attrs__")

    def test_iaudit_checkable(self) -> None:
        assert hasattr(IAudit, "__protocol_attrs__")

    def test_iorchestration_checkable(self) -> None:
        assert hasattr(IOrchestration, "__protocol_attrs__")


class TestProtocolStructure:
    """Smoke-check that each Protocol exposes the right method names."""

    def test_igateway_has_ingest(self) -> None:
        assert "ingest" in IGateway.__protocol_attrs__

    def test_igate_has_check(self) -> None:
        assert "check" in IGate.__protocol_attrs__

    def test_isignal_has_extract(self) -> None:
        assert "extract" in ISignalExtractor.__protocol_attrs__

    def test_ievidence_has_all_methods(self) -> None:
        attrs = IEvidenceFabric.__protocol_attrs__
        assert "read" in attrs
        assert "update" in attrs
        assert "decay" in attrs

    def test_iageband_has_estimate(self) -> None:
        assert "estimate" in IAgeBandInference.__protocol_attrs__

    def test_ipolicy_has_decide(self) -> None:
        assert "decide" in IPolicyDecision.__protocol_attrs__

    def test_ienforcement_has_emit(self) -> None:
        assert "emit" in IEnforcement.__protocol_attrs__

    def test_istepup_has_compose_and_persist(self) -> None:
        attrs = IStepupVerification.__protocol_attrs__
        assert "compose" in attrs
        assert "persist_confirmed" in attrs

    def test_iaudit_has_record(self) -> None:
        assert "record" in IAudit.__protocol_attrs__

    def test_iorchestration_has_run_turn(self) -> None:
        assert "run_turn" in IOrchestration.__protocol_attrs__
