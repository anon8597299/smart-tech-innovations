"""
agents/manager.py — Manager Agent

Orchestrates all workers:
 - Reads all agent states + today's digest
 - Sends daily summary email to James at 7 AM
 - Flags agents stuck in 'error' state
 - Logs a system-wide health summary to the dashboard

Schedule: Daily 7:00 AM AEST
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

JAMES_EMAIL = "hello@improveyoursite.com"


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
                    f"The following agents are in error state and need attention:\n\n"
                    + "\n".join(
                        f"  • {a['name']} — {a['error_count']} error(s) total"
                        for a in error_agents
                    )
                    + "\n\nLog in to the dashboard for details: http://localhost:8080"
                ),
            )

        self.update_progress(tid, 50)

        # ── Daily digest ──────────────────────────────────────────────────
        summary = db.digest_summary()

        subject = (
            f"[IYS Daily] {summary['tasks_completed']} tasks · "
            f"{summary['content_delivered']} content · "
            f"{summary['errors']} error(s)"
        )

        body_lines = [
            "ImproveYourSite — Daily Agent Digest",
            "=" * 40,
            "",
            f"Tasks completed today : {summary['tasks_completed']}",
            f"Content delivered     : {summary['content_delivered']}",
            f"Errors logged         : {summary['errors']}",
            "",
        ]

        if summary["recent_errors"]:
            body_lines.append("Recent errors:")
            for err in summary["recent_errors"]:
                body_lines.append(f"  [{err['agent_id']}] {err['message']}  ({err['timestamp']})")
            body_lines.append("")

        body_lines += [
            "Agent Status:",
        ]
        for a in agents:
            last = a["last_run"] or "never"
            body_lines.append(f"  {a['name']:<12} {a['status']:<10} last run: {last}")

        body_lines += [
            "",
            "Dashboard: http://localhost:8080",
        ]

        self.update_progress(tid, 80)

        self.send_email(subject=subject, body="\n".join(body_lines))

        preview = f"{summary['tasks_completed']} tasks, {summary['content_delivered']} content, {summary['errors']} errors"
        self.complete_task(tid, preview)
        self.log_info(f"Manager: digest sent — {preview}")
