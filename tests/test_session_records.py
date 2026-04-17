"""tests/test_session_records.py"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_gate.session import (
    _sessions_file,
    _load_local,
    _save_local,
    SessionManager,
)


@pytest.fixture
def tmp_home(tmp_path):
    """Use a temporary .hermes-gate dir for all tests."""
    with patch("hermes_gate.session.Path.home", return_value=tmp_path):
        yield tmp_path


# ─── _sessions_file ────────────────────────────────────────────────────────────

def test_sessions_file_includes_port(tmp_home):
    """Same user@host but different ports must produce different files."""
    f22 = _sessions_file("root", "example.com", "22")
    f2222 = _sessions_file("root", "example.com", "2222")
    assert f22 != f2222
    assert f22.name.startswith("sessions_")
    assert f2222.name.startswith("sessions_")


def test_sessions_file_default_port(tmp_home):
    """Default port 22 must produce a stable filename."""
    f = _sessions_file("admin", "host.local", "22")
    assert "22" in f.name or "#22" in f.name


def test_sessions_file_ipv6_and_special_chars(tmp_home):
    """IPv6 and hostnames with special chars must not break the filename."""
    f = _sessions_file("user", "::1", "22")
    # Must not raise, must be a valid Path
    assert isinstance(f, Path)
    assert "/" not in f.name


# ─── _load_local / _save_local ────────────────────────────────────────────────

def test_load_local_empty_when_no_file(tmp_home):
    assert _load_local("root", "example.com", "22") == []


def test_save_and_load_local(tmp_home):
    entries = [{"id": 0, "created": "2024-01-01T10:00:00"}]
    _save_local("root", "example.com", "22", entries)
    loaded = _load_local("root", "example.com", "22")
    assert loaded == entries


def test_load_local_corrupt_json_returns_empty(tmp_home):
    cfg = tmp_home / ".hermes-gate"
    cfg.mkdir()
    bad = cfg / f"sessions_root@example.com#22.json"
    bad.write_text("{ not valid json")
    with patch("hermes_gate.session._sessions_file") as mock_f:
        mock_f.return_value = bad
        # Force the file path used by _load_local
        result = _load_local("root", "example.com", "22")
    assert result == []


# ─── Session files are port-scoped ───────────────────────────────────────────

def test_session_files_are_port_scoped(tmp_home):
    """Two sessions on same user@host but different ports get separate files."""
    # Create entries for port 22
    _save_local("root", "example.com", "22", [{"id": 0, "created": "2024-01-01T10:00"}])
    # Create entry for port 2222
    _save_local("root", "example.com", "2222", [{"id": 0, "created": "2024-01-02T10:00"}])

    # Load for port 22 — must only see the port-22 entry
    port22 = _load_local("root", "example.com", "22")
    assert len(port22) == 1
    assert port22[0]["id"] == 0
    assert "2024-01-01" in port22[0]["created"]

    # Load for port 2222 — must only see the port-2222 entry
    port2222 = _load_local("root", "example.com", "2222")
    assert len(port2222) == 1
    assert port2222[0]["id"] == 0
    assert "2024-01-02" in port2222[0]["created"]


def test_kill_session_only_removes_matching_port_record(tmp_home):
    """Killing session on port 2222 must not affect port 22 record."""
    # Pre-populate both port files
    _save_local("root", "example.com", "22", [{"id": 0, "created": "2024-01-01T10:00"}])
    _save_local("root", "example.com", "2222", [{"id": 0, "created": "2024-01-02T10:00"}])

    with patch.object(SessionManager, "_ssh_cmd") as mock_ssh:
        mock_ssh.return_value.returncode = 0
        mgr = SessionManager("root", "example.com", "2222")
        mgr.kill_session(0)

    # Port 22 must be untouched
    port22 = _load_local("root", "example.com", "22")
    assert len(port22) == 1
    assert port22[0]["id"] == 0

    # Port 2222 must be empty
    port2222 = _load_local("root", "example.com", "2222")
    assert port2222 == []


def test_ssh_base_args_uses_config_alias(tmp_home):
    """Alias-backed connections must preserve SSH config identity settings."""
    ssh_dir = tmp_home / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text(
        "\n".join(
            [
                "Host production",
                "  HostName 203.0.113.10",
                "  User deploy",
                "  IdentityFile ~/.ssh/production_key",
                "  IdentitiesOnly yes",
            ]
        )
    )

    mgr = SessionManager(
        "deploy", "203.0.113.10", "22", ssh_alias="production"
    )
    args = mgr.ssh_base_args(timeout=8)

    assert args[-1] == "production"
    assert "deploy@203.0.113.10" not in args
    assert "-p" not in args
    assert "-F" in args


def test_ssh_base_args_uses_runtime_ssh_config_env(monkeypatch, tmp_path):
    """Alias-backed SSH should use the sanitized runtime config when provided."""
    config = tmp_path / "runtime_ssh_config"
    config.write_text("Host production\n  HostName 203.0.113.10\n")
    monkeypatch.setenv("HERMES_GATE_SSH_CONFIG", str(config))

    mgr = SessionManager("deploy", "203.0.113.10", "22", ssh_alias="production")
    args = mgr.ssh_base_args(timeout=8)

    assert ["-F", str(config)] == args[args.index("-F") : args.index("-F") + 2]


# ─── Legacy migration ─────────────────────────────────────────────────────────

def test_default_port_migrates_legacy_record(tmp_home):
    """When port=22 and legacy file exists, it must be migrated."""
    # Create only the legacy file (no port in name)
    cfg = tmp_home / ".hermes-gate"
    cfg.mkdir()
    legacy = cfg / "sessions_root@example.com.json"
    legacy.write_text(json.dumps([{"id": 1, "created": "2024-01-01T10:00"}]))

    # Patch _sessions_file to return the NEW-style path
    new_file = cfg / f"sessions_root@example.com#22.json"

    with patch("hermes_gate.session._sessions_file", return_value=new_file):
        with patch.object(SessionManager, "_ssh_output", return_value=""):
            with patch.object(SessionManager, "_ssh_cmd"):
                mgr = SessionManager("root", "example.com", "22")
                sessions = mgr.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["id"] == 1
    # New file must be created
    assert new_file.exists()


def test_non_default_port_does_not_consume_legacy_record(tmp_home):
    """Port 2222 must not read the legacy port-22 file."""
    cfg = tmp_home / ".hermes-gate"
    cfg.mkdir()
    legacy = cfg / "sessions_root@example.com.json"
    legacy.write_text(json.dumps([{"id": 1, "created": "2024-01-01T10:00"}]))

    # When we ask for port 2222, it should NOT see the legacy file
    with patch.object(SessionManager, "_ssh_output", return_value=""):
        with patch.object(SessionManager, "_ssh_cmd"):
            mgr = SessionManager("root", "example.com", "2222")
            sessions = mgr.list_sessions()

    # Should be empty — didn't consume legacy record
    assert sessions == []
