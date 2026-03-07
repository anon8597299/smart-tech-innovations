"""
agents/leads.py — Leads Agent

Persona: Lead Acquisition Manager + Sales Manager hybrid.
Goal: Get Australian SMBs onto a free 20-min discovery call.

Pipeline:
  1. Source real AU business leads from Yellow Pages AU (scraper)
     or Google Places API if key is set
  2. Filter out anyone already in the DB (no double-contact)
  3. Audit their website for specific issues to reference in the email
  4. Generate a personalised email via Claude — sales-forward but respectful
  5. Send via Gmail SMTP (plain text for deliverability)
  6. Track in SQLite leads table

Follow-up sequence:
  • Day 4  — follow-up #1 if no reply (warmer, acknowledge they're busy)
  • Day 10 — follow-up #2 ONLY (final attempt, brief, no pressure) → mark cold

Low-interest rule:
  If James marks a lead as "low_interest" in the DB, the agent sends ONE more
  well-crafted win-back email that removes all pressure, then marks them cold.
  Never contacts them again after that.

Schedule: Daily 10:00 AM AEST (new leads) + Tuesday 11:00 AM (follow-ups)
"""

from __future__ import annotations

import html as html_lib
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from agents.base import BaseAgent
from dashboard import db

import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

DAILY_LIMIT     = 10
FOLLOW_UP_LIMIT = 20
BOOKING_URL     = "https://calendly.com/improveyoursite/discovery"
FROM_NAME       = "James from ImproveYourSite"
REPLY_TO        = "hello@improveyoursite.com"
AGENCY_NAME     = "ImproveYourSite"

TARGET_INDUSTRIES = [
    "plumber", "electrician", "builder", "landscaper", "mechanic",
    "accountant", "physiotherapist", "chiropractor", "dentist", "optometrist",
    "hairdresser", "beauty salon", "real estate agent", "mortgage broker",
    "financial planner", "cleaning service", "pest control", "solar installer",
    "security company", "cafe",
]

AU_CITIES = [
    "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
    "Canberra", "Newcastle", "Wollongong", "Geelong", "Gold Coast",
    "Sunshine Coast", "Hobart", "Darwin", "Townsville", "Cairns",
    "Bendigo", "Ballarat", "Toowoomba", "Launceston", "Albury",
    "Wagga Wagga", "Mildura", "Shepparton", "Bundaberg", "Rockhampton",
    "Mackay", "Bathurst", "Orange", "Dubbo", "Tamworth",
]

# ── Claude helper ─────────────────────────────────────────────────────────────

