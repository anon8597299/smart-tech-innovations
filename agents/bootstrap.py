"""
agents/bootstrap.py — Self-Install Bootstrap System

Called once at startup. Ensures all agent dependencies are installed.
Each agent declares its required packages. This file installs anything missing
so agents never fail due to missing libraries.

Also handles:
  - Node/npm tool installs (n8n, playwright)
  - Playwright browser install (Chromium for headless Chrome tasks)
  - MCP server registration stubs
  - Environment variable validation + guidance

Run: python agents/bootstrap.py
Or auto-called from run.py on startup.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent
BUILDER_DIR  = PROJECT_ROOT / "builder"

# ── Python package requirements per agent ─────────────────────────────────────

AGENT_PACKAGES = {
    "core": [
        "fastapi",
        "uvicorn[standard]",
        "apscheduler",
        "python-dotenv",
        "anthropic",
        "requests",
    ],
    "instagram": [
        "anthropic",
        "pillow",         # image manipulation for story overlays
    ],
    "stripe_monitor": [
        "stripe",         # official Stripe SDK
    ],
    "seo_monitor": [
        "google-auth",
        "google-auth-oauthlib",
        "google-auth-httplib2",
    ],
    "inbox": [
        "anthropic",
    ],
    "social_intel": [
        "anthropic",
    ],
    "browser_tools": [
        "playwright",     # headless Chrome for web scraping / screenshots
        "beautifulsoup4",
        "lxml",
    ],
    "builder": [
        "jinja2",
        "pygithub",
    ],
    "leads": [
        "anthropic",
        "beautifulsoup4",
        "lxml",
    ],
}

# ── npm / Node tools ──────────────────────────────────────────────────────────

NODE_TOOLS = [
    # Uncomment to auto-install n8n locally (heavy — only if needed)
    # "n8n",
]

# ── MCP servers (Claude Code MCP stubs) ──────────────────────────────────────

MCP_STUBS = {
    # "n8n": "npx @n8n/mcp-server",
    # "playwright": "npx @playwright/mcp",
}


def run(verbose: bool = True):
    """Main entry point. Install everything missing."""
    _log("Bootstrap: checking agent dependencies...", verbose)

    # 1. Python packages
    missing_py = _check_python_packages()
    if missing_py:
        _log(f"Bootstrap: installing {len(missing_py)} Python package(s): {', '.join(missing_py)}", verbose)
        _install_python_packages(missing_py)
    else:
        _log("Bootstrap: all Python packages present", verbose)

    # 2. Playwright browsers
    if _has_package("playwright"):
        _install_playwright_browser(verbose)

    # 3. Node tools
    for tool in NODE_TOOLS:
        _install_node_tool(tool, verbose)

    # 4. Create required directories
    _ensure_dirs(verbose)

    # 5. Validate .env
    _validate_env(verbose)

    # 6. Chrome / Playwright path
    _check_chrome(verbose)

    _log("Bootstrap: complete", verbose)


def _check_python_packages() -> list[str]:
    """Return list of packages that are not importable."""
    all_packages = set()
    for pkgs in AGENT_PACKAGES.values():
        all_packages.update(pkgs)

    missing = []
    for pkg in all_packages:
        # Normalise package name to importable name
        import_name = _pkg_to_import(pkg)
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    return missing


def _pkg_to_import(pkg: str) -> str:
    """Map pip package name to Python import name."""
    mapping = {
        "python-dotenv":        "dotenv",
        "uvicorn[standard]":    "uvicorn",
        "google-auth":          "google.auth",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "google-auth-httplib2": "google_auth_httplib2",
        "beautifulsoup4":       "bs4",
        "pygithub":             "github",
        "pillow":               "PIL",
    }
    base = pkg.split("[")[0].lower()
    return mapping.get(base, base.replace("-", "_"))


def _install_python_packages(packages: list[str]):
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + packages,
            cwd=str(PROJECT_ROOT),
        )
        print(f"Bootstrap: ✓ installed {len(packages)} package(s)")
    except subprocess.CalledProcessError as exc:
        print(f"Bootstrap: ✗ pip install failed: {exc}")


def _has_package(pkg: str) -> bool:
    import_name = _pkg_to_import(pkg)
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def _install_playwright_browser(verbose: bool):
    """Install Chromium for Playwright if not already installed."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            _log("Bootstrap: ✓ Playwright Chromium ready", verbose)
        else:
            _log(f"Bootstrap: ⚠ Playwright Chromium install failed: {result.stderr[:200]}", verbose)
    except Exception as exc:
        _log(f"Bootstrap: ⚠ Playwright install skipped: {exc}", verbose)


