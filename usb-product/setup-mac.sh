#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────
#  Jarvis by ImproveYourSite — macOS Setup Script
#  Version 1.0.0
# ──────────────────────────────────────────────────────────────

# Colour codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓ ${1}${RESET}"; }
err()  { echo -e "${RED}  ✗ ${1}${RESET}"; }
info() { echo -e "${YELLOW}  → ${1}${RESET}"; }
head() { echo -e "${CYAN}${BOLD}${1}${RESET}"; }

# ── Banner ──────────────────────────────────────────────────────
clear
echo ""
echo -e "${CYAN}${BOLD}"
echo "     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗"
echo "     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝"
echo "     ██║███████║██████╔╝██║   ██║██║███████╗"
echo "██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║"
echo "╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║"
echo " ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝"
echo ""
echo -e "${RESET}${BOLD}           by ImproveYourSite.com${RESET}"
echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────${RESET}"
echo -e "${BOLD}  AI Staff in a Box — macOS Installer${RESET}"
echo -e "${CYAN}────────────────────────────────────────────────────────${RESET}"
echo ""
echo "  This installer will:"
echo "    1. Install required software (Homebrew, Node, Python)"
echo "    2. Install Jarvis components"
echo "    3. Copy your agent stack to ~/jarvis-workspace/"
echo "    4. Launch the setup wizard in your browser"
echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────${RESET}"
echo ""
read -r -p "  Press ENTER to begin, or Ctrl+C to cancel... " _
echo ""

# ── Architecture Detection ───────────────────────────────────────
head "[ 1 / 8 ]  Detecting system..."
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    ok "Apple Silicon (arm64) detected"
    BREW_PREFIX="/opt/homebrew"
elif [[ "$ARCH" == "x86_64" ]]; then
    ok "Intel (x86_64) detected"
    BREW_PREFIX="/usr/local"
else
    err "Unknown architecture: $ARCH"
    exit 1
fi

# macOS version
MACOS_VERSION=$(sw_vers -productVersion)
ok "macOS $MACOS_VERSION"
echo ""

# ── Homebrew ─────────────────────────────────────────────────────
head "[ 2 / 8 ]  Checking Homebrew..."
if command -v brew &>/dev/null; then
    ok "Homebrew already installed ($(brew --version | head -1))"
else
    info "Installing Homebrew — you may be prompted for your password..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this session
    eval "$("${BREW_PREFIX}/bin/brew" shellenv)"
    ok "Homebrew installed"
fi

# Ensure brew is on PATH
eval "$("${BREW_PREFIX}/bin/brew" shellenv)" 2>/dev/null || true
echo ""

# ── Brew Packages ─────────────────────────────────────────────────
head "[ 3 / 8 ]  Installing system packages..."

install_brew_pkg() {
    local pkg="$1"
    if brew list "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        info "Installing $pkg..."
        if brew install "$pkg" &>/dev/null; then
            ok "$pkg installed"
        else
            err "Failed to install $pkg"
            exit 1
        fi
    fi
}

install_brew_pkg node
install_brew_pkg python3
install_brew_pkg cloudflared
echo ""

# ── OpenClaw ──────────────────────────────────────────────────────
head "[ 4 / 8 ]  Installing OpenClaw..."
if brew list openclaw-cli &>/dev/null; then
    ok "openclaw-cli already installed"
else
    info "Installing openclaw-cli..."
    if brew install openclaw-cli 2>/dev/null; then
        ok "openclaw-cli installed"
    else
        err "Could not install openclaw-cli — check your internet connection and try again"
        exit 1
    fi
fi
echo ""

# ── Python Packages ───────────────────────────────────────────────
head "[ 5 / 8 ]  Installing Python packages..."
PYTHON_PKGS=(
    "anthropic"
    "apscheduler"
    "fastapi"
    "uvicorn"
    "python-dotenv"
    "requests"
)

for pkg in "${PYTHON_PKGS[@]}"; do
    info "Installing $pkg..."
    if pip3 install --quiet "$pkg"; then
        ok "$pkg installed"
    else
        err "Failed to install Python package: $pkg"
        exit 1
    fi
