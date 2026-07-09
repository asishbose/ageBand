"""Helpers for the AgeBand interactive demo notebook.

Launches the AgeBand agent (and, optionally, a standalone static UI server) as
background subprocesses and polls them for readiness.  Designed to work both on
a local laptop, on a remote AMD GPU box reached over a public IP, and inside
hosted Jupyter environments (Google Colab, Kaggle, Binder).

Two serving modes are supported:

1. **Combined (recommended, works remotely)** — one process serves both the API
   and the built UI on a single port.  Start the agent with ``serve_ui=True``
   (sets ``AGEBAND_SERVE_UI=1``, handled in ``src/orchestration/api.py``) and
   point the browser at ``http://<host>:<port>/``.  Single origin, no CORS.

2. **Two-port (classic local dev)** — the agent on one port and a static UI
   server (this module's ``serve-ui`` entrypoint) on another that
   reverse-proxies ``/v1`` and ``/health`` to the agent.  Use ``start_ui(…)``
   for this.

CLI entrypoint (used internally by ``start_ui``)::

    python -m scripts.notebook_server_utils serve-ui \\
        --dist src/ui/dist --port 8081 --agent-port 8080 --host 0.0.0.0
"""

from __future__ import annotations

import contextlib
import glob as _glob
import importlib.util
import os
import shutil
import socket as _socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

AGENT_PORT: int = 8080
UI_PORT: int = 8081

_DEFAULT_TIMEOUT: float = 30.0
_POLL_INTERVAL: float = 0.5

#: Well-known loopback aliases that trivially identify the local machine.
_LOCAL_ALIASES: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", ""})

# ---------------------------------------------------------------------------
# Health-check polling
# ---------------------------------------------------------------------------


def wait_for_url(
    url: str,
    timeout: float = _DEFAULT_TIMEOUT,
    interval: float = _POLL_INTERVAL,
) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout* seconds elapse.

    Uses only stdlib (``urllib``) so it works before any extras are installed.

    Returns:
        ``True`` if the service became ready within the timeout, else ``False``.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001  # broad by design — any failure → retry
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# ManagedProcess
# ---------------------------------------------------------------------------


class ManagedProcess:
    """Wraps a ``subprocess.Popen`` with a human-readable name and lifecycle helpers."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        name: str,
        log_path: str | None = None,
    ) -> None:
        self._proc = proc
        self.name = name
        self.log_path = log_path

    @property
    def pid(self) -> int:
        return self._proc.pid

    def is_running(self) -> bool:
        """Return ``True`` if the subprocess is still alive."""
        return self._proc.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        """Terminate the process gracefully; kill if it doesn't exit in time."""
        if not self.is_running():
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

    def tail(self, n: int = 30) -> str:
        """Return the last *n* lines of the process log file, if one was set."""
        if not self.log_path or not Path(self.log_path).exists():
            return "(no log captured)"
        lines = Path(self.log_path).read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])


# ---------------------------------------------------------------------------
# Agent server
# ---------------------------------------------------------------------------


