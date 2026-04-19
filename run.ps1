#Requires -Version 5.1
<#
.SYNOPSIS
    Start the Hermes Gate TUI on Windows.

.EXAMPLE
    .\run.ps1
    .\run.ps1 rebuild
    .\run.ps1 update
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("rebuild", "update")]
    [string]$Command
)

$ErrorActionPreference = "Stop"
$ContainerName = "hermes-gate"
$ProjectDir = $PSScriptRoot

# ---------------------------------------------------------------------------
# Docker Compose on Windows cannot mount /etc/hosts (Linux/macOS only).
# We generate a standalone compose file that skips that mount.
# ---------------------------------------------------------------------------
function Get-ComposeFile {
    $winCompose = Join-Path $ProjectDir "docker-compose.win.yml"
    if (-not (Test-Path $winCompose)) {
        @"
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
"@ | Set-Content -Path $winCompose -Encoding UTF8NoBOM
        Write-Host "Created docker-compose.win.yml for Windows."
    }
    return $winCompose
}

# ---------------------------------------------------------------------------
# Attach to container with cleanup on Ctrl+C
# ---------------------------------------------------------------------------
function Attach-Container([string]$Name) {
    Write-Host ""
    Write-Host "Attaching to $Name... (Press Ctrl+C to detach)"
    Write-Host ""
    try {
        docker attach $Name
    } finally {
        Write-Host ""
        Write-Host "Stopping container $Name..."
        docker stop $Name 2>$null | Out-Null
        Write-Host "Stopped."
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Set-Location $ProjectDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker not found. Please install Docker Desktop for Windows." -ForegroundColor Red
    exit 1
}

$ComposeFile = Get-ComposeFile
$ComposeArgs = @("-f", $ComposeFile)

# --- update ---
if ($Command -eq "update") {
    Write-Host "Pulling latest changes..."
    git pull
    $Command = "rebuild"
}

# --- rebuild ---
if ($Command -eq "rebuild") {
    Write-Host "Force rebuilding..."
    docker compose @ComposeArgs down 2>$null
    docker compose @ComposeArgs up -d --build
    Write-Host "Build complete, attaching..."
    Attach-Container $ContainerName
    exit 0
}

# --- default: smart start ---

$running = docker inspect -f '{{.State.Running}}' $ContainerName 2>$null
if ($running -eq "true") {
    Write-Host "Container already running, attaching..."
    Attach-Container $ContainerName
    exit 0
}

$exists = docker inspect -f '{{.Id}}' $ContainerName 2>$null
if ($exists) {
    Write-Host "Container exists (stopped), starting..."
    docker start $ContainerName | Out-Null
    Write-Host "Started, attaching..."
    Attach-Container $ContainerName
    exit 0
}

$hasImage = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -match "hermes" }
if ($hasImage) {
    Write-Host "Image found, starting container (skip build)..."
    docker compose @ComposeArgs up -d
    Write-Host "Started, attaching..."
    Attach-Container $ContainerName
    exit 0
}

Write-Host "No image found, building for the first time..."
docker compose @ComposeArgs up -d --build
Write-Host "Build complete, attaching..."
Attach-Container $ContainerName
