#!/usr/bin/env python3
"""
google_ads_reply_watcher.py

Polls hello@improveyoursite.com every 5 minutes for a Google Ads API
approval email. When found, automatically:
  1. Logs the reply
  2. Tests the Google Ads API connection (runs AdsAgent)
  3. Sends James a summary email with the result

Run: python3 google_ads_reply_watcher.py
"""

import imaplib
import email
import json
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(Path("builder/.env"))

IMAP_HOST   = "imap.gmail.com"
INBOX_USER  = os.environ.get("HELLO_EMAIL_USER", "hello@improveyoursite.com")
INBOX_PASS  = os.environ.get("HELLO_EMAIL_PASS", "")
CHECK_EVERY = 300  # seconds (5 min)
LOG_FILE    = "/tmp/google-ads-reply-watcher.log"

GOOGLE_SENDERS = ["@google.com", "googleads.com", "ads-api@google", "adwords@google"]
GOOGLE_SUBJECTS = ["developer token", "ads api", "api access", "api center", "access level"]

TRIGGERED_FLAG = "/tmp/google-ads-reply-triggered.flag"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def decode_str(s):
    parts = _decode_header(s or "")
    out = ""
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out += chunk.decode(enc or "utf-8", errors="ignore")
        else:
            out += chunk
    return out


def is_google_ads_reply(from_addr, subject):
    from_l = from_addr.lower()
    subj_l = subject.lower()
    sender_match = any(g in from_l for g in GOOGLE_SENDERS)
    subject_match = any(g in subj_l for g in GOOGLE_SUBJECTS)
    # Require BOTH — must be from Google AND have ads-related subject
    return sender_match and subject_match


def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    return ""


def check_inbox():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(INBOX_USER, INBOX_PASS)
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        msg_ids = data[0].split()
        found = []
        for mid in msg_ids:
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            from_raw = decode_str(msg.get("From", ""))
            subject  = decode_str(msg.get("Subject", ""))
            if is_google_ads_reply(from_raw, subject):
                body = get_body(msg)
                found.append({"from": from_raw, "subject": subject, "body": body[:2000]})
                log(f"MATCH — From: {from_raw} | Subject: {subject}")
        mail.logout()
        return found
    except Exception as e:
        log(f"IMAP error: {e}")
        return []


def run_ads_agent():
    log("Running AdsAgent to test connection...")
    result = subprocess.run(
        [sys.executable, "-c", """
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; from pathlib import Path
load_dotenv(Path('builder/.env'))
from dashboard import db; db.init_db()
from agents.ads import AdsAgent
a = AdsAgent(); a.execute()
print('AdsAgent complete')
"""],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent),
        timeout=60,
    )
    output = result.stdout + result.stderr
    log(f"AdsAgent output: {output[:500]}")
    return output


def send_notification(google_email, ads_output):
    try:
        smtp_user = os.environ.get("GMAIL_USER", "")
        smtp_pass = os.environ.get("GMAIL_APP_PASS", "")
        if not smtp_user or not smtp_pass:
            log("No SMTP creds — skipping notification email")
            return

        approved = any(w in google_email.get("body", "").lower()
                       for w in ["approved", "granted", "access level", "welcome"])
        rejected = any(w in google_email.get("body", "").lower()
                       for w in ["rejected", "denied", "not approved", "cannot"])

        status = "APPROVED" if approved else ("REJECTED" if rejected else "RECEIVED")

        body = f"""Google Ads API reply detected automatically.

From: {google_email['from']}
Subject: {google_email['subject']}
Status detected: {status}

--- Google email body (first 1000 chars) ---
{google_email['body'][:1000]}

--- Ads Agent test result ---
{ads_output[:800]}

---
Watcher log: {LOG_FILE}
"""
        msg = MIMEText(body)
        msg["Subject"] = f"[IYS] Google Ads API reply — {status}"
        msg["From"]    = smtp_user
        msg["To"]      = INBOX_USER

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        log(f"Notification sent to {INBOX_USER}")
    except Exception as e:
        log(f"Notification email failed: {e}")


def main():
    log("=== Google Ads reply watcher started ===")
    log(f"Monitoring: {INBOX_USER} every {CHECK_EVERY}s")
    log(f"Log: {LOG_FILE}")

    while True:
        if os.path.exists(TRIGGERED_FLAG):
            log("Already triggered — exiting watcher")
            break

        matches = check_inbox()
        if matches:
            log(f"Found {len(matches)} Google Ads reply email(s) — acting now")
            Path(TRIGGERED_FLAG).write_text("triggered")
            for m in matches:
                ads_output = run_ads_agent()
                send_notification(m, ads_output)
            log("All done — watcher exiting")
            break
        else:
            log(f"No match — checking again in {CHECK_EVERY}s")
            time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
