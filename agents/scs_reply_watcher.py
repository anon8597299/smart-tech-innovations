"""
agents/scs_reply_watcher.py

Monitors outreach.improveyoursite@gmail.com for a reply from
sthcoastsolar@gmail.com.

If reply is negative:
  1. Marks them cold in the leads DB
  2. Deletes customers/south-coast-solar/ from the repo
  3. Git commits and pushes
  4. Logs the event and self-disables

Runs via scheduler.py every 30 minutes.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from dashboard import db

PROJECT_ROOT  = Path(__file__).parent.parent
CUSTOMER_DIR  = PROJECT_ROOT / "customers" / "south-coast-solar"
DONE_FLAG     = PROJECT_ROOT / "agents" / ".scs_watcher_done"

GMAIL_USER    = os.environ.get("GMAIL_USER", "")
GMAIL_PASS    = os.environ.get("GMAIL_APP_PASS", "")
SCS_EMAIL     = "sthcoastsolar@gmail.com"
IMAP_HOST     = "imap.gmail.com"

NEGATIVE_WORDS = [
    "unsubscribe", "remove", "stop", "don't contact", "do not contact",
    "leave me alone", "not interested", "spam", "harassment", "reported",
    "angry", "furious", "piss off", "f**k", "fuck", "scam", "fraud",
    "police", "legal", "lawyer", "solicitor", "cease", "desist",
    "reported to", "optout", "opt out", "opt-out", "no thanks",
    "not needed", "go away", "delete", "remove me",
]


def _is_negative(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    return any(w in text for w in NEGATIVE_WORDS)


def _get_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body


def check_for_reply() -> Optional[dict]:
    """
    Check inbox for a reply from SCS. Returns dict with subject/body if found,
    None otherwise.
    """
    if not GMAIL_PASS:
        return None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("INBOX")

        _, data = mail.search(None, f'(FROM "{SCS_EMAIL}")')
        uids = data[0].split() if data[0] else []

        for uid in uids:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            subject = msg.get("Subject", "")
            body    = _get_body(msg)
            mail.logout()
            return {"uid": uid, "subject": subject, "body": body}

        mail.logout()
    except Exception as exc:
        print(f"SCS watcher IMAP error: {exc}")
    return None


def remove_scs_from_leads():
    try:
        with db.transaction() as conn:
            conn.execute(
                "UPDATE leads SET status='cold' WHERE LOWER(email)=?",
                (SCS_EMAIL.lower(),)
            )
        print("  SCS marked cold in leads DB")
    except Exception as exc:
        print(f"  DB update failed: {exc}")


def delete_demo_and_push():
    if CUSTOMER_DIR.exists():
        shutil.rmtree(CUSTOMER_DIR)
        print(f"  Deleted {CUSTOMER_DIR}")
    else:
        print("  Demo directory already gone")
        return

    try:
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "add", "customers/south-coast-solar"],
            check=True
        )
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (
            f"Remove South Coast Solar demo — negative reply [{ts}]\n\n"
            "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        )
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "commit", "-m", msg],
            check=True
        )
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "pull", "--rebase", "origin", "main"],
            check=True
        )
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "push", "origin", "main"],
            check=True
        )
        print("  Pushed — demo removed from GitHub Pages")
    except subprocess.CalledProcessError as exc:
        print(f"  Git error: {exc}")


def run_once() -> bool:
    """Returns True if reply found and handled (positive or negative)."""
    if DONE_FLAG.exists():
        return True

    print(f"[{datetime.now().strftime('%H:%M:%S')}] SCS watcher: checking for reply...")

    reply = check_for_reply()
    if not reply:
        print("  No reply yet.")
        return False

    print(f"  Reply found: '{reply['subject']}'")

    if _is_negative(reply["subject"], reply["body"]):
        print("  Negative reply detected — removing...")
        db.event_log("inbox", "warn",
                     f"SCS negative reply: '{reply['subject'][:80]}' — removing demo + marking cold")
        remove_scs_from_leads()
        delete_demo_and_push()
    else:
        print("  Reply is not negative — no action taken")
        db.event_log("inbox", "info",
                     f"SCS reply received (neutral/positive): '{reply['subject'][:80]}'")

    # Either way, stop watching
    DONE_FLAG.touch()
    return True


if __name__ == "__main__":
    run_once()