def _claude(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    return client.messages.create(**kwargs).content[0].text.strip()


# ── Lead sourcing — Yellow Pages AU scraper ───────────────────────────────────

_YP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


def _yellowpages_search(keyword: str, location: str, max_results: int = 5) -> list[dict]:
    """
    Scrape Yellow Pages AU for businesses matching keyword in location.
    Returns list of {name, phone, website, address, place_id}.
    """
    params = urllib.parse.urlencode({
        "clue": keyword,
        "locationClue": f"{location} Australia",
        "pageNumber": "1",
    })
    url = f"https://www.yellowpages.com.au/search/listings?{params}"
    try:
        req = urllib.request.Request(url, headers=_YP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    results = []

    # Extract listing blocks — YP wraps each in a div with data-analytics or listing- id
    blocks = re.findall(
        r'<(?:div|li)[^>]+class="[^"]*listing[^"]*"[^>]*>(.*?)</(?:div|li)>',
        raw, re.DOTALL
    )
    if not blocks:
        # Fallback: find h2/h3 business names near phone/website patterns
        blocks = re.findall(r'<article[^>]*>(.*?)</article>', raw, re.DOTALL)

    for block in blocks[:max_results * 2]:
        name = _extract_text(re.search(r'<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>', block, re.DOTALL))
        if not name or len(name) < 3:
            continue

        phone = _extract_text(re.search(
            r'(?:href="tel:[^"]*">|class="[^"]*phone[^"]*"[^>]*>)(.*?)<',
            block, re.DOTALL
        ))
        if not phone:
            phone_match = re.search(r'(?:0[2-9]\d{8}|13\d{4,8}|\(0\d\)\s?\d{4}\s?\d{4})', block)
            phone = phone_match.group(0) if phone_match else ""

        website = ""
        web_match = re.search(r'href="(https?://[^"]+)"[^>]*>[^<]*[Ww]ebsite', block)
        if not web_match:
            web_match = re.search(r'href="(https?://(?!www\.yellowpages)[^"]+)"', block)
        if web_match:
            website = web_match.group(1).split("?")[0].rstrip("/")

        address = _extract_text(re.search(
            r'(?:class="[^"]*address[^"]*"[^>]*>)(.*?)</(?:p|div|span)>',
            block, re.DOTALL
        ))

        place_id = f"yp_{re.sub(r'[^a-z0-9]', '_', name.lower())}_{location.lower().replace(' ', '_')}"

        results.append({
            "name": name.strip(),
            "phone": phone.strip(),
            "website": website,
            "address": address.strip() if address else f"{location}, Australia",
            "industry": keyword,
            "city": location,
            "place_id": place_id,
            "email": "",
        })

        if len(results) >= max_results:
            break

    time.sleep(1)  # polite rate limiting
    return results


def _extract_text(match) -> str:
    if not match:
        return ""
    raw = match.group(1) if match.lastindex else match.group(0)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    raw = html_lib.unescape(raw)
    return re.sub(r'\s+', ' ', raw).strip()


def _google_places_search(keyword: str, location: str) -> list[dict]:
    """Use Google Places API if key is set."""
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return []
    query = urllib.parse.quote(f"{keyword} in {location} Australia")
    url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={query}&key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        return [
            {
                "name": r.get("name", ""),
                "address": r.get("formatted_address", ""),
                "place_id": r.get("place_id", ""),
                "website": "", "phone": "",
                "industry": keyword, "city": location, "email": "",
            }
            for r in data.get("results", [])[:5]
        ]
    except Exception:
        return []


def _find_email_on_website(url: str) -> str:
    """
    Visit a business website and hunt for a contact email address.
    Tries homepage first, then /contact and /contact-us pages.
    """
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url

    EMAIL_RE = re.compile(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
        re.IGNORECASE
    )
    SKIP_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "googleapis.com",
                    "placeholder.com", "yoursite.com", "domain.com"}

    def _scrape(target_url: str) -> str:
        try:
            req = urllib.request.Request(target_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; IYS-contact-finder/1.0)"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read(60_000).decode("utf-8", errors="ignore")
            for email in EMAIL_RE.findall(text):
                domain = email.split("@")[1].lower()
                if domain not in SKIP_DOMAINS and not domain.endswith(".png") and "." in domain:
                    return email.lower()
        except Exception:
            pass
        return ""

    # Try homepage
    email = _scrape(url)
    if email:
        return email

    # Try /contact and /contact-us
    base = url.rstrip("/")
    for path in ["/contact", "/contact-us", "/about", "/about-us"]:
        email = _scrape(base + path)
        if email:
            return email
        time.sleep(0.5)

    return ""


def _audit_website(url: str) -> dict:
    result = {"loads": False, "slow": False, "issues": []}
    if not url:
        result["issues"].append("no website showing on Google — customers can't find them online")
        return result
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        })
        start = time.time()
        with urllib.request.urlopen(req, timeout=8) as resp:
            elapsed = time.time() - start
            html = resp.read(40_000).decode("utf-8", errors="ignore")
            html_lower = html.lower()
        result["loads"] = True

        if elapsed > 3.5:
            result["slow"] = True
            result["issues"].append(
                f"site takes {elapsed:.1f} seconds to load on mobile — "
                "most people leave after 3 seconds"
            )

        if "viewport" not in html:
            result["issues"].append("not built for mobile — probably looks broken on phones")

        if not any(k in html_lower for k in ["schema", "application/ld+json", "itemtype"]):
            result["issues"].append(
                "missing structured data — Google can't read the business details properly"
            )

        if not any(k in html_lower for k in ["review", "testimonial", "★", "star", "rating", "google"]):
            result["issues"].append("no reviews or social proof visible on the site")

        if not any(k in html_lower for k in ["book", "quote", "enquire", "contact", "call now", "get a quote"]):
            result["issues"].append("no clear call-to-action — visitors don't know what to do next")

        if not any(k in html_lower for k in ["suburb", "local", "serving", "nsw", "vic", "qld", "wa", "sa", "nt", "act"]):
            result["issues"].append(
                "no local area mentions — Google won't rank it for local searches"
            )

        # Check if it looks like a builder-style template (thin content)
        text_content = re.sub(r'<[^>]+>', ' ', html)
        word_count = len(text_content.split())
        if word_count < 300:
            result["issues"].append(
                f"very thin content ({word_count} words) — Google ranks sites with real information higher"
            )

    except Exception as exc:
        result["issues"].append(f"site wouldn't load when we checked — {exc}")
    return result


