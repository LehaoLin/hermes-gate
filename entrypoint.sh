#!/bin/bash
set -e

# 1. 检查 SSH 密钥
if [ ! -f ~/.ssh/id_rsa ] && [ ! -f ~/.ssh/id_ed25519 ] && [ ! -f ~/.ssh/id_ecdsa ]; then
    echo "❌ 未找到 SSH 密钥，请挂载 ~/.ssh 目录"
    exit 1
fi
chmod 600 ~/.ssh/id_* 2>/dev/null || true
chmod 644 ~/.ssh/id_*.pub 2>/dev/null || true

# 2. 启动 TUI
exec python -m hermes_gate "$@"
