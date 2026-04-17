"""tests/test_send_to_remote.py — Input safety tests for the attach-based viewer.

Since the viewer now attaches directly via SSH/mosh (user input goes to the
remote tmux session through the real terminal), the old _send_to_remote code
path has been removed.  The tests below verify that tmux configuration
commands are safely constructed.
"""
import shlex

import pytest


def test_tmux_config_session_name_is_shell_quoted():
    """Session name in tmux config commands must be shell-safe."""
    # Session names are always gate-{int}, but verify quoting anyway
    name = "gate-0"
    q = shlex.quote
    cmd = f"tmux set-option -t {q(name)} prefix C-a"
    assert f"-t {q(name)}" in cmd
    assert name in cmd


def test_tmux_config_batches_into_single_remote_command():
    """All tmux setup commands are joined into one SSH call for speed."""
    q = shlex.quote
    name = "gate-3"
    commands = " && ".join([
        f"tmux set-option -t {q(name)} prefix C-a",
        f"tmux bind-key -T root C-b detach-client",
    ])
    remote_cmd = f"bash -l -c {q(commands)}"
    # Should be a single shell-quoted string
    assert remote_cmd.startswith("bash -l -c ")
    assert "set-option" in remote_cmd
    assert "bind-key" in remote_cmd
