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

function Launch-Tui([string]$Name) {
    try {
        Invoke-Tui $Name
    }
    finally {
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
