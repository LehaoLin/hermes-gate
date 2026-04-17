"""Hermes Gate Main TUI Application — Built with Textual"""

import asyncio
import re
import shlex

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Center
from textual.events import Key
from textual.widgets import (
    Header,
    Footer,
    Label,
    Button,
    ListItem,
    ListView,
    Input,
    Static,
)
from textual.reactive import reactive
from textual import work
from textual.screen import ModalScreen

from hermes_gate.session import SessionManager
from hermes_gate.network import NetworkMonitor, NetStatus
from hermes_gate.servers import (
    load_servers,
    add_server,
    display_name,
    find_ssh_alias,
)


# ─── Add Server Dialog ────────────────────────────────────────────


class NewServerScreen(ModalScreen[str | None]):
    CSS = """
    NewServerScreen { align: center middle; }
    #dialog {
        width: 60; height: 11;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #dialog-title { text-style: bold; margin-bottom: 1; }
    #input { margin-bottom: 1; }
    #hint { color: $text-muted; margin-bottom: 1; }
    #btn-row { layout: horizontal; height: auto; }
    #btn-row Button { margin-right: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("🔗 Add Server", id="dialog-title")
            yield Input(
                placeholder="e.g.: root@1.2.3.4 or admin@myserver:2222", id="input"
            )
            yield Label("Enter to confirm · Esc to cancel", id="hint")
            with Horizontal(id="btn-row"):
                yield Button("Connect", variant="success", id="btn-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.dismiss(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            val = self.query_one("#input", Input).value.strip()
            if val:
                self.dismiss(val)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Connecting Dialog ────────────────────────────────────────────


class ConnectingScreen(ModalScreen):
    CSS = """
    ConnectingScreen { align: center middle; }
    #connect-dialog {
        width: 50; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self._msg = message

    def compose(self) -> ComposeResult:
        with Container(id="connect-dialog"):
            yield Label(self._msg)

    def update_msg(self, msg: str) -> None:
        try:
            self.query_one(Label).update(msg)
        except Exception:
            pass


# ─── Status Dot ──────────────────────────────────────────────────


class StatusDot(Label):
    status: reactive[str] = reactive("red")

    def watch_status(self, new_status: str) -> None:
        from rich.text import Text

        colors = {"green": "#00FF00", "yellow": "#FFFF00", "red": "#FF0000"}
        labels = {"green": "Connected", "yellow": "Unstable", "red": "OFFLINE"}
        c = colors.get(new_status, "#FF0000")
        lb = labels.get(new_status, "?")
        t = Text()
        t.append("● ", style=f"bold {c}")
        t.append(lb, style=c)
        self.update(t)

    def on_mount(self) -> None:
        self.status = "red"


class InputDot(Label):
    """Small status dot before the input field"""

    net: reactive[str] = reactive("red")

    def watch_net(self, val: str) -> None:
        from rich.text import Text

        color = "#00FF00" if val == "green" else "#FF0000"
        t = Text("● ", style=f"bold {color}")
        self.update(t)

    def on_mount(self) -> None:
        self.net = "red"


# ─── Main Application ────────────────────────────────────────────


