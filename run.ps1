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

function Write-Utf8NoBomFile([string]$Path, [string]$Content) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

# ---------------------------------------------------------------------------
# Docker Compose on Windows cannot mount /etc/hosts (Linux/macOS only).
# Generate a Windows-specific compose file deterministically on each run.
# ---------------------------------------------------------------------------
function Get-ComposeFile {
    $winCompose = Join-Path $ProjectDir "docker-compose.win.yml"
    $composeContent = @"
services:
  hermes-gate:
    build: .
    container_name: hermes-gate
    volumes:
      - `${HOME}/.ssh:/host/.ssh:ro
      - ./hermes_gate:/app/hermes_gate
    stdin_open: true
    tty: true
    restart: unless-stopped
"@
    Write-Utf8NoBomFile -Path $winCompose -Content $composeContent
    return $winCompose
}

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
    $remaining = docker exec $Name sh -lc "pgrep -fc 'python -m hermes_gate'" 2>$null
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

function Launch-Tui([string]$Name) {
    Write-Host "Launching TUI..."
    try {
        Invoke-Tui $Name
    }
    finally {
        Stop-IfIdle $Name
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Set-Location $ProjectDir

Assert-Command -Name docker -Message "Error: Docker not found. Please install Docker Desktop for Windows."
Assert-DockerCompose
Assert-DockerDaemon
Assert-SshDirectory

if ($Command -eq "update") {
    Assert-Command -Name git -Message "Error: git not found. Please install Git before using '.\run.ps1 update'."
}

$ComposeFile = Get-ComposeFile
$ComposeArgs = @("-f", $ComposeFile)

if ($Command -eq "stop") {
    Write-Host "Stopping $ContainerName..."
    docker compose @ComposeArgs down 2>$null
    if ($LASTEXITCODE -ne 0) {
        docker stop $ContainerName 2>$null | Out-Null
    }
    Write-Host "Stopped."
    exit 0
}

# --- update ---
if ($Command -eq "update") {
    Write-Host "Pulling latest changes..."
    git pull
    $Command = "rebuild"
}

# --- rebuild ---
if ($Command -eq "rebuild") {
    Write-Host "Force rebuilding..."
    docker compose @ComposeArgs down 2>$null | Out-Null
    docker compose @ComposeArgs up -d --build
    Write-Host "Build complete."
    Launch-Tui $ContainerName
    exit 0
}

# --- default: smart start ---
$running = docker inspect -f '{{.State.Running}}' $ContainerName 2>$null
if ($running -eq "true") {
    Write-Host "Container already running."
    Launch-Tui $ContainerName
    exit 0
}

if (Test-ContainerExists $ContainerName) {
    Write-Host "Container exists (stopped), starting..."
    docker start $ContainerName | Out-Null
    Write-Host "Started."
    Launch-Tui $ContainerName
    exit 0
}

$hasImage = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -match "hermes" }
if ($hasImage) {
    Write-Host "Image found, starting container (skip build)..."
    docker compose @ComposeArgs up -d
    Write-Host "Started."
    Launch-Tui $ContainerName
    exit 0
}

Write-Host "No image found, building for the first time..."
docker compose @ComposeArgs up -d --build
Write-Host "Build complete."
Launch-Tui $ContainerName
