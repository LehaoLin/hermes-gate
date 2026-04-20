#Requires -Version 5.1
<#
.SYNOPSIS
    Start the Hermes Gate TUI on Windows.

.EXAMPLE
    .\run.ps1
    .\run.ps1 rebuild
    .\run.ps1 update
    .\run.ps1 stop
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("rebuild", "update", "stop")]
    [string]$Command
)

$ErrorActionPreference = "Stop"
$ContainerName = "hermes-gate"
$ProjectDir = $PSScriptRoot
$ComposeArgs = @("-f", "docker-compose.windows.yml")
$NotifyDir = Join-Path $ProjectDir ".notify"

function Assert-Command([string]$Name, [string]$Message) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
}

function Assert-DockerCompose {
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: 'docker compose' is not available. Please install/update Docker Desktop." -ForegroundColor Red
        exit 1
    }
}

function Assert-DockerDaemon {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Docker daemon is not running. Please start Docker Desktop." -ForegroundColor Red
        exit 1
    }
}

function Assert-SshDirectory {
    $sshDir = Join-Path $HOME ".ssh"
    if (-not (Test-Path $sshDir)) {
        Write-Host "Warning: $sshDir was not found. SSH connections may fail until your SSH keys are available." -ForegroundColor Yellow
    }
}

function Test-ContainerExists([string]$Name) {
    docker inspect -f '{{.Id}}' $Name 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Tui([string]$Name) {
    docker exec -it $Name python -m hermes_gate
}

function Stop-IfIdle([string]$Name) {
    $remaining = docker exec $Name pgrep -c python 2>$null
    if ($LASTEXITCODE -ne 0) {
        $remaining = "0"
    }
    $remaining = ($remaining | Out-String).Trim()
    if (-not $remaining) {
        $remaining = "0"
    }
    if ([int]$remaining -eq 0) {
        Write-Host "No active sessions, stopping container..."
        docker stop $Name 2>$null | Out-Null
    }
}

# ---------------------------------------------------------------------------
# Notification watcher — polls notify dir for signal files from the container
# ---------------------------------------------------------------------------
$script:WatcherJob = $null

function Get-NotificationHostCandidates {
    $candidates = @()
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwsh) {
        $candidates += $pwsh.Source
    }
    $windowsPowerShell = Get-Command powershell -ErrorAction SilentlyContinue
    if ($windowsPowerShell) {
        $candidates += $windowsPowerShell.Source
    }
    return @($candidates | Select-Object -Unique)
}

