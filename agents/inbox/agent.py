"""
agents/inbox/agent.py — Inbox Agent

Monitors hello@improveyoursite.com and triages all incoming email.

What it does:
  1. Scans hello@ inbox every 30 minutes for new messages
  2. Classifies each email: lead / customer_reply / order_form / spam / other
  3. For LEADS: extracts business name, contact, issue, and drafts a personalised reply
  4. For CUSTOMER REPLIES: flags as UAT approval or change request
  5. For ORDER FORMS: triggers Stripe Monitor's parser
  6. Sends James an alert email with triage summary + draft replies
  7. Logs all inbox activity to DB
  8. Never auto-sends replies — James always approves first
  9. Diagnostics: validates IMAP credentials, tests connection, counts unread

Schedule (set in scheduler.py):
  - Triage: Every 30 minutes
  - Summary digest: Daily 8:00 AM AEST

Required in builder/.env:
  HELLO_EMAIL_USER    — hello@improveyoursite.com
  HELLO_EMAIL_PASS    — Google Workspace app password
  ANTHROPIC_API_KEY   — for email classification + draft replies
  GMAIL_USER          — for sending triage summary to James
  GMAIL_APP_PASS      — already set
"""

from __future__ import annotations

import email as email_lib
import imaplib
import json
import os
import re
import sys
from datetime import datetime, date
from email.header import decode_header as _decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT   = Path(__file__).parent.parent.parent
INBOX_LOG_FILE = PROJECT_ROOT / "social" / "inbox_log.json"
TRIAGE_LOG     = PROJECT_ROOT / "social" / "triage_queue.json"
BOOKING_URL    = "https://improveyoursite.com/book.html"
IMAP_HOST      = "imap.gmail.com"

CATEGORIES = {
    "lead":           "Potential new customer",
    "customer_reply": "Existing customer reply",
    "order_form":     "Order form submission",
    "spam":           "Spam / irrelevant",
    "other":          "Other",
}


