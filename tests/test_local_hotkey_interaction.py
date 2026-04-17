import pytest

pytest.importorskip("textual")

from hermes_gate.app import HermesGateApp


@pytest.mark.asyncio
async def test_local_interaction_uppercase_n_triggers_new_session_action():
    app = HermesGateApp()
    app._show_server_select = lambda: None
    app._phase = "session"
    called = []
    app.action_new_session = lambda: called.append("new")

    async with app.run_test() as pilot:
        await pilot.press("N")

    assert called == ["new"]


@pytest.mark.asyncio
async def test_local_interaction_uppercase_k_triggers_kill_session_action():
    app = HermesGateApp()
    app._show_server_select = lambda: None
    app._phase = "session"
    called = []
    app.action_kill_session = lambda: called.append("kill")

    async with app.run_test() as pilot:
        await pilot.press("K")

    assert called == ["kill"]


@pytest.mark.asyncio
async def test_local_interaction_uppercase_n_is_ignored_outside_session_phase():
    app = HermesGateApp()
    app._show_server_select = lambda: None
    app._phase = "select"
    called = []
    app.action_new_session = lambda: called.append("new")

    async with app.run_test() as pilot:
        await pilot.press("N")

    assert called == []
