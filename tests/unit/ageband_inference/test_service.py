"""Unit tests for AgeBandInferenceService (M4).

All LLM / tinyagent calls are bypassed via the _mock_response seam.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.ageband_inference.service import AgeBandInferenceService
from src.contracts.models import AgeBandEstimate, EvidenceSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence() -> EvidenceSummary:
    return EvidenceSummary(
        session_id="unit-test",
        cues=[],
        corroboration_score=0.7,
        turn_count=5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidEstimate:
    @pytest.mark.asyncio
    async def test_valid_dict_returns_ageband_estimate(self) -> None:
        mock = {
            "band": "teen",
            "cited_cues": ["uses slang", "mentions school"],
            "evasion_flag": False,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        result = await service.estimate(_evidence())

        assert isinstance(result, AgeBandEstimate)
        assert result.band == "teen"
        assert result.cited_cues == ["uses slang", "mentions school"]
        assert result.evasion_flag is False
        assert result.contradictions == []

    @pytest.mark.asyncio
    async def test_adult_band_is_returned_correctly(self) -> None:
        mock = {
            "band": "adult",
            "cited_cues": ["mentions mortgage"],
            "evasion_flag": False,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        result = await service.estimate(_evidence())
        assert result.band == "adult"

    @pytest.mark.asyncio
    async def test_unknown_band_with_empty_cues(self) -> None:
        mock: dict[str, object] = {
            "band": "unknown",
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        result = await service.estimate(_evidence())
        assert result.band == "unknown"
        assert result.cited_cues == []

    @pytest.mark.asyncio
    async def test_evasion_flag_true_is_passed_through(self) -> None:
        mock: dict[str, object] = {
            "band": "unknown",
            "cited_cues": [],
            "evasion_flag": True,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        result = await service.estimate(_evidence())
        assert result.evasion_flag is True


class TestForbiddenConfidenceKey:
    @pytest.mark.asyncio
    async def test_confidence_key_raises_value_error(self) -> None:
        mock: dict[str, object] = {
            "band": "teen",
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
            "confidence": 0.9,
        }
        service = AgeBandInferenceService(_mock_response=mock)
        with pytest.raises(ValueError, match="confidence"):
            await service.estimate(_evidence())

    @pytest.mark.asyncio
    async def test_confidence_score_key_raises_value_error(self) -> None:
        mock: dict[str, object] = {
            "band": "adult",
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
            "confidence_score": 0.75,
        }
        service = AgeBandInferenceService(_mock_response=mock)
        with pytest.raises(ValueError, match="confidence"):
            await service.estimate(_evidence())

    @pytest.mark.asyncio
    async def test_conf_key_raises_value_error(self) -> None:
        mock: dict[str, object] = {
            "band": "child",
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
            "conf": 0.5,
        }
        service = AgeBandInferenceService(_mock_response=mock)
        with pytest.raises(ValueError, match="confidence"):
            await service.estimate(_evidence())


class TestUnknownBandValidation:
    @pytest.mark.asyncio
    async def test_invalid_band_value_raises_validation_error(self) -> None:
        mock: dict[str, object] = {
            "band": "toddler",  # not a valid Literal
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        with pytest.raises(ValidationError):
            await service.estimate(_evidence())

    @pytest.mark.asyncio
    async def test_missing_band_field_raises_validation_error(self) -> None:
        mock: dict[str, object] = {
            "cited_cues": [],
            "evasion_flag": False,
            "contradictions": [],
        }
        service = AgeBandInferenceService(_mock_response=mock)
        with pytest.raises(ValidationError):
            await service.estimate(_evidence())
