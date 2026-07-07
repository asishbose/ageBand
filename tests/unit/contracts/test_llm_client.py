"""Unit tests for src/contracts/llm_client.py.

All tests mock httpx.AsyncClient so no real network call is made.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contracts.llm_client import _parse_json, complete_json

# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_clean_json_object(self) -> None:
        result = _parse_json('{"band": "child", "cues": []}')
        assert result == {"band": "child", "cues": []}

    def test_fenced_json_block(self) -> None:
        result = _parse_json('```json\n{"band": "teen"}\n```')
        assert result == {"band": "teen"}

    def test_fenced_json_no_lang_tag(self) -> None:
        result = _parse_json("```\n{\"x\": 1}\n```")
        assert result == {"x": 1}

    def test_brace_scan_fallback(self) -> None:
        # Model wraps JSON in prose — brace scan should recover it.
        result = _parse_json('Here is the output: {"band": "adult"} end.')
        assert result == {"band": "adult"}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_json("not json at all")


# ---------------------------------------------------------------------------
# complete_json
# ---------------------------------------------------------------------------


def _mock_response(content: str, status_code: int = 200) -> MagicMock:
    """Build a minimal mock for an httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = Exception(
            f"HTTP {status_code}"
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestCompleteJson:
    @pytest.mark.asyncio
    async def test_success_returns_parsed_dict(self) -> None:
        mock_resp = _mock_response('{"band": "child"}')
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("src.contracts.llm_client.httpx.AsyncClient", return_value=mock_client),
            patch.dict("os.environ", {"LOCAL_MODEL": "test-model"}),
        ):
            result = await complete_json("sys", "user")

        assert result == {"band": "child"}

    @pytest.mark.asyncio
    async def test_raises_when_local_model_unset(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LOCAL_MODEL"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(RuntimeError, match="LOCAL_MODEL"),
        ):
            await complete_json("sys", "user")

    @pytest.mark.asyncio
    async def test_non_200_propagates_exception(self) -> None:
        mock_resp = _mock_response("", status_code=503)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("src.contracts.llm_client.httpx.AsyncClient", return_value=mock_client),
            patch.dict("os.environ", {"LOCAL_MODEL": "test-model"}),
            pytest.raises(Exception, match="HTTP 503"),
        ):
            await complete_json("sys", "user")

    @pytest.mark.asyncio
    async def test_model_wraps_json_in_fence(self) -> None:
        mock_resp = _mock_response("```json\n{\"band\": \"adult\"}\n```")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("src.contracts.llm_client.httpx.AsyncClient", return_value=mock_client),
            patch.dict("os.environ", {"LOCAL_MODEL": "test-model"}),
        ):
            result = await complete_json("sys", "user")

        assert result == {"band": "adult"}
