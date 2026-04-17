# Hermes Gate 稳定性修复方案与测试计划

本文档覆盖当前代码审查中会直接影响使用稳定性的 6 类问题：

1. Session 本地记录没有区分 SSH 端口。
2. 网络状态使用 ICMP ping，而不是实际应用依赖的 SSH/TCP 通路。
3. 网络监控 worker 生命周期可能跨页面残留。
4. Session 刷新吞掉所有异常，导致 UI 静默失败。
5. 发送到远程 Hermes 的输入可能被远端 shell 解释，不能保证按原文发送。
6. `GUIDE.md` 仍引用已移除的 `.env.example` 首次使用流程。

修复目标是让实现满足真实接口契约和通用故障模式，而不是适配某个测试样例。测试应通过 mock、临时目录和可替换的探测函数覆盖边界，不依赖真实 SSH 服务器。

## 测试基础设施

当前仓库没有测试目录。建议新增：

- `tests/test_session_records.py`
- `tests/test_network_monitor.py`
- `tests/test_network_worker.py`
- `tests/test_refresh_sessions.py`
- `tests/test_send_to_remote.py`
- `tests/test_docs.py`

建议在 `pyproject.toml` 增加开发依赖：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

测试原则：

- 不连接真实服务器。SSH、tmux、TCP 探测都通过 monkeypatch/fake process 验证行为。
- 使用临时 HOME 或可注入的配置目录，避免读写用户真实 `~/.hermes-gate`。
- 对异常路径做显式断言，不能只断言“没有抛异常”。
- 对用户输入发送做数据边界断言：用户文本只能出现在 stdin/payload 中，不能出现在远程 shell 命令字符串里。

## 1. Session 记录按端口隔离

### 现状

`hermes_gate/session.py` 中 `_sessions_file(user, host)` 只用 `user` 和 `host` 生成文件名：

```python
sessions_{user}@{host}.json
```

但 UI 已支持 `user@host:port`。同一用户、同一主机、不同端口会共享同一个本地 session 记录文件，导致 session 列表、alive 状态、id 分配和 kill 操作互相污染。

### 正确行为

`user@host:22` 和 `user@host:2222` 必须被视为两个独立远程目标。它们的本地 session 记录、id 分配和删除操作必须互不影响。

### 修复方案

1. 修改本地记录 key，显式包含端口：

   ```python
   def _sessions_file(user: str, host: str, port: str = "22") -> Path:
       ...
   ```

2. 文件名不要直接拼未清洗的 host/user。使用稳定编码，避免 IPv6、斜杠、空格等字符破坏路径：

   ```python
   from urllib.parse import quote

   def _server_key(user: str, host: str, port: str) -> str:
       return f"{quote(user, safe='')}@{quote(host, safe='')}#{quote(str(port), safe='')}"
   ```

   文件名可以为：

   ```text
   sessions_{server_key}.json
   ```

3. `_load_local()`、`_save_local()` 改为接收 `port`，`SessionManager` 调用时统一传 `self.port`。

4. 增加向后兼容迁移：

   - 当 `port == "22"` 且新文件不存在、旧文件 `sessions_{user}@{host}.json` 存在时，读取旧文件并写入新文件。
   - 非 22 端口不要自动迁移旧文件，避免把历史默认端口记录错误套用到其他端口。
   - 迁移后可以保留旧文件，降低破坏性；后续可在 release note 中说明。

5. 补充端口校验。至少要求端口为 1 到 65535 的整数。非法端口应在添加服务器阶段被拒绝，而不是延迟到 SSH 报错。

### 测试

`tests/test_session_records.py`

- `test_session_files_are_port_scoped`
  - 使用临时 HOME。
  - 创建同一 `user`/`host` 但端口分别为 `22` 和 `2222` 的 `SessionManager`。
  - mock `_ssh_output()` 返回空 session 列表，mock `_ssh_cmd()` 返回成功。
  - 两边各 `create_session()` 一次。
  - 断言两个目标的 first id 都是 `0`，且生成两个不同 JSON 文件。

- `test_kill_session_only_removes_matching_port_record`
  - 预置两个端口各自的记录文件。
  - 对 `2222` 端口执行 `kill_session(0)`。
  - 断言 `22` 端口记录未被修改。

- `test_default_port_migrates_legacy_record`
  - 只创建旧文件 `sessions_root@example.com.json`。
  - 用 `SessionManager("root", "example.com", "22")` 读取。
  - 断言能读到旧记录，并生成新的端口化文件。

