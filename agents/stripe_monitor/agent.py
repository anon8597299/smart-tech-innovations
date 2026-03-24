"""
agents/stripe_monitor/agent.py — Stripe Monitor Agent

Watches Stripe for new paid orders and fires the site builder automatically.

What it does every run:
  1. Polls Stripe for payment_intent.succeeded events since last check
  2. Matches payments to package type (scan_fix / complete_build / premium)
  3. Sends customer a welcome email with intake form link
  4. Queues a site build job in agents/build_queue.json when form is submitted
  5. Alerts James via email for every new order
  6. Self-diagnostics: validates Stripe key, tests API connectivity

Also handles order.html form submissions from formsubmit.co forwarding:
  - Reads hello@ inbox for order confirmation emails from formsubmit.co
  - Parses customer details and writes a config JSON ready for the builder

Schedule: Every 30 minutes (see scheduler.py)

Required in builder/.env:
  STRIPE_SECRET_KEY     — sk_live_... or sk_test_... key
  GMAIL_USER            — outreach Gmail (already set)
  GMAIL_APP_PASS        — already set
  HELLO_EMAIL_USER      — hello@ inbox for form submission parsing
  HELLO_EMAIL_PASS      — hello@ app password (already set)
"""

from __future__ import annotations

import imaplib
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date
from email import message_from_bytes
from email.header import decode_header as _decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT   = Path(__file__).parent.parent.parent
BUILDER_DIR    = PROJECT_ROOT / "builder"
CUSTOMERS_DIR  = PROJECT_ROOT / "customers"
BUILD_QUEUE    = Path(__file__).parent.parent / "build_queue.json"
ORDERS_FILE    = PROJECT_ROOT / "social" / "orders_seen.json"
STRIPE_API     = "https://api.stripe.com/v1"
BOOKING_URL    = "https://improveyoursite.com/book.html"
ORDER_FORM_URL = "https://improveyoursite.com/order.html"

PACKAGE_MAP = {
    "price_scanfix":  {"name": "Scan & Fix",       "amount": 3000_00, "slug_prefix": "scan"},
    "price_build":    {"name": "Complete Build",    "amount": 5000_00, "slug_prefix": "build"},
    "price_premium":  {"name": "Premium Growth",    "amount": 10000_00, "slug_prefix": "premium"},
    "3000":           {"name": "Scan & Fix",       "amount": 3000_00, "slug_prefix": "scan"},
    "5000":           {"name": "Complete Build",    "amount": 5000_00, "slug_prefix": "build"},
    "10000":          {"name": "Premium Growth",    "amount": 10000_00, "slug_prefix": "premium"},
}


