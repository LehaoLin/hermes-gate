"""tests/test_refresh_sessions.py"""
import pytest
from unittest.mock import patch, MagicMock

from hermes_gate.session import SessionManager


def test_refresh_keeps_existing_list_on_connection_failure():
    """Connection errors during refresh must NOT clear the existing list."""
    # This is tested at the app level: _refresh_sessions replaces
    # self.sessions only after successful fetch. The test for
    # SessionManager.list_sessions raising ConnectionError is below.
    mgr = SessionManager("root", "example.com", "22")
    with patch.object(mgr, "list_sessions", side_effect=ConnectionError("SSH failed")):
        with pytest.raises(ConnectionError):
            mgr.list_sessions()


def test_session_manager_ssh_failure_raises():
    """SSH returncode 255 must raise ConnectionError."""
    mgr = SessionManager("root", "example.com", "22")

    failed_result = MagicMock()
    failed_result.returncode = 255
    failed_result.stderr = "Permission denied"

    # Must have local records AND SSH failure for the error to propagate
    with patch("hermes_gate.session._load_local", return_value=[{"id": 0, "created": "2024-01-01T10:00"}]):
        with patch.object(mgr, "_ssh_cmd", return_value=failed_result):
            with pytest.raises(ConnectionError) as exc_info:
                mgr.list_sessions()
            assert "SSH connection failed" in str(exc_info.value)


def test_tmux_no_sessions_returns_empty_alive_list():
    """tmux returning non-zero (no sessions) must return empty alive list, not raise."""
    mgr = SessionManager("root", "example.com", "22")

    # tmux returns non-zero because there are no sessions, but SSH succeeded
    tmux_no_sessions = MagicMock()
    tmux_no_sessions.returncode = 1
    tmux_no_sessions.stdout = "no sessions"

    with patch.object(mgr, "_ssh_cmd", return_value=tmux_no_sessions):
        with patch("hermes_gate.session._load_local", return_value=[]):
            # With local empty and tmux empty, result should be empty list (no raise)
            result = mgr.list_sessions()
            assert result == []


def test_list_sessions_discovers_remote_gate_sessions_without_local_records():
    """Existing remote gate-* tmux sessions must be visible without local JSON."""
    mgr = SessionManager("root", "example.com", "22")

    remote_sessions = MagicMock()
    remote_sessions.returncode = 0
    remote_sessions.stdout = "gate-0\t1710000000\nother-session\t1710000001\ngate-2\t1710000002\n"
    remote_sessions.stderr = ""

    with patch.object(mgr, "_ssh_cmd", return_value=remote_sessions):
        with patch("hermes_gate.session._load_local", return_value=[]):
            result = mgr.list_sessions()

    assert [s["id"] for s in result] == [0, 2]
    assert all(s["alive"] for s in result)
    assert all(s["remote_only"] for s in result)


def test_tmux_missing_raises_clear_error():
    """A missing remote tmux binary is a setup error, not an empty session list."""
    mgr = SessionManager("root", "example.com", "22")

    missing_tmux = MagicMock()
    missing_tmux.returncode = 127
    missing_tmux.stdout = ""
    missing_tmux.stderr = "bash: tmux: command not found"

    with patch.object(mgr, "_ssh_cmd", return_value=missing_tmux):
        with patch("hermes_gate.session._load_local", return_value=[]):
            with pytest.raises(RuntimeError) as exc_info:
                mgr.list_sessions()

    assert "tmux is not installed" in str(exc_info.value)


def test_fetch_previews_skips_non_numeric_gate_names_instead_of_crashing():
    """Malformed gate-* output lines must be ignored without failing the batch."""
    mgr = SessionManager("root", "example.com", "22")

    preview_result = MagicMock()
    preview_result.returncode = 0
    preview_result.stdout = (
        "gate-0\tignored because no colon\n"
        "gate-0:first preview\n"
        "gate-x:bad name\n"
        "gate-12:second preview\n"
        "gate-bak:also bad\n"
        "junk line\n"
    )
    preview_result.stderr = ""

    with patch.object(mgr, "_ssh_cmd", return_value=preview_result):
        previews = mgr.fetch_previews([0, 12])

    assert previews == {0: "first preview", 12: "second preview"}


def test_fetch_previews_preserves_empty_preview_for_valid_session_names():
    """Valid gate-N names with no extracted message should remain parseable."""
    mgr = SessionManager("root", "example.com", "22")

    preview_result = MagicMock()
    preview_result.returncode = 0
    preview_result.stdout = "gate-0:first\ngate-1:\n"
    preview_result.stderr = ""

    with patch.object(mgr, "_ssh_cmd", return_value=preview_result):
        previews = mgr.fetch_previews([0, 1])

    assert previews == {0: "first", 1: ""}
