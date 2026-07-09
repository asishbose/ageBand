"""Minimal OpenAI-compatible JSON completion client.

Talks to any OpenAI-compatible ``/chat/completions`` endpoint — Ollama
(``http://localhost:11434/v1``), vLLM on AMD ROCm, or Fireworks — so the LLM
delegates can run against local Llama/Gemma or a hosted model with only an
env-var change. No SDK dependency; uses httpx (already a project dep).

Env:
    LOCAL_API_BASE      base URL incl. /v1 (default http://localhost:11434/v1)
    LOCAL_MODEL         model id (e.g. "gemma3:4b"); serves as fallback for
                        per-delegate model vars below
    LOCAL_API_KEY       bearer token ("EMPTY"/unset for Ollama/local vLLM)

Per-delegate model overrides (both fall back to LOCAL_MODEL when unset):
    EXTRACTOR_MODEL     model id for the signal-extraction (M2) delegate
                        (e.g. "gemma3:4b" — smaller model, lower latency)
    ESTIMATOR_MODEL     model id for the age-band-estimation (M4) delegate
                        (e.g. "gemma3:27b" — larger model, better nuance)

Using two different models for M2 and M4 lets a small extractor run at low cost
while the estimator benefits from a higher-capacity model for the ambiguous_adult
and adversarial scenarios where reasoning quality matters most. Both still resolve
against the same LOCAL_API_BASE endpoint (one vLLM instance can serve multiple
LoRA adapters or model shards; alternatively two vLLM processes share a GPU).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Bounded retry config for complete_json.
# 2 retries → up to 3 total attempts. Backoff: 0.5s, 1.0s.
# Motivation: model_comparison.md noted one gemma4:31b call returning unparseable
# JSON (fail-closed; correct) — a bounded retry eliminates that waste without
# masking real failures. Retries only on transient errors (network, 5xx, JSON parse);
# 4xx errors (bad request, auth) are NOT retried.
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF_BASE: float = 0.5  # seconds; doubles each attempt

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _endpoint(model_override: str | None = None) -> tuple[str, str, str]:
    """Return (base_url, model_id, api_key).

    *model_override* — when provided, use this model id instead of LOCAL_MODEL.
    Falls back to LOCAL_MODEL if model_override is empty/None.
    """
    base = os.environ.get("LOCAL_API_BASE", "http://localhost:11434/v1")
    model: str = model_override if model_override else os.environ.get("LOCAL_MODEL", "")
    key = os.environ.get("LOCAL_API_KEY", "EMPTY")
    return base.rstrip("/"), model, key


def extractor_model() -> str:
    """Model id to use for the M2 signal-extraction delegate.

    Returns EXTRACTOR_MODEL if set, else falls back to LOCAL_MODEL.
    """
    return os.environ.get("EXTRACTOR_MODEL", "") or os.environ.get("LOCAL_MODEL", "")


def estimator_model() -> str:
    """Model id to use for the M4 age-band-estimation delegate.

    Returns ESTIMATOR_MODEL if set, else falls back to LOCAL_MODEL.
    """
    return os.environ.get("ESTIMATOR_MODEL", "") or os.environ.get("LOCAL_MODEL", "")


def _parse_json(content: str) -> dict[str, object]:
    """Best-effort: pull a JSON object out of a model's text response."""
    fence = _JSON_FENCE_RE.search(content)
    if fence:
        content = fence.group(1)
    content = content.strip()
    try:
        result: dict[str, object] = json.loads(content)
        return result
    except json.JSONDecodeError:
        # Fall back to the first balanced {...} span.
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            result = json.loads(content[start : end + 1])
            return result
        raise


async def complete_json(
    system_prompt: str,
    user_prompt: str,
    timeout: float = 60.0,
    model: str | None = None,
    json_schema: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Call the chat endpoint and return the parsed JSON object from the reply.

    Includes bounded retry (up to ``_RETRY_ATTEMPTS`` total attempts) with
    exponential backoff for transient errors (network errors, 5xx, JSON parse
    failures). Client errors (4xx) are not retried — they indicate a bad request.

    Args:
        system_prompt: The system instruction.
        user_prompt: The user turn content.
        timeout: HTTP request timeout in seconds (per attempt).
        model: Optional model id override — uses LOCAL_MODEL when not given.
               Pass ``extractor_model()`` or ``estimator_model()`` for
               per-delegate model selection.
        json_schema: Optional JSON Schema dict for guided decoding
                     (``response_format={"type":"json_schema","json_schema":...}``).
                     When None, falls back to ``{"type":"json_object"}``.

    Bounded retry proposal (Phase 0):
        _RETRY_ATTEMPTS = 3, backoff = 0.5s × 2^attempt.
        Rationale: model_comparison.md noted one Gemma 4:31B call returning
        unparseable JSON (fail-closed; correct behaviour, but a wasted GPU call).
        A 2-retry window recovers transient parse failures without masking
        persistent errors or inflating p95 latency beyond ~2s overhead.
    """
    base, resolved_model, key = _endpoint(model)
    if not resolved_model:
        raise RuntimeError("LOCAL_MODEL is not set; cannot call the LLM endpoint.")

    # response_format drives vLLM's guided-decoding (xgrammar) engine. Some ROCm/vLLM
    # builds ship a broken xgrammar (nanobind refcount crash on JSON-grammar compile) that
    # takes the whole server down. Set AGEBAND_NO_RESPONSE_FORMAT=1 to skip it entirely —
    # the model still returns JSON via the prompt and _parse_json extracts it (with retry).
    response_format: dict[str, object] | None
    if json_schema is not None:
        response_format = {"type": "json_schema", "json_schema": json_schema}
    elif os.environ.get("AGEBAND_NO_RESPONSE_FORMAT", "").strip() in ("1", "true", "yes"):
        response_format = None
    else:
        response_format = {"type": "json_object"}

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = f"{base}/chat/completions"

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                # Do not retry client errors — they reflect a bad request, not
                # a transient server problem.
                if 400 <= resp.status_code < 500:
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
            content: str = data["choices"][0]["message"]["content"]
            return _parse_json(content)
        except (httpx.TransportError, httpx.TimeoutException, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS - 1:
                backoff = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "complete_json attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt + 1, _RETRY_ATTEMPTS, type(exc).__name__, backoff,
                )
                await asyncio.sleep(backoff)
        except httpx.HTTPStatusError:
            raise  # 4xx / non-transient 5xx — propagate immediately
    raise last_exc
