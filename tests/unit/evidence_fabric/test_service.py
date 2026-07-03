"""Unit tests for EvidenceFabricService."""

from __future__ import annotations

import uuid

import pytest

from src.contracts.models import Cue, EvidenceSummary, SignalSet
from src.evidence_fabric.service import EvidenceFabricService
from src.evidence_fabric.store import _store


def _fresh_session() -> str:
    return str(uuid.uuid4())


def _cue(weight: float = 0.5, value: str = "test") -> Cue:
    return Cue(type="vocab", value=value, weight=weight)


def _signals(*cues: Cue) -> SignalSet:
    return SignalSet(cues=list(cues))


@pytest.fixture()
def svc() -> EvidenceFabricService:
    return EvidenceFabricService()


class TestEvidenceFabricRead:
    def test_read_fresh_session_returns_empty_summary(
        self, svc: EvidenceFabricService
    ) -> None:
        sid = _fresh_session()
        try:
            result = svc.read(sid)
            assert isinstance(result, EvidenceSummary)
            assert result.session_id == sid
            assert result.cues == []
            assert result.turn_count == 0
            assert result.corroboration_score == 0.0
        finally:
            _store.clear(sid)

    def test_read_after_update_returns_correct_summary(
        self, svc: EvidenceFabricService
    ) -> None:
        sid = _fresh_session()
        try:
            svc.update(sid, _signals(_cue()))
            result = svc.read(sid)
            assert result.turn_count == 1
            assert len(result.cues) == 1
        finally:
            _store.clear(sid)


class TestEvidenceFabricUpdate:
    def test_update_accumulates_cues_across_calls(
        self, svc: EvidenceFabricService
    ) -> None:
        sid = _fresh_session()
        try:
            svc.update(sid, _signals(_cue(0.3, "a")))
            svc.update(sid, _signals(_cue(0.4, "b")))
            result = svc.read(sid)
            assert len(result.cues) == 2
        finally:
            _store.clear(sid)

    def test_update_increments_turn_count(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            svc.update(sid, _signals(_cue()))
            svc.update(sid, _signals(_cue()))
            result = svc.read(sid)
            assert result.turn_count == 2
        finally:
            _store.clear(sid)

    def test_update_recomputes_corroboration(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            result = svc.update(sid, _signals(_cue(0.5)))
            # 0.5 / 5.0 = 0.1
            assert abs(result.corroboration_score - 0.1) < 0.001
        finally:
            _store.clear(sid)

    def test_update_returns_evidence_summary(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            result = svc.update(sid, _signals(_cue()))
            assert isinstance(result, EvidenceSummary)
        finally:
            _store.clear(sid)


class TestEvidenceFabricDecay:
    def test_decay_reduces_cue_weights(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            svc.update(sid, _signals(_cue(0.5)))
            svc.decay(sid)
            result = svc.read(sid)
            assert result.cues[0].weight < 0.5
        finally:
            _store.clear(sid)

    def test_decay_removes_zero_weight_cues(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            # weight=0.1 → after decay(0.1) → 0.0 → removed
            svc.update(sid, _signals(_cue(0.1)))
            svc.decay(sid)
            result = svc.read(sid)
            assert result.cues == []
        finally:
            _store.clear(sid)

    def test_decay_on_fresh_session_is_safe(self, svc: EvidenceFabricService) -> None:
        sid = _fresh_session()
        try:
            svc.decay(sid)  # must not raise
            result = svc.read(sid)
            assert result.cues == []
        finally:
            _store.clear(sid)
