"""Hermes Gate Main TUI Application — Built with Textual"""

import asyncio
import json
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

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
        self._previews: dict[int, str] = {}  # session_id -> last preview text
        self._auto_refresh_timer = None

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
                for widget in self.query(f"#{wid}"):
                    widget.remove()
            except Exception:
                pass

    def _show_server_select(self) -> None:
        self._phase = "select"
        self._clear()

        server_entries = load_servers()
        self.mount(
            Center(
                Vertical(
                    Label("⚡ Hermes Gate — Select Server", id="server-title"),
                    ListView(id="server-list"),
                    Label("↑↓ Select · Enter Connect · d Delete · q Quit", id="server-hint"),
                    id="server-box",
                ),
                id="server-screen",
            )
        )
        lv = self.query_one("#server-list", ListView)
        for server in server_entries:
            alias = find_ssh_alias(server["user"], server["host"], server.get("port", "22"))
            name = alias or display_name(server)
            lv.append(ListItem(Label(f" {name}"), name="srv"))
        lv.append(ListItem(Label(" ➕  Add Server..."), name="add-srv"))
        lv.focus()

    def _hint(self, label_id: str, msg: str, error: bool = True) -> None:
        try:
            h = self.query_one(f"#{label_id}", Label)
            reset_text = None
            if label_id == "server-hint":
                reset_text = "↑↓ Select · Enter Connect · d Delete · q Quit"
            elif label_id == "session-hint":
                reset_text = "↑↓ Select · Enter Attach · n New · k Kill · r Refresh · Ctrl+B Back · q Quit"
            h.update(msg)
            h.styles.color = "red" if error else "green"

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

        # Deploy notification plugin in background (for existing sessions)
        self._ensure_plugin()

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
        self._start_auto_refresh()
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

    def _start_auto_refresh(self) -> None:
        self._stop_auto_refresh()
        self._auto_refresh_timer = self.set_interval(10, self._auto_refresh_tick)

    @work(exit_on_error=False)
    async def _ensure_plugin(self) -> None:
        if not self.session_mgr:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.session_mgr.ensure_notify_plugin)

    def _stop_auto_refresh(self) -> None:
        if self._auto_refresh_timer is not None:
            self._auto_refresh_timer.stop()
            self._auto_refresh_timer = None

    def _auto_refresh_tick(self) -> None:
        if self._phase == "session":
            self._refresh_sessions()
            self._check_completion()

    def _emit_host_notification(
        self,
        title: str,
        message: str,
        sound: str = "complete.wav",
        **extra: str,
    ) -> None:
        notify_dir = Path("/hermes-notify")
        if not notify_dir.is_dir():
            return
        ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
        payload = {
            "title": title,
            "message": message,
            "sound": sound,
            **extra,
        }
        (notify_dir / f"notify-{ts}.json").write_text(json.dumps(payload))

    def _notify(self, session_name: str, message: str) -> None:
        """Dual-layer notification: OSC 9 (instant terminal) + file signal (host system)."""
        text = f"Hermes {session_name}: {message}"

        # Layer 1: OSC 9 terminal notification (iTerm2, Windows Terminal, WezTerm, etc.)
        try:
            sys.stdout.write(f"\033]9;{text}\007")
            sys.stdout.flush()
        except Exception:
            pass

        # Layer 2: Write file signal to mounted volume for host-side watcher
        self._emit_host_notification(
            "Hermes Gate",
            text,
            session_name=session_name,
            response_preview=message,
        )

    @work(exit_on_error=False)
    async def _check_completion(self) -> None:
        if not self.session_mgr:
            return
        loop = asyncio.get_event_loop()
        try:
            signals = await loop.run_in_executor(
                None, self.session_mgr.check_completion_signals
            )
        except Exception:
            return
        for sig in signals:
            name = f"gate-{sig.get('session_id', '?')}"
            preview = sig.get("response_preview") or sig.get("message_preview") or "task completed"
            self._notify(name, preview)

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

            # Fetch previews for alive sessions (single SSH call)
            alive_ids = [s["id"] for s in self.sessions if s.get("alive")]
            if alive_ids:
                new_previews = await loop.run_in_executor(
                    None, self.session_mgr.fetch_previews, alive_ids
                )
                self._previews.update(new_previews)
            lv = self.query_one("#session-list", ListView)

            saved_index = lv.index or 0
            had_focus = lv.has_focus

            await lv.clear()
            for s in self.sessions:
                alive = "🟢" if s.get("alive") else "⚪"
                created = s.get("created", "")
                if "T" in created:
                    created = (
                        created.split("T")[0][5:] + " " + created.split("T")[1][:5]
                    )
                preview = self._previews.get(s["id"], "")
                if preview:
                    text = f" {alive} gate-{s['id']}   ({created})\n     [dim]{preview}[/dim]"
                else:
                    text = f" {alive} gate-{s['id']}   ({created})"
                await lv.append(
                    ListItem(Label(Text.from_markup(text)), name="sess")
                )
            await lv.append(ListItem(Label(" ➕  New Session..."), name="new-sess"))

            if self.sessions:
                lv.index = min(saved_index, len(self.sessions) - 1)
            else:
                lv.index = 0

            if had_focus:
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

        async def do_kill() -> None:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self.session_mgr.kill_session, sid)
            except Exception as e:
                screen.set_error(f"Kill failed: {e}")
                return

            self.pop_screen()
            if result.get("tmux_missing"):
                self._hint("session-hint", f"{name} killed, local record removed", error=False)
            else:
                self._hint("session-hint", f"{name} killed", error=False)
            self._refresh_sessions()

        asyncio.create_task(do_kill())

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Attach to Remote tmux Session
    # ═══════════════════════════════════════════════════════════════

    def _enter_viewer(self, session_id: int) -> None:
        """Suspend TUI and attach to remote tmux session via SSH.

        The user gets a real terminal with the remote tmux session.
        - Ctrl+B detaches and returns to the session list.
        - A green status bar at the bottom shows connection status + hint.
        - A background thread polls for completion signals while attached.
        """
        mgr = self.session_mgr
        if not mgr:
            return
        name = f"gate-{session_id}"

        # Stop network monitor before suspending
        if self.net_monitor:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.net_monitor.stop())
            except RuntimeError:
                asyncio.run(self.net_monitor.stop())
            self.net_monitor = None

        # Configure tmux: Ctrl+B → detach, green status bar at bottom
        self._configure_tmux_for_attach(mgr, name)

        # Start background polling thread — notifies host while TUI is suspended
        self._start_bg_poll(mgr)

        # Suspend Textual and run SSH attach — user gets real terminal
        # The session list DOM stays mounted; after suspend returns we just
        # refresh it in place, avoiding any DuplicateIds issues entirely.
        cmd = mgr.attach_cmd(session_id)
        try:
            with self.suspend():
                subprocess.call(cmd)
        except Exception:
            subprocess.call(cmd)

        # Stop background polling
        self._stop_bg_poll()

        # Restore tmux session options to defaults
        self._restore_tmux_after_detach(mgr, name)

        # Capture last meaningful line as preview after detach
        try:
            preview = mgr.capture_session_preview(session_id)
            if preview:
                self._previews[session_id] = preview
        except Exception:
            pass

        # Refresh the session list (DOM was never touched, just re-query)
        self._refresh_sessions()
        self._check_completion()
        try:
            self.query_one("#session-list", ListView).focus()
        except Exception:
            pass

    # ─── Background Completion Polling ────────────────────────────────

    def _start_bg_poll(self, mgr: SessionManager) -> None:
        """Start a background thread that polls for completion signals."""
        self._bg_poll_stop = threading.Event()

        def _poll():
            while not self._bg_poll_stop.is_set():
                try:
                    signals = mgr.check_completion_signals()
                    for sig in signals:
                        name = f"gate-{sig.get('session_id', '?')}"
                        preview = sig.get("response_preview") or sig.get("message_preview") or "task completed"
                        self._emit_host_notification(
                            "Hermes Gate",
                            f"{name}: {preview}",
                            session_name=name,
                            response_preview=preview,
                        )
                except Exception:
                    pass
                self._bg_poll_stop.wait(3)

        self._bg_poll_thread = threading.Thread(target=_poll, daemon=True)
        self._bg_poll_thread.start()

    def _stop_bg_poll(self) -> None:
        """Stop the background polling thread."""
        if hasattr(self, "_bg_poll_stop") and self._bg_poll_stop:
            self._bg_poll_stop.set()
        if hasattr(self, "_bg_poll_thread") and self._bg_poll_thread:
            self._bg_poll_thread.join(timeout=15)
            self._bg_poll_thread = None

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
            # Enable mouse support and make wheel scroll pane history when not already handling mouse events.
            f"tmux set-option -t {q(name)} mouse on",
            f"tmux bind-key -T root WheelUpPane if-shell -F '#{{mouse_any_flag}}' 'send-keys -M' 'copy-mode -e'",
            f"tmux bind-key -T root WheelDownPane if-shell -F '#{{mouse_any_flag}}' 'send-keys -M' 'send-keys -X scroll-down'",
            f"tmux bind-key -T copy-mode-vi WheelUpPane send-keys -X scroll-up",
            f"tmux bind-key -T copy-mode-vi WheelDownPane send-keys -X scroll-down",
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
        """Restore tmux session options to defaults after detach.

        Skips restore if other clients are still attached to the session.
        """
        q = shlex.quote
        # Check if other clients are still attached
        try:
            result = subprocess.run(
                [*mgr.ssh_base_args(timeout=5),
                 mgr.login_shell_command(f"tmux list-clients -t {q(name)} 2>/dev/null | wc -l")],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and int(result.stdout.strip()) > 0:
                return
        except Exception:
            pass
        commands = " && ".join([
            f"tmux set-option -t {q(name)} prefix C-b",
            f"tmux set-option -u -t {q(name)} mouse",
            f"tmux unbind-key -T root WheelUpPane",
            f"tmux unbind-key -T root WheelDownPane",
            f"tmux unbind-key -T copy-mode-vi WheelUpPane",
            f"tmux unbind-key -T copy-mode-vi WheelDownPane",
            f"tmux set-option -u -t {q(name)} status-style",
            f"tmux set-option -u -t {q(name)} status-left",
            f"tmux set-option -u -t {q(name)} status-left-length",
            f"tmux set-option -u -t {q(name)} status-left-style",
            f"tmux set-option -u -t {q(name)} status-right",
            f"tmux set-option -u -t {q(name)} status-right-length",
            f"tmux set-option -u -t {q(name)} status-right-style",
            f"tmux unbind-key -T root C-b",
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

    def action_back(self) -> None:
        if self._phase == "select":
            return
        if self.net_monitor:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.net_monitor.stop())
            except RuntimeError:
                asyncio.run(self.net_monitor.stop())
            self.net_monitor = None
        self._stop_auto_refresh()
        self._show_server_select()


def main() -> None:
    HermesGateApp().run(mouse=False)


if __name__ == "__main__":
    main()
