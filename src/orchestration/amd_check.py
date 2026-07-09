"""AMD / vLLM endpoint startup check and live telemetry.

Verifies the OpenAI-compatible model serving endpoint is reachable
before the agent service accepts traffic. Also provides
``collect_amd_telemetry()`` for live GPU / throughput metrics visible in
the UI telemetry badge.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import httpx

# Cache of the last (monotonic_time, generation_tokens_total) sample so
# collect_amd_telemetry() can report a real tok/s RATE (delta / elapsed) across
# successive /health polls, instead of the raw cumulative counter.
_LAST_TOK_SAMPLE: tuple[float, float] | None = None


def _tok_per_sec(gen_total: object) -> object:
    """Return a rolling tok/s rate from the cumulative gen-tokens counter.

    Uses the module-level ``_LAST_TOK_SAMPLE`` to diff against the previous poll.
    Returns 0.0 on the first sample (nothing to diff yet) or "N/A" when the
    counter is unavailable / non-increasing.
    """
    global _LAST_TOK_SAMPLE
    try:
        total = float(gen_total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "N/A"
    now = time.monotonic()
    prev = _LAST_TOK_SAMPLE
    _LAST_TOK_SAMPLE = (now, total)
    if prev is None:
        return 0.0
    dt = now - prev[0]
    if dt <= 0:
        return 0.0
    rate = (total - prev[1]) / dt
    return round(rate, 1) if rate > 0 else 0.0


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


def _bytes_to_mb(val: object) -> object:
    """Convert a byte count (int or numeric string) to whole MB; pass through on failure."""
    try:
        return int(int(str(val)) / (1024 * 1024))
    except (TypeError, ValueError):
        return val


def _parse_rocm_smi(stdout: str) -> dict[str, object]:
    """Parse `rocm-smi --showproductname --showmeminfo vram --json` output.

    rocm-smi JSON is `{"card0": {<free-form keys>}, ...}` and key names vary by
    ROCm version, so match tolerantly. VRAM values are bytes → convert to MB.
    """
    data = json.loads(stdout)
    cards = [v for k, v in data.items() if isinstance(v, dict) and k.lower().startswith("card")]
    if not cards:
        return {}
    card = cards[0]
    lower = {k.lower(): v for k, v in card.items()}

    def find(*needles: str) -> object | None:
        for key, val in lower.items():
            if all(n in key for n in needles):
                return val
        return None

    gpu_model = (
        find("series")
        or find("market", "name")
        or find("product", "name")
        or find("device", "name")
        or find("model")
    )
    vram_total = find("vram", "total", "memory")
    vram_used = find("vram", "total", "used")
    # "used" also matches "total memory" via the total-used key; disambiguate:
    vram_used = find("used", "memory")

    out: dict[str, object] = {"available": True, "binary": "rocm-smi"}
    if gpu_model:
        out["gpu_model"] = str(gpu_model)
    if vram_total is not None:
        out["vram_total_mb"] = _bytes_to_mb(vram_total)
    if vram_used is not None:
        out["vram_used_mb"] = _bytes_to_mb(vram_used)
    return out


def _query_amd_smi() -> dict[str, object]:
    """Shell out to amd-smi or rocm-smi to get GPU model + VRAM.

    Config: AMD_SMI_PATH or ROCM_SMI_PATH env var to override the binary path.
    Tries amd-smi first, then rocm-smi (their CLIs and JSON shapes differ).
    Returns {"available": False} on any failure — graceful degrade.
    """
    # amd-smi: `amd-smi showmeminfo vram --json` (subcommand style, list-of-GPUs JSON)
    amd_bin = os.environ.get("AMD_SMI_PATH", "amd-smi")
    try:
        result = subprocess.run(
            [amd_bin, "showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            gpus = data if isinstance(data, list) else data.get("amd_smi_show_meminfo", [])
            if gpus:
                gpu0 = gpus[0]
                return {
                    "available": True,
                    "binary": amd_bin,
                    "gpu_model": str(gpu0.get("gpu", "AMD GPU")),
                    "vram_used_mb": gpu0.get("vram_total", {}).get("used", "N/A"),
                    "vram_total_mb": gpu0.get("vram_total", {}).get("total", "N/A"),
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, Exception):  # noqa: BLE001
        pass

    # rocm-smi: `rocm-smi --showproductname --showmeminfo vram --json` (flag style, {"cardN":{...}})
    rocm_bin = os.environ.get("ROCM_SMI_PATH", "rocm-smi")
    try:
        result = subprocess.run(
            [rocm_bin, "--showproductname", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parsed = _parse_rocm_smi(result.stdout)
            if parsed:
                return parsed
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, Exception):  # noqa: BLE001
        pass

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
        "tok_per_sec": _tok_per_sec(vllm_metrics.get("gen_tokens_total", "N/A")),
        "running_requests": vllm_metrics.get("running_requests", "N/A"),
        "extractor_model": ext_model or "unset",
        "estimator_model": est_model or "unset",
    }
