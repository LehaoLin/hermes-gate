# Changelog

## 2026-04-19 - Windows launcher parity and PowerShell 5.1 compatibility

### Fixed

- Reworked `run.ps1` to launch Hermes Gate via `docker exec -it ... python -m hermes_gate` instead of `docker attach`, aligning Windows startup with the current `run.sh` / `entrypoint.sh` lifecycle.
- Added Windows `stop` command support and replaced unconditional container shutdown with idle-only auto-stop behavior so multiple local TUI sessions can coexist without one exit killing the shared container.
- Regenerate `docker-compose.win.yml` deterministically on each run to avoid silent drift from current compose settings.
- Added preflight checks for `docker compose`, Docker daemon availability, `git` on `update`, and missing `~/.ssh` warnings.
- Replaced `Set-Content -Encoding UTF8NoBOM` with .NET UTF-8 no-BOM file writing so the script remains compatible with Windows PowerShell 5.1.

### Tests

- Added `tests/test_run_ps1.py` to lock Windows launcher behavior: `docker exec` launch path, `stop` command support, PowerShell 5.1-safe compose writing, and README command parity.
- Validation run: `python -m pytest -q tests/test_run_ps1.py` (`4 passed`).
- Validation run: `python -m pytest -q` (`71 passed`).
- Validation run: `python -m compileall -q hermes_gate tests`.

# Changelog

## 2026-04-17 - Compatibility and Stability Fixes

### Compatibility Review

- Confirmed the implementation does not depend on a specific server IP, SSH alias, key filename, Windows username, or local workspace path.
- Replaced local test fixtures that used real-looking host data with documentation-only addresses such as `203.0.113.10`.
- Removed hardcoded `/root/.ssh/config` usage from application code. SSH config discovery now uses `HERMES_GATE_SSH_CONFIG` when provided and falls back to the current user's `~/.ssh/config`.
- Changed Docker SSH handling to mount the host `~/.ssh` directory read-only at `/host/.ssh`, copy it into the container runtime SSH directory, and apply permission/path normalization only to the runtime copy.

### Fixed

- Preserved SSH config aliases for connections, session listing, session creation, output polling, prompt sending, and attach commands so `Host` entries with `IdentityFile`, `User`, `Port`, and `IdentitiesOnly` work consistently.
- Added support for entering either an SSH config alias or `user@host[:port]` in the server prompt.
- Scoped local session records by `user`, `host`, and `port`, with migration support for legacy port-22 records.
- Made session refresh surface errors instead of silently swallowing SSH/tmux failures, while keeping the previous session list intact on refresh failure.
- Discovered existing remote `gate-*` tmux sessions even when no local JSON record exists.
- Added explicit remote preflight checks for `tmux` and `hermes`.
- Replaced ICMP ping network checks with TCP probes against the configured SSH port.
- Prevented stale network monitor workers from continuing after viewer navigation.
- Sent prompts through SSH stdin and a tmux buffer instead of embedding user text into a remote shell command.
- Cleared stale remote input before pasting a prompt so new messages do not append to a half-entered command.
- Added remote control keys in viewer mode: `Ctrl+E` sends remote Escape/C-u and `Ctrl+C` interrupts a stuck remote Hermes request.
- Rendered tmux capture output as plain terminal text, avoiding Rich markup interpretation and remote ANSI background blocks.
- Fixed Textual runtime color reset by clearing the inline color rule instead of assigning a theme variable as a runtime color.
- Removed obsolete `.env.example` setup instructions from `GUIDE.md`.

### Docker

- The host SSH directory is now mounted read-only.
- SSH config path rewriting for Windows and Git Bash paths is applied only inside the container runtime copy.
- OpenSSH key permissions are normalized inside the container without mutating host files.
- Because the compose volume target changed, existing containers must be recreated, not only restarted.

### Tests

- Added coverage for SSH config alias matching, runtime SSH config path selection, tab-separated SSH config parsing, server record alias updates, port-scoped session records, legacy session migration, remote session discovery, tmux-missing errors, refresh failure surfacing, network port probing, network worker lifecycle, guide consistency, Textual hint color reset, tmux capture rendering, prompt command construction, and remote key command construction.
- Added `test` optional dependencies for `pytest` and `pytest-asyncio`, with explicit asyncio pytest configuration so async tests execute consistently in local and CI runs.
- Validation run: `python -m compileall -q hermes_gate tests`.
- Validation run: `python -m pytest -q` (`49 passed`).
- Validation run: `docker compose config`.
- Validation run: `bash -n entrypoint.sh` inside the project Docker image.

### Validation Notes

- Async tests now execute locally after installing `.[test]`; the previous skipped-async-test state is fixed.
- `StrictHostKeyChecking=no` remains an existing security debt from the current SSH command defaults. It is not a machine-specific change, but it should be addressed separately before treating the tool as hardened.

## 2026-04-17 - Session Kill Flow Improvements

### Fixed

- Changed the session-list destructive shortcut from lowercase `k` to uppercase `K` to match the issue requirement and reduce accidental activation.
- Added a confirmation modal before killing a session, with `Kill session <name>? [y/N]` semantics and keyboard/button confirm-cancel flows.
- Updated remote session teardown to detach attached tmux clients before killing the tmux session.
- Treated missing remote tmux sessions as a non-fatal cleanup case so the local record is still removed and the list can refresh cleanly.
- Preserved the local record when remote kill fails for real errors, and surfaced a clear error hint in the TUI instead of silently removing the entry.
- Returned explicit kill result metadata from `SessionManager.kill_session()` so the app can distinguish success, already-missing tmux sessions, and hard failures.

### Tests

- Added TUI tests for uppercase `K`, confirmation gating, confirmed-vs-cancelled behavior, success messaging, and failure messaging.
- Added session-manager tests for detach-before-kill ordering, missing-tmux cleanup, tmux-missing errors, and local-record preservation on remote kill failure.
- Added binding regression tests to prove session/select shortcuts are installed up front and enabled only in the correct phase.
- Added confirm-screen tests to lock keyboard-only kill confirmation behavior (`y`/`Enter` confirm, `n`/`Esc` cancel) with no redundant buttons.
- Added local interaction tests to verify uppercase `N` creates sessions and uppercase `K` opens kill flow only in session phase.
- Added session-hint text regression tests so the footer copy stays aligned with the actual `N/K/R/Esc/Shift+Tab/Q` bindings.
- Added kill-confirm title regression coverage so the prompt stays aligned with the actual `y/n` cancel-confirm semantics.
- Validation run: `. .venv/bin/activate && pytest -q` (`60 passed`).