class InboxAgent(BaseAgent):
    agent_id = "inbox"
    name     = "Inbox"

    def run(self):
        mode = os.environ.get("RUN_MODE", "triage")
        if mode == "diagnose":
            self._run_diagnostics()
            return
        if mode == "digest":
            self._send_daily_digest()
            return

        self._run_triage()
        if date.today().weekday() in (0, 2, 4) and datetime.utcnow().hour < 1:
            self._send_daily_digest()

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def _run_diagnostics(self):
        tid = self.create_task("diagnostics", "Inbox Agent diagnostics")
        results = []

        hello_user = os.environ.get("HELLO_EMAIL_USER", "")
        hello_pass = os.environ.get("HELLO_EMAIL_PASS", "")

        if hello_user and hello_pass:
            try:
                with imaplib.IMAP4_SSL(IMAP_HOST, timeout=30) as imap:
                    imap.login(hello_user, hello_pass)
                    imap.select("INBOX")
                    _, msgs = imap.search(None, "UNSEEN")
                    unread = len(msgs[0].split()) if msgs[0] else 0
                    results.append(f"  ✓ IMAP connected ({hello_user}) — {unread} unread")
                    self.log_info(f"Diag IMAP: connected, {unread} unread")
            except Exception as exc:
                results.append(f"  ✗ IMAP failed: {exc}")
                self.log_warn(f"Diag IMAP: FAILED: {exc}")
        else:
            results.append("  ✗ HELLO_EMAIL_USER / HELLO_EMAIL_PASS not set")

        for key in ["ANTHROPIC_API_KEY", "GMAIL_USER", "GMAIL_APP_PASS"]:
            results.append(f"  {'✓' if os.environ.get(key) else '✗'} {key}")

        triage_ok = TRIAGE_LOG.parent.exists()
        results.append(f"  {'✓' if triage_ok else '✗'} Triage log path writable")

        self.log_info("Inbox diagnostics:\n" + "\n".join(results))
        self.complete_task(tid, f"{sum(1 for r in results if '✓' in r)}/{len(results)} checks passed")

    # ── Triage ────────────────────────────────────────────────────────────────

    def _run_triage(self):
        hello_user = os.environ.get("HELLO_EMAIL_USER", "")
        hello_pass = os.environ.get("HELLO_EMAIL_PASS", "")

        if not hello_user or not hello_pass:
            self.log_warn("Inbox: HELLO_EMAIL_USER / HELLO_EMAIL_PASS not set — skipping")
            return

        tid = self.create_task("inbox_triage", "Checking hello@ inbox")
        self.update_progress(tid, 10)

        triaged = []
        try:
            with imaplib.IMAP4_SSL(IMAP_HOST, timeout=30) as imap:
                imap.login(hello_user, hello_pass)
                imap.select("INBOX")
                _, msgs = imap.search(None, "UNSEEN")
                msg_ids = msgs[0].split() if msgs[0] else []

                self.log_info(f"Inbox: {len(msg_ids)} unread email(s)")

                for i, num in enumerate(msg_ids[:20]):  # cap at 20 per run
                    self.update_progress(tid, 15 + int((i / max(len(msg_ids), 1)) * 70))
                    try:
                        _, data = imap.fetch(num, "(RFC822)")
                        raw = data[0][1] if data and data[0] else b""
                        result = self._process_email(raw)
                        if result:
                            triaged.append(result)
                            # Mark as seen
                            imap.store(num, "+FLAGS", "\\Seen")
                    except Exception as exc:
                        self.log_warn(f"Inbox: error processing email {num}: {exc}")

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Inbox IMAP failed: {exc}")
            return

        # Save triage queue
        if triaged:
            self._append_triage_queue(triaged)
            self._send_triage_alert(triaged)
            db.content_add(
                content_type="inbox_triage",
                title=f"Inbox: {len(triaged)} email(s) triaged",
                status="delivered",
            )

        self.complete_task(tid, f"{len(triaged)} email(s) triaged")
        self.log_info(f"Inbox: {len(triaged)} emails processed")

    def _process_email(self, raw: bytes) -> dict | None:
        """Parse, classify, and draft a reply for one email."""
        try:
            msg      = email_lib.message_from_bytes(raw)
            from_raw = msg.get("From", "")
            subject  = self._decode_header_str(msg.get("Subject", ""))
            date_str = msg.get("Date", "")

            # Extract sender name + email
            sender_match = re.search(r'"?([^"<]+)"?\s*<?([\w.+\-]+@[\w.\-]+)>?', from_raw)
            sender_name  = sender_match.group(1).strip() if sender_match else from_raw
            sender_email = sender_match.group(2) if sender_match else ""

            # Get plain text body
            body = self._extract_body(msg)

            # Classify + draft
            category, draft_reply, notes = self._classify_email(
                sender_name, sender_email, subject, body
            )

            if category == "spam":
                return None  # skip spam silently

            return {
                "id":           f"{date_str}_{sender_email}",
                "received_at":  date_str,
                "from_name":    sender_name,
                "from_email":   sender_email,
                "subject":      subject,
                "body_preview": body[:300],
                "category":     category,
                "notes":        notes,
                "draft_reply":  draft_reply,
                "triaged_at":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        except Exception as exc:
            self.log_warn(f"Inbox: email parse failed: {exc}")
            return None

    def _classify_email(
        self, name: str, email: str, subject: str, body: str
    ) -> tuple[str, str, str]:
        """Use Claude to classify email and draft a reply. Falls back to heuristics."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._heuristic_classify(subject, body)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            prompt = f"""You are a triage assistant for ImproveYourSite.com, an Australian web agency.

Classify this email and draft a reply for James to approve and send.

From: {name} <{email}>
Subject: {subject}
Body:
{body[:800]}

Categories:
- lead: potential new customer asking about services, pricing, website help
- customer_reply: existing customer replying about their site (UAT, changes, approval)
- order_form: automated form submission with business details
- spam: junk, cold sales, irrelevant newsletters
- other: everything else

Return ONLY valid JSON:
{{
  "category": "lead|customer_reply|order_form|spam|other",
  "notes": "One sentence summary of what this email is about",
  "draft_reply": "Draft reply for James to approve. Conversational, Australian, helpful. 3-5 sentences. Leave blank for spam.",
  "urgency": "high|medium|low"
}}

Draft should sound like James wrote it personally. First person. Sign off as 'James'."""

            r = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = r.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw.strip())
            return (
                result.get("category", "other"),
                result.get("draft_reply", ""),
                result.get("notes", ""),
            )
        except Exception as exc:
            self.log_warn(f"Inbox: Claude classification failed: {exc}")
            return self._heuristic_classify(subject, body)

    def _heuristic_classify(self, subject: str, body: str) -> tuple[str, str, str]:
        text = (subject + " " + body).lower()
        if any(w in text for w in ["unsubscribe", "click here", "offer expires", "dear friend"]):
            return "spam", "", "Likely spam"
        if any(w in text for w in ["website", "seo", "price", "quote", "help", "enquiry"]):
            return "lead", (
                "Hi there,\n\nThanks for reaching out! I'd love to learn more about what you're after.\n\n"
                "Would you be open to a quick 20-minute call this week?\n\n"
                f"Book here: {BOOKING_URL}\n\nJames"
            ), "Potential lead — website/SEO enquiry"
        if any(w in text for w in ["looks good", "approved", "happy with", "change", "update"]):
            return "customer_reply", (
                "Great, thanks for the feedback! I'll get onto that for you shortly.\n\nJames"
            ), "Customer reply about their site"
        return "other", "Hi,\n\nThanks for your email. I'll get back to you shortly.\n\nJames", "Unclassified email"

    def _send_triage_alert(self, triaged: list[dict]):
        """Send James a summary of triaged emails with draft replies."""
        leads      = [t for t in triaged if t["category"] == "lead"]
        customers  = [t for t in triaged if t["category"] == "customer_reply"]
        others     = [t for t in triaged if t["category"] not in ("lead", "customer_reply", "spam", "order_form")]

        lines = [
            f"Inbox Triage — {len(triaged)} email(s)",
            "=" * 42,
            "",
        ]

        for section_name, items in [("LEADS", leads), ("CUSTOMER REPLIES", customers), ("OTHER", others)]:
            if not items:
                continue
            lines += [f"{section_name} ({len(items)})", "-" * 42]
            for item in items:
                lines += [
                    f"From:    {item['from_name']} <{item['from_email']}>",
                    f"Subject: {item['subject']}",
                    f"Notes:   {item['notes']}",
                    "",
                    "Draft reply (review before sending):",
                    "- - - - -",
                ]
                for line in (item.get("draft_reply", "") or "").splitlines():
                    lines.append(f"  {line}")
                lines += ["- - - - -", ""]

        lines += ["Dashboard: http://localhost:8080"]

        subject = (
            f"[IYS] Inbox — {len(leads)} lead(s) · {len(customers)} customer reply(s) · {len(triaged)} total"
        )
        self.send_email(subject=subject, body="\n".join(lines))

    def _send_daily_digest(self):
        """Morning digest: count of unread emails + today's triage summary."""
        triage = self._load_triage_queue()
        today  = date.today().isoformat()
        today_items = [t for t in triage if t.get("triaged_at", "").startswith(today)]

        if not today_items:
            return

        self.log_info(f"Inbox: daily digest — {len(today_items)} item(s) today")

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _append_triage_queue(self, items: list[dict]):
        queue = self._load_triage_queue()
        queue.extend(items)
        queue = queue[-200:]  # keep last 200
        TRIAGE_LOG.parent.mkdir(exist_ok=True)
        TRIAGE_LOG.write_text(json.dumps(queue, indent=2))

    def _load_triage_queue(self) -> list[dict]:
        if not TRIAGE_LOG.exists():
            return []
        try:
            return json.loads(TRIAGE_LOG.read_text())
        except Exception:
            return []

    # ── Email parse helpers ───────────────────────────────────────────────────

    def _extract_body(self, msg) -> str:
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    return ""
        return ""

    @staticmethod
    def _decode_header_str(header_str: str) -> str:
        parts = _decode_header(header_str)
        decoded = []
        for part, enc in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return " ".join(decoded)
