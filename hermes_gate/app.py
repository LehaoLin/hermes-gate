"""Hermes Gate Main TUI Application — Built with Textual"""

import asyncio
import shlex
import subprocess

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Center
from textual.widgets import (
    Header,
    Footer,
    Label,
    Button,
    ListItem,
    ListView,
    Input,
    LoadingIndicator,
)
from textual import work
from textual.screen import ModalScreen

from hermes_gate.session import SessionManager
from hermes_gate.network import NetworkMonitor
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


class ConfirmKillScreen(ModalScreen[bool]):
    HINT_TEXT = "enter/y kill · Esc/n cancel"
    TITLE_TEMPLATE = "Kill session {session_name}? [y/n]"
    CSS = """
    ConfirmKillScreen { align: center middle; }
    #kill-dialog {
        width: 60; height: auto;
        border: thick $error; background: $surface; padding: 1 2;
    }
    #kill-title { text-style: bold; margin-bottom: 1; }
    #kill-hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [
        Binding("y", "confirm", "Confirm"),
        Binding("n", "cancel", "Cancel"),
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Confirm"),
    ]

    def __init__(self, session_name: str):
        super().__init__()
        self.session_name = session_name
        self.TITLE_TEXT = self.TITLE_TEMPLATE.format(session_name=session_name)

    def compose(self) -> ComposeResult:
        with Container(id="kill-dialog"):
            yield Label(self.TITLE_TEXT, id="kill-title")
            yield Label(
                "This will detach any attached client, stop the remote Hermes session, and kill the tmux session."
            )
            yield Label(self.HINT_TEXT, id="kill-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WaitingScreen(ModalScreen[None]):
    CSS = """
    WaitingScreen { align: center middle; }
    #waiting-dialog {
        width: 52; height: auto;
        border: thick $warning; background: $surface; padding: 1 2;
    }
    #waiting-label { margin-bottom: 1; }
    """
    BINDINGS = []

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="waiting-dialog"):
            yield Label(self._message, id="waiting-label")
            yield LoadingIndicator()

    def set_error(self, message: str) -> None:
        self.query_one("#waiting-label", Label).update(message)
        self.query_one(LoadingIndicator).remove()
        self.set_timer(3, self.dismiss)


# ─── Main Application ────────────────────────────────────────────


class HermesGateApp(App):
    CSS = """
    Screen { layout: vertical; }

    /* ── Select / Session Screens ── */
    #server-screen, #session-screen {
        align: center middle; height: 1fr;
    }
    #server-box, #session-box {
        width: 72; height: auto; max-height: 85%;
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
    """

    BINDINGS = [
        Binding("ctrl+q", "noop", show=False),
        Binding("q", "quit", "Quit"),
        Binding("d", "delete_server", "Delete"),
        Binding("n", "new_session", "New"),
        Binding("k", "kill_session", "Kill"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "attach_session", "Attach"),
        Binding("escape", "noop", show=False),
        Binding("ctrl+b", "back", "Back"),
    ]
    TITLE = "⚡ Hermes Gate"

    def __init__(self):
        super().__init__()
        self.session_mgr: SessionManager | None = None
        self.net_monitor: NetworkMonitor | None = None
        self.sessions: list[dict] = []
        self._server: dict | None = None
        self._phase = "select"  # select | session

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def on_mount(self) -> None:
        self._show_server_select()

    def on_key(self, event) -> None:
        if event.key not in ("up", "down"):
            return
        try:
            lv_id = "#server-list" if self._phase == "select" else "#session-list"
            lv = self.query_one(lv_id, ListView)
        except Exception:
            return
        if not lv.has_focus:
            lv.focus()
            event.stop()

    # ═══════════════════════════════════════════════════════════════
    # Step 1: Server Selection
    # ═══════════════════════════════════════════════════════════════

    def _clear(self) -> None:
        for wid in ("server-screen", "session-screen"):
            try:
                widget = self.query_one(f"#{wid}")
                widget.remove()
            except Exception:
                pass

    def _show_server_select(self) -> None:
        self._phase = "select"
        self._clear()

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        session_actions = {"new_session", "kill_session", "refresh", "attach_session", "back"}
        select_actions = {"delete_server"}

        if action in session_actions:
            return self._phase == "session"
        if action in select_actions:
            return self._phase == "select"
        return True

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

    async def _ssh_ok(
        self, user: str, host: str, port: str = "22", ssh_alias: str | None = None
    ) -> bool:
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

    async def _hermes_ok(
        self, user: str, host: str, port: str = "22", ssh_alias: str | None = None
    ) -> bool:
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
                "session-hint": "↑↓ Select · Enter Attach · n New · k Kill · r Refresh · Ctrl+B Back · q Quit",
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
        server_name = display_name({"user": user, "host": host, "port": port})
        self.mount(
            Center(
                Vertical(
                    Label(f"⚡ {server_name} — Sessions", id="session-title"),
                    ListView(id="session-list"),
                    Label(
                        "↑↓ Select · Enter Attach · n New · k Kill · r Refresh · Ctrl+B Back · q Quit",
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
        session = self.sessions[idx]
        name = session.get("name") or f"gate-{session['id']}"

        def handle(confirm: bool) -> None:
            if confirm:
                self._kill(session["id"])

        self.push_screen(ConfirmKillScreen(name), handle)

    def _kill(self, sid: int) -> None:
        if not self.session_mgr:
            return
        name = f"gate-{sid}"
        screen = WaitingScreen(f"Waiting for {name} to be killed...")
        self.push_screen(screen)

        async def _do_kill() -> None:
            await self._do_kill_session(sid, screen)

        self.run_worker(_do_kill(), exit_on_error=False)

    async def _do_kill_session(self, sid: int, screen: WaitingScreen) -> None:
        name = f"gate-{sid}"
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self.session_mgr.kill_session, sid)
        except Exception as e:
            screen.set_error(f"Failed to kill {name}: {e}")
            return

        self.pop_screen()
        if result.get("tmux_missing"):
            self._hint("session-hint", f"{name} killed, local record removed", error=False)
        else:
            self._hint("session-hint", f"{name} killed", error=False)
        self._refresh_sessions()

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Attach to Remote tmux Session
    # ═══════════════════════════════════════════════════════════════

    def _enter_viewer(self, session_id: int) -> None:
        """Suspend TUI and attach to remote tmux session via SSH.

        The user gets a real terminal with the remote tmux session.
        - Ctrl+B detaches and returns to the session list.
        - A green status bar at the bottom shows connection status + hint.
        """
        mgr = self.session_mgr
        if not mgr:
            return
        name = f"gate-{session_id}"

        # Stop network monitor before suspending
        if self.net_monitor:
            asyncio.create_task(self.net_monitor.stop())
            self.net_monitor = None

        # Configure tmux: Ctrl+B → detach, green status bar at bottom
        self._configure_tmux_for_attach(mgr, name)

        # Suspend Textual and run SSH attach — user gets real terminal
        # The session list DOM stays mounted; after suspend returns we just
        # refresh it in place, avoiding any DuplicateIds issues entirely.
        cmd = mgr.attach_cmd(session_id)
        try:
            with self.suspend():
                subprocess.call(cmd)
        except Exception:
            subprocess.call(cmd)

        # Restore tmux session options to defaults
        self._restore_tmux_after_detach(mgr, name)

        # Refresh the session list (DOM was never touched, just re-query)
        self._refresh_sessions()
        try:
            self.query_one("#session-list", ListView).focus()
        except Exception:
            pass

    # ─── tmux Configuration ─────────────────────────────────────────

    def _configure_tmux_for_attach(self, mgr: SessionManager, name: str) -> None:
        """Configure tmux session for interactive attach.

        - Changes prefix from C-b to C-a (so C-b is free for detach)
        - Binds C-b in root table to detach-client
        - Sets a green status bar at the bottom showing connection status

        All commands are batched into a single SSH call for speed.
        """
        q = shlex.quote
        commands = " && ".join([
            # Change prefix to C-a so C-b can be used for detach
            f"tmux set-option -t {q(name)} prefix C-a",
            # Bind C-b in root table to detach directly
            f"tmux bind-key -T root C-b detach-client",
            # Status bar: green connection indicator at the bottom
            f"tmux set-option -t {q(name)} status on",
            f"tmux set-option -t {q(name)} status-position bottom",
            f"tmux set-option -t {q(name)} status-style 'bg=#1a1a2e,fg=#00ff00'",
            f"tmux set-option -t {q(name)} status-left '⚡ {name} '",
            f"tmux set-option -t {q(name)} status-left-length 30",
            f"tmux set-option -t {q(name)} status-left-style 'fg=#ffffff,bg=#1a1a2e'",
            f"tmux set-option -t {q(name)} status-right ' ● Connected   Ctrl+B: Back '",
            f"tmux set-option -t {q(name)} status-right-length 40",
            f"tmux set-option -t {q(name)} status-right-style 'fg=#00ff00,bg=#1a1a2e'",
        ])
        remote_cmd = f"bash -l -c {q(commands)}"

        try:
            subprocess.run(
                [*mgr.ssh_base_args(timeout=8), remote_cmd],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            pass  # Best effort — don't block attach if config fails

    def _restore_tmux_after_detach(self, mgr: SessionManager, name: str) -> None:
        """Restore tmux session options to defaults after detach."""
        q = shlex.quote
        commands = " && ".join([
            f"tmux set-option -t {q(name)} prefix C-b",
            f"tmux unbind-key -T root C-b",
            f"tmux set-option -u -t {q(name)} status-style",
            f"tmux set-option -u -t {q(name)} status-left",
            f"tmux set-option -u -t {q(name)} status-left-length",
            f"tmux set-option -u -t {q(name)} status-left-style",
            f"tmux set-option -u -t {q(name)} status-right",
            f"tmux set-option -u -t {q(name)} status-right-length",
            f"tmux set-option -u -t {q(name)} status-right-style",
        ])
        remote_cmd = f"bash -l -c {q(commands)}"

        try:
            subprocess.run(
                [*mgr.ssh_base_args(timeout=8), remote_cmd],
                capture_output=True,
                timeout=15,
            )
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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "delete_server":
            return self._phase == "select"
        if action in {"new_session", "kill_session", "refresh", "attach_session", "back"}:
            return self._phase == "session"
        return True

    def action_back(self) -> None:
        """Ctrl+B — Go back to previous level

        session list → server selection
        """
        # Stop network monitor (all back scenarios)
        if self.net_monitor:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.net_monitor.stop())
            except RuntimeError:
                asyncio.run(self.net_monitor.stop())
            self.net_monitor = None

        if self._phase == "session":
            # Return to server selection
            self._show_server_select()

    async def on_shutdown_request(self) -> None:
        if self.net_monitor:
            await self.net_monitor.stop()
        await super().on_shutdown_request()
