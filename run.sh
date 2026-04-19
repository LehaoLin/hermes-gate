#!/bin/bash

show_help() {
    cat <<'HELP'
Usage: ./run.sh [COMMAND]

Start the Hermes Gate TUI.

Commands:
      (none)         Start (or connect to existing container)
      rebuild        Force rebuild the Docker image, then start
      update         git pull, then rebuild and start
      stop           Stop and remove the container
      --help, -h     Show this help message and exit

Multiple terminals can run ./run.sh simultaneously — each gets an
independent TUI session inside the same container. The container
auto-stops when the last session exits.
HELP
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

set -e

CONTAINER_NAME="hermes-gate"

# ─── auto-stop if no other sessions ───────────────────────────────
_auto_stop() {
    REMAINING=$(docker exec "${CONTAINER_NAME}" pgrep -c python 2>/dev/null || echo "0")
    if [ "$REMAINING" -eq 0 ] 2>/dev/null; then
        echo "No active sessions, stopping container..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    fi
}

# ─── stop subcommand ──────────────────────────────────────────────
if [ "$1" = "stop" ]; then
    echo "Stopping ${CONTAINER_NAME}..."
    docker compose down 2>/dev/null || docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    echo "Stopped."
    exit 0
fi

# ─── rebuild / update ─────────────────────────────────────────────
FORCE_REBUILD=false
if [ "$1" = "rebuild" ]; then
    FORCE_REBUILD=true
elif [ "$1" = "update" ]; then
    echo "Pulling latest changes..."
    git pull
    FORCE_REBUILD=true
fi

if [ "$FORCE_REBUILD" = true ]; then
    echo "Force rebuilding..."
    docker compose down 2>/dev/null || true
    docker compose up -d --build
    echo "Build complete, launching TUI..."
    docker exec -it "${CONTAINER_NAME}" python -m hermes_gate
    _auto_stop
    exit 0
fi

# ─── ensure container is running ──────────────────────────────────
RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo "false")

if [ "$RUNNING" != "true" ]; then
    EXISTS=$(docker inspect -f '{{.Id}}' "${CONTAINER_NAME}" 2>/dev/null || echo "")

    if [ -n "$EXISTS" ]; then
        echo "Container exists (stopped), starting..."
        docker start "${CONTAINER_NAME}"
    else
        HAS_IMAGE=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -i "hermes" || true)
        if [ -n "$HAS_IMAGE" ]; then
            echo "Image found, starting container..."
            docker compose up -d
        else
            echo "No image found, building for the first time..."
            docker compose up -d --build
        fi
    fi
    echo "Container started, launching TUI..."
fi

# ─── launch TUI ───────────────────────────────────────────────────
docker exec -it "${CONTAINER_NAME}" python -m hermes_gate
_auto_stop
