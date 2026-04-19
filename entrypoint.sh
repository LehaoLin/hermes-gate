#!/bin/bash
set -e

SOURCE_SSH_DIR="${HERMES_GATE_HOST_SSH_DIR:-/host/.ssh}"
RUNTIME_SSH_DIR="${HOME}/.ssh"

if [ ! -d "$SOURCE_SSH_DIR" ]; then
    SOURCE_SSH_DIR="$RUNTIME_SSH_DIR"
fi

if [ ! -d "$SOURCE_SSH_DIR" ] || [ -z "$(ls -A "$SOURCE_SSH_DIR" 2>/dev/null)" ]; then
    echo "Warning: SSH directory is empty or missing. SSH connections may fail."
    echo "Mount your host ~/.ssh directory for SSH key access."
fi

if [ "$SOURCE_SSH_DIR" != "$RUNTIME_SSH_DIR" ]; then
    mkdir -p "$RUNTIME_SSH_DIR"
    cp -R "$SOURCE_SSH_DIR"/. "$RUNTIME_SSH_DIR"/
fi

chmod 700 "$RUNTIME_SSH_DIR" 2>/dev/null || true
chmod 600 "$RUNTIME_SSH_DIR"/* 2>/dev/null || true
chmod 644 "$RUNTIME_SSH_DIR"/*.pub 2>/dev/null || true
chmod 644 "$RUNTIME_SSH_DIR"/known_hosts* 2>/dev/null || true

if [ -f "$RUNTIME_SSH_DIR/config" ]; then
    sed -i \
        -e 's|C:\\Users\\[^\\]*\\.ssh\\|/root/.ssh/|g' \
        -e 's|/c/Users/[^/]*/.ssh/|/root/.ssh/|g' \
        "$RUNTIME_SSH_DIR/config"
    export HERMES_GATE_SSH_CONFIG="$RUNTIME_SSH_DIR/config"
fi

exec sleep infinity
