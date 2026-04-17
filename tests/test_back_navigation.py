import pytest

pytest.importorskip("textual")

from hermes_gate.app import HermesGateApp


class _StubMonitor:
    def __init__(self) -> None:
        self.stop_called = False

    async def stop(self) -> None:
        self.stop_called = True


def test_action_back_stops_monitor_and_returns_to_server_list() -> None:
    app = HermesGateApp()
    transitions: list[str] = []

    def fake_show_server_select() -> None:
        transitions.append("show_server_select")
        app._phase = "select"

    app._show_server_select = fake_show_server_select
    app._phase = "session"

    monitor = _StubMonitor()
    app.net_monitor = monitor

    app.action_back()

    assert monitor.stop_called is True
    assert app.net_monitor is None
    assert app._phase == "select"
    assert transitions == ["show_server_select"]


@pytest.mark.asyncio
async def test_ctrl_b_triggers_back_in_session_phase() -> None:
    app = HermesGateApp()
    app.on_mount = lambda: None
    events: list[str] = []

    def fake_show_server_select() -> None:
        events.append("show_server_select")
        app._phase = "select"

    app._show_server_select = fake_show_server_select

    async with app.run_test() as pilot:
        events.clear()
        app._phase = "session"
        await pilot.pause()

        await pilot.press("ctrl+b")
        await pilot.pause()

        assert app._phase == "select"
        assert events == ["show_server_select"]


@pytest.mark.asyncio
async def test_ctrl_b_is_ignored_outside_session_phase() -> None:
    app = HermesGateApp()
    app.on_mount = lambda: None
    events: list[str] = []

    def fake_show_server_select() -> None:
        events.append("show_server_select")
        app._phase = "select"

    app._show_server_select = fake_show_server_select

    async with app.run_test() as pilot:
        events.clear()
        app._phase = "select"
        await pilot.pause()

        await pilot.press("ctrl+b")
        await pilot.pause()

        assert app._phase == "select"
        assert events == []
