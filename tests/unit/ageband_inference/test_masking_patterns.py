"""Tests for the generalized masking/evasion detector (Phase 4).

REGRESSION REQUIREMENT: Every existing fixture/test that triggered evasion_flag=True
under the old single-rule logic must STILL trigger it under the new four-pattern
logic (via the 'mismatch' pattern). This is the single most important check in
Phase 4 — generalization must be a strict superset, never a regression.

Additionally: at least one fixture/test case per pattern exercises that pattern.
"""

from __future__ import annotations

from src.ageband_inference.rule_estimator import estimate
from src.contracts.models import Cue, EvidenceSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    cues: list[Cue],
    band_history: list[str] | None = None,
    turn_count: int = 4,
) -> EvidenceSummary:
    return EvidenceSummary(
        session_id="test-ph9",
        cues=cues,
        corroboration_score=0.5,
        turn_count=turn_count,
        band_history=band_history or [],
    )


def _adult_self_claim(value: str = "i am definitely an adult") -> Cue:
    return Cue(type="style", value=value, subtype="adult_self_claim", weight=0.3)


def _young_cue() -> Cue:
    return Cue(
        type="topic", value="school: 'homework'", subtype="school_topic", weight=0.6
    )


def _guardian_cue() -> Cue:
    return Cue(
        type="topic", value="guardian: 'my parents'", subtype="guardian_reference", weight=0.7
    )


# ---------------------------------------------------------------------------
# Superset regression — mismatch pattern
# ---------------------------------------------------------------------------


class TestMismatchPatternIsSuperset:
    """The original evasion rule must still fire as 'mismatch' pattern."""

    def test_adversarial_fixture_still_triggers_evasion(self) -> None:
        """Classic adversarial: adult claim + young cues → evasion_flag=True."""
        cues = [_adult_self_claim(), _young_cue()]
        result = estimate(_make_evidence(cues))
        assert result.evasion_flag is True, (
            "Regression: mismatch pattern no longer fires on classic adversarial cues."
        )

    def test_mismatch_pattern_name_in_patterns(self) -> None:
        cues = [_adult_self_claim(), _young_cue()]
        result = estimate(_make_evidence(cues))
        assert "mismatch" in result.evasion_patterns, (
            "evasion_patterns must contain 'mismatch' when adult claim + young cues."
        )

    def test_mismatch_with_guardian_cue(self) -> None:
        cues = [
            _adult_self_claim("i'm an adult and not a child"),
            _guardian_cue(),
        ]
        result = estimate(_make_evidence(cues))
        assert result.evasion_flag is True
        assert "mismatch" in result.evasion_patterns

    def test_no_young_cues_no_mismatch(self) -> None:
        """Without young cues, the mismatch pattern must NOT fire."""
        cues = [_adult_self_claim()]
        result = estimate(_make_evidence(cues))
        assert "mismatch" not in result.evasion_patterns


# ---------------------------------------------------------------------------
# Pattern 2 — deflection
# ---------------------------------------------------------------------------


class TestDeflectionPattern:
    def test_deflection_phrase_triggers_deflection(self) -> None:
        """'why do you keep asking' deflection + young cue → deflection pattern."""
        cues = [
            _adult_self_claim("why do you keep asking i'm not a kid"),
            _young_cue(),
        ]
        result = estimate(_make_evidence(cues))
        assert "deflection" in result.evasion_patterns

    def test_deflection_sets_evasion_flag(self) -> None:
        cues = [
            _adult_self_claim("stop treating me like a kid i'm not a child"),
            _young_cue(),
        ]
        result = estimate(_make_evidence(cues))
        assert result.evasion_flag is True

    def test_deflection_without_young_cues_does_not_fire(self) -> None:
        cues = [_adult_self_claim("why do you keep asking")]
        result = estimate(_make_evidence(cues))
        assert "deflection" not in result.evasion_patterns


# ---------------------------------------------------------------------------
# Pattern 3 — register_switching
# ---------------------------------------------------------------------------


class TestRegisterSwitchingPattern:
    def test_young_to_adult_switch_in_history(self) -> None:
        """band_history going from teen/child → adult triggers register_switching."""
        cues = [_young_cue()]
        band_history = ["teen", "teen", "adult"]
        result = estimate(_make_evidence(cues, band_history=band_history))
        assert "register_switching" in result.evasion_patterns

    def test_consistent_history_no_switch(self) -> None:
        cues = [_young_cue()]
        band_history = ["teen", "teen", "teen"]
        result = estimate(_make_evidence(cues, band_history=band_history))
        assert "register_switching" not in result.evasion_patterns

    def test_short_history_no_switch(self) -> None:
        """Less than 3 history entries — not enough to detect switching."""
        cues = [_young_cue()]
        band_history = ["teen", "adult"]
        result = estimate(_make_evidence(cues, band_history=band_history))
        assert "register_switching" not in result.evasion_patterns


# ---------------------------------------------------------------------------
# Pattern 4 — over_insistence
# ---------------------------------------------------------------------------


class TestOverInsistencePattern:
    def test_multiple_adult_claims_triggers_over_insistence(self) -> None:
        """Two or more adult_self_claim cues in evidence → over_insistence."""
        cues = [
            _adult_self_claim("i am definitely an adult"),
            _adult_self_claim("i'm obviously an adult okay"),
        ]
        result = estimate(_make_evidence(cues))
        assert "over_insistence" in result.evasion_patterns

    def test_single_adult_claim_no_over_insistence(self) -> None:
        cues = [_adult_self_claim()]
        result = estimate(_make_evidence(cues))
        assert "over_insistence" not in result.evasion_patterns


# ---------------------------------------------------------------------------
# Combined patterns
# ---------------------------------------------------------------------------


class TestCombinedPatterns:
    def test_all_four_patterns_can_coexist(self) -> None:
        """A maximally adversarial session can trigger multiple patterns at once."""
        cues = [
            _adult_self_claim("i am definitely an adult"),
            _adult_self_claim("why do you keep asking im not a kid stop treating me like a kid"),
            _young_cue(),
        ]
        band_history = ["teen", "teen", "adult"]
        result = estimate(_make_evidence(cues, band_history=band_history))
        assert result.evasion_flag is True
        # At minimum mismatch + over_insistence should fire.
        assert "mismatch" in result.evasion_patterns
        assert "over_insistence" in result.evasion_patterns

    def test_no_evasion_without_indicators(self) -> None:
        """Clean adult session — no patterns should fire."""
        cues = [
            Cue(type="topic", value="mortgage", subtype="adult_life_topic", weight=0.6),
            Cue(type="topic", value="mba", subtype="workplace_topic", weight=0.6),
        ]
        result = estimate(_make_evidence(cues))
        assert result.evasion_flag is False
        assert result.evasion_patterns == []
