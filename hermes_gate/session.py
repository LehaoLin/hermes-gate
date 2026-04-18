"""Remote tmux session management + local records"""

import json
import re
import shlex
import subprocess
import time
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

    def _ssh_options(self, timeout: int = 10) -> list[str]:
        opts = [
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={timeout}",
        ]
        if self.ssh_alias:
            ssh_config = ssh_config_path()
            if ssh_config.exists():
                opts.extend(["-F", str(ssh_config)])
        else:
            opts.extend(["-p", self.port])
        return opts

    def _ssh_destination(self) -> list[str]:
        if self.ssh_alias:
            return [self.ssh_alias]
        return [f"{self.user}@{self._ip}"]

    def ssh_base_args(self, timeout: int = 10) -> list[str]:
        """Build SSH argv prefix for this server, preserving config aliases."""
        return ["ssh", *self._ssh_options(timeout), *self._ssh_destination()]

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

    def _remote_session_info(self) -> dict[str, str]:
        """Return {session_name: created_epoch} for remote tmux sessions."""
        result = self._ssh_cmd(
            self.tmux_command(
                "list-sessions",
                "-F", "#{session_name}\t#{session_created}",
                suppress_stderr=True,
            )
        )
        if result.returncode == 255:
            raise ConnectionError(f"SSH connection failed: {result.stderr.strip()}")
        if result.returncode == 127:
            raise RuntimeError("tmux is not installed or is not available in the login PATH")
        if result.returncode != 0:
            return {}
        info = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2:
                info[parts[0]] = parts[1]
        return info

    # ─── Session Operations ────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """List local records and discover existing remote gate-* sessions."""
        local = _load_local(self.user, self.host, self.port)

        remote_info = self._remote_session_info()
        remote_ids = {}
        for name, epoch in remote_info.items():
            if (match := _GATE_SESSION_RE.match(name)):
                remote_ids[int(match.group(1))] = epoch

        result = []
        local_by_id = {s["id"]: s for s in local if isinstance(s.get("id"), int)}
        for sid in sorted(set(local_by_id) | set(remote_ids)):
            entry = dict(local_by_id.get(sid, {"id": sid, "created": ""}))
            name = f"gate-{sid}"
            if sid not in local_by_id:
                entry["remote_only"] = True
                epoch = remote_ids.get(sid, "")
                if epoch:
                    entry["created"] = datetime.fromtimestamp(
                        int(epoch)
                    ).strftime("%Y-%m-%dT%H:%M:%S")
            entry["name"] = name
            entry["alive"] = sid in remote_ids
            result.append(entry)
        return result

    def capture_session_preview(self, session_id: int) -> str:
        """Capture the last user-sent message from a session's tmux pane.

        Hermes shows user messages with a "●" prefix. We look for the last
        such line and extract the message text.
        """
        name = f"gate-{session_id}"
        result = self._ssh_cmd(
            self.tmux_command("capture-pane", "-t", name, "-p", "-S", "-50"),
            timeout=8,
        )
        if result.returncode != 0:
            return ""
        for line in reversed(result.stdout.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("● "):
                msg = stripped[2:].strip()
                if msg and len(msg) > 40:
                    msg = msg[:37] + "..."
                return msg
        return ""
        return ""

    def create_session(self) -> dict:
        """Create session: find smallest available id → create remote tmux → save local record"""
        local = _load_local(self.user, self.host, self.port)

        remote_names = set(self._remote_session_info().keys())

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

    @staticmethod
    def _tmux_session_missing(result: subprocess.CompletedProcess) -> bool:
        stderr = (result.stderr or "").lower()
        stdout = (result.stdout or "").lower()
        text = f"{stdout}\n{stderr}"
        return "can't find session" in text or "no such session" in text

    def kill_session(self, session_id: int) -> dict:
        """Send quit to hermes, kill remote tmux session, and remove local record."""
        name = f"gate-{session_id}"

        # Send 'q' to hermes inside the tmux session for graceful exit
        self._ssh_cmd(
            self.tmux_command("send-keys", "-t", name, "q", suppress_stderr=True)
        )
        time.sleep(1)

        # Detach any remaining clients, then kill the tmux session
        detach_result = self._ssh_cmd(
            self.tmux_command("detach-client", "-s", name, suppress_stderr=True)
        )
        if detach_result.returncode == 127:
            raise RuntimeError(
                "Failed to kill remote session: tmux is not installed or is not available in the login PATH"
            )

        result = self._ssh_cmd(
            self.tmux_command("kill-session", "-t", name, suppress_stderr=True)
        )
        if result.returncode == 127:
            raise RuntimeError(
                "Failed to kill remote session: tmux is not installed or is not available in the login PATH"
            )

        tmux_missing = self._tmux_session_missing(result)
        if result.returncode != 0 and not tmux_missing:
            raise RuntimeError(result.stderr.strip() or f"Failed to kill remote session {name}")

        local = _load_local(self.user, self.host, self.port)
        local = [s for s in local if s["id"] != session_id]
        _save_local(self.user, self.host, self.port, local)

        return {"removed": True, "tmux_missing": tmux_missing}

    def attach_cmd(self, session_id: int) -> list[str]:
        name = f"gate-{session_id}"
        cmd = ["ssh", "-t"]
        cmd.extend(self._ssh_options())
        cmd.extend(self._ssh_destination())
        cmd.append(f"tmux attach -d -t {name}")
        return cmd
