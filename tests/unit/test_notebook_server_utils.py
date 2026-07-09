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
