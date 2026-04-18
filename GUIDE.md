# Hermes Gate Getting Started Guide

## First Time

### 1. One-Click Start

```bash
./run.sh
```

The first run will automatically build the Docker image and launch the TUI interactive interface. Make sure Docker is running and your SSH key is set up (see Prerequisites below). Hermes Gate launches a temporary local client, while the long-lived work remains in the remote tmux / Hermes session.

After entering, select "➕ Add Server..." and input:

```
username@ip_address       e.g. root@1.2.3.4
username@hostname         e.g. admin@myserver
username@hostname:port    e.g. root@1.2.3.4:2222
```

### Prerequisites

- Docker installed and running
- SSH key in local `~/.ssh` directory, added to the target server's `authorized_keys`
- Remote server has `tmux` and `hermes` installed
- Remote command execution currently assumes a bash-based login-shell environment
- `tmux` and `hermes` must be available in the remote login-shell PATH used by SSH
- First-time SSH trust for a new host is currently handled with `StrictHostKeyChecking=accept-new`

## Daily Use

```bash
./run.sh              # Start and enter container (skips build if already built)
./run.sh rebuild      # Force rebuild then start
```

The container stops automatically when you exit the TUI. When you attach to a session, Hermes Gate suspends its own TUI and hands control to the native remote tmux / Hermes session until you detach or exit.

## Hot Reload

Python code under `hermes_gate/` is mounted via a Docker volume. After modification, **no rebuild is needed** — just restart the container.

The following files **require a rebuild** (`./run.sh rebuild`) after changes:

- `pyproject.toml`
- `requirements.txt`
- `entrypoint.sh`
- `Dockerfile`

## Common Docker Commands

```bash
docker compose down              # Stop and remove container
docker compose logs hermes-gate  # View logs
docker exec -it hermes-gate bash # Enter container shell
```

## Notes

- Make sure you have SSH keys (`id_rsa` or `id_ed25519`) in your local `~/.ssh` directory before starting
- The container stops automatically when you exit the TUI; just run `./run.sh` again next time
- Attached interaction is primarily native tmux / Hermes behavior rather than a persistent Gate-controlled viewer layer
- Current remote session checks and launch flow assume bash-based login-shell behavior on the target host
- SSH first-connection trust currently uses `accept-new`, while later host-key changes are still rejected by SSH
