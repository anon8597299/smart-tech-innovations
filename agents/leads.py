"""
agents/leads.py — Leads Agent

Autonomously sources Australian SMB prospects, generates personalised cold
outreach emails via Claude, sends them via Gmail, and tracks follow-ups.

Pipeline:
  1. Source leads from Google Places API (or fallback: local industries list)
  2. Filter out anyone already in the DB (no double-contact)
  3. Audit their website with a lightweight HEAD/GET request
  4. Generate a personalised email via Claude (short, direct, no fluff)
  5. Send via Gmail SMTP
  6. Log to leads DB table for follow-up tracking

Follow-up schedule (run by scheduler):
  • Day 4  — follow-up #1 if no reply
  • Day 10 — follow-up #2 + mark cold if still no reply

Schedule: Daily 10:00 AM AEST (new leads) + Tuesday 11:00 AM (follow-ups)
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from agents.base import BaseAgent
from dashboard import db

import anthropic

# ── Config ───────────────────────────────────────────────────────────────────

DAILY_LIMIT      = 10   # Max new outreach emails per day
FOLLOW_UP_LIMIT  = 20   # Max follow-ups per run
BOOKING_URL      = "https://calendly.com/improveyoursite/discovery"
FROM_NAME        = "James from ImproveYourSite"
REPLY_TO         = "hello@improveyoursite.com"

# Australian industries to target — trades & local services that typically
# have weak websites and rely on word-of-mouth or outdated directories.
TARGET_INDUSTRIES = [
    "plumber",
    "electrician",
    "builder",
    "landscaper",
    "mechanic",
    "accountant",
    "physiotherapist",
    "chiropractor",
    "dentist",
    "optometrist",
    "hairdresser",
    "beauty salon",
    "real estate agent",
    "mortgage broker",
    "financial planner",
    "cleaning service",
    "pest control",
    "solar installer",
    "security company",
    "cafe",
]

AU_CITIES = [
    "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
    "Canberra", "Newcastle", "Wollongong", "Geelong", "Gold Coast",
    "Sunshine Coast", "Hobart", "Darwin", "Townsville", "Cairns",
    "Bendigo", "Ballarat", "Toowoomba", "Launceston", "Albury",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _claude(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": prompt}]
    kwargs = {"model": "claude-sonnet-4-6", "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def _audit_website(url: str) -> dict:
    """Quick surface-level audit — check if site loads, mobile-meta, speed hint."""
    result = {"loads": False, "has_mobile_meta": False, "slow": False, "issues": []}
    if not url:
        result["issues"].append("no website listed")
        return result
    try:
        if not url.startswith("http"):
            url = "https://" + url
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IYS-audit/1.0)"},
        )
        start = time.time()
        with urllib.request.urlopen(req, timeout=8) as resp:
            elapsed = time.time() - start
            html = resp.read(30_000).decode("utf-8", errors="ignore")
        result["loads"] = True
        if elapsed > 3.5:
            result["slow"] = True
            result["issues"].append(f"loads slowly ({elapsed:.1f}s)")
        if 'name="viewport"' not in html and "viewport" not in html:
            result["has_mobile_meta"] = False
            result["issues"].append("missing mobile viewport meta tag")
        else:
            result["has_mobile_meta"] = True
        if "https://" not in html[:5000]:
            result["issues"].append("possible mixed-content or no HTTPS links")
        if not any(kw in html.lower() for kw in ["contact", "phone", "email", "call us"]):
            result["issues"].append("no visible contact call-to-action found")
    except Exception as exc:
        result["issues"].append(f"site unreachable: {exc}")
    return result


def _google_places_search(keyword: str, location: str) -> list[dict]:
    """
    Search Google Places API for businesses matching keyword in location.
    Returns list of {name, address, website, phone, place_id}.
    Falls back to empty list if API key not set.
    """
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return []

    query = f"{keyword} in {location} Australia"
    url = (
        "https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={urllib.parse.quote(query)}&key={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for r in data.get("results", [])[:5]:
            results.append({
                "name": r.get("name", ""),
                "address": r.get("formatted_address", ""),
                "place_id": r.get("place_id", ""),
                "website": "",  # textsearch doesn't return website — need details call
                "phone": "",
            })
        return results
    except Exception:
        return []


def _generate_lead_targets(n: int = 20) -> list[dict]:
    """
    Build a list of candidate leads to research.
    Uses Google Places if key available, otherwise generates plausible AU business
    names for manual enrichment — these act as seeds to find real businesses.
    """
    targets = []
    tried_industries = set()

    # Shuffle to vary what we try each day
    industries = TARGET_INDUSTRIES.copy()
    random.shuffle(industries)
    cities = AU_CITIES.copy()
    random.shuffle(cities)

    for industry in industries:
        if len(targets) >= n:
            break
        city = cities[len(tried_industries) % len(cities)]
        tried_industries.add(industry)

        places = _google_places_search(industry, city)
        if places:
            targets.extend(places[:2])
        else:
            # Fallback: synthesise a realistic AU business record
            # Real enrichment step happens in the agent's sourcing phase
            targets.append({
                "name": f"Local {industry.title()} — {city}",
                "industry": industry,
                "city": city,
                "address": f"{city}, Australia",
                "website": "",
                "phone": "",
                "place_id": f"synthetic_{industry}_{city}".replace(" ", "_"),
            })

    return targets[:n]


# ── Email generation ──────────────────────────────────────────────────────────

_SYSTEM = """\
You are a direct, plain-talking Australian copywriter writing short cold outreach
emails on behalf of a web design agency called ImproveYourSite.

