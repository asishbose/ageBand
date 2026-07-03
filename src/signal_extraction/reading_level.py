"""Deterministic Flesch-Kincaid reading level for signal extraction (M2).

Pure Python — no LLM calls, no external I/O.
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
_VOWEL_RUN_RE = re.compile(r"[aeiou]+")
_FK_DIVISOR: float = 16.0
_FK_WORD_COEFF: float = 0.39
_FK_SYLLABLE_COEFF: float = 11.8
_FK_INTERCEPT: float = 15.59


def compute_reading_level(text: str) -> float:
    """Return a Flesch-Kincaid grade normalised to [0.0, 1.0].

    Higher score = harder text (more adult-like).

    Algorithm:
    1. Count sentences (split on [.!?]+)
    2. Count words (split on whitespace, filter empty)
    3. Count syllables (vowel-group heuristic via _count_syllables)
    4. ASL = words / max(sentences, 1)
    5. ASW = syllables / max(words, 1)
    6. FK_grade = 0.39 * ASL + 11.8 * ASW - 15.59
    7. Normalise: clamp(FK_grade / 16.0, 0.0, 1.0)

    Empty text → 0.0.
    """
    words = _tokenise_words(text)
    if not words:
        return 0.0
    sentence_count = _count_sentences(text)
    return _fk_score(words, sentence_count)


def _tokenise_words(text: str) -> list[str]:
    """Return non-empty whitespace tokens from *text*."""
    return [w for w in text.strip().split() if w]


def _count_sentences(text: str) -> int:
    """Return number of sentences (floor 1) by splitting on [.!?]+."""
    parts = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    return max(len(parts), 1)


def _fk_score(words: list[str], sentence_count: int) -> float:
    """Compute normalised FK grade from word list and sentence count."""
    word_count = len(words)
    syllable_count = sum(_count_syllables(w) for w in words)
    asl = word_count / sentence_count
    asw = syllable_count / word_count
    fk_grade = _FK_WORD_COEFF * asl + _FK_SYLLABLE_COEFF * asw - _FK_INTERCEPT
    return max(0.0, min(fk_grade / _FK_DIVISOR, 1.0))


def _count_syllables(word: str) -> int:
    """Count syllable groups in a word using a vowel-run heuristic."""
    cleaned = word.lower()
    vowels = _VOWEL_RUN_RE.findall(cleaned)
    return max(len(vowels), 1)
