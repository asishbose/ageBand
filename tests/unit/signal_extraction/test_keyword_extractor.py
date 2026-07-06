"""Unit tests for the deterministic offline keyword extractor (M2 fallback)."""

from __future__ import annotations

from src.contracts.models import SignalSet
from src.signal_extraction.keyword_extractor import extract_cues


class TestExtractCues:
    def test_returns_signalset(self) -> None:
        assert isinstance(extract_cues("hello"), SignalSet)

    def test_weights_come_from_lexicon(self) -> None:
        cues = extract_cues("my mom said i have homework").cues
        by_sub = {c.subtype: c.weight for c in cues}
        assert by_sub["guardian_reference"] == 0.7
        assert by_sub["school_topic"] == 0.6

    def test_every_cue_has_subtype_and_valid_weight(self) -> None:
        cues = extract_cues("I am 12 and in 8th grade, my mom is strict").cues
        assert cues, "expected some cues"
        for c in cues:
            assert c.subtype
            assert 0.0 <= c.weight <= 1.0

    def test_reading_level_cue_always_present_for_nonempty(self) -> None:
        cues = extract_cues("The macroeconomic implications are considerable.").cues
        subtypes = {c.subtype for c in cues}
        assert subtypes & {"reading_level_low", "reading_level_high"}

    def test_empty_text_no_reading_level(self) -> None:
        assert extract_cues("   ").cues == []

    def test_explicit_age_detected(self) -> None:
        cues = extract_cues("I am 25 years old").cues
        assert any(c.subtype == "explicit_adult_age" for c in cues)
