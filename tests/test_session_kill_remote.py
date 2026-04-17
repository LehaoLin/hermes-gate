"""tests/test_session_kill_remote.py"""
from unittest.mock import MagicMock, call, patch

from hermes_gate.session import _load_local, _save_local, SessionManager


def test_kill_session_detaches_clients_before_killing_tmux_and_removes_record(tmp_path):
    with patch("hermes_gate.session.Path.home", return_value=tmp_path):
        _save_local("root", "example.com", "22", [{"id": 2, "created": "2024-01-01T10:00"}])
        mgr = SessionManager("root", "example.com", "22")

        ok = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(mgr, "_ssh_cmd", return_value=ok) as mock_ssh:
            result = mgr.kill_session(2)

        assert result == {"removed": True, "tmux_missing": False}
        commands = [args[0][0] for args in mock_ssh.call_args_list]
        assert "detach-client" in commands[0]
        assert "kill-session" in commands[1]
        assert _load_local("root", "example.com", "22") == []


def test_kill_session_treats_missing_tmux_session_as_successful_cleanup(tmp_path):
    with patch("hermes_gate.session.Path.home", return_value=tmp_path):
        _save_local("root", "example.com", "22", [{"id": 8, "created": "2024-01-01T10:00"}])
        mgr = SessionManager("root", "example.com", "22")

        detach_missing = MagicMock(returncode=1, stdout="", stderr="can't find session: gate-8")
        kill_missing = MagicMock(returncode=1, stdout="", stderr="can't find session: gate-8")
        with patch.object(mgr, "_ssh_cmd", side_effect=[detach_missing, kill_missing]):
            result = mgr.kill_session(8)

        assert result == {"removed": True, "tmux_missing": True}
        assert _load_local("root", "example.com", "22") == []


def test_kill_session_keeps_local_record_when_tmux_kill_fails_for_other_reason(tmp_path):
    with patch("hermes_gate.session.Path.home", return_value=tmp_path):
        record = {"id": 6, "created": "2024-01-01T10:00"}
        _save_local("root", "example.com", "22", [record])
        mgr = SessionManager("root", "example.com", "22")

        detach_ok = MagicMock(returncode=0, stdout="", stderr="")
        kill_failed = MagicMock(returncode=1, stdout="", stderr="permission denied")
        with patch.object(mgr, "_ssh_cmd", side_effect=[detach_ok, kill_failed]):
            try:
                mgr.kill_session(6)
            except RuntimeError as exc:
                assert "permission denied" in str(exc)
            else:
                raise AssertionError("kill_session should raise on non-missing tmux failure")

        assert _load_local("root", "example.com", "22") == [record]


def test_kill_session_raises_clear_error_when_tmux_binary_missing(tmp_path):
    with patch("hermes_gate.session.Path.home", return_value=tmp_path):
        _save_local("root", "example.com", "22", [{"id": 1, "created": "2024-01-01T10:00"}])
        mgr = SessionManager("root", "example.com", "22")

        missing_tmux = MagicMock(returncode=127, stdout="", stderr="tmux: command not found")
        with patch.object(mgr, "_ssh_cmd", return_value=missing_tmux):
            try:
                mgr.kill_session(1)
            except RuntimeError as exc:
                assert "tmux is not installed" in str(exc)
            else:
                raise AssertionError("kill_session should raise when tmux is missing")

        assert _load_local("root", "example.com", "22") == [{"id": 1, "created": "2024-01-01T10:00"}]
