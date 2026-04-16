# Hermes Gate

远程连接云服务器 [Hermes](https://github.com/NomicFoundation/hermes) tmux session 的 TUI 工具。

通过 Docker 容器运行，提供服务器选择、Session 管理、实时输出查看和网络状态监控。

## 功能

- 多服务器管理与快速切换
- 远程 tmux session 创建 / 连接 / 销毁
- 实时查看远程 Hermes 输出，支持向远程发送指令
- 网络状态监控（延迟显示 + 断线自动重连）
- hostname 自动解析（通过 `/etc/hosts`）

## 安装

### 前置要求

- [Docker](https://docs.docker.com/get-dinned/)
- SSH 密钥（`~/.ssh/id_rsa` 或 `~/.ssh/id_ed25519`），已添加到目标服务器的 `authorized_keys`

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/LehaoLin/hermes-gate.git
cd hermes-gate

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入服务器信息：
#   SERVER_HOST=your_server_ip_or_hostname
#   SERVER_USER=root
#   SERVER_PORT=22

# 3. 启动
./start.sh
```

首次运行会自动构建 Docker 镜像并进入 TUI。

## 使用

### 启动

```bash
./start.sh              # 启动（已构建过则跳过 build）
./start.sh --rebuild    # 强制重新构建后启动
```

### TUI 操作

| 阶段 | 按键 | 功能 |
|------|------|------|
| 服务器选择 | `↑↓` | 切换服务器 |
| | `Enter` | 连接选中服务器 |
| | `D` | 删除选中服务器 |
| | `Q` | 退出 |
| Session 列表 | `↑↓` | 切换 session |
| | `Enter` | 进入 session |
| | `N` | 新建 session |
| | `K` | 销毁 session |
| | `R` | 刷新列表 |
| | `Shift+Tab` | 返回服务器选择 |
| 查看器 | 输入框输入 + `Enter` | 向远程 Hermes 发送指令 |
| | `Ctrl+B` | 返回 Session 列表 |

### 添加服务器

在服务器选择界面选择「➕ Add Server...」，输入格式：

```
用户名@IP地址       例: root@1.2.3.4
用户名@主机名       例: admin@myserver
```

## 开发

`hermes_gate/` 目录通过 volume 挂载到容器中，修改 Python 代码后**重启容器即可生效**，无需重新构建。

以下文件修改后需要重新构建（`./start.sh --rebuild`）：

- `pyproject.toml` / `requirements.txt`
- `Dockerfile` / `entrypoint.sh`

### 常用命令

```bash
docker compose down              # 停止并删除容器
docker compose logs hermes-gate  # 查看日志
docker exec -it hermes-gate bash # 进入容器 shell
```

## 项目结构

```
hermes-gate/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── start.sh
├── .env.example
├── pyproject.toml
└── hermes_gate/
    ├── __main__.py    # 入口
    ├── app.py         # TUI 主界面
    ├── servers.py     # 服务器管理 & hostname 解析
    ├── session.py     # 远程 tmux session 管理
    └── network.py     # 网络状态监控
```

## License

MIT
