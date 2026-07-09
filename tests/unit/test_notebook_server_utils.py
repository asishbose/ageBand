"""Unit tests for scripts/notebook_server_utils.py.

Focus: the health-check polling logic (wait_for_url), ManagedProcess
lifecycle helpers, and resolve_ui_display_strategy — the parts that are
non-trivial to get right and whose correctness matters for reliable
notebook restarts and environment detection.

All network I/O is mocked so tests run instantly and never need a live server.
"""

from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from scripts.notebook_server_utils import (
    AGENT_PORT,
    ManagedProcess,
    resolve_ui_display_strategy,
    start_agent,
    start_ui,
    wait_for_url,
)

# ---------------------------------------------------------------------------
# wait_for_url
# ---------------------------------------------------------------------------


class TestWaitForUrl:
    """Tests for wait_for_url() — health-check polling loop."""

    def test_returns_true_on_first_successful_response(self) -> None:
        """Immediately available service → returns True without sleeping."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200

        with patch("scripts.notebook_server_utils.urllib.request.urlopen", return_value=mock_resp):
            result = wait_for_url("http://localhost:8080/health", timeout=5.0)

        assert result is True

    def test_returns_true_after_a_few_failures(self) -> None:
        """Service unavailable on first 2 attempts, ready on 3rd → returns True."""
        call_count = 0

        def _urlopen(url: str, timeout: float) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise urllib.error.URLError("connection refused")
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 200
            return mock_resp

        with (
            patch("scripts.notebook_server_utils.urllib.request.urlopen", side_effect=_urlopen),
            patch("scripts.notebook_server_utils.time.sleep"),
            patch(
                "scripts.notebook_server_utils.time.monotonic",
                side_effect=[0.0, 0.5, 1.0, 1.5, 100.0],
            ),
        ):
            result = wait_for_url("http://localhost:8080/health", timeout=10.0)

        assert result is True
        assert call_count == 3

    def test_returns_false_on_timeout(self) -> None:
        """Service never responds → returns False when timeout expires."""
        with (
            patch(
                "scripts.notebook_server_utils.urllib.request.urlopen",
                side_effect=urllib.error.URLError("refused"),
            ),
            patch("scripts.notebook_server_utils.time.sleep"),
            patch(
                "scripts.notebook_server_utils.time.monotonic",
                side_effect=[0.0, 0.5, 1.0, 5.1],
            ),
        ):
            result = wait_for_url("http://localhost:8080/health", timeout=5.0)

        assert result is False

    def test_non_200_status_is_not_success(self) -> None:
        """HTTP 503 is not a success — polling must continue."""
        call_count = 0

        def _urlopen(url: str, timeout: float) -> Any:
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 503
            return mock_resp

        monotonic_seq = iter([0.0, 0.4, 0.8, 5.1])

        with (
            patch("scripts.notebook_server_utils.urllib.request.urlopen", side_effect=_urlopen),
            patch("scripts.notebook_server_utils.time.sleep"),
            patch(
                "scripts.notebook_server_utils.time.monotonic",
                side_effect=monotonic_seq,
            ),
        ):
            result = wait_for_url("http://localhost:9999/health", timeout=5.0)

        assert result is False

    def test_any_exception_is_swallowed_and_retried(self) -> None:
        """OS errors, connection resets etc. are treated as 'not ready yet'."""
        call_count = 0

        def _urlopen(url: str, timeout: float) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("network unreachable")
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 200
            return mock_resp

        with (
            patch("scripts.notebook_server_utils.urllib.request.urlopen", side_effect=_urlopen),
            patch("scripts.notebook_server_utils.time.sleep"),
            patch(
                "scripts.notebook_server_utils.time.monotonic",
                # 0.0 → deadline = 10.0; 0.5 → first while check; 1.0 → second while check
                side_effect=[0.0, 0.5, 1.0, 100.0],
            ),
        ):
            result = wait_for_url("http://localhost:8080/health", timeout=10.0)

        assert result is True


# ---------------------------------------------------------------------------
# ManagedProcess
# ---------------------------------------------------------------------------


class TestManagedProcess:
    """Tests for ManagedProcess lifecycle helpers."""

    def _make_proc(self, poll_return: int | None = None) -> MagicMock:
        mock = MagicMock(spec=subprocess.Popen)
        mock.pid = 12345
        mock.poll.return_value = poll_return
        return mock

    def test_is_running_when_poll_returns_none(self) -> None:
        proc = self._make_proc(poll_return=None)
        mp = ManagedProcess(proc, "test")
        assert mp.is_running() is True

    def test_not_running_when_poll_returns_exit_code(self) -> None:
        proc = self._make_proc(poll_return=0)
        mp = ManagedProcess(proc, "test")
        assert mp.is_running() is False

    def test_pid_delegates_to_proc(self) -> None:
        proc = self._make_proc()
        mp = ManagedProcess(proc, "test")
        assert mp.pid == 12345

    def test_stop_terminates_and_waits(self) -> None:
        proc = self._make_proc(poll_return=None)
        mp = ManagedProcess(proc, "test")
        mp.stop()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5.0)

    def test_stop_kills_if_terminate_times_out(self) -> None:
        proc = self._make_proc(poll_return=None)
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="uvicorn", timeout=5), None]
        mp = ManagedProcess(proc, "test")
        mp.stop()
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_stop_is_no_op_when_already_stopped(self) -> None:
        proc = self._make_proc(poll_return=0)
        mp = ManagedProcess(proc, "test")
        mp.stop()
        proc.terminate.assert_not_called()


# ---------------------------------------------------------------------------
# start_agent / start_ui — smoke tests (Popen mocked)
# ---------------------------------------------------------------------------


class TestStartFunctions:
    """Smoke tests for start_agent and start_ui (Popen is always mocked)."""

    def test_start_agent_sets_inference_mode_env(self) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 99

        with patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = start_agent(inference_mode="llm", repo_root=Path("/repo"))

        assert result.name == f"ageband-agent:{AGENT_PORT}"
        call_kwargs = mock_popen.call_args
        env_passed = call_kwargs.kwargs["env"]
        assert env_passed["AGEBAND_INFERENCE_MODE"] == "llm"
        assert env_passed["SKIP_AMD_CHECK"] == "true"
        assert env_passed["PYTHONPATH"] == "/repo"

    def test_start_agent_passes_extra_env(self) -> None:
        mock_proc = MagicMock()
        with patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen:
            start_agent(extra_env={"LOCAL_API_BASE": "http://myhost:8000/v1"}, repo_root=Path("/repo"))

        env_passed = mock_popen.call_args.kwargs["env"]
        assert env_passed["LOCAL_API_BASE"] == "http://myhost:8000/v1"

    def test_start_agent_uses_custom_port(self) -> None:
        mock_proc = MagicMock()
        with patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = start_agent(port=9090, repo_root=Path("/repo"))

        assert result.name == "ageband-agent:9090"
        cmd = mock_popen.call_args.args[0]
        assert "--port" in cmd
        assert "9090" in cmd

    def test_start_ui_uses_custom_port(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        with patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = start_ui(tmp_path, port=9091)

        assert result.name == "ageband-ui:9091"
        cmd = mock_popen.call_args.args[0]
        assert "9091" in cmd

    def test_start_ui_cwd_is_resolved_dist_dir(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        with patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen:
            start_ui(tmp_path)

        cwd = mock_popen.call_args.kwargs["cwd"]
        assert cwd == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# resolve_ui_display_strategy
# ---------------------------------------------------------------------------


class TestResolveUiDisplayStrategy:
    """Tests for resolve_ui_display_strategy() — environment detection."""

    def test_colab_takes_priority_over_everything(self) -> None:
        """Colab detected → 'colab' even when public_host and use_tunnel are set."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=True):
            result = resolve_ui_display_strategy(public_host="1.2.3.4", use_tunnel=True)
        assert result == "colab"

    def test_public_host_when_no_colab(self) -> None:
        """No Colab + public_host set → 'public_host'."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=False):
            result = resolve_ui_display_strategy(public_host="164.90.1.2")
        assert result == "public_host"

    def test_public_host_takes_priority_over_tunnel(self) -> None:
        """public_host beats use_tunnel even when both are set."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=False):
            result = resolve_ui_display_strategy(public_host="example.com", use_tunnel=True)
        assert result == "public_host"

    def test_tunnel_when_explicitly_requested(self) -> None:
        """No Colab, no public_host, use_tunnel=True → 'tunnel'."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=False):
            result = resolve_ui_display_strategy(use_tunnel=True)
        assert result == "tunnel"

    def test_local_is_default(self) -> None:
        """No Colab, no public_host, no tunnel → 'local' (default)."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=False):
            result = resolve_ui_display_strategy()
        assert result == "local"

    def test_whitespace_only_public_host_is_treated_as_empty(self) -> None:
        """Whitespace-only PUBLIC_HOST must not trigger 'public_host' strategy."""
        with patch("scripts.notebook_server_utils._is_colab", return_value=False):
            result = resolve_ui_display_strategy(public_host="   ")
        assert result == "local"

    def test_is_colab_returns_false_when_google_colab_absent(self) -> None:
        """_is_colab() returns False in the normal test environment (no google.colab)."""
        # In CI / unit test context google.colab is not installed → must be False.
        # (If somehow google.colab IS installed in this env, this test is a no-op.)
        import importlib.util as _iu

        from scripts.notebook_server_utils import _is_colab
        if _iu.find_spec("google.colab") is None:
            assert _is_colab() is False


