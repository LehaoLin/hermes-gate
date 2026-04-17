import json
from unittest.mock import patch

from hermes_gate.servers import add_server, find_ssh_alias, load_servers, ssh_config_path


def test_find_ssh_alias_matches_user_host_port(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text(
        "\n".join(
            [
                "Host production",
                "  HostName 203.0.113.10",
                "  User deploy",
                "  Port 22",
                "  IdentityFile ~/.ssh/production_key",
                "  IdentitiesOnly yes",
            ]
        )
    )

    with patch("hermes_gate.servers.Path.home", return_value=tmp_path):
        assert find_ssh_alias("deploy", "203.0.113.10", "22") == "production"
        assert find_ssh_alias("deploy", "203.0.113.10", "2222") is None


def test_find_ssh_alias_accepts_tab_separated_config(tmp_path):
    """OpenSSH config allows arbitrary whitespace between key and value."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text(
        "Host\tproduction\nHostName\t203.0.113.10\nUser\tdeploy\nPort\t22\n"
    )

    with patch("hermes_gate.servers.Path.home", return_value=tmp_path):
        assert find_ssh_alias("deploy", "203.0.113.10", "22") == "production"


def test_add_server_updates_existing_record_with_ssh_alias(tmp_path):
    cfg_dir = tmp_path / ".hermes-gate"
    cfg_dir.mkdir()
    (cfg_dir / "servers.json").write_text(
        json.dumps([{"user": "deploy", "host": "203.0.113.10", "port": "22"}])
    )

    with patch("hermes_gate.servers.Path.home", return_value=tmp_path):
        entry = add_server(
            "deploy", "203.0.113.10", "22", ssh_alias="production"
        )
        servers = load_servers()

    assert entry["ssh_alias"] == "production"
    assert servers == [
        {
            "user": "deploy",
            "host": "203.0.113.10",
            "port": "22",
            "ssh_alias": "production",
        }
    ]


def test_ssh_config_path_honors_runtime_env(monkeypatch, tmp_path):
    """Docker can point the app at a sanitized runtime SSH config copy."""
    config = tmp_path / "ssh_config"
    monkeypatch.setenv("HERMES_GATE_SSH_CONFIG", str(config))

    assert ssh_config_path() == config
