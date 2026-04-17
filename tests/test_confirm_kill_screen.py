import pytest

pytest.importorskip("textual")

from hermes_gate.app import ConfirmKillScreen, HermesGateApp


def test_session_bindings_use_uppercase_n_for_new_session_and_uppercase_k_for_kill():
    app = HermesGateApp()
    new_binding = next(binding for binding in app._BIND_SESSION if binding.action == "new_session")
    kill_binding = next(binding for binding in app._BIND_SESSION if binding.action == "kill_session")

    assert new_binding.key == "N"
    assert kill_binding.key == "K"


def test_confirm_kill_screen_prompt_and_hint_text_match_single_key_logic():
    screen = ConfirmKillScreen("gate-7")

    assert screen.session_name == "gate-7"
    assert screen.BINDINGS[0].key == "y"
    assert screen.BINDINGS[1].key == "n"
    assert screen.BINDINGS[2].key == "escape"
    assert screen.BINDINGS[3].key == "enter"
    assert not hasattr(screen, "on_button_pressed")
    assert screen.HINT_TEXT == "enter/y kill · Esc/n cancel"


def test_confirm_kill_screen_accepts_lowercase_n_for_cancel():
    screen = ConfirmKillScreen("gate-7")
    events = []
    screen.dismiss = lambda value: events.append(value)

    screen.action_cancel()

    assert events == [False]


def test_confirm_kill_screen_accepts_enter_for_confirm():
    screen = ConfirmKillScreen("gate-7")
    events = []
    screen.dismiss = lambda value: events.append(value)

    screen.action_confirm()

    assert events == [True]
