"""Lightweight embeddings client for cross-turn persona consistency (Phase 5).

Calls an OpenAI-compatible /embeddings endpoint to compute turn embeddings,
then tracks cosine similarity to a running session centroid. A degrading
similarity score feeds into _compute_uncertainty() as an additional penalty
factor.

**Neutral no-op when offline:** if no embedding endpoint is configured
(EMBEDDING_MODEL is unset or AGEBAND_INFERENCE_MODE=deterministic), all
functions return a similarity of 1.0 (maximum — no penalty) so the
offline pipeline is completely unaffected. This is the same "graceful
degrade to neutral" pattern as use_llm() in contracts/runtime.py.

Env:
    EMBEDDING_API_BASE   base URL for the embeddings endpoint (defaults to
                         LOCAL_API_BASE — same vLLM process can serve both)
    EMBEDDING_MODEL      model id for embeddings (e.g. "BAAI/bge-small-en-v1.5")
                         A small lightweight model is sufficient; no need for
                         the full 27B estimator model.
    EMBEDDING_API_KEY    bearer token (defaults to LOCAL_API_KEY)
"""

from __future__ import annotations

import math
import os
from typing import Any

import httpx


def _embedding_endpoint() -> tuple[str, str, str]:
    base = (
        os.environ.get("EMBEDDING_API_BASE", "")
        or os.environ.get("LOCAL_API_BASE", "http://localhost:8000/v1")
    )
    model = os.environ.get("EMBEDDING_MODEL", "")
    key = (
        os.environ.get("EMBEDDING_API_KEY", "")
        or os.environ.get("LOCAL_API_KEY", "EMPTY")
    )
    return base.rstrip("/"), model, key


def embeddings_available() -> bool:
    """Return True when an embedding model is configured."""
    from src.contracts.runtime import use_llm
    _, model, _ = _embedding_endpoint()
    return bool(model) and use_llm()


async def embed_text(text: str, timeout: float = 10.0) -> list[float] | None:
    """Request an embedding vector for *text*.

    Returns None on any error (network, model not available) so callers can
    treat it as a graceful missing-signal rather than an exception.
    """
    base, model, key = _embedding_endpoint()
    if not model:
        return None

    payload: dict[str, Any] = {"model": model, "input": text}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/embeddings", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        vec: list[float] = data["data"][0]["embedding"]
        return vec
    except Exception:  # noqa: BLE001 — treat all errors as "signal unavailable"
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (clipped to [-1.0, 1.0])."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return max(-1.0, min(dot / (norm_a * norm_b), 1.0))


def centroid(vectors: list[list[float]]) -> list[float]:
    """Component-wise mean of a list of vectors."""
    if not vectors:
        return []
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


# ---------------------------------------------------------------------------
# Session embedding store — ephemeral in-process dict (same lifecycle as
# EphemeralStore in evidence_fabric/store.py; cleared on process restart).
# ---------------------------------------------------------------------------

_session_vectors: dict[str, list[list[float]]] = {}


async def update_session_similarity(
    session_id: str,
    turn_text: str,
) -> float | None:
    """Embed *turn_text*, update the session centroid, return cosine similarity.

    Returns None when embeddings are not available (offline / no EMBEDDING_MODEL).
    Callers should treat None as "no penalty" (neutral 1.0 similarity).

    Side-effect: appends the new vector to ``_session_vectors[session_id]``.
    """
    if not embeddings_available():
        return None

    vec = await embed_text(turn_text)
    if vec is None:
        return None

    history = _session_vectors.setdefault(session_id, [])
    if history:
        existing_centroid = centroid(history)
        sim = cosine_similarity(vec, existing_centroid)
    else:
        # First turn — no prior centroid; similarity is 1.0 by convention
        # (no drift yet, no penalty).
        sim = 1.0

    history.append(vec)
    return sim