class StripeMonitorAgent(BaseAgent):
    agent_id = "stripe_monitor"
    name     = "Stripe Monitor"

    def run(self):
        mode = os.environ.get("RUN_MODE", "monitor")
        if mode == "diagnose":
            self._run_diagnostics()
            return

        # 1. Poll Stripe for new payments
        self._check_stripe_payments()

        # 2. Scan hello@ inbox for order form submissions
        self._check_order_form_submissions()

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def _run_diagnostics(self):
        tid = self.create_task("diagnostics", "Stripe Monitor diagnostics")
        results = []

        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if stripe_key:
            try:
                req = urllib.request.Request(
                    f"{STRIPE_API}/balance",
                    headers={"Authorization": f"Bearer {stripe_key}"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                avail = data.get("available", [{}])[0].get("amount", 0)
                results.append(f"  ✓ Stripe API connected — balance available: ${avail/100:.2f}")
                self.log_info(f"Diag Stripe: connected, balance ${avail/100:.2f}")
            except Exception as exc:
                results.append(f"  ✗ Stripe API failed: {exc}")
                self.log_warn(f"Diag Stripe: FAILED: {exc}")
        else:
            results.append("  ✗ STRIPE_SECRET_KEY not set")

        hello_user = os.environ.get("HELLO_EMAIL_USER", "")
        hello_pass = os.environ.get("HELLO_EMAIL_PASS", "")
        if hello_user and hello_pass:
            try:
                with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
                    imap.login(hello_user, hello_pass)
                    results.append(f"  ✓ hello@ IMAP connected ({hello_user})")
                    self.log_info(f"Diag IMAP: connected as {hello_user}")
            except Exception as exc:
                results.append(f"  ✗ hello@ IMAP failed: {exc}")
                self.log_warn(f"Diag IMAP: FAILED: {exc}")
        else:
            results.append("  ✗ HELLO_EMAIL_USER / HELLO_EMAIL_PASS not set")

        for key in ["GMAIL_USER", "GMAIL_APP_PASS", "GITHUB_PAT"]:
            val = os.environ.get(key, "")
            results.append(f"  {'✓' if val else '✗'} {key}")

        build_queue_writable = BUILD_QUEUE.parent.exists()
        results.append(f"  {'✓' if build_queue_writable else '✗'} Build queue path writable")
        results.append(f"  {'✓' if CUSTOMERS_DIR.exists() else '✗'} customers/ directory exists")

        self.log_info("Stripe Monitor diagnostics:\n" + "\n".join(results))
        self.complete_task(tid, f"{sum(1 for r in results if '✓' in r)}/{len(results)} checks passed")

    # ── Stripe polling ────────────────────────────────────────────────────────

    def _check_stripe_payments(self):
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe_key:
            self.log_warn("Stripe Monitor: STRIPE_SECRET_KEY not set — skipping Stripe poll")
            return

        seen = self._load_seen_orders()
        tid  = self.create_task("stripe_poll", "Polling Stripe for new payments")
        self.update_progress(tid, 20)

        try:
            # Pull last 20 successful payment intents
            params = urllib.parse.urlencode([
                ("limit", 20),
                ("expand[]", "data.customer"),
            ])
            req = urllib.request.Request(
                f"{STRIPE_API}/payment_intents?{params}",
                headers={"Authorization": f"Bearer {stripe_key}"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())

            new_orders = 0
            for pi in data.get("data", []):
                if pi.get("status") != "succeeded":
                    continue
                pi_id = pi.get("id", "")
                if pi_id in seen:
                    continue

                amount   = pi.get("amount", 0)
                currency = pi.get("currency", "aud").upper()
                customer = pi.get("customer", {})
                email    = customer.get("email", "") if isinstance(customer, dict) else ""
                name     = customer.get("name", "Customer") if isinstance(customer, dict) else "Customer"
                meta     = pi.get("metadata", {})
                package  = self._detect_package(amount, meta)

                self.update_progress(tid, 40 + new_orders * 10)
                self._handle_new_order(pi_id, name, email, amount, currency, package)
                seen.add(pi_id)
                new_orders += 1

            self._save_seen_orders(seen)
            msg = f"{new_orders} new order(s) found" if new_orders else "No new orders"
            self.complete_task(tid, msg)
            self.log_info(f"Stripe Monitor: {msg}")

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Stripe poll failed: {exc}")

    def _handle_new_order(
        self, pi_id: str, name: str, email: str, amount: int, currency: str, package: dict
    ):
        amount_str = f"${amount/100:.0f} {currency}"
        pkg_name   = package.get("name", "Website Package")

        self.log_info(f"Stripe Monitor: NEW ORDER — {name} ({email}) — {pkg_name} {amount_str} [{pi_id}]")

        # Alert James
        self.send_email(
            subject=f"[IYS] NEW ORDER 🎉 — {pkg_name} {amount_str}",
            body=(
                f"New payment received!\n\n"
                f"Customer: {name}\n"
                f"Email:    {email}\n"
                f"Package:  {pkg_name}\n"
                f"Amount:   {amount_str}\n"
                f"Stripe ID: {pi_id}\n\n"
                f"Customer will receive intake form at: {ORDER_FORM_URL}?package={package.get('slug_prefix','build')}\n\n"
                f"Next step: Wait for order form submission, then trigger Builder agent.\n"
                f"Dashboard: http://localhost:8080"
            ),
        )

        # Send customer welcome email
        if email:
            self._send_customer_welcome(name, email, package)

        # Log to DB
        db.content_add(
            content_type="order",
            title=f"Order: {name} — {pkg_name}",
            customer_slug=name.lower().replace(" ", "-")[:20],
            status="delivered",
        )

    def _send_customer_welcome(self, name: str, email: str, package: dict):
        pkg_name    = package.get("name", "your website package")
        intake_url  = f"{ORDER_FORM_URL}?package={package.get('slug_prefix','build')}"
        booking_url = BOOKING_URL
        first_name  = name.split()[0] if name else "there"

        body = (
            f"Hi {first_name},\n\n"
            f"Thanks for choosing ImproveYourSite — your payment for {pkg_name} has been received!\n\n"
            f"Here's what happens next:\n\n"
            f"1. Fill in your business details (takes about 5 minutes):\n"
            f"   {intake_url}\n\n"
            f"2. We'll review your details and get to work right away.\n\n"
            f"3. You'll receive a preview link within 2-4 business days.\n\n"
            f"If you have any questions, just reply to this email.\n\n"
            f"Want to chat through your goals? Book a quick call here:\n"
            f"{booking_url}\n\n"
            f"Looking forward to building something great for your business!\n\n"
            f"James\n"
            f"ImproveYourSite\n"
            f"hello@improveyoursite.com"
        )
        # Send via Gmail SMTP (reuse BaseAgent method but to customer)
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        gmail_user = os.environ.get("GMAIL_USER", "")
        gmail_pass = os.environ.get("GMAIL_APP_PASS", "")
        if not gmail_user or not gmail_pass:
            return

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Your {pkg_name} order is confirmed — next steps"
            msg["From"]    = f"James from ImproveYourSite <{gmail_user}>"
            msg["To"]      = email
            msg["Reply-To"] = "hello@improveyoursite.com"
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, email, msg.as_string())

            self.log_info(f"Stripe Monitor: welcome email sent to {email}")
        except Exception as exc:
            self.log_warn(f"Stripe Monitor: welcome email failed: {exc}")

    def _detect_package(self, amount: int, meta: dict) -> dict:
        """Identify which package was purchased by amount or metadata."""
        # Try metadata first
        pkg_key = meta.get("package") or meta.get("price_id") or ""
        if pkg_key in PACKAGE_MAP:
            return PACKAGE_MAP[pkg_key]
        # Fall back to amount
        amount_key = str(amount // 100)
        return PACKAGE_MAP.get(amount_key, {"name": "Website Package", "slug_prefix": "build"})

    # ── Order form submission parsing ─────────────────────────────────────────

    def _check_order_form_submissions(self):
        """Scan hello@ inbox for formsubmit.co order submissions."""
        hello_user = os.environ.get("HELLO_EMAIL_USER", "")
        hello_pass = os.environ.get("HELLO_EMAIL_PASS", "")

        if not hello_user or not hello_pass:
            return

        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
                imap.login(hello_user, hello_pass)
                imap.select("INBOX")

                # Search for unread formsubmit.co order emails
                _, msgs = imap.search(None, '(UNSEEN SUBJECT "New submission")')
                for num in (msgs[0].split() if msgs[0] else []):
                    _, data = imap.fetch(num, "(RFC822)")
                    raw = data[0][1] if data and data[0] else b""
                    self._parse_order_email(raw)
                    # Mark as seen
                    imap.store(num, "+FLAGS", "\\Seen")

        except Exception as exc:
            self.log_warn(f"Stripe Monitor: IMAP order scan failed: {exc}")

    def _parse_order_email(self, raw: bytes):
        """Parse a formsubmit.co order submission email and write a customer config."""
        try:
            msg = message_from_bytes(raw)

            # Get email body
            body = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break

            # Extract fields (formsubmit.co sends as key: value pairs)
            def extract(pattern: str, default: str = "") -> str:
                m = re.search(pattern, body, re.IGNORECASE)
                return m.group(1).strip() if m else default

            business_name = extract(r"business[_ ]?name[:\s]+(.+)")
            contact_name  = extract(r"(?:your )?name[:\s]+(.+)")
            email_addr    = extract(r"email[:\s]+([\w.@+\-]+)")
            phone         = extract(r"phone[:\s]+([\d\s\+\-\(\)]+)")
            suburb        = extract(r"suburb[:\s]+(.+)")
            state         = extract(r"state[:\s]+(.+)")
            package_slug  = extract(r"package[:\s]+(.+)")
            tagline       = extract(r"tagline[:\s]+(.+)")

            if not business_name:
                return  # not a valid order form

            slug = re.sub(r"[^a-z0-9]+", "-", business_name.lower()).strip("-")[:30]
            config = {
                "BUSINESS_NAME":    business_name,
                "CONTACT_NAME":     contact_name,
                "EMAIL":            email_addr,
                "PHONE":            phone,
                "SUBURB":           suburb,
                "STATE":            state or "NSW",
                "TAGLINE":          tagline or f"Quality {business_name} services",
                "PACKAGE":          package_slug,
                "SLUG":             slug,
                "COLOR_PRIMARY":    "#5b4dff",
                "COLOR_BG":         "#ffffff",
                "META_TITLE":       f"{business_name} | Professional Website",
                "META_DESCRIPTION": f"Welcome to {business_name}. Contact us today.",
            }

            # Write config file
            CUSTOMERS_DIR.mkdir(exist_ok=True)
            cfg_file = CUSTOMERS_DIR / f"{slug}.json"
            cfg_file.write_text(json.dumps(config, indent=2))

            # Enqueue build job
            self._enqueue_build(str(cfg_file))

            self.log_info(
                f"Stripe Monitor: order form parsed for '{business_name}' → {cfg_file.name}"
            )
            self.send_email(
                subject=f"[IYS] Order form received — {business_name}",
                body=(
                    f"Order form submitted by {contact_name} ({email_addr}).\n\n"
                    f"Business: {business_name}\n"
                    f"Suburb: {suburb}, {state}\n"
                    f"Package: {package_slug}\n\n"
                    f"Config written to: {cfg_file}\n"
                    f"Build queued automatically.\n\n"
                    f"Dashboard: http://localhost:8080"
                ),
            )

        except Exception as exc:
            self.log_warn(f"Stripe Monitor: order form parse error: {exc}")

    # ── Build queue helpers ───────────────────────────────────────────────────

    def _enqueue_build(self, config_path: str):
        """Add a config to the builder agent's queue."""
        jobs = []
        if BUILD_QUEUE.exists():
            try:
                jobs = json.loads(BUILD_QUEUE.read_text())
            except Exception:
                jobs = []
        jobs.append({"config": config_path})
        BUILD_QUEUE.write_text(json.dumps(jobs, indent=2))
        self.log_info(f"Stripe Monitor: queued build for {config_path}")

    # ── Seen orders persistence ───────────────────────────────────────────────

    def _load_seen_orders(self) -> set:
        if not ORDERS_FILE.exists():
            return set()
        try:
            return set(json.loads(ORDERS_FILE.read_text()))
        except Exception:
            return set()

    def _save_seen_orders(self, seen: set):
        ORDERS_FILE.parent.mkdir(exist_ok=True)
        ORDERS_FILE.write_text(json.dumps(list(seen)))
