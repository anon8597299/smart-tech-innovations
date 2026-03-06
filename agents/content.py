"""
agents/content.py — Content Agent

Runs auto_blog.py for each blog-enabled customer in the registry.
Wraps the existing script; does NOT rewrite it.

Schedule: Monday 6:00 AM AEST
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db


PROJECT_ROOT = Path(__file__).parent.parent
BUILDER_DIR  = PROJECT_ROOT / "builder"
REGISTRY     = PROJECT_ROOT / "customers" / "registry.json"


class ContentAgent(BaseAgent):
    agent_id = "content"
    name     = "Content"

    def run(self):
        import json

        if not REGISTRY.exists():
            self.log_warn("customers/registry.json not found — skipping")
            return

        registry = json.loads(REGISTRY.read_text())
        customers = [c for c in registry if c.get("blog_enabled")]

        if not customers:
            self.log_info("No blog-enabled customers in registry")
            return

        self.log_info(f"Running auto_blog for {len(customers)} customer(s)")

        for customer in customers:
            slug  = customer.get("slug", "unknown")
            tid   = self.create_task("blog", f"Auto-blog: {slug}")

            env = os.environ.copy()
            env["TARGET_SLUG"] = slug

            self.update_progress(tid, 20)

            result = subprocess.run(
                [sys.executable, str(BUILDER_DIR / "auto_blog.py")],
                capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT)
            )

            if result.returncode == 0:
                preview = f"Blog post generated for {slug}"
                self.complete_task(tid, preview)
                db.content_add(
                    content_type="blog",
                    title=f"Blog post — {slug}",
                    customer_slug=slug,
                    status="delivered",
                )
                self.log_info(f"Blog post generated for {slug}")
            else:
                err = result.stderr.strip()[-200:] if result.stderr else "Unknown error"
                self.fail_task(tid, err)
                self.log_error(f"auto_blog failed for {slug}: {err}")
