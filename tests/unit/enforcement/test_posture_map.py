"""Unit tests for enforcement.posture_map (M6).

Coverage:
- Each posture level (standard/caution/restricted/blocked) → correct safety_posture flags
- Invalid posture_level → ValueError (fail closed)
- Decision.flags are merged onto canonical flags, overriding them
"""

from __future__ import annotations

import pytest

from src.contracts.models import Decision, safety_posture
from src.enforcement.posture_map import POSTURE_DEFINITIONS, build_posture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(posture_level: str, flags: dict[str, bool] | None = None) -> Decision:
    return Decision(  # type: ignore[arg-type]
        action="apply",
        posture_level=posture_level,  # type: ignore[arg-type]
        reason="test",
        flags=flags or {},
    )


# ---------------------------------------------------------------------------
# Canonical posture levels
# ---------------------------------------------------------------------------


class TestPostureMapCanonical:
    def test_standard_flags(self) -> None:
        posture = build_posture(_decision("standard"))
        assert posture.level == "standard"
        assert posture.flags["mature_content"] is True
        assert posture.flags["feature_full"] is True
        assert posture.flags["tone_strict"] is False

    def test_caution_flags(self) -> None:
        posture = build_posture(_decision("caution"))
        assert posture.level == "caution"
        assert posture.flags["mature_content"] is False
        assert posture.flags["feature_full"] is True
        assert posture.flags["tone_strict"] is True

    def test_restricted_flags(self) -> None:
        posture = build_posture(_decision("restricted"))
        assert posture.level == "restricted"
        assert posture.flags["mature_content"] is False
        assert posture.flags["feature_full"] is False
        assert posture.flags["tone_strict"] is True

    def test_blocked_flags(self) -> None:
        posture = build_posture(_decision("blocked"))
        assert posture.level == "blocked"
        assert posture.flags["mature_content"] is False
        assert posture.flags["feature_full"] is False
        assert posture.flags["tone_strict"] is True

    def test_returns_safety_posture_instance(self) -> None:
        posture = build_posture(_decision("standard"))
        assert isinstance(posture, safety_posture)


# ---------------------------------------------------------------------------
# Invalid posture level — fail closed
# ---------------------------------------------------------------------------


class TestPostureMapInvalidLevel:
    def test_unknown_level_raises_value_error(self) -> None:
        bad_decision = Decision(action="none", posture_level="standard", reason="test")
        # Manually override posture_level to simulate an invalid value reaching the map.
        object.__setattr__(bad_decision, "posture_level", "super_strict")
        with pytest.raises(ValueError, match="Unknown posture_level"):
            build_posture(bad_decision)

    def test_empty_level_raises_value_error(self) -> None:
        bad_decision = Decision(action="none", posture_level="standard", reason="test")
        object.__setattr__(bad_decision, "posture_level", "")
        with pytest.raises(ValueError, match="Unknown posture_level"):
            build_posture(bad_decision)


# ---------------------------------------------------------------------------
# Flag merging — Decision.flags override canonical flags
# ---------------------------------------------------------------------------


class TestPostureMapFlagMerge:
    def test_decision_flag_overrides_canonical(self) -> None:
        """A Decision that sets feature_full=False should override caution's True."""
        posture = build_posture(_decision("caution", {"feature_full": False}))
        assert posture.flags["feature_full"] is False

    def test_extra_decision_flag_added(self) -> None:
        """A flag not in the canonical set is added to the result."""
        posture = build_posture(_decision("standard", {"custom_flag": True}))
        assert posture.flags.get("custom_flag") is True

    def test_canonical_flags_preserved_when_no_override(self) -> None:
        posture = build_posture(_decision("restricted", {}))
        assert posture.flags["tone_strict"] is True

    def test_posture_definitions_dict_covers_all_levels(self) -> None:
        assert set(POSTURE_DEFINITIONS.keys()) == {"standard", "caution", "restricted", "blocked"}
