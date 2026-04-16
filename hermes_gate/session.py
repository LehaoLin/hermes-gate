"""远端 tmux session 管理 + 本地记录"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


def _config_dir() -> Path:
    d = Path.home() / ".hermes-gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sessions_file(user: str, host: str) -> Path:
    """每个服务器一个本地记录文件"""
    return _config_dir() / f"sessions_{user}@{host}.json"


def _load_local(user: str, host: str) -> list[dict]:
    """加载本地 session 记录 [{"id": 0, "created": "..."}, ...]"""
    f = _sessions_file(user, host)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_local(user: str, host: str, sessions: list[dict]) -> None:
    f = _sessions_file(user, host)
    f.write_text(json.dumps(sessions, indent=2, ensure_ascii=False))


def _next_id(sessions: list[dict]) -> int:
    """从 0 开始遍历，找到第一个不存在的 id"""
    used = {s["id"] for s in sessions}
    i = 0
    while i in used:
        i += 1
    return i


class SessionManager:
    """管理服务器上的 tmux session，本地记录跟踪"""

    def __init__(self, user: str, host: str, port: str = "22"):
        self.user = user
        self.host = host
        self.port = port

    # ─── SSH 底层 ──────────────────────────────────────────────────

    def _ssh_cmd(self, *args, timeout: int = 10) -> subprocess.CompletedProcess:
        cmd = [
            "ssh", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={timeout}",
            "-p", self.port,
            f"{self.user}@{self.host}",
            *args,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)

    def _ssh_output(self, *args, timeout: int = 10) -> str:
        result = self._ssh_cmd(*args, timeout=timeout)
        return result.stdout.strip()

    # ─── Session 操作 ──────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """列出本地记录的所有 session（附带远端存活状态）"""
        local = _load_local(self.user, self.host)
        if not local:
            return []

        # 查远端哪些 tmux session 还活着
        output = self._ssh_output(
            "tmux list-sessions -F '#{session_name}' 2>/dev/null"
        )
        alive = set(output.splitlines()) if output else set()

        result = []
        for s in local:
            name = f"gate-{s['id']}"
            s["name"] = name
            s["alive"] = name in alive
            result.append(s)
        return result

    def create_session(self) -> dict:
        """新建 session：找最小可用 id → 远端创建 tmux → 本地记录"""
        local = _load_local(self.user, self.host)
        sid = _next_id(local)
        name = f"gate-{sid}"
        now = datetime.now().isoformat(timespec="seconds")

        # 远端创建 detached tmux session，运行 hermes tui
        result = self._ssh_cmd(
            f"tmux new-session -d -s {name} 'hermes tui'"
        )
        if result.returncode != 0:
            raise RuntimeError(f"远端创建 session 失败: {result.stderr.strip()}")

        entry = {"id": sid, "created": now}
        local.append(entry)
        _save_local(self.user, self.host, local)

        entry["name"] = name
        entry["alive"] = True
        return entry

    def kill_session(self, session_id: int) -> bool:
        """杀死远端 session 并从本地记录移除"""
        name = f"gate-{session_id}"
        result = self._ssh_cmd(f"tmux kill-session -t {name} 2>/dev/null")

        # 无论远端是否成功，都从本地移除
        local = _load_local(self.user, self.host)
        local = [s for s in local if s["id"] != session_id]
        _save_local(self.user, self.host, local)

        return result.returncode == 0

    def attach_cmd(self, session_id: int) -> list[str]:
        """返回 mosh/ssh 连接命令"""
        name = f"gate-{session_id}"
        if self._has_mosh():
            return [
                "mosh", "--ssh", f"ssh -p {self.port}",
                f"{self.user}@{self.host}",
                "--", "tmux", "attach", "-d", "-t", name,
            ]
        else:
            return [
                "ssh", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-p", self.port,
                f"{self.user}@{self.host}",
                "-t", f"tmux attach -d -t {name}",
            ]

    def _has_mosh(self) -> bool:
        import shutil
        return shutil.which("mosh") is not None