class HermesGateApp(App):
    CSS = """
    Screen { layout: vertical; }

    /* ── 选择屏通用 ── */
    #server-screen, #session-screen {
        align: center middle; height: 1fr;
    }
    #server-box, #session-box {
        width: 60; height: auto; max-height: 85%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #server-title, #session-title {
        text-align: center; text-style: bold; padding: 0 0 1 0;
    }
    #server-list, #session-list {
        height: auto; max-height: 18; margin-bottom: 1;
    }
    #server-hint, #session-hint {
        color: $text-muted; text-align: center;
    }

    /* ── Hermes 查看器 ── */
    #status-bar {
        dock: top; height: 3;
        background: $surface; border-bottom: solid $primary;
        padding: 0 1; layout: horizontal;
    }
    #title { width: auto; padding: 1 2 0 0; }
    #net-status { width: auto; padding: 1 0 0 0; }
    #latency { width: auto; padding: 1 0 0 1; color: $text-muted; }

    #viewer-area {
        height: 1fr; layout: vertical;
    }
    #hermes-output {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
        overflow-y: auto;
        background: $surface;
    }
    #input-bar {
        height: 3;
        padding: 0 1; layout: horizontal;
        background: $surface;
        border-top: solid $primary;
    }
    #input-dot { width: auto; padding: 1 1 0 0; }
    #hermes-input { width: 1fr; }
    #viewer-hint {
        color: $text-muted; text-align: center;
        padding: 0 1; height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "noop", show=False),
        Binding("q", "quit", "Quit"),
    ]
    TITLE = "⚡ Hermes Gate"

    # 每个 phase 的 bindings（含统一的 Shift+Tab 返回）
    _BIND_SELECT = [
        Binding("ctrl+q", "noop", show=False),
        Binding("d", "delete_server", "Delete"),
        Binding("q", "quit", "Quit"),
    ]
    _BIND_SESSION = [
        Binding("ctrl+q", "noop", show=False),
        Binding("n", "new_session", "New"),
        Binding("k", "kill_session", "Kill"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "attach_session", "Attach"),
        Binding("escape", "back", "Back"),
        Binding("shift+tab", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]
    _BIND_VIEWER = [
        Binding("ctrl+q", "noop", show=False),
        Binding("ctrl+c", "remote_interrupt", "Remote Interrupt"),
        Binding("escape", "back", "Back", show=False),
        Binding("shift+tab", "back", "Back", show=False),
        Binding("ctrl+b", "back", "Back"),
        Binding("ctrl+e", "remote_escape", "Remote Esc"),
    ]

    def __init__(self):
        super().__init__()
        self.session_mgr: SessionManager | None = None
        self.net_monitor: NetworkMonitor | None = None
        self.sessions: list[dict] = []
        self._server: dict | None = None
        self._current_session_id: int | None = None
        self._phase = "select"  # select | session | viewer

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def on_mount(self) -> None:
        self._show_server_select()

    # ═══════════════════════════════════════════════════════════════
    # Step 1: Server Selection
    # ═══════════════════════════════════════════════════════════════

    def _clear(self) -> None:
        for wid in ("server-screen", "session-screen", "status-bar", "viewer-area"):
            try:
                self.query_one(f"#{wid}").remove()
            except Exception:
                pass

    def _show_server_select(self) -> None:
        self._phase = "select"
        self._clear()
        self.BINDINGS = self._BIND_SELECT

        servers = load_servers()
        items = [ListItem(Label(f" 🖥️  {display_name(s)}"), name="srv") for s in servers]
        items.append(ListItem(Label(" ➕  Add Server..."), name="new-srv"))

        self.mount(
            Center(
                Vertical(
                    Label("⚡ Hermes Gate — Select Server", id="server-title"),
                    ListView(*items, id="server-list"),
                    Label(
                        "↑↓ Select · Enter Connect · D Delete · Q Quit",
                        id="server-hint",
                    ),
                    id="server-box",
                ),
                id="server-screen",
            )
        )
        self.query_one("#server-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._phase == "select":
            self._on_server_selected(event)
        elif self._phase == "session":
            self._on_session_selected(event)

    def _on_server_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None:
            return
        servers = load_servers()
        if idx >= len(servers):
            self._prompt_new_server()
        else:
            self._connect_server(servers[idx])

    def action_noop(self) -> None:
        pass

    def action_delete_server(self) -> None:
        """D key to delete selected server (only removes from servers.json)"""
        if self._phase != "select":
            return
        lv = self.query_one("#server-list", ListView)
        idx = lv.index
        if idx is None:
            return
        servers = load_servers()
        if idx >= len(servers):
            return
        server = servers[idx]
        name = display_name(server)

        from hermes_gate.servers import remove_server

        remove_server(server["user"], server["host"], server.get("port", "22"))
        self._hint("server-hint", f"Deleted {name}")
        # 刷新列表
        self._clear()
        self._show_server_select()

    def _prompt_new_server(self) -> None:
        def handle(result: str | None):
            if not result or not result.strip():
                return
            text = result.strip()

            # Try resolving as SSH config alias (e.g. "prod-server")
            from hermes_gate.servers import resolve_ssh_config
            ssh_cfg = resolve_ssh_config(text)
            if ssh_cfg:
                ssh_cfg["ssh_alias"] = text
                self._connect_server(ssh_cfg, new=True)
                return

            # Parse user@host[:port] format
            if "@" not in text:
                self._hint("server-hint", "Invalid format. Use user@host or SSH alias")
                return
            user, host_port = text.split("@", 1)
            user = user.strip()
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                host, port = host.strip(), port.strip()
            else:
                host, port = host_port.strip(), "22"
            if not user or not host:
                self._hint("server-hint", "Username and host cannot be empty")
                return
            self._connect_server({"user": user, "host": host, "port": port}, new=True)

        self.push_screen(NewServerScreen(), handle)

    # ─── Connect Server ────────────────────────────────────────────

    def _connect_server(self, server: dict, new: bool = False) -> None:
        user, host = server["user"], server["host"]
        port = server.get("port", "22")
        ssh_alias = server.get("ssh_alias") or find_ssh_alias(user, host, port)
        if ssh_alias:
            server = {**server, "ssh_alias": ssh_alias}
        name = display_name(server)
        scr = ConnectingScreen(f"🔍 Connecting to {name} ...")
        self.push_screen(scr)

        async def _do():
            scr.update_msg(f"🔍 Testing SSH connection to {name} ...")
            if not await self._ssh_ok(user, host, port, ssh_alias):
                self.pop_screen()
                self._hint(
                    "server-hint",
                    f"Cannot connect to {name}, check address and keys"
                    if new
                    else f"Cannot connect to {name}",
                )
                return
            scr.update_msg(f"🔍 Checking tmux on {name} ...")
            if not await self._remote_command_ok(
                user, host, port, "bash -l -c 'command -v tmux >/dev/null'", ssh_alias
            ):
                self.pop_screen()
                self._hint("server-hint", "Please install tmux on the server")
                return
            scr.update_msg(f"🔍 Checking hermes on {name} ...")
            if not await self._hermes_ok(user, host, port, ssh_alias):
                self.pop_screen()
                self._hint("server-hint", "Please install hermes on the server")
                return
            if new:
                add_server(user, host, port, ssh_alias=ssh_alias)
            self._server = {**server, "ssh_alias": ssh_alias} if ssh_alias else server
            self.pop_screen()
            self._show_session_list(user, host, port, ssh_alias)

        self.run_worker(_do(), exclusive=True)

    async def _ssh_ok(self, user: str, host: str, port: str = "22", ssh_alias: str | None = None) -> bool:
        try:
            mgr = SessionManager(user, host, port, ssh_alias=ssh_alias)
            p = await asyncio.create_subprocess_exec(
                *mgr.ssh_base_args(timeout=8),
                "echo",
                "ok",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(p.communicate(), timeout=15)
            return p.returncode == 0 and b"ok" in out
        except Exception:
            return False

    async def _hermes_ok(self, user: str, host: str, port: str = "22", ssh_alias: str | None = None) -> bool:
        return await self._remote_command_ok(
            user,
            host,
            port,
            "bash -l -c 'command -v hermes >/dev/null && hermes --version >/dev/null'",
            ssh_alias,
        )

    async def _remote_command_ok(
        self,
        user: str,
        host: str,
        port: str,
        remote_command: str,
        ssh_alias: str | None = None,
    ) -> bool:
        try:
            mgr = SessionManager(user, host, port, ssh_alias=ssh_alias)
            p = await asyncio.create_subprocess_exec(
                *mgr.ssh_base_args(timeout=8),
                remote_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(p.communicate(), timeout=15)
            return p.returncode == 0
        except Exception:
            return False

    def _hint(self, hint_id: str, msg: str, error: bool = True) -> None:
        try:
            h = self.query_one(f"#{hint_id}", Label)
            prefix = "❌" if error else "✅"
            h.update(f"{prefix} {msg}")
            h.styles.color = "red" if error else "green"

            reset_text = {
                "server-hint": "↑↓ Select · Enter Connect · D Delete · Q Quit",
                "session-hint": "↑↓ Select · Enter Attach · N New · K Kill · Shift+Tab Back",
                "viewer-hint": "Ctrl+B Back · Ctrl+C Interrupt · Ctrl+E Remote Esc · Enter Send",
            }.get(hint_id, "")

            def reset_hint() -> None:
                if reset_text:
                    h.update(reset_text)
                h.styles.clear_rule("color")

            self.set_timer(3, reset_hint)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # Step 2: Session List
    # ═══════════════════════════════════════════════════════════════

    def _show_session_list(
        self, user: str, host: str, port: str = "22", ssh_alias: str | None = None
    ) -> None:
        self._phase = "session"
        self._clear()

        ssh_alias = ssh_alias or find_ssh_alias(user, host, port)
        self.session_mgr = SessionManager(user, host, port, ssh_alias=ssh_alias)
        self.net_monitor = NetworkMonitor(host, port)

        self.BINDINGS = self._BIND_SESSION

        server_name = display_name({"user": user, "host": host, "port": port})
        self.mount(
            Center(
                Vertical(
                    Label(f"⚡ {server_name} — Sessions", id="session-title"),
                    ListView(id="session-list"),
                    Label(
                        "↑↓ Select · Enter Attach · N New · K Kill · Shift+Tab Back",
                        id="session-hint",
                    ),
                    id="session-box",
                ),
                id="session-screen",
            )
        )
        self._refresh_sessions()
        self.query_one("#session-list", ListView).focus()

    def _on_session_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None:
            return
        if idx >= len(self.sessions):
            self.action_new_session()
        else:
            s = self.sessions[idx]
            if not s.get("alive"):
                self._hint("session-hint", f"{s['name']} is dead, please refresh")
                return
            self._enter_viewer(s["id"])

    @work(exit_on_error=False)
    async def _refresh_sessions(self) -> None:
        if not self.session_mgr:
            return
        try:
            loop = asyncio.get_event_loop()
            new_sessions = await loop.run_in_executor(
                None, self.session_mgr.list_sessions
            )
            # Only replace list after successful fetch — preserve existing on failure
            self.sessions = new_sessions
            lv = self.query_one("#session-list", ListView)
            await lv.clear()
            for s in self.sessions:
                alive = "🟢" if s.get("alive") else "⚪"
                created = s.get("created", "")
                if "T" in created:
                    created = (
                        created.split("T")[0][5:] + " " + created.split("T")[1][:5]
                    )
                await lv.append(
                    ListItem(
                        Label(f" {alive} gate-{s['id']}   ({created})"), name="sess"
                    )
                )
            await lv.append(ListItem(Label(" ➕  New Session..."), name="new-sess"))
            lv.focus()
        except (TimeoutError, ConnectionError, RuntimeError) as e:
            self._hint("session-hint", f"Refresh failed: {e}")
        except Exception as e:
            self._hint("session-hint", f"Refresh failed: {e}")

    def action_refresh(self) -> None:
        if self._phase == "session":
            self._refresh_sessions()

    # ─── New Session ────────────────────────────────────────────────

    def action_new_session(self) -> None:
        if self._phase != "session":
            return
        self._create_session()

    @work(exit_on_error=False)
    async def _create_session(self) -> None:
        if not self.session_mgr:
            return
        try:
            loop = asyncio.get_event_loop()
            entry = await loop.run_in_executor(None, self.session_mgr.create_session)
            self._enter_viewer(entry["id"])
        except Exception as e:
            self._hint("session-hint", f"Failed to create: {e}")

    # ─── Kill Session ────────────────────────────────────────────────

    def action_kill_session(self) -> None:
        if self._phase != "session":
            return
        idx = self.query_one("#session-list", ListView).index
        if idx is None or idx >= len(self.sessions):
            self._hint("session-hint", "Please select a session first")
            return
        self._kill(self.sessions[idx]["id"])

    @work(exit_on_error=False)
    async def _kill(self, sid: int) -> None:
        if not self.session_mgr:
            return
        name = f"gate-{sid}"
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self.session_mgr.kill_session, sid)
        self._hint(
            "session-hint",
            f"Killed {name}"
            if ok
            else f"{name} no longer exists on remote, record removed",
        )
        self._refresh_sessions()

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Hermes Viewer (live output + input + network dot)
    # ═══════════════════════════════════════════════════════════════

    def _enter_viewer(self, session_id: int) -> None:
        """Enter hermes viewer interface"""
        self._phase = "viewer"
        self._current_session_id = session_id
        self._clear()

        name = f"gate-{session_id}"
        server_name = display_name(self._server) if self._server else name

        self.BINDINGS = self._BIND_VIEWER

        self.mount(
            Horizontal(
                Label(f"⚡ {server_name} → {name}", id="title"),
                StatusDot(id="net-status"),
                Label("", id="latency"),
                id="status-bar",
            ),
            Vertical(
                Static("", id="hermes-output"),
                Horizontal(
                    InputDot(id="input-dot"),
                    Input(
                        placeholder="Enter prompt to send to remote hermes ...",
                        id="hermes-input",
                    ),
                    id="input-bar",
                ),
                Label(
                    "Ctrl+B Back · Ctrl+C Interrupt · Ctrl+E Remote Esc · Enter Send",
                    id="viewer-hint",
                ),
                id="viewer-area",
            ),
        )

        self.query_one("#hermes-input", Input).focus()
        self._start_network_monitor()
        self._start_output_poll(session_id)

    # ─── Poll Remote tmux Output ───────────────────────────────────

    @work(exit_on_error=False)
    async def _start_output_poll(self, session_id: int) -> None:
        """Poll remote tmux pane content every 1.5s via SSH"""
        name = f"gate-{session_id}"
        mgr = self.session_mgr
        if not mgr:
            return
        prev_content = ""
        last_error = ""

        while (
            self._phase == "viewer"
            and self.session_mgr is mgr
            and self._current_session_id == session_id
        ):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *mgr.ssh_base_args(timeout=5),
                    mgr.tmux_command(*_tmux_capture_args(name)),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    err = stderr.decode(errors="replace").strip() or "capture-pane failed"
                    raise RuntimeError(err)
                raw = stdout.decode(errors="replace")

                clean = _strip_ansi(raw)

                if clean != prev_content:
                    prev_content = clean
                    try:
                        widget = self.query_one("#hermes-output", Static)
                        widget.update(_tmux_capture_to_text(raw))
                        widget.scroll_end(animate=False)
                    except Exception:
                        pass

                last_error = ""
                await asyncio.sleep(1.5)
            except Exception as exc:
                err = str(exc) or exc.__class__.__name__
                if err != last_error:
                    last_error = err
                    self._hint("viewer-hint", f"Output refresh failed: {err}")
                await asyncio.sleep(3)

    # ─── User Input → Send to Remote tmux ──────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "hermes-input" or self._phase != "viewer":
            return
        text = event.value
        if not text:
            return
        event.input.value = ""
        self._send_to_remote(text)

    def action_remote_escape(self) -> None:
        """Send Escape/C-u to the remote Hermes pane without leaving the viewer."""
        if self._phase == "viewer":
            self._send_keys_to_remote("Escape", "C-u")

    def action_remote_interrupt(self) -> None:
        """Interrupt the current remote Hermes request without leaving the viewer."""
        if self._phase == "viewer":
            self._send_keys_to_remote("C-c")

    @work(exit_on_error=False)
    async def _send_to_remote(self, text: str) -> None:
        """Send user input to remote tmux session via SSH stdin + tmux buffer.

        User text goes through stdin only — never into the remote command string —
        so shell metacharacters cannot be interpreted by the remote shell.
        """
        if not self.session_mgr or self._current_session_id is None:
            return
        name = f"gate-{self._current_session_id}"
        mgr = self.session_mgr

        # Build fixed remote command: load buffer from stdin, paste, send Enter.
        # Session name is always gate-{id} — never user-supplied.
        remote_cmd = _build_tmux_send_command(name)

        proc = await asyncio.create_subprocess_exec(
            *mgr.ssh_base_args(timeout=10),
            mgr.login_shell_command(remote_cmd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=text.encode("utf-8")),
            timeout=15,
        )
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip() or "send failed"
            self._hint("viewer-hint", f"Send failed: {err}")
            return
        self._hint("viewer-hint", "Sent", error=False)

    @work(exit_on_error=False)
    async def _send_keys_to_remote(self, *keys: str) -> None:
        """Send control keys to the remote tmux session."""
        if not keys or not self.session_mgr or self._current_session_id is None:
            return
        name = f"gate-{self._current_session_id}"
        mgr = self.session_mgr
        remote_cmd = _build_tmux_key_command(name, *keys)
        action = _remote_key_action_name(keys)

        proc = await asyncio.create_subprocess_exec(
            *mgr.ssh_base_args(timeout=10),
            mgr.login_shell_command(remote_cmd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip() or "key send failed"
            self._hint("viewer-hint", f"{action} failed: {err}")
            return
        self._hint("viewer-hint", f"{action} sent", error=False)

    # ─── Network Monitor ────────────────────────────────────────────

    @work(exit_on_error=False)
    async def _start_network_monitor(self) -> None:
        monitor = self.net_monitor
        if not monitor:
            return
        await monitor.start()
        was_reconnecting = False
        while self._phase in ("viewer",) and self.net_monitor is monitor:
            await asyncio.sleep(0.5)
            state = monitor.state
            try:
                dot = self.query_one("#net-status", StatusDot)
                lat = self.query_one("#latency", Label)
                dot.status = state.status.value
                lat.update(state.message)
            except Exception:
                pass
            try:
                idot = self.query_one("#input-dot", InputDot)
                idot.net = state.status.value
            except Exception:
                pass
            if state.reconnecting and self._phase == "viewer":
                was_reconnecting = True
                try:
                    output = self.query_one("#hermes-output", Static)
                    output.update(
                        f"🔄 Network disconnected! Reconnecting...\n\n"
                        f"   Countdown: {state.countdown}s\n"
                        f"   Attempt #{state.reconnect_attempt}\n\n"
                        f"   Remote hermes is still running, will auto-resume after reconnection"
                    )
                except Exception:
                    pass
            elif (
                was_reconnecting and not state.reconnecting and self._phase == "viewer"
            ):
                was_reconnecting = False
                try:
                    output = self.query_one("#hermes-output", Static)
                    output.update("✅ Reconnected! Resuming output...")
                except Exception:
                    pass

    # ─── Navigation ────────────────────────────────────────────────

    def action_attach_session(self) -> None:
        """Enter key to attach session"""
        if self._phase != "session":
            return
        idx = self.query_one("#session-list", ListView).index
        if idx is None or idx >= len(self.sessions):
            return
        s = self.sessions[idx]
        if not s.get("alive"):
            self._hint("session-hint", f"{s['name']} is dead, please refresh")
            return
        self._enter_viewer(s["id"])

    def action_back(self) -> None:
        """Shift+Tab / Esc — Go back to previous level

        viewer → session list (remote hermes unaffected, tmux keeps running in background)
        session list → server selection
        server selection → no-op (already at top level)
        """
        # Stop network monitor (all back scenarios)
        if self.net_monitor:
            asyncio.create_task(self.net_monitor.stop())
            self.net_monitor = None

        if self._phase == "viewer":
            # Return to session list (remote tmux not killed)
            self._phase = "session"
            if self._server and self.session_mgr:
                self._show_session_list(
                    self._server["user"],
                    self._server["host"],
                    self._server.get("port", "22"),
                    self._server.get("ssh_alias"),
                )

        elif self._phase == "session":
            # Return to server selection
            self._show_server_select()

    async def on_shutdown_request(self) -> None:
        if self.net_monitor:
            await self.net_monitor.stop()
        await super().on_shutdown_request()


# ─── Utility Functions ────────────────────────────────────────────

_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?[a-zA-Z]|\x1b\([A-Z]"
)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences"""
    return _ANSI_RE.sub("", text)