- `test_non_default_port_does_not_consume_legacy_record`
  - 只创建旧文件。
  - 用 `SessionManager("root", "example.com", "2222")` 读取。
  - 断言不会把旧记录当成 `2222` 端口记录。

### 验收标准

- 同一 host 的不同端口在 UI 中显示、刷新、创建、删除 session 时互不影响。
- 默认端口用户升级后仍能看到旧 session 记录。

## 2. 网络状态改为探测 SSH/TCP 通路

### 现状

`NetworkMonitor._probe()` 使用：

```bash
ping -c 1 -W 2 <host>
```

但应用实际依赖 SSH 连接到指定端口。很多云服务器禁用 ICMP，ping 失败不代表 SSH 失败；ping 成功也不代表 SSH 端口可用。

### 正确行为

状态栏应反映当前 Hermes Gate 实际依赖的连接通路：解析后的 host 和用户配置的 SSH port。网络状态不能依赖 ICMP。

### 修复方案

1. `NetworkMonitor` 增加 `port` 参数：

   ```python
   class NetworkMonitor:
       def __init__(self, host: str, port: str = "22"):
           ...
   ```

2. `_probe()` 改为 TCP connect 探测：

   ```python
   reader, writer = await asyncio.wait_for(
       asyncio.open_connection(self._ip, int(self.port)),
       timeout=5,
   )
   ```

   连接成功后立即关闭 writer。用 `time.monotonic()` 计算延迟。

3. 状态阈值保留当前语义：

   - `< 200ms`: green
   - `200ms <= latency < 500ms`: yellow
   - `>= 500ms`: red/unstable，具体文案建议用 `"Slow: 650ms"`，不要和完全断连混淆。

4. `_show_session_list()` 创建 monitor 时传入端口：

   ```python
   self.net_monitor = NetworkMonitor(host, port)
   ```

5. 后续如果需要更严格的 SSH 探测，可以在 TCP connect 后增加可选的 `ssh -o BatchMode=yes true` 探测。但默认不建议把认证失败直接归类为网络断开，因为 host/port 可达和用户密钥有效是两个不同问题。

### 测试

`tests/test_network_monitor.py`

- `test_probe_uses_configured_port`
  - monkeypatch `asyncio.open_connection`。
  - 创建 `NetworkMonitor("example.com", "2222")`。
  - 调用 `_probe()`。
  - 断言 open_connection 收到端口 `2222`。

- `test_probe_success_sets_latency_state`
  - fake open_connection 成功返回 fake reader/writer。
  - monkeypatch `time.monotonic()` 返回稳定时间序列。
  - 断言状态为 green/yellow，并包含毫秒文案。

- `test_probe_timeout_sets_red_state`
  - fake open_connection 抛 `asyncio.TimeoutError`。
  - 断言返回 `False`，状态为 RED，message 为明确的 timeout/disconnected 文案。

- `test_probe_closes_writer_on_success`
  - fake writer 记录 `close()` 和 `wait_closed()`。
  - 断言成功路径会关闭连接。

### 验收标准

- 禁 ICMP 但 SSH 端口开放的服务器不会被 UI 误报为断线。
- SSH 端口不可达时，状态栏能进入断线/重连状态。

## 3. 网络监控 worker 生命周期收敛

### 现状

`_start_network_monitor()` 循环内持续读取 `self.net_monitor`：

```python
while self._phase in ("viewer", "session"):
    state = self.net_monitor.state
```

导航返回时 `action_back()` 会 stop 并清空 `self.net_monitor`，之后进入新页面又会创建新的 monitor。旧 worker 可能继续运行，读到新的 monitor 或吞掉异常，导致状态闪烁、重复刷新、后台任务泄漏。

### 正确行为

每次进入 viewer 最多只有一个网络监控 worker。离开 viewer 或切换服务器/session 后，旧 worker 必须退出，不能继续读取新的 `self.net_monitor`。

### 修复方案

1. 在 `_start_network_monitor()` 开始时捕获局部 monitor：

   ```python
   monitor = self.net_monitor
   if monitor is None:
       return
   await monitor.start()
   try:
       while self._phase == "viewer" and self.net_monitor is monitor:
           state = monitor.state
           ...
   finally:
       await monitor.stop()
   ```

2. `action_back()` 停止 monitor 时先断开全局引用：

   ```python
   monitor = self.net_monitor
   self.net_monitor = None
   if monitor:
       asyncio.create_task(monitor.stop())
   ```

   这样旧 worker 的 `self.net_monitor is monitor` 条件会立即失败。