def start_agent(
    *,
    port: int = AGENT_PORT,
    inference_mode: str = "deterministic",
    extra_env: dict[str, str] | None = None,
    repo_root: Path | None = None,
    host: str = "0.0.0.0",
    serve_ui: bool = False,
    log_path: str | None = None,
) -> ManagedProcess:
    """Launch ``uvicorn src.orchestration.api:app`` as a background subprocess.

    Args:
        port: TCP port for the agent service (default ``8080``).
        inference_mode: Value for ``AGEBAND_INFERENCE_MODE`` (default
            ``"deterministic"`` — works with no GPU).
        extra_env: Additional environment variable overrides (e.g. to set
            ``LOCAL_API_BASE`` for LLM mode).
        repo_root: Absolute path to the repo root; defaults to the parent of
            the ``scripts/`` directory containing this file.
        host: Interface to bind (default ``"0.0.0.0"`` — all interfaces).
        serve_ui: If ``True``, sets ``AGEBAND_SERVE_UI=1`` so the agent also
            serves the pre-built UI at ``/`` (combined one-port mode).
        log_path: Optional file path to capture combined stdout/stderr output
            (useful for remote-box debugging).  When ``None`` output goes to
            ``DEVNULL``.

    Returns:
        A :class:`ManagedProcess` wrapping the running uvicorn subprocess.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent.resolve()

    env = os.environ.copy()
    env["AGEBAND_INFERENCE_MODE"] = inference_mode
    env["SKIP_AMD_CHECK"] = "true"
    env["PYTHONPATH"] = str(repo_root)
    if serve_ui:
        env["AGEBAND_SERVE_UI"] = "1"
    if extra_env:
        env.update(extra_env)

    _out = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115

    proc: subprocess.Popen[bytes] = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.orchestration.api:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=_out,
        stderr=_out,
    )
    return ManagedProcess(proc, f"ageband-agent:{port}", log_path=log_path)


# ---------------------------------------------------------------------------
# UI static server
# ---------------------------------------------------------------------------


def start_ui(
    ui_dist_dir: Path | str,
    *,
    port: int = UI_PORT,
) -> ManagedProcess:
    """Serve the pre-built UI ``dist/`` directory with Python's ``http.server``.

    The notebook must have already run ``npm run build`` in ``src/ui/`` before
    calling this.

    Args:
        ui_dist_dir: Path to the directory containing ``index.html`` (the built
            Vite output, typically ``src/ui/dist/``).
        port: TCP port to bind (default ``8081``).

    Returns:
        A :class:`ManagedProcess` wrapping the http.server subprocess.
    """
    dist = Path(ui_dist_dir).resolve()
    proc: subprocess.Popen[bytes] = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(dist),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return ManagedProcess(proc, f"ageband-ui:{port}")


# ---------------------------------------------------------------------------
# AMD GPU detection
# ---------------------------------------------------------------------------


def detect_amd_gpu() -> bool:
    """Return ``True`` when an AMD GPU with ROCm is accessible on this machine.

    Checks for the AMD compute device node (``/dev/kfd``) and at least one
    render node (``/dev/dri/renderD*``) — the same signals used by
    ``src/orchestration/amd_check.py``.  Does not require ``rocm-smi`` /
    ``amd-smi`` to be on PATH, since the device nodes are sufficient to confirm
    the GPU is passed through to this process.
    """
    return bool(
        os.path.exists("/dev/kfd")
        and _glob.glob("/dev/dri/renderD*")
    )


# ---------------------------------------------------------------------------
# Local-host resolution
# ---------------------------------------------------------------------------


def is_local_host(host: str) -> bool:
    """Return ``True`` when *host* refers to this machine.

    First matches well-known loopback aliases (``localhost``, ``127.0.0.1``,
    ``::1``, empty string).  Then attempts best-effort IP resolution to detect
    whether the host points to one of this machine's own network interfaces,
    using the outbound-UDP trick (no packet is sent — just reads the OS routing
    table).

    All network calls are wrapped in :func:`contextlib.suppress` so the
    function degrades gracefully in sandboxed or offline environments.
    """
    if host.strip().lower() in _LOCAL_ALIASES:
        return True

    # Collect this machine's IPs without relying on ``/etc/hosts`` or DNS.
    _local: set[str] = set()
    with contextlib.suppress(Exception), _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
        _s.connect(("8.8.8.8", 80))
        _local.add(_s.getsockname()[0])
    with contextlib.suppress(Exception):
        _local.add(_socket.gethostbyname(_socket.gethostname()))

    with contextlib.suppress(Exception):
        resolved = _socket.gethostbyname(host)
        return resolved in _local

    return False


# ---------------------------------------------------------------------------
# vLLM server
# ---------------------------------------------------------------------------

#: Docker image for the AMD ROCm vLLM container.
#: Matches the command documented in ``docs/benchmarks_mi300x.md``
#: (tested on AMD Instinct MI300X, 2026-07-09).
VLLM_ROCM_IMAGE: str = "vllm/vllm-openai-rocm:v0.23.0"


def start_vllm(
    model: str,
    *,
    port: int = 8000,
    rocm_image: str = VLLM_ROCM_IMAGE,
    extra_args: list[str] | None = None,
    hf_token: str = "",
    hf_cache_dir: Path | None = None,
    served_model_names: list[str] | None = None,
) -> ManagedProcess:
    """Start a vLLM model server as a background subprocess.

    Prefers the **Docker ROCm container** when ``docker`` is on PATH and an
    AMD GPU is attached (``/dev/kfd`` present).  Falls back to the native
    ``vllm serve`` binary if Docker is unavailable but ``vllm`` is on PATH.

    The Docker ROCm invocation matches the command documented in
    ``docs/benchmarks_mi300x.md`` (tested on AMD Instinct MI300X, 2026-07-09).

    The subprocess's ``stdout`` is set to ``PIPE`` (``stderr`` merged into it)
    so the caller can stream startup / weight-download progress lines from
    ``proc._proc.stdout`` while polling ``/v1/models`` for readiness.

    Args:
        model: HuggingFace model ID (e.g. ``"google/gemma-3-27b-it"``).
        port: TCP port to bind (default ``8000``).
        rocm_image: Docker image tag for the ROCm vLLM container.
        extra_args: Additional CLI args appended after the model name (e.g.
            ``["--quantization", "awq", "--max-model-len", "8192"]``).
        hf_token: HuggingFace API token for gated models (Gemma, Llama, …).
        hf_cache_dir: HuggingFace model-cache directory; defaults to
            ``~/.cache/huggingface``.
        served_model_names: Additional model name aliases registered via
            ``--served-model-name``.  Lets one vLLM process load *model*
            (``LOCAL_MODEL``) but respond to API requests that use a different
            name in the ``model`` field — e.g. ``EXTRACTOR_MODEL`` and
            ``ESTIMATOR_MODEL`` when they differ from ``LOCAL_MODEL``.
            If not provided (or empty), only the primary *model* name is served.

    Returns:
        A :class:`ManagedProcess` wrapping the running process.

    Raises:
        RuntimeError: If neither Docker (with ``/dev/kfd``) nor native
            ``vllm`` is available.
    """
    _extra = extra_args or []
    _hf_cache = Path(hf_cache_dir or Path.home() / ".cache" / "huggingface")
    _docker = shutil.which("docker")
    _native_vllm = shutil.which("vllm")
    _has_kfd = os.path.exists("/dev/kfd")

    # Build --served-model-name flags: include primary model + any extra aliases,
    # deduplicated while preserving order (primary first).
    _seen: set[str] = set()
    _alias_names: list[str] = []
    for _n in [model] + (served_model_names or []):
        if _n and _n not in _seen:
            _alias_names.append(_n)
            _seen.add(_n)
    # Only emit the flag when aliases differ from the default (primary model only).
    _served_name_flags: list[str] = []
    if len(_alias_names) > 1:
        _served_name_flags = ["--served-model-name"] + _alias_names

    cmd: list[str]
    if _docker and _has_kfd:
        # Docker ROCm path — exact flags from docs/benchmarks_mi300x.md
        cmd = [
            "docker", "run", "--rm", "--network=host",
            "--device=/dev/kfd", "--device=/dev/dri",
            "--group-add", "video",
            "--ipc=host", "--shm-size", "16G",
            "--name", "ageband-vllm",
            "-e", "VLLM_HOST_IP=127.0.0.1",
            "-e", "GLOO_SOCKET_IFNAME=lo",
            "-v", f"{_hf_cache}:/root/.cache/huggingface",
        ]
        if hf_token:
            cmd += ["-e", f"HF_TOKEN={hf_token}"]
        cmd += [
            rocm_image,
            model,
            "--host", "0.0.0.0",
            "--port", str(port),
        ]
        cmd += _served_name_flags
        cmd += _extra
    elif _native_vllm:
        # Native vllm serve path (CPU or non-Docker ROCm install)
        env = os.environ.copy()
        if hf_token:
            env["HF_TOKEN"] = hf_token
        cmd = [
            "vllm", "serve", model,
            "--host", "0.0.0.0",
            "--port", str(port),
        ]
        cmd += _served_name_flags
        cmd += _extra
    else:
        raise RuntimeError(
            "Cannot start vLLM: neither 'docker' (with /dev/kfd) nor 'vllm' is available.\n"
            "  → On AMD ROCm: ensure docker is installed and GPU devices are accessible\n"
            "  → On CPU/NVIDIA: pip install vllm"
        )

    proc: subprocess.Popen[bytes] = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merge stderr → single stream for progress display
    )
    return ManagedProcess(proc, f"vllm:{port}")


# ---------------------------------------------------------------------------
# Public host detection (for building the browser URL on a remote box)
# ---------------------------------------------------------------------------


def detect_public_host() -> str:
    """Best-effort external host/IP for building the browser URL.

    Honours ``AGEBAND_PUBLIC_HOST`` / ``PUBLIC_HOST`` env vars first; otherwise
    returns the primary outbound-interface IP.  Falls back to ``"localhost"``.
    """
    for key in ("AGEBAND_PUBLIC_HOST", "PUBLIC_HOST"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    with contextlib.suppress(Exception), _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
        _s.connect(("8.8.8.8", 80))
        ip: str = _s.getsockname()[0]
        return ip
    return "localhost"


# ---------------------------------------------------------------------------
# UI display strategy
# ---------------------------------------------------------------------------


def _is_colab() -> bool:
    """Return ``True`` when running inside Google Colab."""
    return importlib.util.find_spec("google.colab") is not None


DisplayStrategy = Literal["colab", "public_host", "tunnel", "local"]


def resolve_ui_display_strategy(
    public_host: str = "",
    use_tunnel: bool = False,
) -> DisplayStrategy:
    """Choose the best way to expose the UI to the notebook viewer.

    Priority order (first match wins):

    1. **colab** — ``google.colab`` is importable (Google Colab detected).
    2. **public_host** — ``public_host`` is a non-empty, non-whitespace string.
    3. **tunnel** — ``use_tunnel=True`` was explicitly requested.
    4. **local** — plain local Jupyter / JupyterLab (default).

    Args:
        public_host: Public IP or hostname of the machine running this notebook.
        use_tunnel: Request the ``localtunnel`` fallback path.

    Returns:
        One of ``"colab"``, ``"public_host"``, ``"tunnel"``, ``"local"``.
    """
    if _is_colab():
        return "colab"
    if public_host.strip():
        return "public_host"
    if use_tunnel:
        return "tunnel"
    return "local"


# ---------------------------------------------------------------------------
# serve-ui subprocess implementation (reverse-proxy + static file server)
# ---------------------------------------------------------------------------


def _run_ui_server(dist: str, port: int, agent_port: int, host: str) -> None:
    """Run the static-file + API proxy server (called in-process by the subprocess)."""
    import http.server
    import socketserver

    dist_path = Path(dist).resolve()
    agent_base = f"http://127.0.0.1:{agent_port}"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **k: object) -> None:
            super().__init__(*a, directory=str(dist_path), **k)  # type: ignore[arg-type]

        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(
                agent_base + self.path, data=body, method=self.command,
            )
            for h in ("Content-Type", "Accept"):
                if h in self.headers:
                    req.add_header(h, self.headers[h])
            try:
                with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
                    data = r.read()
                    self.send_response(r.status)
                    self.send_header(
                        "Content-Type", r.headers.get("Content-Type", "application/json"),
                    )
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as exc:
                data = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).encode()
                self.send_response(502)
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health" or self.path.startswith("/v1/"):
                return self._proxy()
            target = dist_path / self.path.lstrip("/")
            if not target.exists() and "." not in Path(self.path).name:
                self.path = "/index.html"
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/health" or self.path.startswith("/v1/"):
                return self._proxy()
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_a: object) -> None:  # silence access logs
            pass

    class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    with _Server((host, port), Handler) as srv:
        srv.serve_forever()


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="notebook_server_utils")
    sub = parser.add_subparsers(dest="cmd")
    ui_p = sub.add_parser("serve-ui", help="Serve built UI + proxy /v1,/health to the agent")
    ui_p.add_argument("--dist", required=True)
    ui_p.add_argument("--port", type=int, default=8081)
    ui_p.add_argument("--agent-port", type=int, default=8080)
    ui_p.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)

    if args.cmd == "serve-ui":
        _run_ui_server(args.dist, args.port, args.agent_port, args.host)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
