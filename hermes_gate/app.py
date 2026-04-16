"""Hermes Gate 主 TUI 应用 — 基于 Textual"""
import asyncio
import os
import re
import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Center
from textual.widgets import (
    Header, Footer, Label, Button, ListItem, ListView,
    Input, RichLog, Static,
)
from textual.reactive import reactive
from textual import work
from textual.screen import ModalScreen

from hermes_gate.session import SessionManager
from hermes_gate.network import NetworkMonitor, NetStatus
from hermes_gate.servers import load_servers, add_server, display_name


# ─── 新增服务器弹窗 ───────────────────────────────────────────────

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
    BINDINGS = [Binding("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("🔗 新增服务器", id="dialog-title")
            yield Input(placeholder="例如: root@1.2.3.4 或 admin@myserver", id="input")
            yield Label("Enter 确认 · Esc 取消", id="hint")
            with Horizontal(id="btn-row"):
                yield Button("连接", variant="success", id="btn-ok")
                yield Button("取消", variant="default", id="btn-cancel")

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


# ─── 连接中弹窗 ────────────────────────────────────────────────────

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


# ─── 状态灯 ────────────────────────────────────────────────────────

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
    """输入框前的小状态灯"""
    net: reactive[str] = reactive("red")

    def watch_net(self, val: str) -> None:
        from rich.text import Text
        color = "#00FF00" if val == "green" else "#FF0000"
        t = Text("● ", style=f"bold {color}")
        self.update(t)

    def on_mount(self) -> None:
        self.net = "red"


# ─── 主应用 ─────────────────────────────────────────────────────────

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
        overflow: auto auto;
        background: $surface;
    }
    #input-bar {
        dock: bottom; height: 3;
        padding: 0 1; layout: horizontal;
        background: $surface;
        border-top: solid $primary;
    }
    #input-dot { width: auto; padding: 1 1 0 0; }
    #hermes-input { width: 1fr; }
    """

    BINDINGS = [Binding("q", "quit", "退出")]
    TITLE = "⚡ Hermes Gate"

    # 每个 phase 的 bindings（含统一的 Shift+Tab 返回）
    _BIND_SELECT = [
        Binding("d", "delete_server", "删除"),
        Binding("q", "quit", "退出"),
    ]
    _BIND_SESSION = [
        Binding("n", "new_session", "新建"),
        Binding("k", "kill_session", "杀死"),
        Binding("r", "refresh", "刷新"),
        Binding("enter", "attach_session", "连接"),
        Binding("escape", "back", "返回"),
        Binding("shift+tab", "back", "返回"),
        Binding("q", "quit", "退出"),
    ]
    _BIND_VIEWER = [
        Binding("escape", "back", "返回"),
        Binding("shift+tab", "back", "返回"),
        Binding("q", "quit", "退出"),
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
    # 第一步：服务器选择
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
        items.append(ListItem(Label(" ➕  新增服务器..."), name="new-srv"))

        self.mount(Center(
            Vertical(
                Label("⚡ Hermes Gate — 选择服务器", id="server-title"),
                ListView(*items, id="server-list"),
                Label("↑↓ 选择 · Enter 连接 · D 删除 · Q 退出", id="server-hint"),
                id="server-box",
            ), id="server-screen",
        ))
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

    def action_delete_server(self) -> None:
        """D 键删除选中的服务器（仅删除 servers.json 中的记录）"""
        if self._phase != "select":
            return
        lv = self.query_one("#server-list", ListView)
        idx = lv.index
        if idx is None:
            return
        servers = load_servers()
        if idx >= len(servers):
            # 选中的是"新增服务器"，不删除
            return
        server = servers[idx]
        name = display_name(server)

        from hermes_gate.servers import remove_server
        remove_server(server["user"], server["host"])
        self._hint("server-hint", f"已删除 {name}")
        # 刷新列表
        self._clear()
        self._show_server_select()

    def _prompt_new_server(self) -> None:
        def handle(result: str | None):
            if not result or not result.strip():
                return
            text = result.strip()
            if "@" not in text:
                self._hint("server-hint", "格式错误，请输入 user@host")
                return
            user, host = text.split("@", 1)
            user, host = user.strip(), host.strip()
            if not user or not host:
                self._hint("server-hint", "用户名和主机不能为空")
                return
            self._connect_server({"user": user, "host": host}, new=True)
        self.push_screen(NewServerScreen(), handle)

    # ─── 连接服务器 ────────────────────────────────────────────────

    def _connect_server(self, server: dict, new: bool = False) -> None:
        user, host = server["user"], server["host"]
        name = display_name(server)
        scr = ConnectingScreen(f"🔍 正在连接 {name} ...")
        self.push_screen(scr)

        async def _do():
            scr.update_msg(f"🔍 测试 SSH 连接 {name} ...")
            if not await self._ssh_ok(user, host):
                self.pop_screen()
                self._hint("server-hint",
                    f"无法连接 {name}，请检查地址和密钥" if new else f"无法连接 {name}")
                return
            scr.update_msg(f"🔍 检查 {name} 上的 hermes ...")
            if not await self._hermes_ok(user, host):
                self.pop_screen()
                self._hint("server-hint", "请在服务器上安装 hermes")
                return
            if new:
                add_server(user, host)
            self._server = server
            self.pop_screen()
            self._show_session_list(user, host)

        self.run_worker(_do(), exclusive=True)

    @work(exit_on_error=False)
    async def _ssh_ok(self, user: str, host: str) -> bool:
        try:
            p = await asyncio.create_subprocess_exec(
                "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=8", f"{user}@{host}", "echo", "ok",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(p.communicate(), timeout=15)
            return p.returncode == 0 and b"ok" in out
        except Exception:
            return False

    @work(exit_on_error=False)
    async def _hermes_ok(self, user: str, host: str) -> bool:
        try:
            p = await asyncio.create_subprocess_exec(
                "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=8", f"{user}@{host}", "hermes", "-v",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(p.communicate(), timeout=15)
            return p.returncode == 0 and len((out or b"").decode(errors="replace").strip()) > 0
        except Exception:
            return False

    def _hint(self, hint_id: str, msg: str) -> None:
        try:
            h = self.query_one(f"#{hint_id}", Label)
            h.update(f"❌ {msg}")
            h.styles.color = "red"
            self.set_timer(3, lambda: h.update("↑↓ 选择 · Enter 确认 · Esc 返回 · Q 退出"))
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # 第三步：Session 列表
    # ═══════════════════════════════════════════════════════════════

    def _show_session_list(self, user: str, host: str) -> None:
        self._phase = "session"
        self._clear()

        port = os.environ.get("SERVER_PORT", "22")
        self.session_mgr = SessionManager(user, host, port)
        self.net_monitor = NetworkMonitor(host)

        self.BINDINGS = self._BIND_SESSION

        server_name = display_name({"user": user, "host": host})
        self.mount(Center(
            Vertical(
                Label(f"⚡ {server_name} — Session 列表", id="session-title"),
                ListView(id="session-list"),
                Label("↑↓ 选择 · Enter 连接 · N 新建 · K 杀死 · Shift+Tab 返回",
                      id="session-hint"),
                id="session-box",
            ), id="session-screen",
        ))
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
                self._hint("session-hint", f"{s['name']} 已失效，请刷新")
                return
            self._enter_viewer(s["id"])

    @work(exit_on_error=False)
    async def _refresh_sessions(self) -> None:
        if not self.session_mgr:
            return
        try:
            loop = asyncio.get_event_loop()
            self.sessions = await loop.run_in_executor(None, self.session_mgr.list_sessions)
            lv = self.query_one("#session-list", ListView)
            await lv.clear()
            for s in self.sessions:
                alive = "🟢" if s.get("alive") else "⚪"
                created = s.get("created", "")
                if "T" in created:
                    created = created.split("T")[0][5:] + " " + created.split("T")[1][:5]
                await lv.append(ListItem(
                    Label(f" {alive} gate-{s['id']}   ({created})"), name="sess"))
            await lv.append(ListItem(
                Label(" ➕  新建 session..."), name="new-sess"))
            lv.focus()
        except Exception:
            pass

    def action_refresh(self) -> None:
        if self._phase == "session":
            self._refresh_sessions()

    # ─── 新建 Session ─────────────────────────────────────────────

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
            self._hint("session-hint", f"创建失败: {e}")

    # ─── 杀死 Session ─────────────────────────────────────────────

    def action_kill_session(self) -> None:
        if self._phase != "session":
            return
        idx = self.query_one("#session-list", ListView).index
        if idx is None or idx >= len(self.sessions):
            self._hint("session-hint", "请先选择一个 session")
            return
        self._kill(self.sessions[idx]["id"])

    @work(exit_on_error=False)
    async def _kill(self, sid: int) -> None:
        if not self.session_mgr:
            return
        name = f"gate-{sid}"
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self.session_mgr.kill_session, sid)
        self._hint("session-hint",
            f"已杀死 {name}" if ok else f"{name} 远端已不存在，已移除记录")
        self._refresh_sessions()

    # ═══════════════════════════════════════════════════════════════
    # 第五步：Hermes Viewer（实时输出 + 输入框 + 网络灯）
    # ═══════════════════════════════════════════════════════════════

    def _enter_viewer(self, session_id: int) -> None:
        """进入 hermes viewer 界面"""
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
                    Input(placeholder="输入 prompt 发送给远端 hermes ...", id="hermes-input"),
                    id="input-bar",
                ),
                id="viewer-area",
            ),
        )

        self.query_one("#hermes-input", Input).focus()
        self._start_network_monitor()
        self._start_output_poll(session_id)

    # ─── 轮询远端 tmux 输出 ───────────────────────────────────────

    @work(exit_on_error=False)
    async def _start_output_poll(self, session_id: int) -> None:
        """每 1.5 秒通过 SSH 抓取远端 tmux pane 内容"""
        name = f"gate-{session_id}"
        mgr = self.session_mgr
        if not mgr:
            return
        prev_content = ""

        while self._phase == "viewer":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ssh", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5",
                    "-p", mgr.port,
                    f"{mgr.user}@{mgr.host}",
                    "tmux", "capture-pane", "-t", name, "-p", "-S", "-80",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                raw = stdout.decode(errors="replace")

                # 去掉 ANSI 转义序列
                clean = _strip_ansi(raw)

                # 只在内容变化时更新
                if clean != prev_content:
                    prev_content = clean
                    try:
                        widget = self.query_one("#hermes-output", Static)
                        widget.update(clean)
                    except Exception:
                        pass

                await asyncio.sleep(1.5)
            except Exception:
                await asyncio.sleep(3)

    # ─── 用户输入 → 发送到远端 tmux ───────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "hermes-input" or self._phase != "viewer":
            return
        text = event.value
        if not text:
            return
        event.input.value = ""
        self._send_to_remote(text)

    @work(exit_on_error=False)
    async def _send_to_remote(self, text: str) -> None:
        """通过 SSH 把用户输入发送到远端 tmux session"""
        if not self.session_mgr or self._current_session_id is None:
            return
        name = f"gate-{self._current_session_id}"
        mgr = self.session_mgr

        # 转义单引号
        safe = text.replace("'", "'\\''")

        # 分两步：先发送文本，再发送 Enter
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            "-p", mgr.port,
            f"{mgr.user}@{mgr.host}",
            "tmux", "send-keys", "-t", name, "-l", safe,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)

        # 发送回车
        proc2 = await asyncio.create_subprocess_exec(
            "ssh", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            "-p", mgr.port,
            f"{mgr.user}@{mgr.host}",
            "tmux", "send-keys", "-t", name, "Enter",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc2.communicate(), timeout=10)

    # ─── 网络监控 ─────────────────────────────────────────────────

    @work(exit_on_error=False)
    async def _start_network_monitor(self) -> None:
        if not self.net_monitor:
            return
        await self.net_monitor.start()
        while self._phase in ("viewer", "session"):
            await asyncio.sleep(1)
            state = self.net_monitor.state
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

    # ─── 导航 ─────────────────────────────────────────────────────

    def action_attach_session(self) -> None:
        """Enter 键连接 session"""
        if self._phase != "session":
            return
        idx = self.query_one("#session-list", ListView).index
        if idx is None or idx >= len(self.sessions):
            return
        s = self.sessions[idx]
        if not s.get("alive"):
            self._hint("session-hint", f"{s['name']} 已失效，请刷新")
            return
        self._enter_viewer(s["id"])

    def action_back(self) -> None:
        """Shift+Tab / Esc — 统一返回上一级

        viewer → session 列表（远端 hermes 不受影响，tmux 仍在后台跑）
        session 列表 → 服务器选择
        服务器选择 → 无操作（已是最顶层）
        """
        # 停止网络监控（所有 back 场景都要）
        if self.net_monitor:
            asyncio.create_task(self.net_monitor.stop())
            self.net_monitor = None

        if self._phase == "viewer":
            # 回到 session 列表（远端 tmux 不 kill）
            self._phase = "session"
            if self._server and self.session_mgr:
                self._show_session_list(
                    self._server["user"], self._server["host"])

        elif self._phase == "session":
            # 回到服务器选择
            self._show_server_select()

    async def on_shutdown_request(self) -> None:
        if self.net_monitor:
            await self.net_monitor.stop()
        await super().on_shutdown_request()


# ─── 工具函数 ──────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?[a-zA-Z]|\x1b\([A-Z]")

def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义序列"""
    return _ANSI_RE.sub("", text)