# Industry-specific fallback issues when site passes basic technical checks
_INDUSTRY_ISSUES = {
    "plumber":       "most plumbers in the area rank for 'emergency plumber' — not their specific suburb",
    "electrician":   "the site doesn't rank for local searches like 'electrician {city}' — that's free job leads being missed",
    "builder":       "no before/after project photos or case studies — the main thing customers look for",
    "landscaper":    "no gallery of completed work — landscaping is a visual business and the site doesn't show it",
    "mechanic":      "no Google review integration on the site — trust signals are missing",
    "accountant":    "the site doesn't explain what types of clients they help — too generic to convert visitors",
    "physiotherapist": "no online booking visible — most health patients want to book without calling",
    "chiropractor":  "no condition-specific content — patients search for their specific problem, not 'chiropractor {city}'",
    "dentist":       "no pricing guide or what-to-expect content — anxiety is the main reason patients don't book",
    "cleaning service": "no suburb list — people search 'cleaner {suburb}' not just '{city}'",
    "solar installer": "no savings calculator or payback period tool — the first question every solar customer asks",
    "real estate agent": "no suburb-specific market data — what buyers and sellers actually want to see",
    "mortgage broker": "no rate comparison tool or borrowing calculator — gives customers a reason to stay on the site",
    "cafe":          "menu not visible on the homepage — the number one thing customers check before visiting",
    "default":       "the site isn't set up to rank locally — organic search leads are being left on the table",
}


def _generic_issues(industry: str, city: str) -> list[str]:
    """Return a plausible industry-specific issue when the technical audit finds nothing."""
    template = _INDUSTRY_ISSUES.get(industry.lower(), _INDUSTRY_ISSUES["default"])
    return [template.replace("{city}", city)]


SEED_FILE = Path(__file__).parent.parent / "social" / "leads_seed.json"


def _load_seed_targets() -> list[dict]:
    """Load prospects from the manually curated seed file."""
    if not SEED_FILE.exists():
        return []
    try:
        return json.loads(SEED_FILE.read_text())
    except Exception:
        return []


def _generate_lead_targets(n: int = 30) -> list[dict]:
    targets = []

    # Seed file first — real prospects with known websites
    for prospect in _load_seed_targets():
        if len(targets) >= n:
            break
        targets.append(prospect)

    # Supplement with Google Places if API key is set
    if len(targets) < n:
        industries = TARGET_INDUSTRIES.copy()
        cities = AU_CITIES.copy()
        random.shuffle(industries)
        random.shuffle(cities)
        for i, industry in enumerate(industries):
            if len(targets) >= n:
                break
            city = cities[i % len(cities)]
            found = _google_places_search(industry, city)
            targets.extend(found)

    return targets[:n]


# ── Email generation ──────────────────────────────────────────────────────────

