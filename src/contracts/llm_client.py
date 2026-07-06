"""Minimal OpenAI-compatible JSON completion client.

Talks to any OpenAI-compatible ``/chat/completions`` endpoint — Ollama
(``http://localhost:11434/v1``), vLLM on AMD ROCm, or Fireworks — so the LLM
delegates can run against local Llama/Gemma or a hosted model with only an
env-var change. No SDK dependency; uses httpx (already a project dep).

Env:
    LOCAL_API_BASE  base URL incl. /v1 (default http://localhost:11434/v1)
    LOCAL_MODEL     model id (e.g. "llama3.1:8b", "gemma2:9b")
    LOCAL_API_KEY   bearer token ("EMPTY"/unset for Ollama/local vLLM)
"""

from __future__ import annotations

import json
import os
import re

import httpx

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _endpoint() -> tuple[str, str, str]:
    base = os.environ.get("LOCAL_API_BASE", "http://localhost:11434/v1")
    model = os.environ.get("LOCAL_MODEL", "")
    key = os.environ.get("LOCAL_API_KEY", "EMPTY")
    return base.rstrip("/"), model, key


def _parse_json(content: str) -> dict[str, object]:
    """Best-effort: pull a JSON object out of a model's text response."""
    fence = _JSON_FENCE_RE.search(content)
    if fence:
        content = fence.group(1)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fall back to the first balanced {...} span.
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


async def complete_json(
    system_prompt: str, user_prompt: str, timeout: float = 60.0
) -> dict[str, object]:
    """Call the chat endpoint and return the parsed JSON object from the reply.

    Requests ``response_format={"type": "json_object"}`` (honoured by Ollama,
    vLLM, and Fireworks); falls back to lenient parsing if the model wraps the
    JSON in prose or fences.
    """
    base, model, key = _endpoint()
    if not model:
        raise RuntimeError("LOCAL_MODEL is not set; cannot call the LLM endpoint.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    return _parse_json(content)
