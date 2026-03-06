"""
agents/manager.py — Manager Agent

Orchestrates all workers:
 - Reads all agent states + today's digest
 - Sends daily summary email to James at 7 AM
 - Includes social post queue — ready-to-post captions + image paths
 - Flags agents stuck in 'error' state

Schedule: Daily 7:00 AM AEST
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

SOCIAL_DIR  = Path(__file__).parent.parent / "social"
QUEUE_FILE  = SOCIAL_DIR / "upload_queue.json"
REPORT_FILE = SOCIAL_DIR / "intel_report.json"


class ManagerAgent(BaseAgent):
    agent_id = "manager"
    name     = "Manager"

    def run(self):
        tid = self.create_task("digest", "Daily digest + health check")
        self.update_progress(tid, 20)

        # ── Agent health check ────────────────────────────────────────────
        agents = db.agents_all()
        error_agents = [a for a in agents if a["status"] == "error"]

        if error_agents:
            names = ", ".join(a["name"] for a in error_agents)
            self.log_warn(f"Agents in error state: {names}")
            self.send_email(
                subject=f"[IYS] Agent errors — {names}",
                body=(
                    "The following agents are in error state and need attention:\n\n"
                    + "\n".join(
                        f"  • {a['name']} — {a['error_count']} error(s) total"
                        for a in error_agents
                    )
                    + "\n\nDashboard: http://localhost:8080"
                ),
            )

        self.update_progress(tid, 40)

        # ── Social post queue ─────────────────────────────────────────────
        pending_posts = self._load_pending_posts()
        self.update_progress(tid, 60)

        # ── Daily digest ──────────────────────────────────────────────────
        summary = db.digest_summary()
        intel   = self._load_intel_report()

        subject = (
            f"[IYS Daily] {len(pending_posts)} post(s) ready · "
            f"{summary['tasks_completed']} tasks · "
            f"{summary['errors']} error(s)"
        )

        body_lines = [
            "ImproveYourSite — Daily Digest",
            "=" * 42,
            "",
        ]

        # ── Social section ────────────────────────────────────────────────
        if pending_posts:
            body_lines += [
                f"INSTAGRAM — {len(pending_posts)} POST(S) READY TO PUBLISH",
                "-" * 42,
                "Post these via Meta Business Suite app on your phone.",
                "Open the image, copy the caption below, paste and post.",
                "",
            ]
            for i, post in enumerate(pending_posts, 1):
                img = post.get("image_path", "No image")
                body_lines += [
                    f"Post {i} — {post.get('headline', '')}",
                    f"  Image : {img}",
                    f"  Caption:",
                    "",
                ]
                # Indent caption for readability
                for line in post.get("caption", "").splitlines():
                    body_lines.append(f"    {line}")
                body_lines += ["", "  - - -", ""]
        else:
            body_lines += [
                "INSTAGRAM — No posts queued (social agent hasn't run yet today)",
                "",
            ]

        # ── Market intel summary ──────────────────────────────────────────
        if intel:
            pulse = intel.get("market_pulse", "")
            trending = intel.get("trending_topics", [])[:3]
            gaps = intel.get("content_gaps", [])[:2]

            if pulse or trending:
                body_lines += [
                    "TODAY'S MARKET INTEL",
                    "-" * 42,
                ]
                if pulse:
                    body_lines += [f"Market pulse: {pulse}", ""]
                if trending:
                    body_lines.append("Trending topics AU SMBs are talking about:")
                    for t in trending:
                        body_lines.append(f"  • {t}")
                    body_lines.append("")
                if gaps:
                    body_lines.append("Content gaps competitors are missing (opportunities):")
                    for g in gaps:
                        body_lines.append(f"  • {g}")
                    body_lines.append("")

        # ── System stats ──────────────────────────────────────────────────
        body_lines += [
            "SYSTEM",
            "-" * 42,
            f"Tasks completed today  : {summary['tasks_completed']}",
            f"Content delivered      : {summary['content_delivered']}",
            f"Errors logged          : {summary['errors']}",
            "",
        ]

        if summary["recent_errors"]:
            body_lines.append("Recent errors:")
            for err in summary["recent_errors"]:
                body_lines.append(f"  [{err['agent_id']}] {err['message']}")
            body_lines.append("")

        body_lines += ["Agent status:"]
        for a in agents:
            last = a["last_run"] or "never"
            body_lines.append(f"  {a['name']:<12} {a['status']:<10} last run: {last}")

        body_lines += [
            "",
            "Dashboard: http://localhost:8080",
        ]

        self.update_progress(tid, 90)
        self.send_email(subject=subject, body="\n".join(body_lines))

        preview = (
            f"{len(pending_posts)} posts queued · "
            f"{summary['tasks_completed']} tasks · "
            f"{summary['errors']} errors"
        )
        self.complete_task(tid, preview)
        self.log_info(f"Manager: digest sent — {preview}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _load_pending_posts(self) -> list[dict]:
        if not QUEUE_FILE.exists():
            return []
        try:
            posts = json.loads(QUEUE_FILE.read_text())
            return [p for p in posts if p.get("status") == "pending"]
        except Exception:
            return []

    def _load_intel_report(self) -> dict:
        if not REPORT_FILE.exists():
            return {}
        try:
            return json.loads(REPORT_FILE.read_text())
        except Exception:
            return {}
