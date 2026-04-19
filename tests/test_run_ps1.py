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
    assert 'System.Text.UTF8Encoding($false)' in content


def test_readme_documents_windows_stop_command():
    """README Windows usage should stay aligned with run.ps1 command surface."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '.\\run.ps1 stop' in readme
