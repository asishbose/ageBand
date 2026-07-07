"""Unit tests for amd_check.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.orchestration.amd_check import (
    collect_amd_telemetry,
    verify_amd_endpoint,
)


class TestVerifyAmdEndpoint:
    def test_reachable_endpoint_succeeds(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "Qwen/Qwen2.5-7B-Instruct"}]}

        with patch("httpx.get", return_value=mock_response):
            verify_amd_endpoint(
                base_url="http://localhost:8000/v1",
                model="Qwen/Qwen2.5-7B-Instruct",
            )

    def test_unreachable_endpoint_raises_runtime_error(self) -> None:
        import httpx
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")), \
             pytest.raises(RuntimeError, match="not reachable"):
            verify_amd_endpoint(base_url="http://localhost:9999/v1")

    def test_http_error_raises_runtime_error(self) -> None:
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 503
        with patch(
            "httpx.get",
            side_effect=httpx.HTTPStatusError(
                "503", request=MagicMock(), response=mock_response
            ),
        ), pytest.raises(RuntimeError, match="503"):
            verify_amd_endpoint(base_url="http://localhost:8000/v1")

    def test_timeout_raises_runtime_error(self) -> None:
        import httpx
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")), \
             pytest.raises(RuntimeError, match="timed out"):
            verify_amd_endpoint(base_url="http://localhost:8000/v1")

    def test_model_not_found_raises_runtime_error(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "other-model"}]}

        with patch("httpx.get", return_value=mock_response), \
             pytest.raises(RuntimeError, match="not found"):
            verify_amd_endpoint(
                base_url="http://localhost:8000/v1",
                model="expected-model",
            )

    def test_no_model_check_when_model_empty(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": []}

        with patch("httpx.get", return_value=mock_response):
            # No model specified → no model check, should not raise
            verify_amd_endpoint(base_url="http://localhost:8000/v1", model="")


class TestCollectAmdTelemetryDegradePath:
    """Phase P1-D (Phase 04) requirement: explicit test for the no-GPU degrade path.

    The 'graceful degrade' path is the one most likely to be under-tested since
    it's the happy path in our offline CI. These tests confirm available=False
    is returned with the correct shape rather than raising or fabricating numbers.
    """

    def test_deterministic_mode_returns_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGEBAND_INFERENCE_MODE=deterministic → available=False, no GPU query."""
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
        monkeypatch.delenv("LOCAL_MODEL", raising=False)
        monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
        monkeypatch.delenv("ESTIMATOR_MODEL", raising=False)

        result = collect_amd_telemetry()

        assert result["available"] is False
        assert "reason" in result
        assert result["gpu_model"] == "unavailable"
        assert result["tok_per_sec"] == "N/A"

    def test_no_gpu_found_returns_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM mode, amd-smi not present, vLLM metrics unreachable → available=False."""
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")
        monkeypatch.setenv("LOCAL_MODEL", "some-model")

        # Both amd-smi and vllm metrics unavailable → degrade
        with (
            patch(
                "src.orchestration.amd_check._query_amd_smi",
                return_value={"available": False},
            ),
            patch(
                "src.orchestration.amd_check._scrape_vllm_metrics",
                return_value={},
            ),
            patch(
                "subprocess.run",
                side_effect=FileNotFoundError("binary not found"),
            ),
        ):
            result = collect_amd_telemetry()

        assert result["available"] is False
        assert "gpu_model" in result
        assert result["tok_per_sec"] == "N/A"
        assert result["running_requests"] == "N/A"

    def test_degrade_path_has_required_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All expected keys present even when degraded."""
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
        result = collect_amd_telemetry()

        required_keys = {
            "available", "gpu_model", "rocm_version",
            "vram_used_mb", "vram_total_mb", "tok_per_sec",
            "running_requests", "extractor_model", "estimator_model",
        }
        missing = required_keys - set(result.keys())
        assert not missing, f"Telemetry response missing keys: {missing}"
