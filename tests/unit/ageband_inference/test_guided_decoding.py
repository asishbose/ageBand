"""Unit tests for Phase 5 guided-decoding toggle in AgeBandInferenceService.

Verifies that:
1. GUIDED_DECODING_ENABLED=1 passes the JSON schema to complete_json.
2. GUIDED_DECODING_ENABLED unset/empty passes schema=None.
3. The schema excludes 'confidence' (design invariant).
4. All schema-allowed band values are valid AgeBandEstimate bands.
"""

from __future__ import annotations

import pytest

from src.ageband_inference.service import _ESTIMATOR_JSON_SCHEMA


class TestEstimatorJsonSchema:
    def test_schema_has_required_fields(self) -> None:
        required = set(_ESTIMATOR_JSON_SCHEMA.get("required", []))
        assert "band" in required
        assert "evasion_flag" in required
        assert "evasion_patterns" in required
        assert "cited_cues" in required

    def test_schema_excludes_confidence(self) -> None:
        """Invariant: the LLM must never emit a confidence value."""
        props = _ESTIMATOR_JSON_SCHEMA.get("properties", {})
        assert "confidence" not in props, (
            "confidence MUST NOT appear in _ESTIMATOR_JSON_SCHEMA; "
            "confidence is computed deterministically downstream."
        )

    def test_band_enum_values_match_model(self) -> None:
        from typing import get_args

        from src.contracts.models import AgeBandEstimate

        # Reflect the 'band' field's Literal type from AgeBandEstimate.
        band_field = AgeBandEstimate.model_fields["band"]
        annotation = band_field.annotation
        valid_bands = set(get_args(annotation))

        props = _ESTIMATOR_JSON_SCHEMA.get("properties", {})
        schema_bands = set(props.get("band", {}).get("enum", []))
        assert schema_bands == valid_bands, (
            f"Schema band enum {schema_bands} does not match "
            f"AgeBandEstimate.band Literal {valid_bands}"
        )

    def test_evasion_patterns_enum_matches_rule_estimator(self) -> None:
        from src.ageband_inference.rule_estimator import _MASKING_PATTERNS_ALL
        props = _ESTIMATOR_JSON_SCHEMA.get("properties", {})
        schema_patterns = set(
            props.get("evasion_patterns", {})
            .get("items", {})
            .get("enum", [])
        )
        assert schema_patterns == _MASKING_PATTERNS_ALL, (
            "Guided-decoding schema evasion_patterns enum must match "
            "the deterministic rule estimator's _MASKING_PATTERNS_ALL."
        )

    def test_additional_properties_false(self) -> None:
        """additionalProperties: false prevents the model from sneaking in extra keys."""
        assert _ESTIMATOR_JSON_SCHEMA.get("additionalProperties") is False


@pytest.mark.anyio
class TestGuidedDecodingToggle:
    async def test_schema_passed_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GUIDED_DECODING_ENABLED", "1")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")
        monkeypatch.setenv("LOCAL_MODEL", "test-model")

        captured: dict[str, object] = {}

        async def mock_complete_json(
            system_prompt: str,
            user_prompt: str,
            timeout: float = 60.0,
            model: str | None = None,
            json_schema: object = None,
        ) -> dict[str, object]:
            captured["json_schema"] = json_schema
            return {
                "band": "adult",
                "cited_cues": [],
                "evasion_flag": False,
                "evasion_patterns": [],
                "contradictions": [],
            }

        import src.ageband_inference.service as svc_module
        monkeypatch.setattr(
            svc_module,
            "_call_estimator_complete_json",
            mock_complete_json,
            raising=False,
        )

        # Directly test the internal path by calling _call_estimator with a
        # mock that patches complete_json at the import source.
        import src.contracts.llm_client as llm_module
        monkeypatch.setattr(llm_module, "complete_json", mock_complete_json)

        from src.ageband_inference.service import AgeBandInferenceService
        from src.contracts.models import EvidenceSummary

        svc = AgeBandInferenceService()
        evidence = EvidenceSummary(session_id="s", turn_count=3)
        await svc._call_estimator(evidence)

        assert captured.get("json_schema") == _ESTIMATOR_JSON_SCHEMA

    async def test_schema_not_passed_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GUIDED_DECODING_ENABLED", "")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")
        monkeypatch.setenv("LOCAL_MODEL", "test-model")

        captured: dict[str, object] = {}

        async def mock_complete_json(
            system_prompt: str,
            user_prompt: str,
            timeout: float = 60.0,
            model: str | None = None,
            json_schema: object = None,
        ) -> dict[str, object]:
            captured["json_schema"] = json_schema
            return {
                "band": "unknown",
                "cited_cues": [],
                "evasion_flag": False,
                "evasion_patterns": [],
                "contradictions": [],
            }

        import src.contracts.llm_client as llm_module
        monkeypatch.setattr(llm_module, "complete_json", mock_complete_json)

        from src.ageband_inference.service import AgeBandInferenceService
        from src.contracts.models import EvidenceSummary

        svc = AgeBandInferenceService()
        evidence = EvidenceSummary(session_id="s2", turn_count=1)
        await svc._call_estimator(evidence)

        assert captured.get("json_schema") is None
