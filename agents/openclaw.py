"""
agents/openclaw.py — OpenClaw Escalation Engine

When agents hit hard problems they can't solve programmatically, they escalate
to OpenClaw which invokes Claude Code (or the Anthropic API) to complete the task.

Two modes:
  escalate_sync()  — blocks until Claude finishes, returns the result
  escalate_async() — queues in background thread, returns escalation ID

Usage in any agent:
    # Quick: blocks the agent until solved (good for short tasks <60s)
    result = self.escalate_to_openclaw(
        "Find the contact email for Burke's Bakery, 123 Main St Bathurst NSW",
        context={"business_name": "Burke's Bakery", "city": "Bathurst"},
        task_id=tid,
    )
    if result["success"]:
        email = result["output"]

    # Fire-and-forget: agent continues, Claude works in background
    esc_id = self.escalate_to_openclaw(
        "Scrape all blog post URLs from improveyoursite.com",
        context={"url": "https://improveyoursite.com"},
        sync=False,
    )
    # Later, check: db.escalation_get(esc_id)

Claude Code CLI invocation:
    claude -p "<prompt>" --output-format text --no-confirm
    Runs non-interactively in the project workspace.
    Falls back to direct Anthropic API (claude-opus-4-6) if CLI isn't available.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent
CLAUDE_BIN   = os.environ.get("CLAUDE_BIN", "claude")
DEFAULT_TIMEOUT = 180  # seconds


# ── Claude Code CLI ────────────────────────────────────────────────────────────

def _run_claude_cli(
    prompt: str,
    allowed_tools: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Invoke Claude Code CLI in non-interactive mode."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "text",
           "--permission-mode", "bypassPermissions"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=timeout,
        )
        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout.strip(),
                "source": "claude_cli",
            }
        err = (result.stderr or "").strip() or f"Exit code {result.returncode}"
        return {"success": False, "error": err, "source": "claude_cli"}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timed out after {timeout}s", "source": "claude_cli"}
    except FileNotFoundError:
        return {"success": False, "error": "claude CLI not found on PATH", "source": "claude_cli"}
    except Exception as exc:
        return {"success": False, "error": str(exc), "source": "claude_cli"}


# ── Anthropic API fallback ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are OpenClaw, an autonomous problem-solver built into the ImproveYourSite.com agent system.

Agents escalate hard problems to you — tasks they cannot complete programmatically.
Your job: solve the problem completely and return a clean, actionable result.

This system runs on a Mac Mini in an Australian web agency. You have access to:
- The full project workspace at {root}
- All Python dependencies installed in the project
- The internet (for research and verification)

Guidelines:
- Be thorough but concise in your response
- Return structured data (JSON) when the agent needs to parse your output
- If you can't fully solve the problem, explain exactly why and what the next step is
- Prioritise practical outcomes over perfect solutions"""


def _run_anthropic_api(
    prompt: str,
    context: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Fall back to direct Anthropic API if Claude CLI isn't available."""
    try:
        import anthropic
    except ImportError:
        return {"success": False, "error": "anthropic package not installed", "source": "anthropic_api"}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY not set in .env", "source": "anthropic_api"}

    system = _SYSTEM_PROMPT.format(root=PROJECT_ROOT)
    if context:
        system += f"\n\nAgent context:\n{json.dumps(context, indent=2, default=str)}"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        text   = next((b.text for b in msg.content if b.type == "text"), "")
        tokens = msg.usage.input_tokens + msg.usage.output_tokens
        return {
            "success": True,
            "output": text,
            "tokens": tokens,
            "model": "claude-opus-4-6",
            "source": "anthropic_api",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "source": "anthropic_api"}


# ── Core escalation functions ──────────────────────────────────────────────────

def _execute(
    esc_id: int,
    prompt: str,
    context: Optional[dict],
    timeout: int,
    allowed_tools: list[str] | None,
):
    """Run the escalation — tries CLI first, falls back to API."""
    db.escalation_set_status(esc_id, "running")
    result = _run_claude_cli(prompt, allowed_tools=allowed_tools, timeout=timeout)

    if not result["success"] and "not found on PATH" in result.get("error", ""):
        # Claude CLI not installed — use Anthropic API directly
        result = _run_anthropic_api(prompt, context, timeout=timeout)

    tokens    = result.get("tokens", 0)
    model     = result.get("model", result.get("source", "unknown"))

    if result["success"]:
        db.escalation_resolve(esc_id, result["output"], tokens_used=tokens, model_used=model)
    else:
        db.escalation_fail(esc_id, result.get("error", "Unknown error"))

    return result


def escalate_sync(
    agent_id: str,
    prompt: str,
    context: Optional[dict] = None,
    task_id: Optional[int] = None,
    priority: str = "normal",
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: list[str] | None = None,
) -> dict:
    """
    Escalate to OpenClaw synchronously (blocks the calling agent).
    Returns: {"success": bool, "output": str, "esc_id": int, ...}
    """
    esc_id = db.escalation_create(agent_id, prompt, context or {}, task_id, priority)
    result = _execute(esc_id, prompt, context, timeout, allowed_tools)
    result["esc_id"] = esc_id
    return result


def escalate_async(
    agent_id: str,
    prompt: str,
    context: Optional[dict] = None,
    task_id: Optional[int] = None,
    priority: str = "normal",
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: list[str] | None = None,
) -> int:
    """
    Submit escalation to a background thread. Returns escalation ID immediately.
    Poll result later with: db.escalation_get(esc_id)
    """
    esc_id = db.escalation_create(agent_id, prompt, context or {}, task_id, priority)

    def _run():
        _execute(esc_id, prompt, context, timeout, allowed_tools)

    threading.Thread(target=_run, daemon=True, name=f"openclaw-esc-{esc_id}").start()
    return esc_id


# ── Manual trigger (called from dashboard "Run" button) ───────────────────────

def run_manual(prompt: str, agent_id: str = "manual", timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Kick off a manual escalation from the dashboard. Returns result synchronously."""
    return escalate_sync(
        agent_id=agent_id,
        prompt=prompt,
        priority="high",
        timeout=timeout,
    )