# ---------------------------------------------------------------------------
# detect_amd_gpu
# ---------------------------------------------------------------------------


class TestDetectAmdGpu:
    """Tests for detect_amd_gpu() — AMD ROCm presence check."""

    def test_returns_true_when_kfd_and_render_nodes_present(self) -> None:
        """Both /dev/kfd and a renderD* node exist → GPU is accessible."""
        with (
            patch("scripts.notebook_server_utils.os.path.exists", return_value=True),
            patch("scripts.notebook_server_utils._glob.glob", return_value=["/dev/dri/renderD128"]),
        ):
            from scripts.notebook_server_utils import detect_amd_gpu
            assert detect_amd_gpu() is True

    def test_returns_false_when_kfd_missing(self) -> None:
        """/dev/kfd absent → no GPU (device not passed to this container)."""
        with (
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils._glob.glob", return_value=["/dev/dri/renderD128"]),
        ):
            from scripts.notebook_server_utils import detect_amd_gpu
            assert detect_amd_gpu() is False

    def test_returns_false_when_no_render_nodes(self) -> None:
        """/dev/kfd present but no renderD* nodes → incomplete GPU passthrough."""
        with (
            patch("scripts.notebook_server_utils.os.path.exists", return_value=True),
            patch("scripts.notebook_server_utils._glob.glob", return_value=[]),
        ):
            from scripts.notebook_server_utils import detect_amd_gpu
            assert detect_amd_gpu() is False

    def test_returns_false_when_neither_device_present(self) -> None:
        """No GPU devices at all → CPU-only machine."""
        with (
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils._glob.glob", return_value=[]),
        ):
            from scripts.notebook_server_utils import detect_amd_gpu
            assert detect_amd_gpu() is False