Rules:
- 3 short paragraphs, max 120 words total
- No subject line — just the body
- No "Dear Sir/Madam" — use their first name or business name
- Mention one specific issue found on their website (from the audit notes)
- Don't mention price or packages — just offer a free 20-min audit call
- Australian English, confident but not pushy
- End with a single CTA: book a call at the provided URL
- No emojis, no exclamation marks
"""


def _generate_email_body(
    business_name: str,
    industry: str,
    city: str,
    audit_issues: list[str],
    follow_up_num: int = 0,
) -> str:
    issue_text = audit_issues[0] if audit_issues else "the site could do more to convert visitors"
    if follow_up_num == 0:
        prompt = f"""\
Business: {business_name}
Industry: {industry}
City: {city}
Website issue: {issue_text}
Booking URL: {BOOKING_URL}

Write the cold outreach email body."""
    else:
        prompt = f"""\
Business: {business_name}
Industry: {industry}
City: {city}
Follow-up number: {follow_up_num}
Previous email sent about: {issue_text}
Booking URL: {BOOKING_URL}

Write a short follow-up email (2 paragraphs max, 70 words). Reference the earlier
email briefly, keep it warm and direct. Not desperate."""

    return _claude(prompt, system=_SYSTEM)


def _generate_subject(business_name: str, audit_issues: list[str], follow_up: int = 0) -> str:
    if follow_up > 0:
        return f"Re: Quick question about {business_name}'s website"
    issue = audit_issues[0] if audit_issues else "your website"
    # Short, plain subject lines outperform clever ones for cold email
    subjects = [
        f"Quick question about {business_name}'s website",
        f"{business_name} — spotted something on your site",
        f"Your website ({issue[:40]})",
        f"Two things about {business_name}.com.au",
    ]
    return random.choice(subjects)


# ── DB helpers (leads table) ──────────────────────────────────────────────────
# We add these to dashboard/db.py if not already present.

def _ensure_leads_table():
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            industry      TEXT,
            city          TEXT,
            email         TEXT,
            website       TEXT,
            phone         TEXT,
            place_id      TEXT UNIQUE,
            audit_issues  TEXT,
            status        TEXT DEFAULT 'new',
            email_count   INTEGER DEFAULT 0,
            last_emailed  TEXT,
            notes         TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _lead_exists(place_id: str) -> bool:
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    row = conn.execute(
        "SELECT id FROM leads WHERE place_id = ?", (place_id,)
    ).fetchone()
    conn.close()
    return row is not None


def _insert_lead(lead: dict) -> int:
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    cur = conn.execute(
        """INSERT OR IGNORE INTO leads
           (business_name, industry, city, email, website, phone, place_id,
            audit_issues, status, email_count, last_emailed)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            lead["business_name"], lead.get("industry", ""), lead.get("city", ""),
            lead.get("email", ""), lead.get("website", ""), lead.get("phone", ""),
            lead.get("place_id", ""), json.dumps(lead.get("audit_issues", [])),
            "contacted", 1, date.today().isoformat(),
        ),
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def _leads_due_followup(follow_up_num: int, days_since: int) -> list[dict]:
    """Return leads where email_count == follow_up_num and last_emailed was ~days_since ago."""
    import sqlite3
    cutoff = (date.today() - timedelta(days=days_since)).isoformat()
    conn = sqlite3.connect(db.DB_PATH)
    rows = conn.execute(
        """SELECT id, business_name, industry, city, email, audit_issues
           FROM leads
           WHERE status = 'contacted'
             AND email_count = ?
             AND last_emailed <= ?""",
        (follow_up_num, cutoff),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "business_name": r[1], "industry": r[2],
            "city": r[3], "email": r[4],
            "audit_issues": json.loads(r[5] or "[]"),
        }
        for r in rows
    ]


