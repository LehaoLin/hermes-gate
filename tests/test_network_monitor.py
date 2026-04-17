"""tests/test_network_monitor.py"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from hermes_gate.network import NetworkMonitor, NetStatus


@pytest.mark.asyncio
async def test_probe_uses_configured_port():
    """TCP connect probe must use the port stored in self.port."""
    monitor = NetworkMonitor("example.com", "2222")

    # Verify the monitor stores and uses the correct port
    assert monitor.port == "2222"
    assert int(monitor.port) == 2222

    # Spy on the actual open_connection call to verify port
    import asyncio
    captured_args = {}

    async def fake_open_connection(host, port):
        captured_args["host"] = host
        captured_args["port"] = port
        await asyncio.sleep(0)
        writer = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        return MagicMock(), writer

    with patch("hermes_gate.network.asyncio.open_connection", fake_open_connection):
        with patch("hermes_gate.network.asyncio.wait_for", lambda coro, timeout: coro):
            with patch("hermes_gate.network.time.monotonic", side_effect=[0.0, 0.01]):
                result = await monitor._probe()

    assert captured_args.get("port") == 2222, f"Expected 2222, got {captured_args}"


def test_state_thresholds_green():
    """Latency < 200ms must produce GREEN status."""
    m = NetworkMonitor("x", "22")
    m.state.status = NetStatus.GREEN
    m.state.latency = 50.0
    m.state.message = "50ms"
    assert m.state.status == NetStatus.GREEN
    assert m.state.latency < 200


def test_state_thresholds_yellow():
    """200ms <= latency < 500ms must produce YELLOW status."""
    m = NetworkMonitor("x", "22")
    m.state.status = NetStatus.YELLOW
    m.state.latency = 300.0
    m.state.message = "300ms"
    assert 200 <= m.state.latency < 500
    assert m.state.status == NetStatus.YELLOW


def test_state_thresholds_red_slow():
    """Latency >= 500ms must produce RED/Slow status."""
    m = NetworkMonitor("x", "22")
    m.state.status = NetStatus.RED
    m.state.latency = 650.0
    m.state.message = "Slow: 650ms"
    assert m.state.latency >= 500
    assert m.state.status == NetStatus.RED
    assert "Slow" in m.state.message


def test_state_message_on_timeout():
    """Timeout must produce RED status with clear message."""
    m = NetworkMonitor("x", "22")
    m.state.status = NetStatus.RED
    m.state.latency = 0.0
    m.state.message = "Timeout — port unreachable"
    assert m.state.status == NetStatus.RED
    assert "timeout" in m.state.message.lower()


def test_state_message_on_connection_refused():
    """Connection refused must produce RED with descriptive message."""
    m = NetworkMonitor("x", "22")
    m.state.status = NetStatus.RED
    m.state.latency = 0.0
    m.state.message = "Disconnected: Connection refused"
    assert m.state.status == NetStatus.RED
    assert "disconnect" in m.state.message.lower() or "refused" in m.state.message.lower()


def test_monitor_has_port_parameter():
    """NetworkMonitor must accept and store a port parameter."""
    m = NetworkMonitor("example.com", "2222")
    assert m.port == "2222"
    assert m._ip == "example.com"


@pytest.mark.asyncio
async def test_monitor_start_stop_lifecycle():
    """Monitor can be started and stopped without error."""
    import asyncio
    m = NetworkMonitor("example.com", "22")
    await m.start()
    assert m._running is True
    assert m._task is not None
    await m.stop()
    assert m._running is False


def test_monitor_independent_state_objects():
    """Two monitors must have independent state objects."""
    a = NetworkMonitor("x", "22")
    b = NetworkMonitor("x", "22")
    a.state.status = NetStatus.GREEN
    b.state.status = NetStatus.RED
    assert a.state.status != b.state.status
    assert a.state.status == NetStatus.GREEN
    assert b.state.status == NetStatus.RED
