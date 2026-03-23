#Requires -Version 5.1
<#
.SYNOPSIS
    Jarvis by ImproveYourSite — Windows Setup Script
.DESCRIPTION
    Installs all dependencies and launches the Jarvis setup wizard.
    Requires Windows 10 / 11 and an internet connection.
    Must be run as Administrator.
.VERSION
    1.0.0
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Colour helpers ───────────────────────────────────────────────
function Write-Ok   { param([string]$msg) Write-Host "  $([char]0x221A) $msg" -ForegroundColor Green }
function Write-Err  { param([string]$msg) Write-Host "  X $msg" -ForegroundColor Red }
function Write-Info { param([string]$msg) Write-Host "  -> $msg" -ForegroundColor Yellow }
function Write-Head { param([string]$msg) Write-Host "`n$msg" -ForegroundColor Cyan }
function Write-Rule { Write-Host ("  " + ("-" * 56)) -ForegroundColor Cyan }

# ── Re-launch as Administrator if needed ──────────────────────────
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "`n  Jarvis Setup requires Administrator privileges." -ForegroundColor Yellow
    Write-Host "  Re-launching with elevated permissions...`n" -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    exit
}

# ── Banner ───────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗" -ForegroundColor Cyan
Write-Host "     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝" -ForegroundColor Cyan
Write-Host "     ██║███████║██████╔╝██║   ██║██║███████╗" -ForegroundColor Cyan
Write-Host "██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║" -ForegroundColor Cyan
Write-Host "╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║" -ForegroundColor Cyan
Write-Host " ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "           by ImproveYourSite.com" -ForegroundColor White
Write-Host ""
Write-Rule
Write-Host "  AI Staff in a Box — Windows Installer" -ForegroundColor White
Write-Rule
Write-Host ""
Write-Host "  This installer will:"
Write-Host "    1. Install required software (Chocolatey, Node, Python)"
Write-Host "    2. Install Jarvis components"
Write-Host "    3. Copy your agent stack to C:\Jarvis\"
Write-Host "    4. Launch the setup wizard in your browser"
Write-Host ""
Write-Rule
Write-Host ""
Read-Host "  Press ENTER to begin, or close this window to cancel"
Write-Host ""

# ── Chocolatey ───────────────────────────────────────────────────
Write-Head "[ 1 / 8 ]  Checking Chocolatey..."

$chocoCmd = Get-Command choco -ErrorAction SilentlyContinue
if ($chocoCmd) {
    Write-Ok "Chocolatey already installed ($((choco --version).Trim()))"
} else {
    Write-Info "Installing Chocolatey..."
    try {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        # Refresh environment so choco is available
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
        Write-Ok "Chocolatey installed"
    } catch {
        Write-Err "Failed to install Chocolatey: $_"
        exit 1
    }
}

# ── Chocolatey Packages ──────────────────────────────────────────
Write-Head "[ 2 / 8 ]  Installing system packages..."

function Install-ChocoPackage {
    param([string]$PackageName, [string]$DisplayName = "")
    if (-not $DisplayName) { $DisplayName = $PackageName }
    $installed = choco list --local-only --exact $PackageName 2>$null | Select-String $PackageName
    if ($installed) {
        Write-Ok "$DisplayName already installed"
    } else {
        Write-Info "Installing $DisplayName..."
        $result = choco install $PackageName -y --no-progress 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "$DisplayName installed"
        } else {
            Write-Err "Failed to install $DisplayName"
            exit 1
        }
    }
}

Install-ChocoPackage "nodejs"   "Node.js"
Install-ChocoPackage "python3"  "Python 3"

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

# ── OpenClaw ─────────────────────────────────────────────────────
Write-Head "[ 3 / 8 ]  Installing OpenClaw..."

$openclawInstalled = npm list -g openclaw --depth=0 2>$null | Select-String "openclaw"
if ($openclawInstalled) {
    Write-Ok "openclaw already installed"
} else {
    Write-Info "Installing openclaw via npm..."
    npm install -g openclaw 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "openclaw installed"
    } else {
        Write-Err "Failed to install openclaw"
        exit 1
    }
}

# ── Python Packages ──────────────────────────────────────────────
Write-Head "[ 4 / 8 ]  Installing Python packages..."

