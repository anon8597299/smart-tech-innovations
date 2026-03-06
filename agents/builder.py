"""
agents/builder.py — Builder Agent

Wraps builder/generate.py. On-demand only (triggered via POST /api/trigger/builder
with optional config_path in request, or reads from a queue file).

The agent checks agents/build_queue.json for pending configs on each run.
Format: [{"config": "path/to/customer.json"}, ...]
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent
BUILDER_DIR  = PROJECT_ROOT / "builder"
QUEUE_FILE   = Path(__file__).parent / "build_queue.json"


class BuilderAgent(BaseAgent):
    agent_id = "builder"
    name     = "Builder"

    def run(self):
        jobs = self._dequeue()

        if not jobs:
            self.log_info("Builder: no jobs queued")
            return

        self.log_info(f"Builder: processing {len(jobs)} job(s)")

        for job in jobs:
            config_path = job.get("config")
            if not config_path:
                continue

            config_file = Path(config_path)
            if not config_file.is_absolute():
                config_file = PROJECT_ROOT / config_path

            if not config_file.exists():
                self.log_error(f"Config not found: {config_path}")
                continue

            # Read business name for task title
            try:
                cfg = json.loads(config_file.read_text())
                title = f"Build: {cfg.get('BUSINESS_NAME', config_path)}"
            except Exception:
                title = f"Build: {config_path}"

            tid = self.create_task("site_build", title)
            self.update_progress(tid, 15, "Rendering templates…")

            result = subprocess.run(
                [sys.executable, str(BUILDER_DIR / "generate.py"), "--config", str(config_file)],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT)
            )

            if result.returncode == 0:
                # Extract live URL from stdout
                live_url = ""
                for line in result.stdout.splitlines():
                    if "github.io" in line or "live" in line.lower():
                        live_url = line.strip()
                        break

                preview = live_url or "Site pushed to GitHub Pages"
                self.complete_task(tid, preview)
                db.content_add(
                    content_type="site",
                    title=title,
                    customer_slug=cfg.get("SLUG", ""),
                    status="delivered",
                )
                self.log_info(f"Site built: {title}")
            else:
                err = (result.stderr or result.stdout or "Unknown error").strip()[-300:]
                self.fail_task(tid, err)
                self.log_error(f"generate.py failed: {err}")

    # ── Queue helpers ─────────────────────────────────────────────────────

    def _dequeue(self) -> list[dict]:
        """Read and clear the build queue file."""
        if not QUEUE_FILE.exists():
            return []
        try:
            jobs = json.loads(QUEUE_FILE.read_text())
            QUEUE_FILE.write_text("[]")  # clear queue
            return jobs if isinstance(jobs, list) else []
        except Exception as exc:
            self.log_error(f"Failed reading build queue: {exc}")
            return []

    @staticmethod
    def enqueue(config_path: str):
        """Add a job to the build queue (call from API or admin)."""
        jobs = []
        if QUEUE_FILE.exists():
            try:
                jobs = json.loads(QUEUE_FILE.read_text())
            except Exception:
                jobs = []
        jobs.append({"config": config_path})
        QUEUE_FILE.write_text(json.dumps(jobs, indent=2))