3. 进入新的 viewer 前，如果存在旧 monitor，先停止旧实例，再创建新实例。

4. 将循环限制为 `viewer` 阶段。session 列表页没有 `#net-status` 和 `#latency`，继续运行只会依赖异常吞掉查询失败。

### 测试

`tests/test_network_worker.py`

- `test_network_worker_exits_when_monitor_replaced`
  - 构造 fake app 或提取一个可测 helper。
  - worker 启动后将 `app.net_monitor` 替换为另一个对象。
  - 断言旧 worker 退出，并调用旧 monitor 的 `stop()`。

- `test_network_worker_exits_when_leaving_viewer`
  - phase 从 `"viewer"` 改为 `"session"`。
  - 断言循环停止，不再更新 UI。

- `test_only_current_monitor_updates_ui`
  - 旧 monitor 和新 monitor 都有不同状态。
  - 断言旧 worker 不会把旧状态写到新 viewer 的状态栏。

### 验收标准

- 多次进入/退出 viewer 后，后台 monitor 数量不会增长。
- 状态栏只显示当前 session 对应的 monitor 状态。

## 4. Session 刷新显式暴露失败

### 现状

`_refresh_sessions()` 捕获所有异常后直接 `pass`：

```python
except Exception:
    pass
```

SSH 超时、认证失败、tmux 不存在、本地 JSON 损坏、代码错误都会表现为列表不动或空白。

### 正确行为

刷新失败应保留现有列表，并在 UI hint 显示明确错误。预期内的远程空 session 不是错误；连接失败、超时和本地记录无法读取才是错误。

### 修复方案

1. `SessionManager._ssh_cmd()` 保留 `CompletedProcess`，但上层要区分 SSH 失败和远端 tmux 无 session：

   - SSH 连接失败通常返回 `255`，应转成 `ConnectionError` 或自定义 `SSHCommandError`。
   - `tmux list-sessions` 无 server/no sessions 可以返回非 0，但这应被解释为空 alive 集合，不是刷新失败。

2. `_refresh_sessions()` 只捕获明确异常类型：

   ```python
   except (TimeoutError, subprocess.TimeoutExpired, ConnectionError, RuntimeError) as e:
       self._hint("session-hint", f"Refresh failed: {e}")
       self.log.error(...)
   ```

3. 成功拿到新 session 列表后再清空 ListView。这样失败时不会把旧列表清掉。

4. 本地 JSON 解析失败建议在 `load` 层返回空列表并记录 warning；如果文件存在但 schema 不合法，应显示“local session record is invalid”更利于排障。

### 测试

`tests/test_refresh_sessions.py`

- `test_refresh_keeps_existing_list_on_connection_failure`
  - fake `session_mgr.list_sessions()` 抛 `ConnectionError`。
  - 预置 `self.sessions` 和 ListView 内容。
  - 调用 `_refresh_sessions()`。
  - 断言 `self.sessions` 未被覆盖为空，hint 显示 refresh failed。

- `test_refresh_success_replaces_list`
  - fake 返回两个 session。
  - 断言 ListView 先清空再 append 两个 session 和 New Session 项。

- `test_session_manager_distinguishes_ssh_failure_from_no_tmux_sessions`
  - mock `_ssh_cmd()` 返回 returncode 255 时，`list_sessions()` 抛连接错误。
  - mock tmux no sessions 的返回时，`list_sessions()` 返回本地记录但 alive 为 false，或者空 alive 集合。

### 验收标准

- 网络/认证错误能被用户看到。
- 刷新失败不会破坏当前可见 session 列表。

## 5. 远程输入按原文发送

### 现状

`_send_to_remote()` 对用户输入做手工单引号转义，然后作为远程命令参数传给 SSH：

```python
safe = text.replace("'", "'\\''")
...
"tmux", "send-keys", "-t", name, "-l", safe
```

OpenSSH 的远程命令最终仍会经过远端 shell。用户输入中的 shell 元字符可能被解释；普通包含空格、引号、换行的 prompt 也不能保证逐字进入 Hermes。

### 正确行为

输入框中的任何文本都应作为数据发送到 tmux pane，不参与构造远端 shell 语法。远端命令字符串必须只包含由程序生成的固定命令和经过严格限制的 session 名。

### 修复方案

推荐使用 tmux buffer，通过 SSH stdin 传输用户文本：

