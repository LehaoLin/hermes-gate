# Hermes Gate 启动指南

## 首次使用

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的服务器地址
# SERVER_HOST=xxx.xxx.xxx.xxx
# SERVER_USER=root
# SERVER_PORT=22
```

### 2. 一键启动

```bash
./start.sh
```

首次运行会自动构建 Docker 镜像并进入 TUI 交互界面。

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
