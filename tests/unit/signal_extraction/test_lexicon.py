"""Unit tests for the deterministic cue lexicon (M2)."""

from __future__ import annotations

from src.signal_extraction import lexicon


class TestAssignWeight:
    def test_known_subtype_returns_spec_weight(self) -> None:
        assert lexicon.assign_weight("grade_level") == 0.9
        assert lexicon.assign_weight("guardian_reference") == 0.7
        assert lexicon.assign_weight("texting_shorthand") == 0.4

    def test_unknown_subtype_returns_default(self) -> None:
        assert lexicon.assign_weight("nonsense") == lexicon.DEFAULT_WEIGHT

    def test_special_subtypes_via_assign_weight_any(self) -> None:
        assert lexicon.assign_weight_any("explicit_child_age") == 1.0
        assert lexicon.assign_weight_any("reading_level_low") == 0.3
        assert lexicon.assign_weight_any("grade_level") == 0.9  # still resolves specs


class TestFairnessOrdering:
    def test_disclosure_outweighs_topic_outweighs_style(self) -> None:
        disclosure = lexicon.assign_weight("grade_level")
        topic = lexicon.assign_weight("guardian_reference")
        style = lexicon.assign_weight("texting_shorthand")
        assert disclosure > topic > style

    def test_lexical_signal_is_downweighted(self) -> None:
        # Reading level / vocab must sit below topic & disclosure (fairness).
        assert lexicon.assign_weight_any("reading_level_low") < lexicon.assign_weight(
            "school_topic"
        )


class TestDetectAge:
    def test_explicit_child_age(self) -> None:
        out = lexicon.detect_age("I am 11 years old")
        assert out is not None and out[1] == "explicit_child_age"

    def test_explicit_teen_age(self) -> None:
        out = lexicon.detect_age("i'm 15")
        assert out is not None and out[1] == "explicit_teen_age"

    def test_explicit_adult_age(self) -> None:
        out = lexicon.detect_age("I am 25 years old")
        assert out is not None and out[1] == "explicit_adult_age"

    def test_no_age(self) -> None:
        assert lexicon.detect_age("hello there") is None


class TestClassifyText:
    def test_guardian_and_school(self) -> None:
        hits = lexicon.classify_text("my mom said i have homework")
        subtypes = {s for _t, s, _m in hits}
        assert "guardian_reference" in subtypes
        assert "school_topic" in subtypes

    def test_adult_life(self) -> None:
        hits = lexicon.classify_text("my mortgage renewal and my job")
        subtypes = {s for _t, s, _m in hits}
        assert "adult_life_topic" in subtypes

    def test_adult_self_claim(self) -> None:
        hits = lexicon.classify_text("stop treating me like a kid, I'm an adult")
        subtypes = {s for _t, s, _m in hits}
        assert "adult_self_claim" in subtypes

    def test_band_hints(self) -> None:
        assert lexicon.band_hint("guardian_reference") == "child"
        assert lexicon.band_hint("adult_life_topic") == "adult"
        assert lexicon.band_hint_any("explicit_teen_age") == "teen"