1. session name 只允许程序生成的 `gate-{int}`，不要接受外部字符串。

2. 构造固定远端命令：

   ```bash
   tmux load-buffer -b hermes-gate-input - \
     \; paste-buffer -b hermes-gate-input -t gate-0 \
     \; send-keys -t gate-0 Enter
   ```

   用户文本通过 `proc.communicate(input=text.encode())` 发送到 stdin。远端 shell 只解释固定命令，不解释用户文本。

3. Python 侧：

   ```python
   proc = await asyncio.create_subprocess_exec(
       "ssh",
       ...,
       fixed_remote_command,
       stdin=asyncio.subprocess.PIPE,
       stdout=asyncio.subprocess.PIPE,
       stderr=asyncio.subprocess.PIPE,
   )
   stdout, stderr = await asyncio.wait_for(
       proc.communicate(input=text.encode("utf-8")),
       timeout=10,
   )
   if proc.returncode != 0:
       raise RuntimeError(stderr.decode(errors="replace").strip() or "send failed")
   ```

4. 如果需要兼容不支持 `tmux load-buffer -` 的环境，可以退化为安全的 base64 stdin 脚本，但仍必须保持用户文本只走 stdin，不拼进远端命令。

5. 发送失败应在 viewer hint 或 output 中显示错误，不能静默失败。

### 测试

`tests/test_send_to_remote.py`

- `test_user_text_is_sent_via_stdin_not_remote_command`
  - monkeypatch `asyncio.create_subprocess_exec` 捕获 argv 和 communicate input。
  - 输入：`"hello; whoami $(id) 'x'\nnext"`。
  - 断言该输入原文只出现在 `communicate(input=...)`，不出现在 argv 的远端命令字符串中。

- `test_send_preserves_whitespace_and_newlines`
  - 输入包含前后空格、多个空格、换行。
  - 断言 stdin bytes 与输入 UTF-8 编码完全一致。

- `test_send_uses_generated_session_name_only`
  - `_current_session_id = 3`。
  - 断言远端命令中目标是 `gate-3`，没有其他用户可控 session 名。

- `test_send_failure_surfaces_error`
  - fake process returncode 非 0，stderr 为 `"no such session"`。
  - 断言 UI 显示发送失败，或 `_send_to_remote()` 抛出可处理异常。

### 验收标准

- 任意合法 prompt 文本都按原文进入 Hermes。
- shell 元字符不会在远端执行。
- 远端 tmux 失败时用户能看到错误。

## 6. GUIDE.md 首次使用流程更新

### 现状

`GUIDE.md` 仍要求：

```bash
cp .env.example .env
```

但仓库没有 `.env.example`，README 也说明当前无需配置文件。

### 正确行为

用户按 `GUIDE.md` 操作时，应能完成首次启动。文档应与当前交互式添加服务器流程一致。

### 修复方案

1. 删除 `.env.example` 相关步骤。

2. 首次使用改为：

   ```bash
   ./start.sh
   ```

   然后在 TUI 中选择 `Add Server...`，输入 `user@host` 或 `user@host:port`。

3. 补充前置条件：

   - Docker 可用。
   - 本机 `~/.ssh` 存在可用私钥。
   - 远端已允许该公钥登录。
   - 远端已安装 `tmux` 和 `hermes`。

### 测试

`tests/test_docs.py`

- `test_guide_does_not_reference_missing_env_example`
  - 读取 `GUIDE.md`。
  - 断言不包含 `.env.example`。

- `test_guide_documents_interactive_server_input`
  - 断言包含 `Add Server` 或 `user@host:port`。

### 验收标准

- 首次用户不会被引导到不存在的文件。
- README 和 GUIDE 对启动流程没有互相冲突。

## 推荐实现顺序

1. 先补测试基础设施和文档测试，确保后续改动可验证。
2. 修复远程输入发送。这同时影响稳定性和安全性，风险最高。
3. 修复 session 记录按端口隔离，避免操作串服。
4. 修复网络探测和 worker 生命周期，降低状态误报和后台任务残留。
5. 修复 refresh 异常显示，让后续远程问题可诊断。
6. 更新 `GUIDE.md`。

## 最小回归命令

实现后至少运行：

```bash
python -m compileall -q hermes_gate
python -m pytest -q
docker compose config --quiet
```

如果 Docker 可用且允许构建，再运行：

```bash
docker compose build
```

真实远程服务器的集成验证可以作为手动项，不应作为默认单元测试前置条件。
