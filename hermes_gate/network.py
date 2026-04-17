"""Network Status Monitor"""

import asyncio
import time
from enum import Enum
from dataclasses import dataclass

from hermes_gate.servers import resolve_to_ip


class NetStatus(Enum):
    GREEN = "green"  # Connected
    YELLOW = "yellow"  # Unstable
    RED = "red"  # Disconnected


@dataclass
class NetState:
    status: NetStatus = NetStatus.RED
    latency: float = 0.0
    message: str = "Not checked"
    reconnecting: bool = False
    countdown: int = 0
    reconnect_attempt: int = 0


class NetworkMonitor:
    """Async network monitor, periodically probes SSH port, auto-reconnects on disconnect."""

    RECONNECT_INTERVAL = 5

    def __init__(self, host: str = "", port: str = "22"):
        self.host = host
        self._ip = resolve_to_ip(self.host)
        self.port = port
        self.state = NetState()
        self._running = False
        self._task: asyncio.Task | None = None
        self._reconnect_attempt = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        while self._running:
            connected = await self._probe()
            if connected:
                self._reconnect_attempt = 0
                await asyncio.sleep(3)
            else:
                await self._reconnect_cycle()

    async def _reconnect_cycle(self):
        self._reconnect_attempt += 1
        attempt = self._reconnect_attempt
        for countdown in range(self.RECONNECT_INTERVAL, 0, -1):
            if not self._running:
                return
            self.state = NetState(
                status=NetStatus.RED,
                latency=0,
                message=f"Reconnecting... {countdown}s (attempt #{attempt})",
                reconnecting=True,
                countdown=countdown,
                reconnect_attempt=attempt,
            )
            await asyncio.sleep(1)
        connected = await self._probe()
        if connected:
            self.state = NetState(
                status=NetStatus.GREEN,
                latency=self.state.latency,
                message="Reconnected",
            )
            self._reconnect_attempt = 0

    async def _probe(self) -> bool:
        """Probe the SSH port with TCP connect. Returns True if connected."""
        try:
            t0 = time.monotonic()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._ip, int(self.port)),
                timeout=5,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            writer.close()
            await writer.wait_closed()

            if latency_ms < 200:
                self.state = NetState(NetStatus.GREEN, latency_ms, f"{latency_ms:.0f}ms")
            elif latency_ms < 500:
                self.state = NetState(NetStatus.YELLOW, latency_ms, f"{latency_ms:.0f}ms")
            else:
                self.state = NetState(NetStatus.RED, latency_ms, f"Slow: {latency_ms:.0f}ms")
            return True
        except asyncio.TimeoutError:
            self.state = NetState(NetStatus.RED, 0, "Timeout — port unreachable")
            return False
        except (ConnectionRefusedError, OSError) as e:
            self.state = NetState(NetStatus.RED, 0, f"Disconnected: {e}")
            return False
        except Exception:
            self.state = NetState(NetStatus.RED, 0, "Disconnected")
            return False