def _mark_followup_sent(lead_id: int, new_count: int, mark_cold: bool = False):
    import sqlite3
    status = "cold" if mark_cold else "contacted"
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute(
        "UPDATE leads SET email_count=?, last_emailed=?, status=? WHERE id=?",
        (new_count, date.today().isoformat(), status, lead_id),
    )
    conn.commit()
    conn.close()


# ── Agent ─────────────────────────────────────────────────────────────────────

class LeadsAgent(BaseAgent):
    agent_id = "leads"
    name     = "Leads"

    def run(self):
        _ensure_leads_table()
        self._run_new_outreach()
        self._run_followups()

    # ── New outreach ──────────────────────────────────────────────────────

    def _run_new_outreach(self):
        tid = self.create_task("leads", "Source & email new prospects")
        sent = 0

        targets = _generate_lead_targets(n=DAILY_LIMIT * 3)
        self.update_progress(tid, 10)

        for prospect in targets:
            if sent >= DAILY_LIMIT:
                break

            place_id = prospect.get("place_id", "")
            if place_id and _lead_exists(place_id):
                continue

            # We need a real email to send — skip synthetic entries that have none
            email = prospect.get("email", "").strip()
            if not email:
                # Log as sourced but unemailed — James can enrich manually
                self.log_info(
                    f"Sourced (no email yet): {prospect.get('name')} — {prospect.get('city')}"
                )
                continue

            website  = prospect.get("website", "")
            industry = prospect.get("industry", "business")
            city     = prospect.get("city", "Australia")
            name     = prospect.get("name", "there")

            audit    = _audit_website(website)
            issues   = audit["issues"] or ["the site could do more to convert visitors"]

            body     = _generate_email_body(name, industry, city, issues)
            subject  = _generate_subject(name, issues)

            self._send_outreach(
                to_email=email,
                to_name=name,
                subject=subject,
                body=body,
            )

            _insert_lead({
                "business_name": name,
                "industry": industry,
                "city": city,
                "email": email,
                "website": website,
                "phone": prospect.get("phone", ""),
                "place_id": place_id,
                "audit_issues": issues,
            })

            self.log_info(f"Outreach sent → {name} ({email}) — issues: {', '.join(issues[:2])}")
            sent += 1
            time.sleep(2)  # be polite to SMTP relay

        self.update_progress(tid, 80)
        self.complete_task(tid, preview=f"{sent} new outreach email(s) sent")
        self.log_info(f"Leads: {sent} new emails sent")

    # ── Follow-ups ────────────────────────────────────────────────────────

    def _run_followups(self):
        tid = self.create_task("leads", "Follow-up sequence check")
        sent = 0

        # Follow-up #1: sent 4 days after first contact (email_count == 1)
        for lead in _leads_due_followup(follow_up_num=1, days_since=4):
            if sent >= FOLLOW_UP_LIMIT:
                break
            body    = _generate_email_body(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=1,
            )
            subject = _generate_subject(lead["business_name"], lead["audit_issues"], follow_up=1)
            self._send_outreach(
                to_email=lead["email"],
                to_name=lead["business_name"],
                subject=subject,
                body=body,
            )
            _mark_followup_sent(lead["id"], new_count=2)
            self.log_info(f"Follow-up #1 → {lead['business_name']} ({lead['email']})")
            sent += 1
            time.sleep(2)

        # Follow-up #2: sent 10 days after first contact (email_count == 2), then go cold
        for lead in _leads_due_followup(follow_up_num=2, days_since=6):
            if sent >= FOLLOW_UP_LIMIT:
                break
            body    = _generate_email_body(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=2,
            )
            subject = _generate_subject(lead["business_name"], lead["audit_issues"], follow_up=2)
            self._send_outreach(
                to_email=lead["email"],
                to_name=lead["business_name"],
                subject=subject,
                body=body,
            )
            _mark_followup_sent(lead["id"], new_count=3, mark_cold=True)
            self.log_info(f"Follow-up #2 (final) → {lead['business_name']} — marking cold")
            sent += 1
            time.sleep(2)

        self.complete_task(tid, preview=f"{sent} follow-up(s) sent")

    # ── Email sender ──────────────────────────────────────────────────────

    def _send_outreach(self, to_email: str, to_name: str, subject: str, body: str):
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        gmail_user = os.environ.get("GMAIL_USER", "")
        gmail_pass = os.environ.get("GMAIL_APP_PASS", "")

        if not gmail_user or not gmail_pass:
            self.log_warn(f"Email skipped (no Gmail creds) — {to_name} <{to_email}>")
            return

        # Plain-text cold email — HTML formatting hurts deliverability
        msg = MIMEMultipart("alternative")
        msg["Subject"]  = subject
        msg["From"]     = f"{FROM_NAME} <{gmail_user}>"
        msg["To"]       = f"{to_name} <{to_email}>"
        msg["Reply-To"] = REPLY_TO
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