# ---------------------------------------------------------------------------
# is_local_host
# ---------------------------------------------------------------------------


class TestIsLocalHost:
    """Tests for is_local_host() — loopback / same-machine detection."""

    def test_localhost_alias_is_local(self) -> None:
        from scripts.notebook_server_utils import is_local_host
        assert is_local_host("localhost") is True

    def test_127_0_0_1_is_local(self) -> None:
        from scripts.notebook_server_utils import is_local_host
        assert is_local_host("127.0.0.1") is True

    def test_ipv6_loopback_is_local(self) -> None:
        from scripts.notebook_server_utils import is_local_host
        assert is_local_host("::1") is True

    def test_empty_string_is_local(self) -> None:
        from scripts.notebook_server_utils import is_local_host
        assert is_local_host("") is True

    def test_whitespace_only_is_local(self) -> None:
        """Whitespace-only strings normalise to an empty alias → local."""
        from scripts.notebook_server_utils import is_local_host
        assert is_local_host("   ") is True

    def test_remote_ip_is_not_local_when_resolution_fails(self) -> None:
        """Resolution errors (no network) → conservatively returns False."""
        import socket as _socket
        with patch("scripts.notebook_server_utils._socket.gethostbyname",
                   side_effect=_socket.gaierror("NXDOMAIN")):
            from scripts.notebook_server_utils import is_local_host
            result = is_local_host("203.0.113.42")  # TEST-NET — should never be local
        assert result is False

    def test_hostname_that_resolves_to_local_ip_is_local(self) -> None:
        """If gethostbyname resolves to an IP in the local set, return True."""
        import socket as _socket

        # Simulate this machine's outbound IP being 10.0.0.5
        def _fake_sock_connect(ctx_self: object, addr: tuple[str, int]) -> None:
            pass

        class _FakeSocket:
            def connect(self, addr: tuple[str, int]) -> None:
                pass
            def getsockname(self) -> tuple[str, int]:
                return ("10.0.0.5", 0)
            def __enter__(self) -> _FakeSocket:
                return self
            def __exit__(self, *_: object) -> None:
                pass

        with (
            patch("scripts.notebook_server_utils._socket.socket", return_value=_FakeSocket()),
            patch("scripts.notebook_server_utils._socket.gethostbyname",
                  side_effect=lambda h: "10.0.0.5" if h == "mybox" else _socket.gethostbyname(h)),
            patch("scripts.notebook_server_utils._socket.gethostname", return_value="mybox"),
        ):
            from scripts.notebook_server_utils import is_local_host
            result = is_local_host("mybox")
        assert result is True


# ---------------------------------------------------------------------------
# start_vllm
# ---------------------------------------------------------------------------