function Start-NotifyWatcher {
    New-Item -ItemType Directory -Force -Path $NotifyDir | Out-Null
    $dir = $NotifyDir
    $notificationHosts = Get-NotificationHostCandidates
    $soundsDir = Join-Path $ProjectDir "sounds"
    $script:WatcherJob = Start-Job -ScriptBlock {
        param($NotifyDir, $NotificationHosts, $SoundsDir)
        $logPath = Join-Path $NotifyDir "watcher.log"
        # Truncate log on startup to prevent unbounded growth
        if (Test-Path $logPath) {
            try { Set-Content -Path $logPath -Value $null -ErrorAction SilentlyContinue } catch {}
        }
        while ($true) {
            Get-ChildItem -Path $NotifyDir -Filter "notify-*.json" -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $data = Get-Content $_.FullName -Raw | ConvertFrom-Json
                    $sessionName = if ($data.session_name) { [string]$data.session_name } else { $null }
                    $responsePreview = if ($data.response_preview) { [string]$data.response_preview } else { $null }
                    $title = if ($sessionName) { $sessionName } elseif ($data.title) { [string]$data.title } else { "Hermes Gate" }
                    $msg = if ($responsePreview) { $responsePreview } elseif ($data.message) { [string]$data.message } else { "Notification received." }

                    # Visible notifications run in a separate PowerShell process so toast/UI
                    # APIs execute in a normal user-session context instead of the background job.
                    $escapedTitle = $title.Replace("'", "''")
                    $escapedMsg = $msg.Replace("'", "''")
                    $escapedLogPath = $logPath.Replace("'", "''")
                    $soundName = if ($data.sound) { [string]$data.sound } else { $null }
                    $notifyCommand = @"
`$ErrorActionPreference = 'Stop'
`$logPath = '$escapedLogPath'
function Write-NotifyLog([string]`$entry) {
    Add-Content -Path `$logPath -Value ((Get-Date -Format s) + ' ' + `$entry)
}
try {
    if (-not (Get-Module -ListAvailable -Name BurntToast -ErrorAction SilentlyContinue)) {
        throw 'BurntToast module not available'
    }
    Import-Module BurntToast -ErrorAction Stop
    New-BurntToastNotification -Text '$escapedTitle', '$escapedMsg' 2>`$null | Out-Null
    Write-NotifyLog 'Toast notification sent successfully'
    exit 0
}
catch {
    Write-NotifyLog ('Notification host failed: ' + `$_)
    exit 1
}
"@
                    $encodedNotifyCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($notifyCommand))

                    $toastShown = $false
                    foreach ($notificationHost in $NotificationHosts) {
                        try {
                            $process = Start-Process $notificationHost -ArgumentList @(
                                '-NoProfile',
                                '-WindowStyle', 'Hidden',
                                '-EncodedCommand',
                                $encodedNotifyCommand
                            ) -WindowStyle Hidden -PassThru
                            if (-not $process.WaitForExit(5000)) {
                                try {
                                    $process.Kill()
                                }
                                catch {}
                                Add-Content -Path $logPath -Value ((Get-Date -Format s) + ' Notification host timed out: ' + $notificationHost)
                                continue
                            }
                            if ($null -ne $process.ExitCode -and $process.ExitCode -eq 0) {
                                $toastShown = $true
                                break
                            }
                        }
                        catch {
                            Add-Content -Path $logPath -Value ((Get-Date -Format s) + ' Notification host failed: ' + $_)
                        }
                    }

                    if (-not $toastShown) {
                        Add-Content -Path $logPath -Value ((Get-Date -Format s) + ' No notification host succeeded, skipping visual notification')
                    }

                    # Play custom sound if available
                    if ($soundName) {
                        $soundPath = Join-Path $SoundsDir $soundName
                        if (Test-Path $soundPath) {
                            try {
                                $player = New-Object System.Media.SoundPlayer $soundPath
                                $player.Play()
                            }
                            catch {
                                Add-Content -Path $logPath -Value ((Get-Date -Format s) + ' Sound playback failed: ' + $_)
                            }
                        }
                    }
                } catch {
                    Add-Content -Path $logPath -Value ((Get-Date -Format s) + ' Watcher processing failed: ' + $_)
                }
                Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
        }
    } -ArgumentList $dir, $notificationHosts, $soundsDir
}

function Stop-NotifyWatcher {
    if ($script:WatcherJob) {
        Stop-Job $script:WatcherJob -ErrorAction SilentlyContinue
        Remove-Job $script:WatcherJob -Force -ErrorAction SilentlyContinue
        $script:WatcherJob = $null
    }
}

function Launch-Tui([string]$Name) {
    Write-Host "Launching TUI..."
    Start-NotifyWatcher
    try {
        Invoke-Tui $Name
    }
    finally {
        Stop-NotifyWatcher
        Stop-IfIdle $Name
    }
}

Set-Location $ProjectDir

Assert-Command -Name docker -Message "Error: Docker not found. Please install Docker Desktop for Windows."
Assert-DockerCompose
Assert-DockerDaemon
Assert-SshDirectory

if ($Command -eq "update") {
    Assert-Command -Name git -Message "Error: git not found. Please install Git before using '.\run.ps1 update'."
}

if ($Command -eq "stop") {
    Write-Host "Stopping $ContainerName..."
    docker compose @ComposeArgs down 2>$null
    if ($LASTEXITCODE -ne 0) {
        docker stop $ContainerName 2>$null | Out-Null
    }
    Write-Host "Stopped."
    exit 0
}

if ($Command -eq "update") {
    Write-Host "Pulling latest changes..."
    git pull
    $Command = "rebuild"
}

if ($Command -eq "rebuild") {
    Write-Host "Force rebuilding..."
    docker compose @ComposeArgs down --rmi local 2>$null | Out-Null
    docker compose @ComposeArgs up -d --build
    Write-Host "Build complete, launching TUI..."
    Launch-Tui $ContainerName
    exit 0
}

$running = docker inspect -f '{{.State.Running}}' $ContainerName 2>$null
if ($running -ne "true") {
    $exists = docker inspect -f '{{.Id}}' $ContainerName 2>$null

    if ($LASTEXITCODE -eq 0 -and $exists) {
        Write-Host "Container exists (stopped), starting..."
        docker start $ContainerName | Out-Null
    }
    else {
        $hasImage = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -match "hermes" }
        if ($hasImage) {
            Write-Host "Image found, starting container..."
            docker compose @ComposeArgs up -d
        }
        else {
            Write-Host "No image found, building for the first time..."
            docker compose @ComposeArgs up -d --build
        }
    }
    Write-Host "Container started, launching TUI..."
}

Launch-Tui $ContainerName