def _install_node_tool(tool: str, verbose: bool):
    try:
        result = subprocess.run(
            ["npm", "install", "-g", tool],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            _log(f"Bootstrap: ✓ npm installed {tool}", verbose)
        else:
            _log(f"Bootstrap: ⚠ npm install {tool} failed", verbose)
    except Exception as exc:
        _log(f"Bootstrap: ⚠ npm tool install skipped: {exc}", verbose)


def _ensure_dirs(verbose: bool):
    """Create all directories agents expect to exist."""
    dirs = [
        PROJECT_ROOT / "social" / "posts",
        PROJECT_ROOT / "social" / "stories",
        PROJECT_ROOT / "social" / "reels",
        PROJECT_ROOT / "customers",
        PROJECT_ROOT / "agents" / "browser_data",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    _log(f"Bootstrap: ✓ {len(dirs)} directories verified", verbose)


def _validate_env(verbose: bool):
    """Check .env for required keys and warn about missing ones."""
    env_file = BUILDER_DIR / ".env"
    if not env_file.exists():
        _log("Bootstrap: ⚠ builder/.env not found — agents will use system environment", verbose)
        return

    from dotenv import dotenv_values
    env = dotenv_values(str(env_file))

    critical = {
        "ANTHROPIC_API_KEY":   "AI content generation (required by all agents)",
        "GITHUB_PAT":          "Image hosting + site deployment",
        "GMAIL_USER":          "Email sending",
        "GMAIL_APP_PASS":      "Gmail app password",
        "HELLO_EMAIL_USER":    "Inbox monitoring",
        "HELLO_EMAIL_PASS":    "Inbox IMAP access",
        "MAKE_WEBHOOK_URL":    "Instagram carousel publishing",
        "MAKE_STORY_WEBHOOK_URL": "Instagram story publishing",
        "INSTAGRAM_ACCOUNT_ID":  "Instagram insights + publishing",
        "STRIPE_SECRET_KEY":   "Order monitoring",
        "GOOGLE_REFRESH_TOKEN": "GSC + Google Ads API",
    }

    missing = []
    for key, desc in critical.items():
        if not env.get(key):
            missing.append(f"  ✗ {key:<35} — {desc}")
        else:
            _log(f"Bootstrap: ✓ {key}", verbose)

    if missing:
        _log("Bootstrap: MISSING .env variables:\n" + "\n".join(missing), verbose)
        _log("\nAdd these to builder/.env to enable full agent functionality.\n", verbose)


def _check_chrome(verbose: bool):
    """Find Chrome/Chromium path for browser-based tasks."""
    # macOS default Chrome path
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ]
    for path in chrome_paths:
        if Path(path).exists():
            os.environ.setdefault("CHROME_EXECUTABLE", path)
            _log(f"Bootstrap: ✓ Chrome found: {path}", verbose)
            return

    # Try Playwright's Chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _log("Bootstrap: ✓ Playwright Chromium available", verbose)
        os.environ.setdefault("CHROME_EXECUTABLE", "playwright")
    except Exception:
        _log("Bootstrap: ⚠ No Chrome found — browser tasks will fail", verbose)
        _log("  Fix: Install Chrome or run: python -m playwright install chromium", verbose)


def _log(msg: str, verbose: bool):
    if verbose:
        print(msg)


# ── Browser helper (shared by agents that need Chrome) ────────────────────────

class BrowserHelper:
    """
    Shared browser automation helper for agents that need Chrome.
    Uses Playwright under the hood.

    Usage:
        from agents.bootstrap import BrowserHelper
        with BrowserHelper() as browser:
            page = browser.new_page()
            page.goto("https://example.com")
            screenshot = page.screenshot()
    """

    def __init__(self, headless: bool = True, timeout_ms: int = 30_000):
        self.headless   = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser    = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser    = self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            return self._browser
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: python agents/bootstrap.py"
            )

    def __exit__(self, *args):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()


# ── Skill installer (agents can call this to install OpenClaw skills) ─────────

class SkillInstaller:
    """
    Allows agents to install OpenClaw skills at runtime.

    Usage:
        installer = SkillInstaller()
        installer.ensure_skill("google-ads")   # installs if not present
        installer.ensure_skill("ga4-analytics")
    """

    OPENCLAW_DIR   = Path.home() / ".openclaw"
    WORKSPACE_DIR  = OPENCLAW_DIR / "workspace"
    SKILLS_DIR     = WORKSPACE_DIR / "skills"
    OPENCLAW_BIN   = OPENCLAW_DIR / "bin" / "gog"

    def ensure_skill(self, skill_name: str) -> bool:
        """Install a skill from the OpenClaw workspace if not already present."""
        skill_dir = self.SKILLS_DIR / skill_name
        if skill_dir.exists():
            return True  # already installed
        print(f"SkillInstaller: installing skill '{skill_name}'...")
        try:
            # Try OpenClaw CLI first
            if self.OPENCLAW_BIN.exists():
                result = subprocess.run(
                    [str(self.OPENCLAW_BIN), "skill", "install", skill_name],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    print(f"SkillInstaller: ✓ installed {skill_name}")
                    return True
            print(f"SkillInstaller: ⚠ could not install {skill_name} — skill dir not found")
            return False
        except Exception as exc:
            print(f"SkillInstaller: ✗ skill install failed: {exc}")
            return False

    def list_available(self) -> list[str]:
        if not self.SKILLS_DIR.exists():
            return []
        return [d.name for d in self.SKILLS_DIR.iterdir() if d.is_dir()]


if __name__ == "__main__":
    run(verbose=True)
