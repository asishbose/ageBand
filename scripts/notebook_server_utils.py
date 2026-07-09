<<<<<<< HEAD
"""Helpers for the AgeBand interactive demo notebook.

Launches the AgeBand agent (and, optionally, a standalone static UI server) as
background subprocesses and polls them for readiness. Designed to work both on a
local laptop and on a remote AMD GPU box reached over a public IP.

Two serving modes are supported:

1. **Combined (recommended, works remotely)** — one process serves both the API
   and the built UI on a single port. Start the agent with ``serve_ui=True``
   (sets ``AGEBAND_SERVE_UI=1``, handled in ``src/orchestration/api.py``) and
   point the browser at ``http://<host>:<port>/``. Single origin, no CORS, no
   proxy — the UI's root-relative ``/v1`` and ``/health`` calls just work.

2. **Two-port (classic local dev)** — the agent on one port and a static UI
   server (this module's ``serve-ui`` entrypoint) on another that reverse-proxies
   ``/v1`` and ``/health`` to the agent. Use ``start_ui(...)`` for this.

CLI entrypoint (used internally by ``start_ui``)::

    python -m scripts.notebook_server_utils serve-ui \
        --dist src/ui/dist --port 8081 --agent-port 8080 --host 0.0.0.0
=======
"""Server process management helpers for the AgeBand demo notebook.

Starts / stops the agent (uvicorn) and UI (http.server) as background
subprocesses and provides health-check polling so notebook cells can
wait for services to become ready without a hard-coded sleep.

Also provides ``resolve_ui_display_strategy()`` so environment-specific
display logic is testable rather than inlined in notebook cells.

