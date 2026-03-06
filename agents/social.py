"""
agents/social.py — Social Agent

Reads Instagram Insights via the Graph API and optionally triggers
carousel generation scripts from social/.

Requires in builder/.env:
  INSTAGRAM_ACCESS_TOKEN=<long-lived token, instagram_basic + read_insights>
  INSTAGRAM_ACCOUNT_ID=<Instagram Business Account ID>

Schedule: Daily 8:00 AM AEST
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent
SOCIAL_DIR   = PROJECT_ROOT / "social"

GRAPH_BASE = "https://graph.facebook.com/v19.0"


class SocialAgent(BaseAgent):
    agent_id = "social"
    name     = "Social"

    def run(self):
        token      = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

        # ── Instagram Insights ────────────────────────────────────────────
        if token and account_id:
            self._fetch_insights(token, account_id)
        else:
            self.log_warn(
                "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID not set — "
                "skipping insights (add to builder/.env once Meta token obtained)"
            )

        # ── Carousel generation ────────────────────────────────────────────
        self._run_carousel_scripts()

    def _fetch_insights(self, token: str, account_id: str):
        try:
            import urllib.request, json as _json
            url = (
                f"{GRAPH_BASE}/{account_id}/insights"
                f"?metric=reach,impressions,profile_views"
                f"&period=week"
                f"&access_token={token}"
            )
            with urllib.request.urlopen(url, timeout=10) as r:
                data = _json.loads(r.read())

            metrics = {m["name"]: m["values"][-1]["value"] for m in data.get("data", [])}
            reach       = metrics.get("reach", 0)
            impressions = metrics.get("impressions", 0)
            profile_views = metrics.get("profile_views", 0)

            self.log_info(
                f"Instagram (7d): reach={reach}, impressions={impressions}, "
                f"profile_views={profile_views}"
            )

            db.event_log("social", "info",
                f"IG metrics — reach:{reach} impressions:{impressions} views:{profile_views}")

        except Exception as exc:
            self.log_error(f"Instagram insights failed: {exc}")

    def _run_carousel_scripts(self):
        """Run carousel generation scripts that don't need interactive input."""
        scripts = list(SOCIAL_DIR.glob("make_*.py"))
        if not scripts:
            self.log_info("No carousel scripts found in social/")
            return

        self.log_info(f"Social: running {len(scripts)} carousel script(s)")

        for script in scripts:
            tid = self.create_task("carousel", f"Carousel: {script.stem}")
            self.update_progress(tid, 20)

            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT)
            )

            if result.returncode == 0:
                self.complete_task(tid, f"Generated: {script.stem}")
                db.content_add(
                    content_type="carousel",
                    title=script.stem.replace("_", " ").title(),
                    status="delivered",
                )
                self.log_info(f"Carousel generated: {script.stem}")
            else:
                err = (result.stderr or result.stdout or "Unknown").strip()[-200:]
                self.fail_task(tid, err)
                self.log_warn(f"Carousel {script.stem} failed: {err}")
