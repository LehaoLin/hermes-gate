# Hermes Gate 启动指南

## 首次使用

### 1. 一键启动

```bash
./start.sh
```

首次运行会自动构建 Docker 镜像并进入 TUI 交互界面。无需任何配置文件。

进入后选择「➕ Add Server...」，输入：

```
用户名@IP地址           例: root@1.2.3.4
用户名@主机名           例: admin@myserver
用户名@主机名:端口      例: root@1.2.3.4:2222
```

### 前置条件

- Docker 已安装并运行
- 本机 `~/.ssh` 目录下有 SSH 私钥（`id_rsa` 或 `id_ed25519`），且已添加到目标服务器的 `authorized_keys`
- 远端服务器已安装 `tmux` 和 `hermes`

## 日常使用

```bash
./start.sh              # 启动并进入容器（已构建过则跳过 build）
./start.sh --rebuild    # 强制重新构建后启动
```

退出 TUI 后容器会自动停止。

## 热更新

`hermes_gate/` 目录下的 Python 代码已通过 volume 挂载，修改后**无需重新构建**，重启容器即可生效。

以下文件修改后**需要重新构建**（`./start.sh --rebuild`）：

- `pyproject.toml`
- `requirements.txt`
- `entrypoint.sh`
- `Dockerfile`

## 常用 Docker 命令

```bash
docker compose down              # 停止并删除容器
docker compose logs hermes-gate  # 查看日志
docker exec -it hermes-gate bash # 进入容器 shell
```

## 注意事项

- 启动前确保本机 `~/.ssh` 目录下有 SSH 密钥（`id_rsa` 或 `id_ed25519`）
- 退出 TUI 后容器会自动停止，下次运行 `./start.sh` 即可