done
echo ""

# ── Workspace ─────────────────────────────────────────────────────
head "[ 6 / 8 ]  Creating workspace..."
WORKSPACE="$HOME/jarvis-workspace"

if [[ -d "$WORKSPACE" ]]; then
    ok "Workspace already exists at $WORKSPACE"
else
    mkdir -p "$WORKSPACE"
    ok "Created $WORKSPACE"
fi

# Copy agent stack from USB
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_STACK_SRC="$SCRIPT_DIR/agent-stack"

if [[ -d "$AGENT_STACK_SRC" ]]; then
    info "Copying agent stack to workspace..."
    cp -r "$AGENT_STACK_SRC/." "$WORKSPACE/"
    ok "Agent stack copied"
else
    info "No agent-stack directory found on USB — skipping copy"
fi

# Create subdirectories Jarvis expects
mkdir -p "$WORKSPACE/builder"
mkdir -p "$WORKSPACE/logs"
mkdir -p "$WORKSPACE/data"
ok "Workspace directories ready"
echo ""

# ── Setup Wizard ──────────────────────────────────────────────────
head "[ 7 / 8 ]  Launching setup wizard..."
WIZARD_DIR="$SCRIPT_DIR/setup-wizard"

if [[ ! -f "$WIZARD_DIR/server.py" ]]; then
    err "Setup wizard not found at $WIZARD_DIR/server.py"
    exit 1
fi

info "Starting wizard server on http://localhost:9999 ..."
# Launch server in background
python3 "$WIZARD_DIR/server.py" &
WIZARD_PID=$!

# Give the server a moment to start
sleep 1

# Open browser
if open "http://localhost:9999" 2>/dev/null; then
    ok "Browser opened"
else
    info "Open your browser and go to: http://localhost:9999"
fi

echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────${RESET}"
echo -e "  ${BOLD}Complete the setup wizard in your browser.${RESET}"
echo -e "  When you're done, come back here."
echo -e "${CYAN}────────────────────────────────────────────────────────${RESET}"
echo ""

# Wait for wizard to signal completion
info "Waiting for wizard to complete..."
COMPLETE_FLAG="$WORKSPACE/.setup-complete"
TIMEOUT=600  # 10 minutes
ELAPSED=0

while [[ ! -f "$COMPLETE_FLAG" ]]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        err "Timed out waiting for setup wizard. Re-run this script to try again."
        kill "$WIZARD_PID" 2>/dev/null || true
        exit 1
    fi
done

# Stop wizard server
kill "$WIZARD_PID" 2>/dev/null || true
ok "Setup wizard complete"
echo ""

# ── LaunchAgent ───────────────────────────────────────────────────
head "[ 8 / 8 ]  Installing background service..."
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.improveyoursite.jarvis.plist"
mkdir -p "$LAUNCH_AGENTS_DIR"

# Determine openclaw path
OPENCLAW_BIN=$(command -v openclaw 2>/dev/null || echo "${BREW_PREFIX}/bin/openclaw")

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.improveyoursite.jarvis</string>
    <key>ProgramArguments</key>
    <array>
        <string>${OPENCLAW_BIN}</string>
        <string>start</string>
        <string>--config</string>
        <string>${HOME}/.openclaw/openclaw.json</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${WORKSPACE}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${WORKSPACE}/logs/openclaw.log</string>
    <key>StandardErrorPath</key>
    <string>${WORKSPACE}/logs/openclaw-error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${BREW_PREFIX}/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

# Load the LaunchAgent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"
ok "Jarvis background service installed and started"

# Open dashboard
sleep 2
open "http://localhost:8080" 2>/dev/null || true

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}"
echo "   Jarvis is live."
echo ""
echo -e "${RESET}   Your AI assistant is running in the background."
echo "   Dashboard: http://localhost:8080"
echo ""
echo "   Jarvis starts automatically every time you log in."
echo -e "${CYAN}════════════════════════════════════════════════════════${RESET}"
echo ""
echo "   Need help? Visit https://improveyoursite.com/jarvis"
echo ""
