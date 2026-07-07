"""Unit tests for EnforcementService (M6).

Coverage:
- emit() returns correct posture for each decision posture level
- Result is always a valid safety_posture instance
"""

from __future__ import annotations

import pytest

from src.contracts.models import Decision, safety_posture
from src.enforcement.service import EnforcementService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(posture_level: str, action: str = "apply") -> Decision:
    return Decision(  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        posture_level=posture_level,  # type: ignore[arg-type]
        reason="test",
    )


# ---------------------------------------------------------------------------
# EnforcementService.emit()
# ---------------------------------------------------------------------------


class TestEnforcementServiceEmit:
    def setup_method(self) -> None:
        self.svc = EnforcementService()

    @pytest.mark.parametrize(
        "posture_level,expected_level",
        [
            ("standard", "standard"),
            ("caution", "caution"),
            ("restricted", "restricted"),
            ("blocked", "blocked"),
        ],
    )
    def test_emit_returns_correct_level(self, posture_level: str, expected_level: str) -> None:
        posture = self.svc.emit(_decision(posture_level))
        assert posture.level == expected_level

    def test_emit_returns_safety_posture_instance(self) -> None:
        posture = self.svc.emit(_decision("standard"))
        assert isinstance(posture, safety_posture)

    def test_emit_blocked_has_restrictive_flags(self) -> None:
        posture = self.svc.emit(_decision("blocked"))
        assert posture.flags["mature_content"] is False
        assert posture.flags["feature_full"] is False

    def test_emit_standard_has_permissive_flags(self) -> None:
        posture = self.svc.emit(_decision("standard", action="none"))
        assert posture.flags["mature_content"] is True
        assert posture.flags["feature_full"] is True

    def test_emit_with_decision_flags_merges_correctly(self) -> None:
        decision = Decision(
            action="apply",
            posture_level="caution",
            reason="test",
            flags={"feature_full": False},
        )
        posture = self.svc.emit(decision)
        assert posture.flags["feature_full"] is False
        assert posture.flags["tone_strict"] is True
