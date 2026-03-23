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
import sys
from pathlib import Path

# Ensure project root is on path for all imports
sys.path.insert(0, str(Path(__file__).parent))

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