This module is regular Python (not a notebook cell), so it goes through
the normal mypy / ruff / test pipeline.
>>>>>>> 1065eae (first round commit - notebook)
"""

from __future__ import annotations

<<<<<<< HEAD
import os
import socket
=======
import importlib.util
import os
>>>>>>> 1065eae (first round commit - notebook)
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
<<<<<<< HEAD


# ---------------------------------------------------------------------------
# Readiness polling
# ---------------------------------------------------------------------------

def wait_for_url(url: str, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Poll *url* until it responds (any status < 500) or *timeout* elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return True
        except Exception:  # noqa: BLE001 — not up yet
=======
from typing import Literal

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

AGENT_PORT: int = 8080
UI_PORT: int = 8081

_DEFAULT_TIMEOUT: float = 30.0
_POLL_INTERVAL: float = 0.5


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
>>>>>>> 1065eae (first round commit - notebook)
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
<<<<<<< HEAD
# Process handle
# ---------------------------------------------------------------------------

class _Proc:
    """Thin wrapper over subprocess.Popen with the interface the notebook uses."""

    def __init__(self, popen: subprocess.Popen, log_path: str | None = None) -> None:
        self._p = popen
        self.pid = popen.pid
        self.log_path = log_path

    def is_running(self) -> bool:
        return self._p.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        if self._p.poll() is None:
            self._p.terminate()
            try:
                self._p.wait(timeout)
            except subprocess.TimeoutExpired:
                self._p.kill()
                self._p.wait()

    def tail(self, n: int = 30) -> str:
        """Return the last *n* lines of the process log, if a log_path was set."""
        if not self.log_path or not Path(self.log_path).exists():
            return "(no log captured)"
        lines = Path(self.log_path).read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])


# ---------------------------------------------------------------------------
# Agent (FastAPI / uvicorn)
# ---------------------------------------------------------------------------

def start_agent(
    port: int = 8080,
    inference_mode: str = "llm",
    repo_root: str | os.PathLike[str] = ".",
    host: str = "0.0.0.0",
    serve_ui: bool = True,
    log_path: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> _Proc:
    """Launch ``uvicorn src.orchestration.api:app`` as a background subprocess.

    Inherits the current ``os.environ`` (so LLM endpoint vars set in the
    notebook config cell are passed through), then forces ``AGEBAND_INFERENCE_MODE``
    and ``AGEBAND_SERVE_UI``. When ``serve_ui`` is True the same process also
    serves the built UI at ``/`` (see api.py) — one port for everything.
    """
    root = Path(repo_root).resolve()
    env = dict(os.environ)
    env["AGEBAND_INFERENCE_MODE"] = inference_mode
    env["AGEBAND_SERVE_UI"] = "1" if serve_ui else "0"
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)

    cmd = [
        sys.executable, "-m", "uvicorn", "src.orchestration.api:app",
        "--host", host, "--port", str(port),
    ]
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115
    proc = subprocess.Popen(cmd, cwd=str(root), env=env, stdout=out, stderr=out)
    return _Proc(proc, log_path)


# ---------------------------------------------------------------------------
# Standalone static UI server (two-port mode)
# ---------------------------------------------------------------------------

def start_ui(
    dist_dir: str | os.PathLike[str],
    port: int = 8081,
    agent_port: int = 8080,
    host: str = "0.0.0.0",
    log_path: str | None = None,
) -> _Proc:
    """Launch a static server for *dist_dir* that proxies /v1 and /health to the agent.

    Only needed for classic two-port local dev. For remote/public-IP use, prefer
    the combined server (``start_agent(serve_ui=True)``) so there is one origin.
    """
    dist = Path(dist_dir).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable, "-m", "scripts.notebook_server_utils", "serve-ui",
        "--dist", str(dist), "--port", str(port),
        "--agent-port", str(agent_port), "--host", host,
    ]
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115
    proc = subprocess.Popen(cmd, cwd=str(repo_root), env=env, stdout=out, stderr=out)
    return _Proc(proc, log_path)


# ---------------------------------------------------------------------------
# Public host detection (for building the browser URL on a remote box)
# ---------------------------------------------------------------------------

def detect_public_host() -> str:
    """Best-effort external host/IP for building the browser URL.

    Honours ``AGEBAND_PUBLIC_HOST`` / ``PUBLIC_HOST`` first; otherwise returns the
    primary outbound-interface IP (may be private on some clouds — override the
    env var with the real public IP if so). Falls back to ``localhost``.
    """
    for key in ("AGEBAND_PUBLIC_HOST", "PUBLIC_HOST"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "localhost"


# ---------------------------------------------------------------------------
# serve-ui implementation (invoked as a subprocess by start_ui)
# ---------------------------------------------------------------------------

def _run_ui_server(dist: str, port: int, agent_port: int, host: str) -> None:
    import http.server
    import socketserver

    dist_path = Path(dist).resolve()
    agent_base = f"http://127.0.0.1:{agent_port}"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, directory=str(dist_path), **k)

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
            # SPA fallback: unknown non-file routes -> index.html
            if not target.exists() and "." not in Path(self.path).name:
                self.path = "/index.html"
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/health" or self.path.startswith("/v1/"):
                return self._proxy()
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a) -> None:  # silence access logs
            pass

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    with Server((host, port), Handler) as srv:
        srv.serve_forever()


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="notebook_server_utils")
    sub = parser.add_subparsers(dest="cmd")
    ui = sub.add_parser("serve-ui", help="Serve built UI + proxy /v1,/health to the agent")
    ui.add_argument("--dist", required=True)
    ui.add_argument("--port", type=int, default=8081)
    ui.add_argument("--agent-port", type=int, default=8080)
    ui.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)

    if args.cmd == "serve-ui":
        _run_ui_server(args.dist, args.port, args.agent_port, args.host)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
=======
# ManagedProcess
# ---------------------------------------------------------------------------


class ManagedProcess:
    """Wraps a ``subprocess.Popen`` with a human-readable name and lifecycle helpers."""

    def __init__(self, proc: subprocess.Popen[bytes], name: str) -> None:
        self._proc = proc
        self.name = name

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


# ---------------------------------------------------------------------------
# Agent server
# ---------------------------------------------------------------------------


def start_agent(
    *,
    port: int = AGENT_PORT,
    inference_mode: str = "deterministic",
    extra_env: dict[str, str] | None = None,
    repo_root: Path | None = None,
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

    Returns:
        A :class:`ManagedProcess` wrapping the running uvicorn subprocess.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent.resolve()

    env = os.environ.copy()
    env["AGEBAND_INFERENCE_MODE"] = inference_mode
    env["SKIP_AMD_CHECK"] = "true"
    env["PYTHONPATH"] = str(repo_root)
    if extra_env:
        env.update(extra_env)

    proc: subprocess.Popen[bytes] = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.orchestration.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return ManagedProcess(proc, f"ageband-agent:{port}")


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
       Use ``google.colab.output.serve_kernel_port_as_iframe()``.
    2. **public_host** — ``public_host`` is a non-empty, non-whitespace string
       (self-managed remote VM: DigitalOcean Droplet, EC2, GCP, etc.).
       Use ``IPython.display.IFrame(src=f"http://{public_host}:{port}")``.
    3. **tunnel** — ``use_tunnel=True`` was explicitly requested (Kaggle,
       Binder, JupyterHub without a controlled public IP).
       Use ``npx localtunnel --port {port}`` and ``IFrame`` the public URL.
    4. **local** — plain local Jupyter / JupyterLab (default, requires nothing).
       Use ``IPython.display.IFrame(src=f"http://localhost:{port}")``.

    Args:
        public_host: Public IP or hostname of the machine running this notebook,
            when it is a remote VM with open firewall ports. Leave empty for local.
        use_tunnel: Request the ``localtunnel`` fallback path for sandboxed hosted
            environments (Kaggle, Binder, etc.) where no other strategy applies.

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
>>>>>>> 1065eae (first round commit - notebook)