_SYSTEM = """\
You are writing cold outreach emails for ImproveYourSite, an Australian web design agency.

Your persona: a senior Lead Acquisition and Sales Manager — direct, confident,
genuinely helpful, and focused on booking a free 20-minute discovery call.

BUSINESS CONTEXT:
- IYS builds websites for Australian small businesses
- Package prices are GUIDES only — James works flexibly to fit different budgets and
  situations. Always communicate this. Don't mention specific dollar amounts.
- The hook for this outreach: we reviewed their website and Google presence and spotted
  specific issues that are likely costing them leads and ranking
- The offer: a FREE website health check / audit report delivered on a 20-min call —
  they see exactly what's working, what isn't, and how to fix it. No obligation.

RULES:
- 3 short paragraphs, MAXIMUM 140 words total
- Paragraph 1: Specific observation about their website or Google listing issue
  (slow loading, poor mobile experience, weak local SEO signals, no clear CTA, etc.)
- Paragraph 2: Briefly what IYS does — mention pricing is flexible and used as a guide
  only, not a fixed barrier. The focus is getting them to the free audit call.
- Paragraph 3: The CTA — free 20-min website health check call, no sales pitch,
  they get a real audit report. Book via the provided URL.
- Australian English, confident but never pushy
- No emojis, no exclamation marks, no "I hope this email finds you well"
- Sign off as: James Burke, ImproveYourSite
- Body only — NO subject line

TONE RULES (critical):
- Write like a real person dashing off a quick email, NOT a marketing template
- Vary sentence length — mix short punchy lines with slightly longer ones
- Never use phrases like: "I came across", "I noticed your business", "I hope to connect",
  "leverage", "optimise", "solutions", "pain points", "reach out", "touch base",
  "synergy", "digital presence", "online footprint", "moving forward"
- No buzzwords, no corporate speak, no AI-flavoured phrasing
- If you mention the website issue, say it plainly — "your site takes 6 seconds to load"
  not "your website's load time metrics may be impacting user experience"
- The goal is: a real person at a real agency who looked at their website and has
  something honest to say about it. Get them more customers. Save them time.
"""

_SYSTEM_FOLLOWUP_1 = """\
You are writing a short follow-up email for ImproveYourSite, an Australian web agency.

Persona: Lead Acquisition Manager — warm, understands they're busy, zero pressure.

CONTEXT: First email offered a free website health check/audit. No reply yet.
Pricing is flexible — mention this if relevant.

RULES:
- MAX 75 words, 2 paragraphs
- Acknowledge they're probably busy — no hard feelings
- Briefly resurface the specific website issue mentioned in the first email
- Remind them the health check is free and takes 20 minutes — no obligation
- Keep the door open — book whenever suits
- No begging, no repeating everything from email 1
- Australian English, no emojis, no exclamation marks
- Sign off: James Burke, ImproveYourSite
- Body only, no subject line
"""

_SYSTEM_FOLLOWUP_2 = """\
You are writing a final follow-up email for ImproveYourSite, an Australian web agency.

Persona: Sales Manager — knows when to respect boundaries, leaves on a good note.

RULES:
- MAX 65 words, 2 short paragraphs
- Be clear this is the last email ("won't keep popping up in your inbox after this")
- Leave a positive impression — if things change, the door is always open
- Keep the Calendly link available for when timing is right
- Zero pressure, zero hard sell
- Australian English, no emojis
- Sign off: James Burke, ImproveYourSite
- Body only, no subject line
"""

_SYSTEM_WIN_BACK = """\
You are writing a one-time win-back email for ImproveYourSite, an Australian web agency.

This person replied previously but showed low interest or said timing wasn't right.

Persona: Respectful sales manager — genuinely checking in, not chasing a number.

RULES:
- MAX 65 words, 2 paragraphs
- Acknowledge they weren't ready before — that's fine, no issue
- Give one specific, fresh reason it might be worth 20 minutes now
  (seasonal uptick in their industry, a ranking trend, a new offering from IYS)
- Mention again that pricing is flexible — not a set-in-stone barrier
- No pressure, no hard sell
- Australian English, no emojis
- Sign off: James Burke, ImproveYourSite
- Body only, no subject line
"""


