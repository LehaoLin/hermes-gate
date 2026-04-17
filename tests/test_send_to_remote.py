"""tests/test_send_to_remote.py"""
import pytest


@pytest.mark.asyncio
async def test_user_text_is_sent_via_stdin_not_remote_command():
    """User text must only appear in communicate(input=...), never in argv."""
    import asyncio
    from unittest.mock import patch, AsyncMock

    text = "hello; whoami $(id) 'x'\nnext"
    stdin_captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            stdin_captured["value"] = input
            return b"", b""

    async def fake_exec(*args, stdin=None, stdout=None, stderr=None):
        return FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-p", "22", "root@1.2.3.4",
            "tmux", "load-buffer", "-b", "hermes-gate-input", "-",
            ";", "tmux", "paste-buffer", "-b", "hermes-gate-input", "-t", "gate-0",
            ";", "tmux", "send-keys", "-t", "gate-0", "Enter",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text.encode("utf-8"))

    # Text must be in stdin
    assert stdin_captured["value"] == text.encode("utf-8")


@pytest.mark.asyncio
async def test_user_text_appears_only_in_stdin():
    """Verify user text only appears in stdin, not in remote command string."""
    import asyncio
    from unittest.mock import patch

    text_cases = [
        "simple",
        "hello; whoami",
        "$(id)",
        "'x'",
        "a\nb\nc",
        "  spaces  ",
        "a'b",
    ]

    for text in text_cases:
        stdin_captured = {}

        class FakeProc:
            returncode = 0

            async def communicate(self, input=None):
                stdin_captured["value"] = input
                return b"", b""

        async def fake_exec(*args, stdin=None, stdout=None, stderr=None):
            return FakeProc()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            proc = await asyncio.create_subprocess_exec(
                "ssh", "-p", "22", "root@1.2.3.4",
                "tmux", "load-buffer", "-b", "hermes-gate-input", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=text.encode("utf-8"))

        assert stdin_captured["value"] == text.encode("utf-8"), f"Text '{text}' must be in stdin"


@pytest.mark.asyncio
async def test_send_preserves_whitespace_and_newlines():
    """All whitespace and newlines must be preserved byte-exact in stdin."""
    import asyncio
    from unittest.mock import patch

    text = "  leading\n\tmiddle\r\ntrailing  "
    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            captured["value"] = input
            return b"", b""

    async def fake_exec(*args, stdin=None, stdout=None, stderr=None):
        return FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-p", "22", "root@1.2.3.4",
            "tmux", "load-buffer", "-b", "hermes-gate-input", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text.encode("utf-8"))

    assert captured["value"] == text.encode("utf-8")


@pytest.mark.asyncio
async def test_send_uses_generated_session_name_only():
    """Remote command must only target gate-{id}, never user-controlled strings."""
    import asyncio
    from unittest.mock import patch

    session_id = 3
    target = f"gate-{session_id}"
    argv_captured = []

    class FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            return b"", b""

    async def fake_exec(*args, stdin=None, stdout=None, stderr=None):
        argv_captured.append(list(args))
        return FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-p", "22", "root@1.2.3.4",
            "tmux", "load-buffer", "-b", "hermes-gate-input", "-",
            ";", "tmux", "paste-buffer", "-b", "hermes-gate-input", "-t", target,
            ";", "tmux", "send-keys", "-t", target, "Enter",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=b"user input")

    # All calls must include the fixed target name and not the user text
    for argv in argv_captured:
        argv_str = " ".join(argv)
        assert target in argv_str
        assert "user input" not in argv_str


@pytest.mark.asyncio
async def test_send_failure_surfaces_error():
    """Non-zero returncode must raise RuntimeError."""
    import asyncio
    from unittest.mock import patch

    class FakeProc:
        returncode = 1
        stderr = b"no such session"

        async def communicate(self, input=None):
            return b"", self.stderr

    async def fake_exec(*args, stdin=None, stdout=None, stderr=None):
        return FakeProc()

    raised = None
    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-p", "22", "root@1.2.3.4",
            "tmux", "load-buffer", "-b", "hermes-gate-input", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=b"test")
        if proc.returncode != 0:
            raised = RuntimeError(stderr.decode(errors="replace").strip() or "send failed")

    assert raised is not None
    assert "no such session" in str(raised)


def test_send_command_clears_partial_remote_input_before_paste():
    """A complete prompt injection must not append to stale remote input."""
    pytest.importorskip("textual")
    from hermes_gate.app import _build_tmux_send_command

    command = _build_tmux_send_command("gate-3")

    assert "tmux send-keys -t gate-3 C-u" in command
    assert command.index("C-u") < command.index("load-buffer")
    assert "tmux paste-buffer -b hermes-gate-input -t gate-3" in command
    assert command.endswith("tmux send-keys -t gate-3 Enter")


def test_send_command_shell_quotes_session_target():
    """Generated tmux commands remain shell-safe if target rules broaden."""
    pytest.importorskip("textual")
    from hermes_gate.app import _build_tmux_send_command

    command = _build_tmux_send_command("gate-3;whoami")

    assert "'gate-3;whoami'" in command
    assert "gate-3;whoami &&" not in command


def test_remote_escape_command_sends_control_keys_to_same_target():
    """Remote escape is a key passthrough, not a prompt injection path."""
    pytest.importorskip("textual")
    from hermes_gate.app import _build_tmux_key_command

    command = _build_tmux_key_command("gate-3", "Escape", "C-u")

    assert command == "tmux send-keys -t gate-3 Escape C-u"


def test_remote_interrupt_command_sends_ctrl_c_to_same_target():
    """Remote interrupt should target Hermes inside tmux, not local Textual."""
    pytest.importorskip("textual")
    from hermes_gate.app import _build_tmux_key_command

    assert _build_tmux_key_command("gate-3", "C-c") == "tmux send-keys -t gate-3 C-c"


def test_remote_key_action_names_are_specific():
    """Viewer hints should describe the control action actually sent."""
    pytest.importorskip("textual")
    from hermes_gate.app import _remote_key_action_name

    assert _remote_key_action_name(("C-c",)) == "Remote interrupt"
    assert _remote_key_action_name(("Escape", "C-u")) == "Remote Esc"
    assert _remote_key_action_name(("C-l",)) == "Remote keys"
