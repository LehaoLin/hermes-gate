# 🏛️ Hermes Gate

[English](README.md) | [简体中文](README_ZH.md)

A feature-rich **terminal TUI** for remotely managing [Hermes Agent](https://github.com/NousResearch/hermes-agent) tmux sessions on cloud servers — all from a single Docker container.

> *"I love watching Hermes Agent work through a TUI — but mine runs on a remote cloud server, and my local network isn't always stable. When the connection drops mid-task, I have no idea if it's still running or already dead. An interrupted task means hours of wasted effort. Sure, I could manage it over raw tmux — but that's just typing the same boilerplate commands over and over. More time lost."*

> **Note:** Hermes Gate is a companion tool for [Hermes Agent](https://github.com/NousResearch/hermes-agent) ([Website](https://hermes-agent.nousresearch.com/)), an open-source AI agent framework by NousResearch.

## Why Hermes Gate?

> **Lifecycle clarification:** Hermes Gate is a **temporary local client**. When you quit the TUI, the Docker container stops. Your remote tmux / Hermes Agent sessions on the server are **not affected** — they keep running. Just run `./run.sh` again to reconnect. Nothing is lost except the local container state.

Running Hermes Agent on a remote server usually means juggling SSH terminals, worrying about dropped connections, and manually managing tmux sessions. Hermes Gate solves all of that:

- **Full TUI Experience** — Browse servers, manage sessions, view live Hermes Agent output, and send prompts, all from an interactive terminal UI built with [Textual](https://textual.textualize.io/). No raw SSH commands to remember.
- **Network Status Monitoring** — Real-time latency monitoring with TCP-level probing. Connection status is displayed in the TUI so you know when the remote server is reachable. Note: if your SSH session drops, you will need to re-enter the session manually.
- **Session Persistence via tmux** — Sessions run inside remote tmux, so your remote processes keep running even if you close Hermes Gate. However, note that the Docker container stops on TUI exit — run `./run.sh` again to reattach.
- **Multi-Server, Multi-Session** — Switch between servers and sessions instantly. Each session is independently tracked and managed.
- **One Command Start** — `./run.sh` builds, starts, and drops you into the TUI. Requires Docker and an SSH key in `~/.ssh/` (see Prerequisites).

## Features

- Interactive server selection with quick switching
- Remote tmux session create / connect / destroy
- Live remote Hermes Agent output viewing with prompt sending
- Network status monitoring (real-time latency display and connection status)
- Automatic hostname resolution (via `/etc/hosts`)
- SSH config alias support (use your `~/.ssh/config` host aliases)
- Remote control keys: `Ctrl+C` interrupt, `Ctrl+E` escape (without leaving the TUI)

## Installation

### Prerequisites

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) installed and running on the target server
- [Docker](https://docs.docker.com/get-docker/)
- SSH key in `~/.ssh/` added to the target server's `authorized_keys` (any key type: `id_rsa`, `id_ed25519`, custom `IdentityFile`, or SSH agent)

### Steps

```bash
git clone https://github.com/LehaoLin/hermes-gate.git
cd hermes-gate
./run.sh
```

The first run will automatically build the Docker image and launch the TUI. Make sure you have Docker running and your SSH key set up before starting.

## Usage

### Starting

```bash
./run.sh              # Start (skips build if already built)
./run.sh rebuild      # Force rebuild then start
./run.sh update       # git pull + rebuild + start
./run.sh -h           # Show help
```

### TUI Controls

| Phase | Key | Action |
|-------|-----|--------|
| Server Selection | `↑↓` | Switch server |
| | `Enter` | Connect to selected server |
| | `D` | Delete selected server |
| | `Q` | Quit |
| Session List | `↑↓` | Switch session |
| | `Enter` | Enter session |
| | `N` | New session |
| | `K` | Kill session |
| | `R` | Refresh list |
| | `Ctrl+B` | Back to server selection |
| Viewer | Type in input + `Enter` | Send prompt to remote Hermes Agent |
| | `Ctrl+B` | Back to session list |

### Adding a Server

Select "➕ Add Server..." on the server selection screen. Input format:

```
username@ip_address       e.g. root@1.2.3.4
username@hostname         e.g. admin@myserver
username@hostname:port    e.g. root@1.2.3.4:2222
```

Default port is 22. Non-standard ports must be specified explicitly.

## Development

The `hermes_gate/` directory is mounted as a volume into the container. After modifying Python code, **just restart the container** — no rebuild needed.

The following files require a rebuild (`./run.sh rebuild`) after changes:

- `pyproject.toml` / `requirements.txt`
- `Dockerfile` / `entrypoint.sh`

### Common Commands

```bash
docker compose down              # Stop and remove container
docker compose logs hermes-gate  # View logs
docker exec -it hermes-gate bash # Enter container shell
```

## Project Structure

```
hermes-gate/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── run.sh
├── pyproject.toml
└── hermes_gate/
    ├── __main__.py    # Entry point
    ├── app.py         # TUI main interface
    ├── servers.py     # Server management & hostname resolution
    ├── session.py     # Remote tmux session management
    └── network.py     # Network status monitoring
```

## Star History

<a href="https://www.star-history.com/?repos=LehaoLin%2Fhermes-gate&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=LehaoLin/hermes-gate&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=LehaoLin/hermes-gate&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=LehaoLin/hermes-gate&type=date&legend=top-left" />
 </picture>
</a>

## License

MIT