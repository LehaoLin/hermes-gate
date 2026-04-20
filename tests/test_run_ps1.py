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


def test_run_ps1_prefers_additive_session_name_and_response_preview_fields_for_windows_notifications():
    """Windows watcher should use additive session_name/response_preview fields when present, without requiring run.sh changes."""
    content = _run_ps1()
    assert '$sessionName = if ($data.session_name) { [string]$data.session_name } else { $null }' in content
    assert '$responsePreview = if ($data.response_preview) { [string]$data.response_preview } else { $null }' in content
    assert '$title = if ($sessionName) { $sessionName } elseif ($data.title)' in content
    assert '$msg = if ($responsePreview) { $responsePreview } elseif ($data.message)' in content


def test_run_ps1_defaults_notification_title_and_message_before_replace_calls():
    """Watcher should still supply safe default title/message values before escaping for detached notification hosts."""
    content = _run_ps1()
    assert '$title = if ($sessionName) { $sessionName } elseif ($data.title) { [string]$data.title } else { "Hermes Gate" }' in content
    assert '$msg = if ($responsePreview) { $responsePreview } elseif ($data.message) { [string]$data.message } else { "Notification received." }' in content


def test_run_ps1_windows_notifications_play_custom_wav_audio():
    """Windows watcher should play custom WAV sounds via SoundPlayer after showing toast."""
    content = _run_ps1()
    assert 'System.Media.SoundPlayer' in content
    assert '# Play custom sound if available' in content


def test_run_ps1_logs_outer_watcher_exceptions_instead_of_swallowing_them():
    """Top-level watcher exceptions should be recorded to watcher.log rather than silently swallowed."""
    content = _run_ps1()
    assert "Watcher processing failed:" in content
    assert "} catch {" in content
    # The outer notification watcher catch block should log, not silently swallow
    assert "Watcher processing failed: ' + $_)" in content


def test_run_ps1_uses_encoded_command_for_detached_notification_hosts():
    """Windows watcher should launch child PowerShell hosts with -EncodedCommand to avoid command injection via notification text."""
    content = _run_ps1()
    assert "'-EncodedCommand'" in content
    assert '$encodedNotifyCommand' in content


def test_run_ps1_uses_detached_notification_process_for_burnttoast():
    """Watcher should delegate visible notifications to a separate PowerShell process instead of invoking BurntToast directly inside the job."""
    content = _run_ps1()
    assert 'Start-Process $notificationHost' in content
    assert "Get-NotificationHostCandidates" in content
    assert 'New-BurntToastNotification' in content
    assert 'Import-Module BurntToast' in content
    assert 'ShowBalloonTip' not in content


def test_run_ps1_prefers_pwsh_before_windows_powershell_for_notifications():
    """Adaptive notification launcher should prefer pwsh before falling back to powershell."""
    content = _run_ps1()
    host_candidates_idx = content.index('function Get-NotificationHostCandidates')
    pwsh_idx = content.index("Get-Command pwsh")
    powershell_idx = content.index("Get-Command powershell")
    assert host_candidates_idx < pwsh_idx < powershell_idx


def test_run_ps1_logs_notification_host_failures():
    """Fallback path should emit diagnostic logs instead of silently swallowing toast host failures."""
    content = _run_ps1()
    assert '$logPath = Join-Path $NotifyDir "watcher.log"' in content
    assert 'Add-Content -Path $logPath' in content
    assert 'Notification host failed:' in content
    assert 'No notification host succeeded' in content


def test_run_ps1_does_not_dispose_notifyicon_immediately_after_notification():
    """The watcher should not create a short-lived NotifyIcon that disappears before the notification is visible."""
    content = _run_ps1()
    assert '$notify.Dispose()' not in content
    assert 'Start-Sleep -Milliseconds 100' not in content


def test_run_ps1_plays_sound_after_toast():
    """Windows watcher plays custom sound after toast notification."""
    content = _run_ps1()
    assert 'Start-Process $notificationHost' in content
    assert '# Play custom sound if available' in content


def test_run_ps1_notification_job_no_longer_calls_burnttoast_inline():
    """The old direct job-scoped BurntToast call shape should be gone once watcher delegates to a detached process."""
    content = _run_ps1()
    assert 'New-BurntToastNotification -Text $title, $msg' not in content
    assert '$shown = $false' not in content


def test_run_ps1_notification_host_wait_has_timeout_instead_of_unbounded_wait():
    """Watcher should not block forever on Start-Process -Wait when a notification host stalls."""
    content = _run_ps1()
    assert '-PassThru' in content
    assert '-Wait' not in content
    assert 'WaitForExit(5000)' in content
    assert '$process.Kill()' in content
