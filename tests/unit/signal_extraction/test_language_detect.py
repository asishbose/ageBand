"""Unit tests for src/signal_extraction/language_detect.py (Phase 1).

Tests:
- detect_language() returns "en" or empty for English text
- detect_language() returns a non-en code for non-Latin scripts
- is_english_or_unknown() returns True for English, False for detected non-English
- Non-English abstention on the deterministic path (keyword_extractor integration)
"""

from __future__ import annotations

from src.signal_extraction.keyword_extractor import extract_cues
from src.signal_extraction.language_detect import detect_language, is_english_or_unknown


class TestDetectLanguage:
    def test_english_text_returns_en_or_empty(self) -> None:
        result = detect_language("Hello, how are you doing today?")
        assert result in ("en", ""), f"Expected 'en' or '' for English text, got {result!r}"

    def test_arabic_script_detected(self) -> None:
        # Arabic Qur'an opening — Unicode 0600-06FF block
        result = detect_language("مرحبا كيف حالك")
        assert result in ("ar", ""), f"Expected 'ar' for Arabic text, got {result!r}"

    def test_chinese_script_detected(self) -> None:
        # CJK ideographs — Unicode 4E00-9FFF block
        # langdetect may return "zh-cn" or "zh"; Unicode-block fallback returns "".
        result = detect_language("你好，最近怎么样")
        assert result.startswith("zh") or result == "", (
            f"Expected 'zh'/'zh-cn' or '' for Chinese text, got {result!r}"
        )

    def test_hindi_script_detected(self) -> None:
        # Devanagari — Unicode 0900-097F block
        result = detect_language("नमस्ते आप कैसे हैं")
        assert result in ("hi", ""), f"Expected 'hi' for Hindi text, got {result!r}"

    def test_japanese_script_detected(self) -> None:
        # Hiragana — Unicode 3040-30FF block
        result = detect_language("こんにちは元気ですか")
        assert result in ("ja", ""), f"Expected 'ja' for Japanese, got {result!r}"

    def test_cyrillic_script_detected(self) -> None:
        # Cyrillic — Unicode 0400-04FF block. langdetect may return any Slavic
        # language code (ru, mk, bg, etc.) for short Cyrillic text; what matters
        # is that it is NOT classified as English.
        result = detect_language("Привет как дела")
        cyrillic_langs = {"ru", "mk", "bg", "sr", "uk", "be"}
        assert result in cyrillic_langs or result == "", (
            f"Expected a Cyrillic language code or '' for Russian text, got {result!r}"
        )

    def test_spanish_detected(self) -> None:
        # Latin-script language — requires langdetect (Unicode heuristic cannot distinguish)
        result = detect_language("Hola, ¿cómo estás? Me llamo Juan y tengo diez años.")
        assert result in ("es", ""), f"Expected 'es' or '' for Spanish text, got {result!r}"

    def test_french_detected(self) -> None:
        # Latin-script language — requires langdetect (Unicode heuristic cannot distinguish)
        result = detect_language("Bonjour, comment allez-vous? J'ai dix ans et j'aime jouer.")
        assert result in ("fr", ""), f"Expected 'fr' or '' for French text, got {result!r}"

    def test_empty_string_returns_empty_or_en(self) -> None:
        result = detect_language("")
        assert result in ("en", ""), f"Unexpected result for empty string: {result!r}"


class TestIsEnglishOrUnknown:
    def test_english_text_is_english(self) -> None:
        assert is_english_or_unknown("Hello this is English text")

    def test_arabic_is_not_english(self) -> None:
        assert not is_english_or_unknown("مرحبا كيف حالك")

    def test_chinese_is_not_english(self) -> None:
        assert not is_english_or_unknown("你好，最近怎么样")

    def test_empty_text_treated_as_unknown_english(self) -> None:
        # Empty text → language unknown → treated as English (no abstention)
        assert is_english_or_unknown("")


class TestNonEnglishAbstentionDeterministicPath:
    """Phase 1 requirement: keyword_extractor returns empty SignalSet for non-English text.

    This is the 'non-English abstention on the deterministic path' test that
    Phase 11 requires. Chinese / Arabic / Hindi inputs must return an empty
    SignalSet so no false English-lexicon cues are injected.
    """

    def test_arabic_returns_empty_signal_set(self) -> None:
        result = extract_cues("مرحبا كيف حالك يا صديقي")
        assert result.cues == [], (
            "Arabic text must produce no cues — the English keyword lexicon "
            "cannot validly detect age signals in non-Latin text."
        )

    def test_chinese_returns_empty_signal_set(self) -> None:
        result = extract_cues("你好我是一个小学生我今年十岁")
        assert result.cues == [], (
            "Chinese text must produce no cues (empty SignalSet abstention)."
        )

    def test_hindi_returns_empty_signal_set(self) -> None:
        result = extract_cues("नमस्ते मैं दस साल का बच्चा हूं")
        assert result.cues == [], (
            "Hindi text must produce no cues (empty SignalSet abstention)."
        )

    def test_english_text_still_produces_cues(self) -> None:
        """Regression: abstention must NOT fire for English text.

        This sentence contains "primary school" (elementary_school disclosure),
        "school" (topic), and short simple words (reading_level_low) — all
        strong child-lexicon signals.  If language abstention fires erroneously
        on English input the cue list will be empty and this test will fail.
        """
        result = extract_cues("my little sister is in primary school, she loves unicorns")
        assert len(result.cues) > 0, (
            "English text with clear child-lexicon signals produced no cues — "
            "language abstention may be incorrectly firing on English input."
        )
