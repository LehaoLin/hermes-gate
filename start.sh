#!/bin/bash

show_help() {
    cat <<'HELP'
Usage: ./start.sh [OPTION]

Start the Hermes Gate TUI.

Options:
      --help, -h     Show this help message and exit
      --rebuild      Force rebuild the Docker image, then start
      --update       git pull, then rebuild and start

If no option is given, starts the existing container or builds on first run.
HELP
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

set -e

CONTAINER_NAME="hermes-gate"

cleanup() {
    echo ""
    echo "Stopping container ${CONTAINER_NAME}..."
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    echo "Stopped."
}
trap cleanup EXIT INT TERM

FORCE_REBUILD=false
if [ "$1" = "--rebuild" ]; then
    FORCE_REBUILD=true
elif [ "$1" = "--update" ]; then
    echo "Pulling latest changes..."
    git pull
    FORCE_REBUILD=true
fi

if [ "$FORCE_REBUILD" = true ]; then
    echo "Force rebuilding..."
    docker compose down 2>/dev/null || true
    docker compose up -d --build
    echo "Build complete, attaching..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo "false")

if [ "$RUNNING" = "true" ]; then
    echo "Container already running, attaching..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

EXISTS=$(docker inspect -f '{{.Id}}' "${CONTAINER_NAME}" 2>/dev/null || echo "")

if [ -n "$EXISTS" ]; then
    echo "Container exists (stopped), starting..."
    docker start "${CONTAINER_NAME}"
    echo "Started, attaching..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

HAS_IMAGE=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -i "hermes" || true)

if [ -n "$HAS_IMAGE" ]; then
    echo "Image found, starting container (skip build)..."
    docker compose up -d
    echo "Started, attaching..."
    docker attach "${CONTAINER_NAME}"
    exit 0
fi

echo "No image found, building for the first time..."
docker compose up -d --build
echo "Build complete, attaching..."
docker attach "${CONTAINER_NAME}"
