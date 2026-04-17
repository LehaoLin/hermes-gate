"""Remote tmux session management + local records"""

import json
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from hermes_gate.servers import resolve_to_ip, ssh_config_path

_GATE_SESSION_RE = re.compile(r"^gate-(\d+)$")


def _config_dir() -> Path:
    d = Path.home() / ".hermes-gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _server_key(user: str, host: str, port: str) -> str:
    """Stable encoded key for (user, host, port) — safe for filenames."""
    return f"{quote(user, safe='')}@{quote(host, safe='')}#{quote(str(port), safe='')}"


def _sessions_file(user: str, host: str, port: str = "22") -> Path:
    """One local record file per (user, host, port) tuple."""
    key = _server_key(user, host, port)
    return _config_dir() / f"sessions_{key}.json"


def _legacy_sessions_file(user: str, host: str) -> Path:
    """Pre-port-isolation filename for backward compatibility."""
    return _config_dir() / f"sessions_{user}@{host}.json"


def _load_local(user: str, host: str, port: str = "22") -> list[dict]:
    """Load local session records [{"id": 0, "created": "..."}, ...]"""
    f = _sessions_file(user, host, port)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    # Backward compatibility: port=22 may have legacy file without port in name
    if port == "22":
        legacy = _legacy_sessions_file(user, host)
        if legacy.exists():
            try:
                entries = json.loads(legacy.read_text())
                # Migrate to new format silently
                _save_local(user, host, port, entries)
                return entries
            except (json.JSONDecodeError, OSError):
                pass
    return []


def _save_local(user: str, host: str, port: str, sessions: list[dict]) -> None:
    f = _sessions_file(user, host, port)
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

    def __init__(
        self, user: str, host: str, port: str = "22", ssh_alias: str | None = None
    ):
        self.user = user
        self.host = host
        self._ip = resolve_to_ip(host)
        self.port = port
        self.ssh_alias = ssh_alias

    # ─── SSH Low-level ─────────────────────────────────────────────

    def ssh_base_args(self, timeout: int = 10) -> list[str]:
        """Build SSH argv prefix for this server, preserving config aliases."""
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"ConnectTimeout={timeout}",
        ]
        if self.ssh_alias:
            ssh_config = ssh_config_path()
            if ssh_config.exists():
                cmd.extend(["-F", str(ssh_config)])
            cmd.append(self.ssh_alias)
        else:
            cmd.extend(["-p", self.port, f"{self.user}@{self._ip}"])
        return cmd

    @staticmethod
    def login_shell_command(command: str) -> str:
        """Run a generated remote command through the user's login shell."""
        return f"bash -l -c {shlex.quote(command)}"

    @staticmethod
    def tmux_command(*args: str, suppress_stderr: bool = False) -> str:
        """Build a tmux command string for the remote login shell."""
        command = shlex.join(["tmux", *[str(arg) for arg in args]])
        if suppress_stderr:
            command = f"{command} 2>/dev/null"
        return SessionManager.login_shell_command(command)

    def _ssh_cmd(self, *args, timeout: int = 10) -> subprocess.CompletedProcess:
        cmd = [*self.ssh_base_args(timeout), *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)

    def _ssh_output(self, *args, timeout: int = 10) -> str:
        result = self._ssh_cmd(*args, timeout=timeout)
        # SSH connection failure returns 255 — treat as connection error
        if result.returncode == 255:
            raise ConnectionError(f"SSH connection failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _remote_session_names(self) -> set[str]:
        """Return remote tmux session names, treating no sessions as empty."""
        result = self._ssh_cmd(
            self.tmux_command("list-sessions", "-F", "#{session_name}", suppress_stderr=True)
        )
        if result.returncode == 255:
            raise ConnectionError(f"SSH connection failed: {result.stderr.strip()}")
        if result.returncode == 127:
            raise RuntimeError("tmux is not installed or is not available in the login PATH")
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    # ─── Session Operations ────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """List local records and discover existing remote gate-* sessions."""
        local = _load_local(self.user, self.host, self.port)

        remote_names = self._remote_session_names()
        remote_ids = {
            int(match.group(1))
            for name in remote_names
            if (match := _GATE_SESSION_RE.match(name))
        }

        result = []
        local_by_id = {s["id"]: s for s in local if isinstance(s.get("id"), int)}
        for sid in sorted(set(local_by_id) | remote_ids):
            entry = dict(local_by_id.get(sid, {"id": sid, "created": ""}))
            name = f"gate-{sid}"
            entry["name"] = name
            entry["alive"] = sid in remote_ids
            if sid not in local_by_id:
                entry["remote_only"] = True
            result.append(entry)
        return result

    def create_session(self) -> dict:
        """Create session: find smallest available id → create remote tmux → save local record"""
        local = _load_local(self.user, self.host, self.port)

        remote_names = self._remote_session_names()

        local_ids = {s["id"] for s in local}
        sid = 0
        while True:
            if sid not in local_ids and f"gate-{sid}" not in remote_names:
                break
            sid += 1

        name = f"gate-{sid}"
        now = datetime.now().isoformat(timespec="seconds")

        result = self._ssh_cmd(
            self.tmux_command("new-session", "-d", "-s", name, "bash -l -c hermes")
        )
        if result.returncode != 0:
            if result.returncode == 127:
                raise RuntimeError(
                    "Failed to create remote session: tmux is not installed or is not available in the login PATH"
                )
            raise RuntimeError(
                f"Failed to create remote session: {result.stderr.strip()}"
            )

        entry = {"id": sid, "created": now}
        local.append(entry)
        _save_local(self.user, self.host, self.port, local)

        entry["name"] = name
        entry["alive"] = True
        return entry

    def kill_session(self, session_id: int) -> bool:
        """Kill remote session and remove from local records"""
        name = f"gate-{session_id}"
        result = self._ssh_cmd(
            self.tmux_command("kill-session", "-t", name, suppress_stderr=True)
        )

        # Remove from local regardless of remote success
        local = _load_local(self.user, self.host, self.port)
        local = [s for s in local if s["id"] != session_id]
        _save_local(self.user, self.host, self.port, local)

        return result.returncode == 0

    def attach_cmd(self, session_id: int) -> list[str]:
        name = f"gate-{session_id}"
        return [*self.ssh_base_args(), "-t", f"tmux attach -d -t {name}"]
