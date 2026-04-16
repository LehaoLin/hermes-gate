"""Remote tmux session management + local records"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from hermes_gate.servers import resolve_to_ip


def _config_dir() -> Path:
    d = Path.home() / ".hermes-gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sessions_file(user: str, host: str) -> Path:
    """One local record file per server"""
    return _config_dir() / f"sessions_{user}@{host}.json"


def _load_local(user: str, host: str) -> list[dict]:
    """Load local session records [{"id": 0, "created": "..."}, ...]"""
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
    """Find the first available id starting from 0"""
    used = {s["id"] for s in sessions}
    i = 0
    while i in used:
        i += 1
    return i


class SessionManager:
    """Manage tmux sessions on server, tracked with local records"""

    def __init__(self, user: str, host: str, port: str = "22"):
        self.user = user
        self.host = host
        self._ip = resolve_to_ip(host)
        self.port = port

    # ─── SSH Low-level ─────────────────────────────────────────────

    def _ssh_cmd(self, *args, timeout: int = 10) -> subprocess.CompletedProcess:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"ConnectTimeout={timeout}",
            "-p",
            self.port,
            f"{self.user}@{self._ip}",
            *args,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)

    def _ssh_output(self, *args, timeout: int = 10) -> str:
        result = self._ssh_cmd(*args, timeout=timeout)
        return result.stdout.strip()

    # ─── Session Operations ────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """List all locally recorded sessions (with remote alive status)"""
        local = _load_local(self.user, self.host)
        if not local:
            return []

        # Check which remote tmux sessions are alive
        output = self._ssh_output("tmux list-sessions -F '#{session_name}' 2>/dev/null")
        alive = set(output.splitlines()) if output else set()

        result = []
        for s in local:
            name = f"gate-{s['id']}"
            s["name"] = name
            s["alive"] = name in alive
            result.append(s)
        return result

    def create_session(self) -> dict:
        """Create session: find smallest available id → create remote tmux → save local record"""
        local = _load_local(self.user, self.host)

        remote_output = self._ssh_output(
            "tmux list-sessions -F '#{session_name}' 2>/dev/null"
        )
        remote_names = set(remote_output.splitlines()) if remote_output else set()

        local_ids = {s["id"] for s in local}
        sid = 0
        while True:
            if sid not in local_ids and f"gate-{sid}" not in remote_names:
                break
            sid += 1

        name = f"gate-{sid}"
        now = datetime.now().isoformat(timespec="seconds")

        result = self._ssh_cmd(f"tmux new-session -d -s {name} 'bash -l -c hermes'")
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create remote session: {result.stderr.strip()}"
            )

        entry = {"id": sid, "created": now}
        local.append(entry)
        _save_local(self.user, self.host, local)

        entry["name"] = name
        entry["alive"] = True
        return entry

    def kill_session(self, session_id: int) -> bool:
        """Kill remote session and remove from local records"""
        name = f"gate-{session_id}"
        result = self._ssh_cmd(f"tmux kill-session -t {name} 2>/dev/null")

        # Remove from local regardless of remote success
        local = _load_local(self.user, self.host)
        local = [s for s in local if s["id"] != session_id]
        _save_local(self.user, self.host, local)

        return result.returncode == 0

    def attach_cmd(self, session_id: int) -> list[str]:
        name = f"gate-{session_id}"
        if self._has_mosh():
            return [
                "mosh",
                "--ssh",
                f"ssh -p {self.port}",
                f"{self.user}@{self._ip}",
                "--",
                "tmux",
                "attach",
                "-d",
                "-t",
                name,
            ]
        else:
            return [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-p",
                self.port,
                f"{self.user}@{self._ip}",
                "-t",
                f"tmux attach -d -t {name}",
            ]

    def _has_mosh(self) -> bool:
        import shutil

        return shutil.which("mosh") is not None
