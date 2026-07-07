"""Lightweight language detection for incoming turn text (M2).

Detects whether the turn is in English or another language so the LLM extraction
path can pass a language hint to the signal_extractor prompt, and so the
deterministic keyword_extractor can explicitly abstain (return empty SignalSet)
rather than silently mis-scanning non-English text with the English lexicon.

Design decisions:
- Uses langdetect when available; falls back to a fast ASCII-ratio heuristic
  for environments where langdetect is not installed.
- Returns a language code (BCP-47 style, e.g. "en", "es", "hi") or "" when
  detection is not possible (text is too short, all punctuation, etc.).
- Very short turns (< MIN_CHARS) return "" (undetermined) — not enough signal.
- The abstention guard for the deterministic path uses ``is_english_or_unknown``
  so that "undetermined" passes through rather than silently dropping cues.

Supported target languages for eval_multilang.py: en, es, hi, fr, ar, zh.
"""

from __future__ import annotations

import re

# Minimum character count to attempt any detection.
MIN_CHARS: int = 8

# Minimum character count before trusting langdetect for Latin-script text.
# langdetect is unreliable on very short Latin-script text (e.g. "i am fine"
# → "no", "my mom said homework" → "no"). Non-Latin scripts are handled before
# langdetect via the Unicode-block heuristic, which is reliable at any length.
LANGDETECT_MIN_CHARS: int = 50

# ASCII-heavy text (> this fraction of printable chars being ASCII) is treated
# as likely English when langdetect is unavailable or text is too short.
_ASCII_RATIO_THRESHOLD: float = 0.85


def _ascii_ratio(text: str) -> float:
    """Fraction of printable characters that are in the 7-bit ASCII range."""
    printable = [c for c in text if c.isprintable() and not c.isspace()]
    if not printable:
        return 1.0
    return sum(1 for c in printable if ord(c) < 128) / len(printable)


# Unicode ranges for non-Latin scripts. Presence of characters in any of these
# ranges is a reliable signal that the text is NOT English (requires no library).
_NON_LATIN_RANGES: list[tuple[int, int, str]] = [
    (0x0600, 0x06FF, "ar"),   # Arabic
    (0x0900, 0x097F, "hi"),   # Devanagari (Hindi/Marathi/Nepali/Sanskrit)
    (0x4E00, 0x9FFF, "zh"),   # CJK Unified Ideographs (Chinese/Japanese/Korean)
    (0x3040, 0x30FF, "ja"),   # Hiragana / Katakana (Japanese)
    (0xAC00, 0xD7AF, "ko"),   # Hangul (Korean)
    (0x0400, 0x04FF, "ru"),   # Cyrillic (Russian/Ukrainian/Bulgarian etc.)
    (0x0590, 0x05FF, "he"),   # Hebrew
    (0x0E00, 0x0E7F, "th"),   # Thai
]


def _detect_by_script(text: str) -> str:
    """Fast Unicode-block based script detection (no library needed).

    Returns a language code when a non-Latin script is detected confidently,
    "" otherwise (Latin script / mixed / undetermined).
    """
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lo, hi, lang in _NON_LATIN_RANGES:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return ""
    # A script with at least 3 characters is a confident non-English signal.
    dominant = max(counts, key=lambda k: counts[k])
    return dominant if counts[dominant] >= 3 else ""


def detect_language(text: str) -> str:
    """Return a BCP-47 language code for *text*, or '' if undetermined.

    Args:
        text: A single chat turn.

    Returns:
        ISO 639-1 language code (e.g. "en", "es", "hi", "fr", "ar", "zh"),
        or "" when confidence is too low or the text is too short to detect.

    Detection priority:
        1. langdetect (if installed — pip install langdetect)
        2. Unicode-block heuristic (handles CJK, Arabic, Devanagari, Cyrillic)
        3. ASCII-ratio heuristic (handles Latin-script non-English as English —
           acceptable because the keyword lexicon won't false-positive on them)
    """
    # Strip whitespace; skip very short text.
    stripped = re.sub(r"\s+", " ", text).strip()
    if len(stripped) < MIN_CHARS:
        return ""

    # Priority 1: Unicode-block detection — fast, reliable at any length for
    # non-Latin scripts (CJK, Arabic, Devanagari, Cyrillic, etc.). Run BEFORE
    # langdetect because langdetect is unreliable on short Latin-script text.
    script_lang = _detect_by_script(stripped)
    if script_lang:
        return script_lang

    # Priority 2: langdetect for Latin-script languages (es/fr/de/pt etc.) —
    # only when text is long enough to be reliable. Short Latin-script text
    # (< LANGDETECT_MIN_CHARS) falls through to the ASCII-ratio heuristic,
    # which correctly passes it as English/unknown.
    if len(stripped) >= LANGDETECT_MIN_CHARS:
        try:
            from langdetect import LangDetectException, detect
            try:
                return str(detect(stripped))
            except LangDetectException:
                pass
        except ImportError:
            pass

    # Priority 3: ASCII-ratio heuristic for short Latin-script text.
    # If text is actually Spanish/French etc. but short, the keyword_extractor
    # won't produce false strong-type cues (only reading_level fires, which is
    # weak and excluded from band establishment by STRONG_CUE_TYPES).
    if _ascii_ratio(stripped) > _ASCII_RATIO_THRESHOLD:
        return "en"

    # Undetermined.
    return ""


def is_english_or_unknown(text: str) -> bool:
    """Return True when the turn is English or language cannot be determined.

    Used by the deterministic keyword_extractor to decide whether to run
    the English lexicon scan. We abstain on confidently non-English/non-Latin
    script text — CJK, Arabic, Devanagari etc. — where the English lexicon
    would produce structurally false signals. Latin-script non-English text
    (Spanish, French, etc.) is passed through because the English keyword
    lexicon won't produce strong-type false positives on it (only the
    reading_level scorer may fire, which is weak and non-band-establishing).
    """
    lang = detect_language(text)
    return lang in ("", "en")
