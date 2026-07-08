"""Unit tests for src/contracts/embeddings_client.py (Phase 5).

All tests run offline — no real HTTP calls. The online path (update_session_similarity
with a live endpoint) is tested via unittest.mock.patch on httpx.AsyncClient.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contracts.embeddings_client import (
    _session_vectors,
    centroid,
    cosine_similarity,
    embeddings_available,
    update_session_similarity,
)

# ---------------------------------------------------------------------------
# Pure maths helpers
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_one(self) -> None:
        # Zero-norm → neutral (no drift penalty).
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_arbitrary_vectors(self) -> None:
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert cosine_similarity(a, b) == pytest.approx(expected, rel=1e-5)


class TestCentroid:
    def test_single_vector(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert centroid([v]) == pytest.approx(v)

    def test_two_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert centroid([a, b]) == pytest.approx([0.5, 0.5])

    def test_empty_returns_empty(self) -> None:
        assert centroid([]) == []


# ---------------------------------------------------------------------------
# embeddings_available() — offline / no env
# ---------------------------------------------------------------------------


class TestEmbeddingsAvailable:
    def test_returns_false_when_no_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "auto")
        monkeypatch.delenv("LOCAL_MODEL", raising=False)
        monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
        monkeypatch.delenv("ESTIMATOR_MODEL", raising=False)
        assert embeddings_available() is False

    def test_returns_false_in_deterministic_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
        assert embeddings_available() is False

    def test_returns_true_with_model_and_llm_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")
        assert embeddings_available() is True


# ---------------------------------------------------------------------------
# update_session_similarity() — no EMBEDDING_MODEL → returns None (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestUpdateSessionSimilarityOffline:
    async def test_returns_none_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
        result = await update_session_similarity("session_offline_x", "hello world")
        assert result is None

    async def test_returns_none_in_deterministic_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "some-model")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")
        result = await update_session_similarity("session_offline_y", "hello world")
        assert result is None


# ---------------------------------------------------------------------------
# update_session_similarity() — mocked HTTP (online path)
# ---------------------------------------------------------------------------


def _mock_embed_response(vec: list[float]) -> MagicMock:
    """Build a mock httpx response returning *vec* as an embedding."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"embedding": vec}]}
    return mock_resp


@pytest.mark.anyio
class TestUpdateSessionSimilarityOnline:
    async def test_first_turn_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First turn: no history → similarity 1.0 by convention."""
        monkeypatch.setenv("EMBEDDING_MODEL", "test-model")
        monkeypatch.setenv("EMBEDDING_API_BASE", "http://embed-test/v1")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")

        session_id = "new_session_first_turn_test"
        _session_vectors.pop(session_id, None)

        mock_vec = [1.0, 0.0, 0.0]
        mock_post = AsyncMock(return_value=_mock_embed_response(mock_vec))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            sim = await update_session_similarity(session_id, "hi there")

        assert sim == pytest.approx(1.0)
        assert session_id in _session_vectors

    async def test_second_turn_identical_vector_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second turn with identical vector → similarity 1.0."""
        monkeypatch.setenv("EMBEDDING_MODEL", "test-model")
        monkeypatch.setenv("EMBEDDING_API_BASE", "http://embed-test/v1")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")

        session_id = "session_second_turn_identical"
        _session_vectors.pop(session_id, None)

        mock_vec = [0.6, 0.8, 0.0]

        async def _run_one_turn() -> float | None:
            mock_post = AsyncMock(return_value=_mock_embed_response(mock_vec))
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = mock_post
                mock_client_cls.return_value = mock_client
                return await update_session_similarity(session_id, "a message")

        await _run_one_turn()  # seed
        sim = await _run_one_turn()  # second identical turn

        assert sim == pytest.approx(1.0)

    async def test_network_error_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network error → graceful None (no penalty)."""
        import httpx as httpx_lib

        monkeypatch.setenv("EMBEDDING_MODEL", "test-model")
        monkeypatch.setenv("EMBEDDING_API_BASE", "http://embed-fail/v1")
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "llm")

        session_id = "session_error_test"
        _session_vectors.pop(session_id, None)

        mock_post = AsyncMock(side_effect=httpx_lib.ConnectError("refused"))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            sim = await update_session_similarity(session_id, "message")

        assert sim is None
