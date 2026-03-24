#!/usr/bin/env python3
"""
run.py — Single entry point for the IYS Agent System.

Starts:
  1. APScheduler (background thread) — cron jobs for all agents
  2. FastAPI (uvicorn) — dashboard on port 8080

Usage:
    python3 run.py
    python3 run.py --port 8080 --host 0.0.0.0

Access:
    Local:    http://localhost:8080
    Tailscale: http://<tailscale-ip>:8080
"""

import argparse
import atexit
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on path for all imports
sys.path.insert(0, str(Path(__file__).parent))

# ── PID lock — prevent duplicate instances ──────────────────────────────────
PID_FILE = Path(__file__).parent / ".run.pid"


def _check_pid_lock():
    """Exit immediately if another instance is already running."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if that process is actually alive
            os.kill(old_pid, 0)
            # It's alive — bail out
            print(f"ERROR: run.py is already running (PID {old_pid}). Kill it first or delete {PID_FILE}")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Stale PID file — previous instance died without cleanup
            pass
        except PermissionError:
            # Process exists but we can't signal it — still running
            print(f"ERROR: run.py is already running (PID in {PID_FILE}). Kill it first.")
            sys.exit(1)

    # Write our PID
    PID_FILE.write_text(str(os.getpid()))


def _cleanup_pid():
    """Remove PID file on exit."""
    try:
        if PID_FILE.exists() and int(PID_FILE.read_text().strip()) == os.getpid():
            PID_FILE.unlink()
    except Exception:
        pass

# Load .env first, overriding any system env vars
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / "builder" / ".env"
    if _env_path.exists():
        load_dotenv(str(_env_path), override=True)
except ImportError:
    pass

from dashboard import db
from agents.scheduler import build_scheduler


def main():
    parser = argparse.ArgumentParser(description="IYS Agent Dashboard")
    parser.add_argument("--host",   default="0.0.0.0",  help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port",   default=8080, type=int, help="Port (default: 8080)")
    parser.add_argument("--reload", action="store_true",   help="Enable uvicorn auto-reload (dev only)")
    args = parser.parse_args()

    # ── 0. PID lock — one instance only ───────────────────────────────────
    _check_pid_lock()
    atexit.register(_cleanup_pid)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    # ── 1. Initialise database ──────────────────────────────────────────────
    print("IYS Agent System — starting up")
    print(f"  DB: {db.DB_PATH}")
    db.init_db()
    print("  Database ready")

    # ── 2. Start scheduler ──────────────────────────────────────────────────
    from agents.scheduler import _update_next_runs
    scheduler = build_scheduler()
    scheduler.start()
    _update_next_runs(scheduler)
    jobs = scheduler.get_jobs()
    print(f"  Scheduler started — {len(jobs)} job(s) scheduled")
    for job in jobs:
        run_time = getattr(job, 'next_run_time', None)
        print(f"    • {job.name}: next run {run_time}")

    # ── 3. Start FastAPI ────────────────────────────────────────────────────
    print(f"\n  Dashboard: http://{args.host}:{args.port}")
    print("  Ctrl+C to stop\n")

    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