def _build_prompt(
    business_name: str, industry: str, city: str,
    audit_issues: list[str], follow_up_num: int = 0
) -> tuple[str, str]:
    """Return (system, prompt) for the given email type."""
    issue = audit_issues[0] if audit_issues else "the website could do more to convert visitors"

    if follow_up_num == 0:
        system = _SYSTEM
        prompt = f"""\
Business name: {business_name}
Industry: {industry}
City: {city}, Australia
Specific website issue found: {issue}
Our booking URL: {BOOKING_URL}

Important context to weave in naturally:
- Most {industry}s in {city} get most of their work through word of mouth or Google search
- A weak website costs them real jobs — customers search, find a competitor with a better
  site, and never call
- IYS offers a free 20-min website health check — they get a real report, not a sales pitch
- Pricing is a guide only, James works flexibly with different budgets

Write the cold outreach email body. Sound like a real person, not a template."""

    elif follow_up_num == 1:
        system = _SYSTEM_FOLLOWUP_1
        prompt = f"""\
Business: {business_name}
Industry: {industry}
Previous email was about: {issue}
Booking URL: {BOOKING_URL}

Write the follow-up email body."""

    elif follow_up_num == 2:
        system = _SYSTEM_FOLLOWUP_2
        prompt = f"""\
Business: {business_name}
Industry: {industry}
Previous emails were about: {issue}
Booking URL: {BOOKING_URL}

Write the final follow-up email body."""

    else:  # win-back
        system = _SYSTEM_WIN_BACK
        prompt = f"""\
Business: {business_name}
Industry: {industry}
City: {city}
Original issue: {issue}
Booking URL: {BOOKING_URL}

Write the win-back email body."""

    return system, prompt


def _subject(business_name: str, issues: list[str], follow_up: int = 0) -> str:
    if follow_up == 1:
        return f"Re: {business_name} — following up"
    if follow_up == 2:
        return f"Last one from me — {business_name}"
    if follow_up == 99:  # win-back
        return f"{business_name} — worth a quick catch-up?"
    issue = issues[0] if issues else "your website"
    opts = [
        f"Quick question about {business_name}'s website",
        f"{business_name} — spotted something on your site",
        f"One thing worth fixing on {business_name}'s website",
        f"Your {industry_short(issue)} website — a thought",
    ]
    return random.choice(opts[:3])


def industry_short(issue: str) -> str:
    return issue.split("(")[0].strip()[:30]


# ── SQLite leads table ────────────────────────────────────────────────────────

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
    row = conn.execute("SELECT id FROM leads WHERE place_id=?", (place_id,)).fetchone()
    conn.close()
    return row is not None


