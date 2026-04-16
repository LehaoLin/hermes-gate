"""Network Status Monitor"""

import asyncio
import subprocess
import os
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
    """Async network monitor, periodically pings server, auto-reconnects on disconnect"""

    RECONNECT_INTERVAL = 5

    def __init__(self, host: str = ""):
        self.host = host or os.environ.get("SERVER_HOST", "")
        self._ip = resolve_to_ip(self.host)
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
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping",
                "-c",
                "1",
                "-W",
                "2",
                self._ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode()
            import re

            match = re.search(r"time=([\d.]+)", output)
            if match:
                latency = float(match.group(1))
                if latency < 200:
                    self.state = NetState(NetStatus.GREEN, latency, f"{latency:.0f}ms")
                elif latency < 500:
                    self.state = NetState(NetStatus.YELLOW, latency, f"{latency:.0f}ms")
                else:
                    self.state = NetState(NetStatus.RED, latency, f"{latency:.0f}ms")
                return self.state.status != NetStatus.RED
            self.state = NetState(NetStatus.RED, 0, "Timeout")
            return False
        except (asyncio.TimeoutError, Exception):
            self.state = NetState(NetStatus.RED, 0, "Disconnected")
            return False
