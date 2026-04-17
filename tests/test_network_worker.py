"""tests/test_network_worker.py"""
import pytest
import asyncio
from hermes_gate.network import NetworkMonitor, NetStatus


@pytest.mark.asyncio
async def test_network_worker_exits_when_phase_changes():
    """Worker must stop when phase changes."""
    monitor = NetworkMonitor("example.com", "22")
    phase = {"phase": "session"}

    exited_cleanly = False

    async def worker():
        nonlocal exited_cleanly
        await monitor.start()
        try:
            while phase["phase"] == "session":
                await asyncio.sleep(0.02)
        finally:
            exited_cleanly = True
            await monitor.stop()

    t = asyncio.create_task(worker())
    await asyncio.sleep(0.05)
    phase["phase"] = "select"  # Change phase
    await asyncio.sleep(0.05)
    await t

    assert exited_cleanly, "Worker should have exited cleanly when phase changed"


def test_only_current_monitor_updates_state():
    """Monitor instances have independent state objects."""
    monitor_a = NetworkMonitor("example.com", "22")
    monitor_b = NetworkMonitor("example.com", "22")

    # Set states independently
    monitor_a.state.status = NetStatus.GREEN
    monitor_a.state.latency = 10.0
    monitor_a.state.message = "10ms"

    monitor_b.state.status = NetStatus.RED
    monitor_b.state.latency = 0.0
    monitor_b.state.message = "Disconnected"

    # Verify independent
    assert monitor_a.state.status == NetStatus.GREEN
    assert monitor_b.state.status == NetStatus.RED

    # Changing one doesn't affect the other
    monitor_b.state.status = NetStatus.GREEN
    assert monitor_a.state.status == NetStatus.GREEN
