from pathlib import Path


ROOT = Path(__file__).parent.parent


def _run_ps1() -> str:
    return (ROOT / "run.ps1").read_text(encoding="utf-8")


def test_run_ps1_uses_docker_exec_for_tui_launch():
    """Windows launcher should start Hermes Gate via docker exec, not attach."""
    content = _run_ps1()
    assert 'docker exec -it $Name python -m hermes_gate' in content
    assert 'docker attach $Name' not in content


def test_run_ps1_supports_stop_command():
    """Windows launcher should expose the same explicit stop command as run.sh."""
    content = _run_ps1()
    assert '[ValidateSet("rebuild", "update", "stop")]' in content
    assert 'if ($Command -eq "stop")' in content


def test_run_ps1_avoids_utf8nobom_encoding_for_ps51_compatibility():
    """PowerShell 5.1-compatible compose writing should not rely on UTF8NoBOM."""
    content = _run_ps1()
    assert 'UTF8NoBOM' not in content
    assert 'System.Text.UTF8Encoding($false)' not in content


def test_run_ps1_uses_checked_in_windows_compose_override():
    """Windows launcher should use the checked-in Windows compose file instead of generating one on the fly."""
    content = _run_ps1()
    assert '$ComposeArgs = @("-f", "docker-compose.windows.yml")' in content
    assert 'docker-compose.win.yml' not in content
    assert 'Write-Utf8NoBomFile' not in content


def test_run_ps1_rebuild_matches_run_sh_image_cleanup_behavior():
    """Windows rebuild flow should match run.sh by removing local images before rebuild."""
    content = _run_ps1()
    assert 'docker compose @ComposeArgs down --rmi local' in content


def test_windows_compose_override_removes_hosts_mount_only():
    """Windows compose file should keep the shared mounts but omit the Linux-only /etc/hosts bind."""
    content = (ROOT / "docker-compose.windows.yml").read_text(encoding="utf-8")
    assert 'services:' in content
    assert 'hermes-gate:' in content
    assert 'image: hermes-gate' in content
    assert 'build: .' in content
    assert 'container_name: hermes-gate' in content
    assert '~/.ssh:/host/.ssh:ro' in content
    assert './hermes_gate:/app/hermes_gate' in content
    assert '/etc/hosts:/host/etc/hosts:ro' not in content


def test_readme_documents_windows_stop_command():
    """README Windows usage should stay aligned with run.ps1 command surface."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '.\\run.ps1 stop' in readme
