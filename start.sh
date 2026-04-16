#!/bin/bash
set -e

CONTAINER_NAME="hermes-gate"

cleanup() {
    echo ""
    echo "正在停止容器 ${CONTAINER_NAME}..."
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    echo "已停止。"
}
trap cleanup EXIT INT TERM

if [ ! -f .env ]; then
    echo "未找到 .env 文件，正在从 .env.example 复制..."
    cp .env.example .env
    echo "已创建 .env，请编辑 .env 填入服务器地址后重新运行此脚本。"
    exit 1
fi

FORCE_REBUILD=false
if [ "$1" = "--rebuild" ]; then
    FORCE_REBUILD=true
fi

if [ "$FORCE_REBUILD" = true ]; then
    echo "强制重新构建..."
    docker compose down 2>/dev/null || true
    docker compose up -d --build
    echo "构建完成，正在进入容器..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo "false")

if [ "$RUNNING" = "true" ]; then
    echo "容器已在运行，正在进入..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

EXISTS=$(docker inspect -f '{{.Id}}' "${CONTAINER_NAME}" 2>/dev/null || echo "")

if [ -n "$EXISTS" ]; then
    echo "容器已存在（已停止），正在启动..."
    docker start "${CONTAINER_NAME}"
    echo "已启动，正在进入..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

HAS_IMAGE=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -i "hermes" || true)

if [ -n "$HAS_IMAGE" ]; then
    echo "镜像已存在，正在启动容器（跳过构建）..."
    docker compose up -d
    echo "已启动，正在进入..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

echo "未找到镜像，正在首次构建..."
docker compose up -d --build
echo "构建完成，正在进入容器..."
docker attach "${CONTAINER_NAME}"
