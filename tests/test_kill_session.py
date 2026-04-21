"""tests/test_kill_session.py"""
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("textual")

from textual.widgets import Label, ListView

from hermes_gate.app import HermesGateApp, WaitingScreen


def test_session_bindings_use_lowercase_k_for_kill():
    app = HermesGateApp()
    kill_binding = next(binding for binding in app.BINDINGS if binding.action == "kill_session")
    assert kill_binding.key == "k"


def test_action_kill_session_opens_confirmation_dialog_instead_of_killing_immediately():
    app = HermesGateApp()
    app._phase = "session"
    app.sessions = [{"id": 7, "name": "gate-7", "alive": True, "attached": False}]

    list_view = MagicMock(spec=ListView)
    list_view.index = 0
    app.query_one = MagicMock(return_value=list_view)
    app.push_screen = MagicMock()
    app._kill = MagicMock()

    app.action_kill_session()

    assert app.push_screen.call_count == 1
    app._kill.assert_not_called()


def test_confirmed_kill_calls_worker_with_selected_session_id():
    app = HermesGateApp()
    app._phase = "session"
    app.sessions = [{"id": 3, "name": "gate-3", "alive": True, "attached": False}]

    list_view = MagicMock(spec=ListView)
    list_view.index = 0
    app.query_one = MagicMock(return_value=list_view)

    callbacks = []

    def fake_push_screen(_screen, callback):
        callbacks.append(callback)

    app.push_screen = fake_push_screen
    app._kill = MagicMock()

    # set_timer defers _kill to avoid ScreenError during dismiss
    timer_callbacks = []
    app.set_timer = MagicMock(side_effect=lambda delay, cb: timer_callbacks.append(cb))

    app.action_kill_session()
    assert len(callbacks) == 1

    callbacks[0](True)
    # _kill is not called immediately — it's deferred via set_timer
    app._kill.assert_not_called()
    assert len(timer_callbacks) == 1
    timer_callbacks[0]()
    app._kill.assert_called_once_with(3)


def test_cancelled_kill_does_not_call_worker():
    app = HermesGateApp()
    app._phase = "session"
    app.sessions = [{"id": 4, "name": "gate-4", "alive": True, "attached": False}]

    list_view = MagicMock(spec=ListView)
    list_view.index = 0
    app.query_one = MagicMock(return_value=list_view)

    callbacks = []
    app.push_screen = lambda _screen, callback: callbacks.append(callback)
    app._kill = MagicMock()

    app.action_kill_session()
    callbacks[0](False)

    app._kill.assert_not_called()


@pytest.mark.asyncio
async def test_kill_updates_hint_when_tmux_session_missing_but_local_record_removed():
    app = HermesGateApp()
    app.session_mgr = MagicMock()
    app.session_mgr.kill_session.return_value = {"removed": True, "tmux_missing": True}
    app._hint = MagicMock()
    app._refresh_sessions = MagicMock()
    app.pop_screen = MagicMock()

    screen = MagicMock(spec=WaitingScreen)
    await app._do_kill_session(9, screen)

    app._hint.assert_called_once_with(
        "session-hint",
        "gate-9 killed, local record removed",
        error=False,
    )
    app._refresh_sessions.assert_called_once()


@pytest.mark.asyncio
async def test_kill_shows_error_when_remote_cleanup_fails():
    app = HermesGateApp()
    app.session_mgr = MagicMock()
    app.session_mgr.kill_session.side_effect = RuntimeError("permission denied")
    app._hint = MagicMock()
    app._refresh_sessions = MagicMock()

    screen = MagicMock(spec=WaitingScreen)
    await app._do_kill_session(5, screen)

    screen.set_error.assert_called_once_with("Failed to kill gate-5: permission denied")
    app._hint.assert_not_called()
    app._refresh_sessions.assert_not_called()


def test_session_hint_mentions_lowercase_k():
    app = HermesGateApp()
    label = Label("initial", id="session-hint")
    app.query_one = MagicMock(return_value=label)
    app.set_timer = MagicMock()

    app._hint("session-hint", "Done", error=False)

    reset = app.set_timer.call_args[0][1]
    reset()
    assert "k Kill" in str(label.content)
