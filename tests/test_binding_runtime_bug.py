from hermes_gate.app import HermesGateApp


def test_app_installs_all_phase_bindings_up_front():
    app = HermesGateApp()

    keymap = getattr(app, "_bindings").key_to_bindings

    assert "n" in keymap
    assert "k" in keymap
    assert "d" in keymap


def test_check_action_disables_session_actions_outside_session_phase():
    app = HermesGateApp()
    app._phase = "select"

    assert app.check_action("new_session", ()) is False
    assert app.check_action("kill_session", ()) is False
    assert app.check_action("attach_session", ()) is False
    assert app.check_action("refresh", ()) is False
    assert app.check_action("back", ()) is False
    assert app.check_action("delete_server", ()) is True


def test_check_action_enables_session_actions_inside_session_phase():
    app = HermesGateApp()
    app._phase = "session"

    assert app.check_action("new_session", ()) is True
    assert app.check_action("kill_session", ()) is True
    assert app.check_action("attach_session", ()) is True
    assert app.check_action("refresh", ()) is True
    assert app.check_action("back", ()) is True
    assert app.check_action("delete_server", ()) is False
