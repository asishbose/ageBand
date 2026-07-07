"""AMD / vLLM endpoint startup check and live telemetry.

Verifies the OpenAI-compatible model serving endpoint is reachable
before the agent service accepts traffic. Also provides
``collect_amd_telemetry()`` for live GPU / throughput metrics visible in
the UI telemetry badge.
"""

from __future__ import annotations

import os
import subprocess

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


def _scrape_vllm_metrics(base_url: str, timeout: float = 3.0) -> dict[str, object]:
    """Scrape vLLM's Prometheus /metrics endpoint synchronously.

    Returns partial results on error (graceful degrade).
    Config: VLLM_METRICS_URL overrides the default derived path.
    """
    metrics_url = os.environ.get(
        "VLLM_METRICS_URL",
        base_url.rstrip("/").replace("/v1", "") + "/metrics",
    )
    try:
        resp = httpx.get(metrics_url, timeout=timeout)
        if resp.status_code != 200:
            return {}
        result: dict[str, object] = {}
        for line in resp.text.splitlines():
            if line.startswith("#"):
                continue
            if "vllm:num_requests_running" in line:
                result["running_requests"] = float(line.split()[-1])
            elif "vllm:generation_tokens_total" in line:
                result["gen_tokens_total"] = float(line.split()[-1])
            elif "vllm:gpu_cache_usage_perc" in line:
                result["gpu_cache_usage_pct"] = float(line.split()[-1]) * 100
        return result
    except Exception:  # noqa: BLE001 — network down / no vLLM
        return {}


def _query_amd_smi() -> dict[str, object]:
    """Shell out to amd-smi or rocm-smi to get GPU info.

    Config: AMD_SMI_PATH or ROCM_SMI_PATH env var to override the binary path.
    Returns empty dict (with available=False) on any failure — graceful degrade.
    """
    for env_var, candidate in [
        ("AMD_SMI_PATH", "amd-smi"),
        ("ROCM_SMI_PATH", "rocm-smi"),
    ]:
        binary = os.environ.get(env_var, candidate)
        try:
            # amd-smi showmeminfo vram --json — returns VRAM used/total + GPU model
            result = subprocess.run(
                [binary, "showmeminfo", "vram", "--json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                # amd-smi JSON shape: list of GPU dicts
                gpus = data if isinstance(data, list) else data.get("amd_smi_show_meminfo", [])
                if gpus:
                    gpu0 = gpus[0]
                    return {
                        "available": True,
                        "binary": binary,
                        "gpu_model": str(gpu0.get("gpu", "AMD GPU")),
                        "vram_used_mb": gpu0.get("vram_total", {}).get("used", "N/A"),
                        "vram_total_mb": gpu0.get("vram_total", {}).get("total", "N/A"),
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):  # noqa: BLE001
            continue
    return {"available": False}


def collect_amd_telemetry() -> dict[str, object]:
    """Collect live AMD GPU + vLLM throughput telemetry for the UI badge.

    Follows the same offline-vs-live branching as ``contracts/runtime.use_llm()``:
    returns a clearly-marked ``available=False`` dict when running in deterministic
    mode or when no AMD GPU is present — never raises, never fabricates numbers.

    Returns a dict with keys:
        available (bool)        — True only when real telemetry was collected
        gpu_model (str)         — e.g. "AMD Instinct MI300X" or "unavailable"
        rocm_version (str)      — ROCm version string or "unavailable"
        vram_used_mb (str|num)  — VRAM used or "N/A"
        vram_total_mb (str|num) — VRAM total or "N/A"
        tok_per_sec (float|str) — derived from vLLM metrics delta or "N/A"
        running_requests (num)  — concurrent in-flight vLLM requests or "N/A"
        extractor_model (str)   — EXTRACTOR_MODEL or LOCAL_MODEL
        estimator_model (str)   — ESTIMATOR_MODEL or LOCAL_MODEL
    """
    from src.contracts.llm_client import estimator_model, extractor_model
    from src.contracts.runtime import use_llm

    ext_model = extractor_model()
    est_model = estimator_model()

    if not use_llm():
        return {
            "available": False,
            "reason": "deterministic/offline mode — no LLM endpoint configured",
            "gpu_model": "unavailable",
            "rocm_version": "unavailable",
            "vram_used_mb": "N/A",
            "vram_total_mb": "N/A",
            "tok_per_sec": "N/A",
            "running_requests": "N/A",
            "extractor_model": ext_model or "unset",
            "estimator_model": est_model or "unset",
        }

    base_url = os.environ.get("LOCAL_API_BASE", "http://localhost:8000/v1")
    vllm_metrics = _scrape_vllm_metrics(base_url)
    amd_info = _query_amd_smi()

    # ROCm version via rocm-smi --version (best effort)
    rocm_version = "unavailable"
    for binary in [os.environ.get("ROCM_SMI_PATH", "rocm-smi"), "amd-smi"]:
        try:
            res = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0:
                rocm_version = res.stdout.strip().splitlines()[0]
                break
        except Exception:  # noqa: BLE001
            continue

    has_gpu = amd_info.get("available", False)
    has_vllm = bool(vllm_metrics)

    return {
        "available": has_gpu or has_vllm,
        "gpu_model": amd_info.get("gpu_model", "unavailable"),
        "rocm_version": rocm_version,
        "vram_used_mb": amd_info.get("vram_used_mb", "N/A"),
        "vram_total_mb": amd_info.get("vram_total_mb", "N/A"),
        "tok_per_sec": vllm_metrics.get("gen_tokens_total", "N/A"),
        "running_requests": vllm_metrics.get("running_requests", "N/A"),
        "extractor_model": ext_model or "unset",
        "estimator_model": est_model or "unset",
    }
