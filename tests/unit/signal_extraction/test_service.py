"""Unit tests for SignalExtractorService (M2).

All tests use the _mock_response seam — no LLM calls are made.

Coverage targets:
- Valid SignalSet dict → parsed correctly
- Invalid JSON structure → ValidationError
- Extra field (LLM hallucination) → rejected by extra="forbid"
- Empty cues list is valid
- Multiple cues with all valid types
- Protocol compliance
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.contracts.models import SignalSet, TurnEvent
from src.contracts.protocols import ISignalExtractor
from src.signal_extraction.service import SignalExtractorService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _turn(**kwargs: object) -> TurnEvent:
    """Build a TurnEvent with sensible defaults."""
    defaults: dict[str, object] = {
        "session_id": "sess-test",
        "turn_text": "I have homework due tomorrow.",
        "turn_number": 1,
    }
    defaults.update(kwargs)
    return TurnEvent(**defaults)  # type: ignore[arg-type]


def _service(mock: dict[str, object]) -> SignalExtractorService:
    return SignalExtractorService(_mock_response=mock)


# ---------------------------------------------------------------------------
# Valid responses
# ---------------------------------------------------------------------------


class TestSignalExtractorServiceValidResponse:
    @pytest.mark.asyncio
    async def test_valid_single_cue_parsed(self) -> None:
        mock = {
            "cues": [
                {"type": "topic", "value": "mentions homework", "weight": 0.75}
            ]
        }
        result = await _service(mock).extract(_turn())
        assert isinstance(result, SignalSet)
        assert len(result.cues) == 1
        assert result.cues[0].type == "topic"
        assert result.cues[0].value == "mentions homework"
        # Weight is re-stamped deterministically from the lexicon (school_topic),
        # NOT the LLM-provided 0.75 — the model detects a cue, Python weights it.
        assert result.cues[0].subtype == "school_topic"
        assert result.cues[0].weight == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_empty_cues_list_is_valid(self) -> None:
        mock: dict[str, object] = {"cues": []}
        result = await _service(mock).extract(_turn())
        assert isinstance(result, SignalSet)
        assert result.cues == []

    @pytest.mark.asyncio
    async def test_multiple_cues_all_types_parsed(self) -> None:
        mock = {
            "cues": [
                {"type": "disclosure", "value": "I am 13", "weight": 0.9},
                {"type": "vocab", "value": "simple word choice", "weight": 0.4},
                {"type": "style", "value": "informal tone", "weight": 0.3},
                {"type": "reading_level", "value": "0.18", "weight": 0.3},
                {"type": "topic", "value": "mentioned curfew", "weight": 0.7},
            ]
        }
        result = await _service(mock).extract(_turn())
        assert len(result.cues) == 5
        types = {c.type for c in result.cues}
        assert types == {"disclosure", "vocab", "style", "reading_level", "topic"}

    @pytest.mark.asyncio
    async def test_weight_boundaries_accepted(self) -> None:
        mock = {
            "cues": [
                {"type": "vocab", "value": "min weight", "weight": 0.0},
                {"type": "vocab", "value": "max weight", "weight": 1.0},
            ]
        }
        result = await _service(mock).extract(_turn())
        assert result.cues[0].weight == pytest.approx(0.0)
        assert result.cues[1].weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Invalid responses — ValidationError expected
# ---------------------------------------------------------------------------


class TestSignalExtractorServiceInvalidResponse:
    @pytest.mark.asyncio
    async def test_null_cues_value_raises_validation_error(self) -> None:
        """cues=None cannot be coerced to list[Cue] → ValidationError."""
        mock: dict[str, object] = {"cues": None}
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())

    @pytest.mark.asyncio
    async def test_extra_field_on_signal_set_raises_validation_error(self) -> None:
        """Top-level hallucination key is rejected by extra='forbid'."""
        mock: dict[str, object] = {
            "cues": [],
            "confidence": 0.8,  # LLM hallucination — must be rejected
        }
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())

    @pytest.mark.asyncio
    async def test_extra_field_on_cue_raises_validation_error(self) -> None:
        """Extra key on a Cue is rejected by extra='forbid'."""
        mock: dict[str, object] = {
            "cues": [
                {
                    "type": "topic",
                    "value": "school",
                    "weight": 0.5,
                    "band_guess": "child",  # hallucinated extra key
                }
            ]
        }
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())

    @pytest.mark.asyncio
    async def test_invalid_cue_type_raises_validation_error(self) -> None:
        mock: dict[str, object] = {
            "cues": [
                {"type": "unknown_type", "value": "something", "weight": 0.5}
            ]
        }
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())

    @pytest.mark.asyncio
    async def test_weight_out_of_range_raises_validation_error(self) -> None:
        mock: dict[str, object] = {
            "cues": [
                {"type": "vocab", "value": "over-weighted", "weight": 1.5}
            ]
        }
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())

    @pytest.mark.asyncio
    async def test_cues_not_a_list_raises_validation_error(self) -> None:
        mock: dict[str, object] = {"cues": "not a list"}
        with pytest.raises(ValidationError):
            await _service(mock).extract(_turn())


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestSignalExtractorServiceProtocol:
    def test_satisfies_isignal_extractor_protocol(self) -> None:
        svc = SignalExtractorService()
        assert isinstance(svc, ISignalExtractor)
