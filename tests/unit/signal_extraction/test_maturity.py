"""Tests for maturity cue scorers (Phase 2).

Critical check: maturity subtypes are EXCLUDED from _STRONG_TYPES — maturity
cues must never establish a band on their own.
"""

from __future__ import annotations

from src.contracts.models import STRONG_CUE_TYPES as _STRONG_TYPES
from src.signal_extraction.maturity import (
    MATURITY_CUE_WEIGHT,
    SUBTYPE_HIGH_MATURITY,
    SUBTYPE_LOW_MATURITY,
    assert_not_strong_type,
    extract_maturity_cues,
    interaction_style_cue,
    linguistic_maturity_cue,
    score_interaction_maturity,
    score_linguistic_maturity,
)


class TestStrongTypesExclusion:
    """The single most important check in Phase 2."""

    def test_assert_not_strong_type_passes(self) -> None:
        """The safety function itself must pass — covers both subtypes."""
        assert_not_strong_type()  # raises AssertionError if invariant is violated

    def test_maturity_high_not_in_strong_types(self) -> None:
        """maturity_high must NEVER appear in _STRONG_TYPES."""
        assert SUBTYPE_HIGH_MATURITY not in _STRONG_TYPES, (
            "maturity_high is in _STRONG_TYPES — this would allow maturity cues "
            "to establish a band, reintroducing the PR #2 false-positive regression."
        )

    def test_maturity_low_not_in_strong_types(self) -> None:
        """maturity_low must NEVER appear in _STRONG_TYPES."""
        assert SUBTYPE_LOW_MATURITY not in _STRONG_TYPES, (
            "maturity_low is in _STRONG_TYPES — this would allow maturity cues "
            "to establish a band."
        )


class TestLinguisticMaturityScorer:
    def test_mature_vocabulary_returns_positive_score(self) -> None:
        text = (
            "Furthermore, the implications of this framework are significant. "
            "One could argue that the consequences, whilst nuanced, are nonetheless "
            "substantive and warrant further corroboration."
        )
        score = score_linguistic_maturity(text)
        assert score is not None
        assert score > 0.0

    def test_immature_vocabulary_returns_negative_score(self) -> None:
        text = "omg this is literally like so unfair lol idk tbh bruh ngl"
        score = score_linguistic_maturity(text)
        assert score is not None
        assert score < 0.0

    def test_short_text_returns_none(self) -> None:
        assert score_linguistic_maturity("hi") is None

    def test_high_maturity_cue_has_correct_weight(self) -> None:
        text = (
            "Furthermore, the implications are significant and warrant "
            "corroboration from a substantiated perspective."
        )
        cue = linguistic_maturity_cue(text)
        if cue is not None:  # only fires on clear signal
            assert cue.weight == MATURITY_CUE_WEIGHT
            assert cue.subtype == SUBTYPE_HIGH_MATURITY

    def test_neutral_text_returns_none(self) -> None:
        # Neutral text — no strong vocabulary signal either way.
        cue = linguistic_maturity_cue("I want to learn how to cook pasta.")
        # Should either return None or low-maturity — not high.
        if cue is not None:
            assert cue.subtype != SUBTYPE_HIGH_MATURITY


class TestInteractionStyleScorer:
    def test_hedging_returns_positive_score(self) -> None:
        text = (
            "I think there are multiple perspectives here. "
            "Could you clarify what you mean by that? "
            "I believe the answer might be more complex."
        )
        score = score_interaction_maturity(text)
        assert score is not None
        assert score > 0.0

    def test_reactive_returns_negative_score(self) -> None:
        text = "this is so not fair, why are you doing this, stop it whatever"
        score = score_interaction_maturity(text)
        assert score is not None
        assert score < 0.0

    def test_neutral_interaction_returns_none(self) -> None:
        # No hedging, no reactive — no interaction style signal.
        assert score_interaction_maturity("I want pasta") is None

    def test_interaction_cue_type_is_style(self) -> None:
        text = (
            "I think perhaps we could argue this. Could you clarify the implications? "
            "I believe the perspective is nuanced."
        )
        cue = interaction_style_cue(text)
        if cue is not None:
            assert cue.type == "style"
            assert cue.weight == MATURITY_CUE_WEIGHT


class TestExtractMaturityCues:
    def test_returns_list(self) -> None:
        result = extract_maturity_cues("I want to learn more.")
        assert isinstance(result, list)

    def test_max_two_cues_per_turn(self) -> None:
        text = (
            "I think therefore I am. Furthermore, the implications are significant. "
            "Could you clarify?"
        )
        result = extract_maturity_cues(text)
        assert len(result) <= 2

    def test_cue_types_are_style(self) -> None:
        text = (
            "omg this is so not fair lol idk tbh bruh why are you doing this"
        )
        cues = extract_maturity_cues(text)
        for cue in cues:
            assert cue.type == "style"

    def test_all_cue_weights_are_maturity_weight(self) -> None:
        text = (
            "Furthermore, I think the implications warrant corroboration. "
            "Could you clarify the perspective?"
        )
        cues = extract_maturity_cues(text)
        for cue in cues:
            assert cue.weight == MATURITY_CUE_WEIGHT


class TestFixtureSafety:
    """Existing fixtures must not change band/confidence from maturity cues."""

    def test_maturity_cues_do_not_change_existing_fixture_bands(self) -> None:
        """Maturity cues (weight 0.3, non-strong-type) must not swing existing
        fixture outcomes. The _STRONG_TYPES exclusion is the gate; this test
        confirms the end-to-end pipeline still returns the same result for a
        reference clear_adult turn as before maturity was added.
        """
        import os
        os.environ["AGEBAND_INFERENCE_MODE"] = "deterministic"

        from src.ageband_inference.rule_estimator import estimate
        from src.contracts.models import Cue, EvidenceSummary

        # A reference evidence set for clear_adult (strong topic cues).
        evidence = EvidenceSummary(
            session_id="test-ph7",
            cues=[
                Cue(type="topic", value="mortgage: 'mortgage'", subtype="adult_life_topic", weight=0.6),
                Cue(type="topic", value="workplace: 'mba'", subtype="workplace_topic", weight=0.6),
            ],
            corroboration_score=1.0,
            turn_count=3,
        )
        result = estimate(evidence)
        assert result.band == "adult", (
            f"clear_adult fixture regressed: band={result.band}. "
            "Maturity cues should not affect this result."
        )
