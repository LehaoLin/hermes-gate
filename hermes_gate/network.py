"""网络状态监控"""
import asyncio
import subprocess
import os
from enum import Enum
from dataclasses import dataclass


class NetStatus(Enum):
    GREEN = "green"      # 连通畅通
    YELLOW = "yellow"    # 不稳定
    RED = "red"          # 断线


@dataclass
class NetState:
    status: NetStatus = NetStatus.RED
    latency: float = 0.0   # ms
    message: str = "未检测"


class NetworkMonitor:
    """异步网络监控，定期 ping 服务器"""

    def __init__(self):
        self.host = os.environ.get("SERVER_HOST", "")
        self.state = NetState()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """启动后台监控"""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        """每 3 秒探测一次"""
        while self._running:
            await self._probe()
            await asyncio.sleep(3)

    async def _probe(self):
        """执行一次 ping 探测"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", "2", self.host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode()

            # 提取延迟
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
            else:
                self.state = NetState(NetStatus.RED, 0, "超时")
        except (asyncio.TimeoutError, Exception):
            self.state = NetState(NetStatus.RED, 0, "断线")
