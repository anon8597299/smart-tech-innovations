"""
agents/base.py — BaseAgent: shared methods inherited by all IYS agents.

Every agent gets:
  - log_event(level, message)   → writes to DB + pushes to SSE queue
  - create_task(type, title)    → returns task_id
  - update_progress(id, pct)    → 0-100
  - complete_task(id, preview)
  - fail_task(id, reason)
  - send_email(subject, body)   → Gmail SMTP from .env creds
  - run()                       → override in subclass

Usage:
    class MyAgent(BaseAgent):
        def run(self):
            tid = self.create_task("blog", "Writing post for Smiths Plumbing")
            ...
            self.complete_task(tid, preview="Post: https://...")
"""

from __future__ import annotations

import os
import smtplib
import sys
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Ensure project root is on path so we can import dashboard.db
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from dashboard import db

# SSE broadcast queue — dashboard/app.py injects this at startup
_sse_queue = None


def set_sse_queue(q):
    global _sse_queue
    _sse_queue = q


JAMES_EMAIL = "hello@improveyoursite.com"
GMAIL_USER  = os.environ.get("GMAIL_USER", "")
GMAIL_PASS  = os.environ.get("GMAIL_APP_PASS", "")


class BaseAgent:
    agent_id: str = "base"
    name: str = "Base Agent"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def execute(self):
        """Called by scheduler. Wraps run() with status + error handling."""
        db.agent_set_status(self.agent_id, "running")
        self.log("info", f"{self.name} started")
        try:
            self.run()
            db.agent_set_status(self.agent_id, "idle")
            self.log("info", f"{self.name} finished")
        except Exception as exc:
            db.agent_set_status(self.agent_id, "error")
            db.agent_increment_error(self.agent_id)
            msg = f"{self.name} crashed: {exc}"
            self.log("error", msg)
            self.send_email(
                subject=f"[IYS Agent ERROR] {self.name}",
                body=f"{msg}\n\n{traceback.format_exc()}",
            )

    def run(self):
        raise NotImplementedError

    # ── Logging ──────────────────────────────────────────────────────────────

    def log(self, level: str, message: str):
        """Write event to DB and push to SSE stream."""
        event = db.event_log(self.agent_id, level, message)
        if _sse_queue:
            try:
                _sse_queue.put_nowait({"type": "event", "data": event})
            except Exception:
                pass

    def log_info(self, message: str):
        self.log("info", message)

    def log_warn(self, message: str):
        self.log("warn", message)

    def log_error(self, message: str):
        self.log("error", message)

    # ── Tasks ────────────────────────────────────────────────────────────────

    def create_task(self, task_type: str, title: str) -> int:
        task_id = db.task_create(self.agent_id, task_type, title)
        if _sse_queue:
            try:
                _sse_queue.put_nowait({"type": "task_created", "data": {
                    "id": task_id,
                    "agent_id": self.agent_id,
                    "title": title,
                    "type": task_type,
                    "status": "running",
                    "progress": 0,
                    "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }})
            except Exception:
                pass
        return task_id

    def update_progress(self, task_id: int, progress: int, preview: str | None = None):
        db.task_update_progress(task_id, progress, preview)
        if _sse_queue:
            try:
                _sse_queue.put_nowait({"type": "task_progress", "data": {
                    "id": task_id,
                    "progress": progress,
                    "preview": preview,
                }})
            except Exception:
                pass

    def complete_task(self, task_id: int, preview: str | None = None):
        db.task_complete(task_id, preview)
        if _sse_queue:
            try:
                _sse_queue.put_nowait({"type": "task_complete", "data": {
                    "id": task_id,
                    "preview": preview,
                }})
            except Exception:
                pass

    def fail_task(self, task_id: int, reason: str):
        db.task_fail(task_id, reason)
        db.agent_increment_error(self.agent_id)
        if _sse_queue:
            try:
                _sse_queue.put_nowait({"type": "task_failed", "data": {
                    "id": task_id,
                    "reason": reason,
                }})
            except Exception:
                pass

    # ── Email ────────────────────────────────────────────────────────────────

    def send_email(self, subject: str, body: str, html: str | None = None):
        """Send an email to James via Gmail SMTP."""
        if not GMAIL_USER or not GMAIL_PASS:
            self.log("warn", "Email skipped — GMAIL_USER / GMAIL_APP_PASS not set in .env")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = GMAIL_USER
            msg["To"] = JAMES_EMAIL
            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_USER, GMAIL_PASS)
                server.sendmail(GMAIL_USER, JAMES_EMAIL, msg.as_string())
            self.log("info", f"Email sent: {subject}")
        except Exception as exc:
            self.log("warn", f"Email failed: {exc}")
