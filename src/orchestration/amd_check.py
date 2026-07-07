"""AMD / vLLM endpoint startup check.

Verifies the OpenAI-compatible model serving endpoint is reachable
before the agent service accepts traffic. This makes "runs on AMD" demonstrable.
"""

from __future__ import annotations

import os

import httpx


def verify_amd_endpoint(
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 10.0,
) -> None:
    """Verify the vLLM/AMD endpoint is reachable and serving the expected model.

    Raises RuntimeError with a human-readable message if unreachable.
    Called once at service startup in runner.py.

    Args:
        base_url: OpenAI-compatible API base (defaults to LOCAL_API_BASE env var).
        model: Model name to verify (defaults to LOCAL_MODEL env var).
        timeout: Request timeout in seconds.
    """
    url = base_url if base_url is not None else os.environ.get(
        "LOCAL_API_BASE", "http://localhost:8000/v1"
    )
    expected_model = model or os.environ.get("LOCAL_MODEL", "")

    models_url = url.rstrip("/") + "/models"

    try:
        response = httpx.get(models_url, timeout=timeout)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"AMD/vLLM endpoint not reachable at {models_url}. "
            "Start vLLM with: vllm serve <model> --host 0.0.0.0 --port 8000 "
            f"and set LOCAL_API_BASE={url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"AMD/vLLM endpoint returned HTTP {exc.response.status_code} at {models_url}."
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"AMD/vLLM endpoint timed out after {timeout}s at {models_url}."
        ) from exc

    if expected_model:
        data = response.json()
        served_models = [m.get("id", "") for m in data.get("data", [])]
        if expected_model not in served_models:
            raise RuntimeError(
                f"Model {expected_model!r} not found on vLLM endpoint. "
                f"Available: {served_models}. "
                f"Set LOCAL_MODEL to one of the available models."
            )
