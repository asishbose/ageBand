"""Unit tests for amd_check.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.orchestration.amd_check import verify_amd_endpoint


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
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="not reachable"):
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
        ):
            with pytest.raises(RuntimeError, match="503"):
                verify_amd_endpoint(base_url="http://localhost:8000/v1")

    def test_timeout_raises_runtime_error(self) -> None:
        import httpx
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RuntimeError, match="timed out"):
                verify_amd_endpoint(base_url="http://localhost:8000/v1")

    def test_model_not_found_raises_runtime_error(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "other-model"}]}

        with patch("httpx.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="not found"):
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
