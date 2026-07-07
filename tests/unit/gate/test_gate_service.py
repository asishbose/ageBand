"""Unit tests for GateService (M1.5 — deterministic gate).

Coverage targets:
- settled session → reuse_posture / settled_session
- high confidence → reuse_posture / high_confidence
- insufficient turns → reuse_posture / insufficient_data
- normal (all conditions clear) → analyze / proceed
- boundary: confidence == threshold exactly → reuse_posture
- boundary: turn_count == MIN_TURNS exactly → analyze
- env-var override for GATE_CONFIDENCE_THRESHOLD
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

from src.contracts.models import AgeBandContext, GateResult
from src.gate.gate_service import GateService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SESSION = "sess-test"
_DEFAULT_THRESHOLD = 0.85
_DEFAULT_MIN_TURNS = 2


def _ctx(**kwargs: object) -> AgeBandContext:
    """Build an AgeBandContext with sensible defaults, overridden by kwargs."""
    defaults: dict[str, object] = {
        "session_id": _DEFAULT_SESSION,
        "current_band": "unknown",
        "confidence": 0.0,
        "settled": False,
        "turn_count": _DEFAULT_MIN_TURNS,
    }
    defaults.update(kwargs)
    return AgeBandContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGateServiceSettled:
    def test_settled_true_returns_reuse_posture(self) -> None:
        result = GateService().check(_ctx(settled=True, confidence=0.0, turn_count=0))
        assert result.action == "reuse_posture"
        assert result.reason == "settled_session"

    def test_settled_overrides_high_confidence(self) -> None:
        """settled=True takes priority even when confidence is 1.0."""
        result = GateService().check(_ctx(settled=True, confidence=1.0, turn_count=99))
        assert result.action == "reuse_posture"
        assert result.reason == "settled_session"


class TestGateServiceHighConfidence:
    def test_high_confidence_returns_reuse_posture(self) -> None:
        result = GateService().check(_ctx(confidence=0.9, turn_count=5))
        assert result.action == "reuse_posture"
        assert result.reason == "high_confidence"

    def test_boundary_confidence_equals_threshold_returns_reuse_posture(self) -> None:
        """confidence == threshold is still >= threshold → reuse."""
        result = GateService().check(
            _ctx(confidence=_DEFAULT_THRESHOLD, turn_count=5)
        )
        assert result.action == "reuse_posture"
        assert result.reason == "high_confidence"

    def test_just_below_threshold_does_not_reuse_on_high_confidence(self) -> None:
        result = GateService().check(_ctx(confidence=0.849, turn_count=5))
        assert result.reason != "high_confidence"


class TestGateServiceInsufficientData:
    def test_low_turns_with_existing_posture_returns_reuse(self) -> None:
        """Insufficient turns AND an existing posture → reuse (don't thrash)."""
        from src.contracts.models import safety_posture

        existing = safety_posture(level="standard", flags={})
        result = GateService().check(_ctx(confidence=0.5, turn_count=1, posture=existing))
        assert result.action == "reuse_posture"
        assert result.reason == "insufficient_data"

    def test_zero_turns_with_existing_posture_returns_reuse(self) -> None:
        from src.contracts.models import safety_posture

        existing = safety_posture(level="standard", flags={})
        result = GateService().check(_ctx(confidence=0.0, turn_count=0, posture=existing))
        assert result.action == "reuse_posture"
        assert result.reason == "insufficient_data"

    def test_low_turns_without_posture_returns_analyze(self) -> None:
        """No existing posture on turn 1 → always analyze to start collecting evidence."""
        result = GateService().check(_ctx(confidence=0.0, turn_count=1, posture=None))
        assert result.action == "analyze"

    def test_zero_turns_without_posture_returns_analyze(self) -> None:
        result = GateService().check(_ctx(confidence=0.0, turn_count=0, posture=None))
        assert result.action == "analyze"


class TestGateServiceAnalyze:
    def test_normal_case_returns_analyze(self) -> None:
        result = GateService().check(
            _ctx(settled=False, confidence=0.4, turn_count=_DEFAULT_MIN_TURNS)
        )
        assert result.action == "analyze"
        assert result.reason == "proceed"

    def test_boundary_turn_count_equals_min_returns_analyze(self) -> None:
        """turn_count == MIN_TURNS is sufficient → analyze."""
        result = GateService().check(
            _ctx(settled=False, confidence=0.0, turn_count=_DEFAULT_MIN_TURNS)
        )
        assert result.action == "analyze"
        assert result.reason == "proceed"


class TestGateServiceEnvOverride:
    def test_confidence_threshold_env_var_lowers_threshold(self) -> None:
        """Setting GATE_CONFIDENCE_THRESHOLD=0.5 should cause confidence=0.6 to reuse."""
        import src.gate.config as gate_config

        try:
            with patch.dict(os.environ, {"GATE_CONFIDENCE_THRESHOLD": "0.5"}):
                importlib.reload(gate_config)
                result = GateService().check(_ctx(confidence=0.6, turn_count=5))
                assert result.action == "reuse_posture"
                assert result.reason == "high_confidence"
        finally:
            # Reload AFTER the patched env is restored, so the module constants
            # return to their defaults for every later test.
            importlib.reload(gate_config)

    def test_min_turns_env_var_raises_bar(self) -> None:
        """Setting GATE_MIN_TURNS=5 should require 5+ turns before reusing (when posture exists)."""
        import src.gate.config as gate_config
        from src.contracts.models import safety_posture

        existing = safety_posture(level="standard", flags={})
        try:
            with patch.dict(os.environ, {"GATE_MIN_TURNS": "5"}):
                importlib.reload(gate_config)
                # turn_count=3 is below the new min of 5 → insufficient_data (posture exists)
                result = GateService().check(_ctx(confidence=0.0, turn_count=3, posture=existing))
                assert result.action == "reuse_posture"
                assert result.reason == "insufficient_data"
        finally:
            # Reload AFTER the patched env is restored (see note above).
            importlib.reload(gate_config)


class TestGateResultShape:
    def test_returns_gate_result_instance(self) -> None:
        result = GateService().check(_ctx())
        assert isinstance(result, GateResult)

    def test_action_is_valid_literal(self) -> None:
        result = GateService().check(_ctx())
        assert result.action in {"analyze", "reuse_posture"}