$pythonPkgs = @("anthropic", "apscheduler", "fastapi", "uvicorn", "python-dotenv", "requests")
foreach ($pkg in $pythonPkgs) {
    Write-Info "Installing $pkg..."
    pip install --quiet $pkg 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$pkg installed"
    } else {
        Write-Err "Failed to install Python package: $pkg"
        exit 1
    }
}

# ── Workspace ────────────────────────────────────────────────────
Write-Head "[ 5 / 8 ]  Creating workspace..."

$workspace = "C:\Jarvis"

if (Test-Path $workspace) {
    Write-Ok "Workspace already exists at $workspace"
} else {
    New-Item -ItemType Directory -Path $workspace -Force | Out-Null
    Write-Ok "Created $workspace"
}

# Copy agent stack from USB
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentStackSrc = Join-Path $scriptDir "agent-stack"

if (Test-Path $agentStackSrc) {
    Write-Info "Copying agent stack to workspace..."
    Copy-Item -Path "$agentStackSrc\*" -Destination $workspace -Recurse -Force
    Write-Ok "Agent stack copied"
} else {
    Write-Info "No agent-stack directory found on USB — skipping copy"
}

# Create subdirectories
@("builder", "logs", "data") | ForEach-Object {
    New-Item -ItemType Directory -Path (Join-Path $workspace $_) -Force | Out-Null
}
Write-Ok "Workspace directories ready"

# ── Setup Wizard ─────────────────────────────────────────────────
Write-Head "[ 6 / 8 ]  Launching setup wizard..."

$wizardDir = Join-Path $scriptDir "setup-wizard"
$wizardServer = Join-Path $wizardDir "server.py"

if (-not (Test-Path $wizardServer)) {
    Write-Err "Setup wizard not found at $wizardServer"
    exit 1
}

Write-Info "Starting wizard server on http://localhost:9999 ..."
$wizardProcess = Start-Process python -ArgumentList "`"$wizardServer`"" -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 2

# Open browser
Start-Process "http://localhost:9999"
Write-Ok "Browser opened"

Write-Host ""
Write-Rule
Write-Host "  Complete the setup wizard in your browser." -ForegroundColor White
Write-Host "  When you are done, come back here."
Write-Rule
Write-Host ""
Write-Info "Waiting for wizard to complete..."

# Wait for completion flag
$completeFlag = Join-Path $workspace ".setup-complete"
$timeout = 600
$elapsed = 0

while (-not (Test-Path $completeFlag)) {
    Start-Sleep -Seconds 2
    $elapsed += 2
    if ($elapsed -ge $timeout) {
        Write-Err "Timed out waiting for setup wizard. Re-run this script to try again."
        Stop-Process -Id $wizardProcess.Id -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

Stop-Process -Id $wizardProcess.Id -Force -ErrorAction SilentlyContinue
Write-Ok "Setup wizard complete"

# ── Scheduled Task ───────────────────────────────────────────────
Write-Head "[ 7 / 8 ]  Installing startup service..."

$openclawPath = (Get-Command openclaw -ErrorAction SilentlyContinue)?.Source
if (-not $openclawPath) {
    $openclawPath = "openclaw"
}

$openclawConfig = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"

$taskName = "JarvisAI"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute $openclawPath `
    -Argument "start --config `"$openclawConfig`"" `
    -WorkingDirectory $workspace

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Jarvis AI Assistant by ImproveYourSite" | Out-Null

# Start it now
Start-ScheduledTask -TaskName $taskName
Write-Ok "Jarvis startup task installed and running"

# ── Done ─────────────────────────────────────────────────────────
Write-Head "[ 8 / 8 ]  Opening dashboard..."
Start-Sleep -Seconds 2
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host ("  " + ("=" * 56)) -ForegroundColor Cyan
Write-Host ""
Write-Host "   Jarvis is live." -ForegroundColor Green
Write-Host ""
Write-Host "   Your AI assistant is running in the background."
Write-Host "   Dashboard: http://localhost:8080"
Write-Host ""
Write-Host "   Jarvis starts automatically every time you log in."
Write-Host ""
Write-Host ("  " + ("=" * 56)) -ForegroundColor Cyan
Write-Host ""
Write-Host "   Need help? Visit https://improveyoursite.com/jarvis"
Write-Host ""

Read-Host "  Press ENTER to close this window"
