"""
agents/analyst.py — Analyst Agent

Reviews recently generated content using the Claude API.
Scores quality 1-10, logs results, flags anything below threshold.

Triggered automatically after each agent run (via scheduler) or on demand.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

QUALITY_THRESHOLD = 6  # score below this triggers a warning email


class AnalystAgent(BaseAgent):
    agent_id = "analyst"
    name     = "Analyst"

    def run(self):
        # Get recent content that hasn't been reviewed yet
        conn = db.get_conn()
        unreviewed = conn.execute(
            "SELECT * FROM content WHERE status='delivered' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        if not unreviewed:
            self.log_info("Analyst: no new content to review")
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.log_warn("ANTHROPIC_API_KEY not set — skipping analysis")
            return

        try:
            import anthropic
        except ImportError:
            self.log_warn("anthropic package not installed — skipping analysis")
            return

        client = anthropic.Anthropic(api_key=api_key)
        low_quality = []

        for row in unreviewed:
            item = dict(row)
            tid  = self.create_task("review", f"Review: {item['title']}")
            self.update_progress(tid, 30)

            prompt = (
                f"You are a quality reviewer for ImproveYourSite.com, an Australian web agency.\n\n"
                f"Content type: {item['type']}\n"
                f"Title: {item['title']}\n"
                f"Customer: {item.get('customer_slug', 'IYS')}\n\n"
                f"Rate the likely quality of this content delivery on a scale of 1-10, "
                f"where 10 is excellent. Consider: relevance, professionalism, value to a "
                f"small business customer. Reply ONLY with JSON: "
                f"{{\"score\": <1-10>, \"notes\": \"<one sentence>\"}}"
            )

            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=100,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                result = json.loads(raw)
                score  = int(result.get("score", 7))
                notes  = result.get("notes", "")

                self.update_progress(tid, 80)

                # Mark content as reviewed
                with db.transaction() as c:
                    c.execute(
                        "UPDATE content SET status='reviewed' WHERE id=?", (item["id"],)
                    )

                preview = f"Score: {score}/10 — {notes}"
                self.complete_task(tid, preview)
                self.log_info(f"Analyst: {item['title']} scored {score}/10")

                if score < QUALITY_THRESHOLD:
                    low_quality.append({"title": item["title"], "score": score, "notes": notes})

            except Exception as exc:
                self.fail_task(tid, str(exc))
                self.log_error(f"Analyst review failed for {item['title']}: {exc}")

        if low_quality:
            lines = "\n".join(
                f"  - {q['title']} (score {q['score']}/10): {q['notes']}"
                for q in low_quality
            )
            self.send_email(
                subject="[IYS] Content quality flag",
                body=f"The following items scored below {QUALITY_THRESHOLD}/10:\n\n{lines}\n\n"
                     f"Please review and consider re-generating.",
            )
            self.log_warn(f"Analyst: {len(low_quality)} low-quality item(s) flagged")
