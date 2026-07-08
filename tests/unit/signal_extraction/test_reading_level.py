"""Unit tests for compute_reading_level (deterministic Flesch-Kincaid).

Coverage targets:
- Empty string → 0.0
- Single short word → low score (normalised toward 0)
- Complex multi-sentence paragraph → score > 0.3
- Result is always in [0.0, 1.0]
- Known simple text → score < known complex text (relative ordering)
"""

from __future__ import annotations

import pytest

from src.signal_extraction.reading_level import _count_syllables, compute_reading_level

# ---------------------------------------------------------------------------
# compute_reading_level
# ---------------------------------------------------------------------------


class TestComputeReadingLevelBoundaries:
    def test_empty_string_returns_zero(self) -> None:
        assert compute_reading_level("") == 0.0

    def test_whitespace_only_returns_zero(self) -> None:
        assert compute_reading_level("   \t\n") == 0.0

    def test_result_is_never_below_zero(self) -> None:
        assert compute_reading_level("hi") >= 0.0

    def test_result_is_never_above_one(self) -> None:
        assert compute_reading_level("hi") <= 1.0

    @pytest.mark.parametrize(
        "text",
        [
            "Cat sat.",
            "I go now.",
            "She is here.",
            "The dog ran fast and far.",
        ],
    )
    def test_result_in_unit_interval(self, text: str) -> None:
        score = compute_reading_level(text)
        assert 0.0 <= score <= 1.0, f"Score {score} out of [0,1] for: {text!r}"


class TestComputeReadingLevelSimpleText:
    def test_single_short_word_is_low(self) -> None:
        """A single one-syllable word produces a near-zero score."""
        score = compute_reading_level("Hi.")
        assert score < 0.4, f"Expected low score, got {score}"

    def test_simple_sentence_is_low(self) -> None:
        score = compute_reading_level("The cat sat on the mat.")
        assert score < 0.5, f"Expected low score for simple text, got {score}"


class TestComputeReadingLevelComplexText:
    _COMPLEX = (
        "The multifaceted implications of socioeconomic stratification on "
        "educational attainment are extensively documented in contemporary "
        "empirical literature. Researchers hypothesize that systemic "
        "disparities perpetuate intergenerational inequality."
    )

    def test_complex_paragraph_score_above_threshold(self) -> None:
        score = compute_reading_level(self._COMPLEX)
        assert score > 0.3, f"Expected score > 0.3 for complex text, got {score}"

    def test_complex_in_unit_interval(self) -> None:
        score = compute_reading_level(self._COMPLEX)
        assert 0.0 <= score <= 1.0


class TestComputeReadingLevelRelativeOrdering:
    _SIMPLE = "I like dogs. Dogs are fun. My dog is big."
    _COMPLEX = (
        "Longitudinal investigations into cognitive developmental trajectories "
        "demonstrate statistically significant correlations between early "
        "linguistic exposure and subsequent academic performance metrics."
    )

    def test_simple_scores_lower_than_complex(self) -> None:
        simple_score = compute_reading_level(self._SIMPLE)
        complex_score = compute_reading_level(self._COMPLEX)
        assert simple_score < complex_score, (
            f"Expected simple ({simple_score:.3f}) < complex ({complex_score:.3f})"
        )


# ---------------------------------------------------------------------------
# _count_syllables (internal helper)
# ---------------------------------------------------------------------------


class TestCountSyllables:
    @pytest.mark.parametrize(
        "word, expected_min",
        [
            ("a", 1),
            ("the", 1),
            ("cat", 1),
            ("beautiful", 3),
            ("education", 4),
            ("multifaceted", 4),
        ],
    )
    def test_syllable_count_at_least(self, word: str, expected_min: int) -> None:
        count = _count_syllables(word)
        assert count >= expected_min, (
            f"_count_syllables({word!r}) = {count}, expected >= {expected_min}"
        )

    def test_returns_at_least_one_for_consonant_only_word(self) -> None:
        """Even a word with no vowels should return 1 (heuristic floor)."""
        assert _count_syllables("gym") >= 1

    def test_case_insensitive(self) -> None:
        assert _count_syllables("APPLE") == _count_syllables("apple")