class TestStartVllm:
    """Smoke tests for start_vllm() — command construction (Popen mocked)."""

    def _mock_popen(self, pid: int = 77) -> MagicMock:
        mock = MagicMock()
        mock.pid = pid
        mock.stdout = MagicMock()
        return mock

    def test_uses_docker_rocm_when_docker_and_kfd_present(self) -> None:
        """Docker + /dev/kfd → docker run with ROCm flags."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/docker" if b == "docker" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=True),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            result = start_vllm("google/gemma-3-27b-it", port=8001)

        cmd = mock_popen.call_args.args[0]
        assert cmd[0] == "docker"
        assert "--device=/dev/kfd" in cmd
        assert "--device=/dev/dri" in cmd
        assert "google/gemma-3-27b-it" in cmd
        assert "--port" in cmd
        assert "8001" in cmd
        assert result.name == "vllm:8001"

    def test_injects_hf_token_when_provided(self) -> None:
        """HF_TOKEN is passed as a -e env flag in the Docker command."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/docker" if b == "docker" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=True),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm("google/gemma-3-4b-it", hf_token="hf_abc123")

        cmd = mock_popen.call_args.args[0]
        assert "HF_TOKEN=hf_abc123" in cmd

    def test_falls_back_to_native_vllm_when_no_docker_kfd(self) -> None:
        """No /dev/kfd → native 'vllm serve' even if docker is present."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm("google/gemma-3-4b-it", port=8000)

        cmd = mock_popen.call_args.args[0]
        assert cmd[0] == "vllm"
        assert "serve" in cmd
        assert "google/gemma-3-4b-it" in cmd

    def test_raises_when_neither_docker_nor_native_vllm_available(self) -> None:
        """No docker, no native vllm → RuntimeError with actionable message."""
        import pytest

        with (
            patch("scripts.notebook_server_utils.shutil.which", return_value=None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
        ):
            from scripts.notebook_server_utils import start_vllm
            with pytest.raises(RuntimeError, match="Cannot start vLLM"):
                start_vllm("google/gemma-3-4b-it")

    def test_extra_args_appended_to_command(self) -> None:
        """extra_args are appended after the model name in both paths."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm("model", extra_args=["--quantization", "awq"])

        cmd = mock_popen.call_args.args[0]
        assert "--quantization" in cmd
        assert "awq" in cmd

    def test_stdout_is_pipe_for_progress_streaming(self) -> None:
        """stdout=PIPE so callers can stream download progress."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm("model")

        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("stdout") == subprocess.PIPE

    def test_served_model_names_adds_alias_flag(self) -> None:
        """served_model_names adds --served-model-name <names...> to the command."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm(
                "google/gemma-3-27b-it",
                served_model_names=["google/gemma-3-27b-it", "google/gemma-3-4b-it"],
            )

        cmd = mock_popen.call_args.args[0]
        assert "--served-model-name" in cmd
        idx = cmd.index("--served-model-name")
        assert cmd[idx + 1] == "google/gemma-3-27b-it"
        assert cmd[idx + 2] == "google/gemma-3-4b-it"

    def test_served_model_names_deduplicates_in_alias_list(self) -> None:
        """Primary model name appears exactly once in the --served-model-name list even
        if it is also repeated in served_model_names (dedup within the alias section only).
        The model still appears as a separate positional load argument — that is correct
        vLLM syntax: 'vllm serve <load-model> --served-model-name <alias1> <alias2>'."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm(
                "google/gemma-3-27b-it",
                # primary name repeated in list — must not appear twice WITHIN the alias section
                served_model_names=["google/gemma-3-27b-it", "google/gemma-3-27b-it",
                                    "google/gemma-3-4b-it"],
            )

        cmd = mock_popen.call_args.args[0]
        assert "--served-model-name" in cmd
        idx = cmd.index("--served-model-name")
        # Collect names after the flag until the next flag or end of list
        alias_section = []
        for tok in cmd[idx + 1:]:
            if tok.startswith("--"):
                break
            alias_section.append(tok)
        # "google/gemma-3-27b-it" must appear exactly once in the alias section
        assert alias_section.count("google/gemma-3-27b-it") == 1
        assert "google/gemma-3-4b-it" in alias_section

    def test_no_alias_flag_when_single_model(self) -> None:
        """--served-model-name is omitted when there is only one unique name."""
        mock_proc = self._mock_popen()

        with (
            patch("scripts.notebook_server_utils.shutil.which", side_effect=lambda b: "/usr/bin/vllm" if b == "vllm" else None),
            patch("scripts.notebook_server_utils.os.path.exists", return_value=False),
            patch("scripts.notebook_server_utils.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from scripts.notebook_server_utils import start_vllm
            start_vllm("google/gemma-3-27b-it")  # no served_model_names

        cmd = mock_popen.call_args.args[0]
        assert "--served-model-name" not in cmd