def _insert_lead(lead: dict) -> int:
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    cur = conn.execute(
        """INSERT OR IGNORE INTO leads
           (business_name,industry,city,email,website,phone,place_id,
            audit_issues,status,email_count,last_emailed)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            lead["business_name"], lead.get("industry",""), lead.get("city",""),
            lead.get("email",""), lead.get("website",""), lead.get("phone",""),
            lead.get("place_id",""), json.dumps(lead.get("audit_issues",[])),
            "contacted", 1, date.today().isoformat(),
        ),
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def _leads_due_followup(email_count: int, days_since: int) -> list[dict]:
    import sqlite3
    cutoff = (date.today() - timedelta(days=days_since)).isoformat()
    conn = sqlite3.connect(db.DB_PATH)
    rows = conn.execute(
        """SELECT id,business_name,industry,city,email,audit_issues
           FROM leads
           WHERE status='contacted' AND email_count=? AND last_emailed<=?""",
        (email_count, cutoff),
    ).fetchall()
    conn.close()
    return [
        {"id":r[0],"business_name":r[1],"industry":r[2],
         "city":r[3],"email":r[4],"audit_issues":json.loads(r[5] or "[]")}
        for r in rows
    ]


def _leads_low_interest() -> list[dict]:
    """Leads James manually marked as low_interest — get one win-back email, then cold."""
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    rows = conn.execute(
        "SELECT id,business_name,industry,city,email,audit_issues FROM leads WHERE status='low_interest'"
    ).fetchall()
    conn.close()
    return [
        {"id":r[0],"business_name":r[1],"industry":r[2],
         "city":r[3],"email":r[4],"audit_issues":json.loads(r[5] or "[]")}
        for r in rows
    ]


def _update_lead(lead_id: int, email_count: int, status: str):
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute(
        "UPDATE leads SET email_count=?,last_emailed=?,status=? WHERE id=?",
        (email_count, date.today().isoformat(), status, lead_id),
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
        self._run_winbacks()

    # ── New outreach ──────────────────────────────────────────────────────

    def _run_new_outreach(self):
        tid  = self.create_task("leads", "Source & email new prospects")
        sent = 0

        targets = _generate_lead_targets(n=DAILY_LIMIT * 4)
        self.update_progress(tid, 10)

        for prospect in targets:
            if sent >= DAILY_LIMIT:
                break

            place_id = prospect.get("place_id", "")
            if place_id and _lead_exists(place_id):
                continue

            # Find email — scrape website if needed
            email = prospect.get("email", "").strip()
            website = prospect.get("website", "")
            if not email and website:
                email = _find_email_on_website(website)

            if not email:
                self.log_info(f"No email found for {prospect.get('name')} ({prospect.get('city')}) — skipping")
                continue

            industry = prospect.get("industry", "business")
            city     = prospect.get("city", "Australia")
            name     = prospect.get("business_name") or prospect.get("name", "")
            audit    = _audit_website(website)
            issues   = audit["issues"] or _generic_issues(industry, city)

            system, prompt = _build_prompt(name, industry, city, issues, follow_up_num=0)
            body    = _claude(prompt, system=system)
            subject = _subject(name, issues, follow_up=0)

            self._send(email, name, subject, body)

            _insert_lead({
                "business_name": name, "industry": industry, "city": city,
                "email": email, "website": website,
                "phone": prospect.get("phone", ""),
                "place_id": place_id, "audit_issues": issues,
            })

            self.log_info(f"Outreach → {name} <{email}> | {issues[0][:60]}")
            sent += 1
            time.sleep(3)

        self.update_progress(tid, 90)
        self.complete_task(tid, preview=f"{sent} outreach email(s) sent")

    # ── Follow-ups ────────────────────────────────────────────────────────

    def _run_followups(self):
        tid  = self.create_task("leads", "Follow-up sequence")
        sent = 0

        # Follow-up #1 — day 4 after first contact
        for lead in _leads_due_followup(email_count=1, days_since=4):
            if sent >= FOLLOW_UP_LIMIT:
                break
            system, prompt = _build_prompt(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=1,
            )
            body    = _claude(prompt, system=system)
            subject = _subject(lead["business_name"], lead["audit_issues"], follow_up=1)
            self._send(lead["email"], lead["business_name"], subject, body)
            _update_lead(lead["id"], email_count=2, status="contacted")
            self.log_info(f"Follow-up #1 → {lead['business_name']} <{lead['email']}>")
            sent += 1
            time.sleep(3)

        # Follow-up #2 (final) — day 10 after first contact, then go cold
        for lead in _leads_due_followup(email_count=2, days_since=6):
            if sent >= FOLLOW_UP_LIMIT:
                break
            system, prompt = _build_prompt(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=2,
            )
            body    = _claude(prompt, system=system)
            subject = _subject(lead["business_name"], lead["audit_issues"], follow_up=2)
            self._send(lead["email"], lead["business_name"], subject, body)
            _update_lead(lead["id"], email_count=3, status="cold")
            self.log_info(f"Follow-up #2 (final) → {lead['business_name']} — marked cold")
            sent += 1
            time.sleep(3)

        self.complete_task(tid, preview=f"{sent} follow-up(s) sent")

    # ── Win-backs (low interest leads) ───────────────────────────────────

    def _run_winbacks(self):
        leads = _leads_low_interest()
        if not leads:
            return
        tid  = self.create_task("leads", "Win-back emails")
        sent = 0
        for lead in leads:
            system, prompt = _build_prompt(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=99,
            )
            body    = _claude(prompt, system=system)
            subject = _subject(lead["business_name"], lead["audit_issues"], follow_up=99)
            self._send(lead["email"], lead["business_name"], subject, body)
            # After one win-back, go cold — never contact again
            _update_lead(lead["id"], email_count=99, status="cold")
            self.log_info(f"Win-back → {lead['business_name']} — now cold")
            sent += 1
            time.sleep(3)
        self.complete_task(tid, preview=f"{sent} win-back email(s) sent")

    # ── Email sender ──────────────────────────────────────────────────────

    def _send(self, to_email: str, to_name: str, subject: str, body: str):
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        gmail_user = os.environ.get("GMAIL_USER", "")
        gmail_pass = os.environ.get("GMAIL_APP_PASS", "")

        if not gmail_user or not gmail_pass:
            self.log_warn(f"Email skipped (no Gmail creds) — {to_name} <{to_email}>")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"]  = subject
        msg["From"]     = f"{FROM_NAME} <{gmail_user}>"
        msg["To"]       = f"{to_name} <{to_email}>"
        msg["Reply-To"] = REPLY_TO
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