def _tmux_capture_to_text(raw: str) -> Text:
    """Render tmux capture as plain terminal text, not Rich markup."""
    return Text(_strip_ansi(raw).rstrip("\n"))


def _tmux_capture_args(session_name: str) -> tuple[str, ...]:
    """Capture the current tmux pane view, not scrollback history."""
    return ("capture-pane", "-t", session_name, "-p")


def _tmux_command(*args: str) -> str:
    """Build one shell-safe tmux command."""
    return shlex.join(["tmux", *[str(arg) for arg in args]])


def _build_tmux_send_command(session_name: str) -> str:
    """Build the remote tmux command used to inject one complete prompt."""
    return " && ".join(
        [
            _build_tmux_key_command(session_name, "C-u"),
            _tmux_command("load-buffer", "-b", "hermes-gate-input", "-"),
            _tmux_command("paste-buffer", "-b", "hermes-gate-input", "-t", session_name),
            _build_tmux_key_command(session_name, "Enter"),
        ]
    )


def _build_tmux_key_command(session_name: str, *keys: str) -> str:
    """Build a shell-safe tmux send-keys command."""
    return _tmux_command("send-keys", "-t", session_name, *keys)


def _remote_key_action_name(keys: tuple[str, ...]) -> str:
    """Name common remote key actions for user-facing hints."""
    if keys == ("C-c",):
        return "Remote interrupt"
    if keys == ("Escape", "C-u"):
        return "Remote Esc"
    return "Remote keys"
