from unittest.mock import patch

import pytest

pytest.importorskip("textual")

from hermes_gate.app import HermesGateApp
from hermes_gate.session import SessionManager


def _fake_completed_process():
    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    return _Result()


def test_configure_tmux_for_attach_enables_mouse_scrolling_passthrough():
    """Attach path should configure tmux so wheel events scroll pane history instead of becoming app up/down input."""
    app = HermesGateApp()
    mgr = SessionManager("user", "example.com", "22")

    with patch("hermes_gate.app.subprocess.run", return_value=_fake_completed_process()) as run_mock:
        app._configure_tmux_for_attach(mgr, "gate-7")

    remote_cmd = run_mock.call_args.args[0][-1]
    assert "set-option -t gate-7 mouse on" in remote_cmd
    assert "bind-key -T root WheelUpPane" in remote_cmd
    assert "#{mouse_any_flag}" in remote_cmd
    assert "send-keys -M" in remote_cmd
    assert "copy-mode -e" in remote_cmd
    assert "bind-key -T copy-mode-vi WheelUpPane send-keys -X scroll-up" in remote_cmd
    assert "bind-key -T copy-mode-vi WheelDownPane send-keys -X scroll-down" in remote_cmd


def test_restore_tmux_after_detach_unsets_mouse_wheel_bindings_when_idle():
    """Attach-specific mouse bindings should be removed when Hermes Gate is the last client."""
    app = HermesGateApp()
    mgr = SessionManager("user", "example.com", "22")

    attached_clients = _fake_completed_process()
    attached_clients.stdout = "0\n"

    with patch(
        "hermes_gate.app.subprocess.run",
        side_effect=[attached_clients, _fake_completed_process()],
    ) as run_mock:
        app._restore_tmux_after_detach(mgr, "gate-7")

    restore_cmd = run_mock.call_args_list[1].args[0][-1]
    assert "set-option -u -t gate-7 mouse" in restore_cmd
    assert "unbind-key -T root WheelUpPane" in restore_cmd
    assert "unbind-key -T root WheelDownPane" in restore_cmd
    assert "unbind-key -T copy-mode-vi WheelUpPane" in restore_cmd
    assert "unbind-key -T copy-mode-vi WheelDownPane" in restore_cmd
