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

import base64
import html as html_lib
import imaplib
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email import message_from_bytes
from email.header import decode_header as _decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from agents.base import BaseAgent
from dashboard import db

import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

DAILY_LIMIT     = 100
FOLLOW_UP_LIMIT = 20
BOOKING_URL     = "https://improveyoursite.com/book.html"
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
        "model": "claude-opus-4-6",
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


def _verify_business(name: str, city: str, website: str = "", phone: str = "") -> dict:
    """
    Cross-reference a business against Google Places + OpenStreetMap (Nominatim)
    to confirm it exists, is operational, and the data we have is accurate.

    Returns:
        {
            "verified":          bool   — pass this lead through (True) or skip (False)
            "confidence":        str    — "high" | "medium" | "low" | "unverified"
            "reason":            str    — why it was rejected (if verified=False)
            "corrected_website": str    — Maps-sourced website if ours was wrong/missing
            "corrected_phone":   str    — Maps-sourced phone if ours was missing
            "maps_source":       str    — "google" | "osm" | "none"
        }

    Google Places is tried first (requires GOOGLE_PLACES_API_KEY).
    OSM Nominatim is used as a free no-key fallback.
    Apple Maps Server API requires a Maps token — add APPLE_MAPS_TOKEN to .env to enable.
    """
    result = {
        "verified": True, "confidence": "unverified",
        "reason": "", "corrected_website": "",
        "corrected_phone": "", "maps_source": "none",
    }

    # ── 1. Google Places API ─────────────────────────────────────────────────
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if api_key:
        try:
            query = urllib.parse.quote(f"{name} {city} Australia")
            search_url = (
                f"https://maps.googleapis.com/maps/api/place/textsearch/json"
                f"?query={query}&key={api_key}"
            )
            with urllib.request.urlopen(search_url, timeout=10) as resp:
                data = json.loads(resp.read())

            places = data.get("results", [])
            if not places:
                return {**result, "verified": False, "confidence": "low",
                        "reason": "not found on Google Maps", "maps_source": "google"}

            top = places[0]
            place_id = top.get("place_id", "")

            # Name similarity check — skip if completely different business
            found_name  = top.get("name", "").lower()
            query_words = set(re.sub(r"[^\w\s]", "", name.lower()).split())
            found_words = set(re.sub(r"[^\w\s]", "", found_name).split())
            # Remove generic stop words that inflate false matches
            stops = {"the", "and", "of", "in", "at", "a", "an", "for", "pty", "ltd"}
            query_words -= stops
            found_words -= stops
            overlap = query_words & found_words
            name_score = len(overlap) / max(len(query_words), 1)

            if name_score < 0.25:
                return {**result, "verified": False, "confidence": "low",
                        "maps_source": "google",
                        "reason": f"Google Maps top result '{top.get('name')}' doesn't match '{name}'"}

            # Get Place Details: business_status, website, phone
            details_url = (
                f"https://maps.googleapis.com/maps/api/place/details/json"
                f"?place_id={place_id}"
                f"&fields=business_status,website,formatted_phone_number"
                f"&key={api_key}"
            )
            with urllib.request.urlopen(details_url, timeout=10) as resp:
                detail = json.loads(resp.read()).get("result", {})

            status = detail.get("business_status", "UNKNOWN")
            if status == "CLOSED_PERMANENTLY":
                return {**result, "verified": False, "confidence": "high",
                        "maps_source": "google",
                        "reason": "permanently closed on Google Maps"}

            maps_web = detail.get("website", "").rstrip("/")
            maps_phone = detail.get("formatted_phone_number", "")

            # Website domain cross-check
            corrected_web = ""
            if maps_web:
                def _domain(u):
                    m = re.search(r"(?:https?://)?(?:www\.)?([^/?#]+)", u.lower())
                    return m.group(1) if m else ""
                our_dom   = _domain(website)
                maps_dom  = _domain(maps_web)
                if our_dom and maps_dom and our_dom != maps_dom:
                    # Different domains — trust Google Maps; flag corrected website
                    corrected_web = maps_web
                elif not our_dom and maps_web:
                    corrected_web = maps_web

            confidence = "high" if name_score >= 0.6 else "medium"
            return {
                "verified":          True,
                "confidence":        confidence,
                "reason":            "",
                "corrected_website": corrected_web,
                "corrected_phone":   maps_phone if not phone else "",
                "maps_source":       "google",
            }

        except Exception:
            pass  # fall through to OSM

    # ── 2. Apple Maps Server API (optional — requires APPLE_MAPS_TOKEN) ───────
    # Add APPLE_MAPS_TOKEN to builder/.env to enable.
    # Token format: JWT from Apple Developer → Maps IDs & Tokens
    apple_token = os.environ.get("APPLE_MAPS_TOKEN", "")
    if apple_token:
        try:
            query = urllib.parse.quote(f"{name} {city} Australia")
            apple_url = (
                f"https://maps-api.apple.com/v1/search?q={query}"
                f"&resultTypeFilter=Poi&limitToCountries=AU"
            )
            req = urllib.request.Request(apple_url, headers={
                "Authorization": f"Bearer {apple_token}",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            places = data.get("results", [])
            if places:
                top = places[0]
                found_name  = top.get("name", "").lower()
                query_words = set(re.sub(r"[^\w\s]", "", name.lower()).split()) - stops
                found_words = set(re.sub(r"[^\w\s]", "", found_name).split()) - stops
                overlap = query_words & found_words
                name_score = len(overlap) / max(len(query_words), 1)
                if name_score < 0.25:
                    return {**result, "verified": False, "confidence": "low",
                            "maps_source": "apple",
                            "reason": f"Apple Maps top result '{top.get('name')}' doesn't match '{name}'"}
                return {**result, "verified": True, "confidence": "medium", "maps_source": "apple"}
            else:
                return {**result, "verified": False, "confidence": "low",
                        "maps_source": "apple", "reason": "not found on Apple Maps"}
        except Exception:
            pass

    # ── 3. OpenStreetMap Nominatim (free, no key required) ───────────────────
    try:
        query = urllib.parse.quote(f"{name}, {city}, Australia")
        osm_url = (
            f"https://nominatim.openstreetmap.org/search"
            f"?q={query}&format=json&limit=3&addressdetails=1&countrycodes=au"
        )
        req = urllib.request.Request(osm_url, headers={
            "User-Agent": "IYSLeadsAgent/1.0 (hello@improveyoursite.com)"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            places = json.loads(resp.read())

        if not places:
            # OSM has lower coverage — treat as unverified rather than rejected
            return {**result, "verified": True, "confidence": "low",
                    "maps_source": "osm", "reason": "not on OpenStreetMap (low coverage area)"}

        top = places[0]
        found_name  = top.get("display_name", "").lower()
        query_words = set(re.sub(r"[^\w\s]", "", name.lower()).split()) - {"the","and","of","pty","ltd"}
        found_words = set(re.sub(r"[^\w\s]", "", found_name).split()) - {"the","and","of","pty","ltd"}
        overlap = query_words & found_words
        name_score = len(overlap) / max(len(query_words), 1)

        # OSM is less authoritative — only hard-reject clear mismatches
        if name_score < 0.2:
            return {**result, "verified": True, "confidence": "low",
                    "maps_source": "osm", "reason": "low OSM match — proceeding with caution"}

        return {**result, "verified": True, "confidence": "medium", "maps_source": "osm"}

    except Exception:
        pass

    # No verification source available — proceed but flag as unverified
    return result


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
            if r.get("name")  # skip results with null/empty names
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


def _safe_browsing_check(url: str) -> bool:
    """
    Returns True if the URL is safe, False if flagged as malware/phishing.
    Skips check gracefully if no API key or network error.
    """
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")  # same key covers Safe Browsing
    if not api_key or not url:
        return True
    try:
        payload = json.dumps({
            "client": {"clientId": "iys-leads", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes":      ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                "platformTypes":    ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries":    [{"url": url}],
            },
        }).encode()
        req = urllib.request.Request(
            f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={api_key}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return len(data.get("matches", [])) == 0  # empty = safe
    except Exception:
        return True  # fail open — don't block on network error


def _pagespeed_audit(url: str) -> dict:
    """
    Run Google PageSpeed Insights (mobile) and return structured issues.
    Falls back to empty dict if API key missing or request fails.
    """
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not api_key or not url:
        return {}
    if not url.startswith("http"):
        url = "https://" + url
    try:
        psi_url = (
            f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
            f"?url={urllib.parse.quote(url)}&strategy=mobile&key={api_key}"
            f"&category=performance&category=seo&category=best-practices"
        )
        with urllib.request.urlopen(psi_url, timeout=30) as resp:
            data = json.loads(resp.read())

        cats    = data.get("lighthouseResult", {}).get("categories", {})
        audits  = data.get("lighthouseResult", {}).get("audits", {})
        metrics = audits.get("metrics", {}).get("details", {}).get("items", [{}])[0]

        perf_score = int((cats.get("performance", {}).get("score") or 0) * 100)
        seo_score  = int((cats.get("seo",         {}).get("score") or 0) * 100)
        bp_score   = int((cats.get("best-practices", {}).get("score") or 0) * 100)

        # Key timing metrics (in ms)
        fcp  = (metrics.get("firstContentfulPaint")  or 0) / 1000   # seconds
        lcp  = (metrics.get("largestContentfulPaint") or 0) / 1000
        tbt  = (metrics.get("totalBlockingTime")      or 0)          # ms
        cls  = audits.get("cumulative-layout-shift",  {}).get("displayValue", "")

        # Specific failed audits for issue text
        failed = []
        check_audits = {
            "uses-responsive-images":  "images not optimised for mobile",
            "render-blocking-resources": "render-blocking scripts slowing the page",
            "unused-css-rules":        "unused CSS adding load time",
            "unused-javascript":       "unused JavaScript adding load time",
            "uses-optimized-images":   "images not compressed",
            "uses-text-compression":   "text files not compressed (gzip/brotli off)",
            "meta-description":        "missing meta description — hurts Google ranking",
            "document-title":          "missing page title tag",
            "link-text":               "vague link text — hurts SEO",
            "is-crawlable":            "page is blocking Google crawlers",
            "structured-data":         "no structured data — Google can't read business details",
        }
        for audit_id, label in check_audits.items():
            a = audits.get(audit_id, {})
            if a.get("score") is not None and a.get("score") < 0.9:
                failed.append(label)

        return {
            "perf_score": perf_score,
            "seo_score":  seo_score,
            "bp_score":   bp_score,
            "fcp":        round(fcp, 1),
            "lcp":        round(lcp, 1),
            "tbt":        int(tbt),
            "cls":        cls,
            "failed":     failed[:4],  # top issues only
        }
    except Exception:
        return {}


def _audit_website(url: str) -> dict:
    result = {"loads": False, "slow": False, "issues": [], "psi": {}}
    if not url:
        result["issues"].append("no website showing on Google — customers can't find them online")
        return result
    if not url.startswith("http"):
        url = "https://" + url

    # ── PageSpeed Insights (real Core Web Vitals) ────────────────────────────
    psi = _pagespeed_audit(url)
    if psi:
        result["psi"]   = psi
        result["loads"] = True
        perf = psi["perf_score"]
        lcp  = psi["lcp"]
        seo  = psi["seo_score"]

        if perf < 50:
            result["slow"] = True
            result["issues"].append(
                f"mobile performance score is {perf}/100 on Google's own test — "
                f"most visitors leave before it finishes loading"
            )
        elif perf < 75:
            result["slow"] = True
            result["issues"].append(
                f"site scores {perf}/100 for mobile speed on PageSpeed — "
                f"loads in {lcp}s on mobile, Google recommends under 2.5s"
            )

        if seo < 80:
            result["issues"].append(
                f"SEO score of {seo}/100 on Google's audit — "
                "missing signals that help local search ranking"
            )

        # Surface the most impactful specific failures
        for issue in psi.get("failed", []):
            result["issues"].append(issue)

        # If PSI gave us enough issues, return now
        if len(result["issues"]) >= 2:
            return result

    # ── HTML fallback audit (when PSI fails or gives few issues) ────────────
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

        if not psi and elapsed > 3.5:
            result["slow"] = True
            result["issues"].append(
                f"site takes {elapsed:.1f}s to load on mobile — "
                "most people leave after 3 seconds"
            )

        if "viewport" not in html:
            result["issues"].append("not built for mobile — probably looks broken on phones")

        if not any(k in html_lower for k in ["schema", "application/ld+json", "itemtype"]):
            result["issues"].append(
                "missing structured data — Google can't read the business details properly"
            )

        if not any(k in html_lower for k in ["review", "testimonial", "★", "star", "rating"]):
            result["issues"].append("no reviews or social proof visible on the site")

        if not any(k in html_lower for k in ["book", "quote", "enquire", "contact", "call now", "get a quote"]):
            result["issues"].append("no clear call-to-action — visitors don't know what to do next")

        if not any(k in html_lower for k in ["suburb", "local", "serving", "nsw", "vic", "qld", "wa", "sa", "nt", "act"]):
            result["issues"].append(
                "no local area mentions — Google won't rank it for local searches"
            )

        text_content = re.sub(r'<[^>]+>', ' ', html)
        word_count = len(text_content.split())
        if word_count < 300:
            result["issues"].append(
                f"very thin content ({word_count} words) — "
                "Google ranks sites with real information higher"
            )

    except Exception as exc:
        if not result["loads"]:
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


SEED_FILE     = Path(__file__).parent.parent / "social" / "leads_seed.json"
CALENDAR_FILE = Path(__file__).parent.parent / "social" / "leads_calendar.json"
GITHUB_REPO   = "anon8597299/smart-tech-innovations"


# ── Calendar helpers ──────────────────────────────────────────────────────────

def _read_calendar() -> list[dict]:
    if CALENDAR_FILE.exists():
        try:
            return json.loads(CALENDAR_FILE.read_text())
        except Exception:
            pass
    return []


def _write_calendar(cal_leads: list[dict]):
    """Write calendar locally and push to GitHub so ops.html picks it up."""
    CALENDAR_FILE.write_text(json.dumps(cal_leads, indent=2) + "\n")
    pat = os.environ.get("GITHUB_PAT", "")
    if not pat:
        return
    content_b64 = base64.b64encode(
        (json.dumps(cal_leads, indent=2) + "\n").encode()
    ).decode()
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/social/leads_calendar.json"
    sha = None
    try:
        req = urllib.request.Request(api_url, headers={
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read()).get("sha")
    except Exception:
        pass
    body: dict = {"message": "Auto: sync leads calendar from reply check", "content": content_b64}
    if sha:
        body["sha"] = sha
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"token {pat}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Non-critical — file is still written locally


# ── Auto-reply: booking intent ───────────────────────────────────────────────

_BOOKING_INTENT_KEYWORDS = [
    "book", "booking", "schedule", "call", "chat", "catch up", "catch-up",
    "available", "availability", "when", "time", "slot", "appointment",
    "interested", "yes", "sure", "happy to", "love to", "keen", "sounds good",
    "how much", "pricing", "price", "cost", "quote", "package",
]

_BOOKING_REPLY_TEMPLATE = """\
Hi {name},

Thanks for getting back to me — really appreciate it.

You can book a time that suits you here (no obligation):

  {booking_url}

I offer a free 15-minute discovery call and a 30-minute planning session. \
Pick whichever fits best.

If you'd rather I give you a call, just reply with a good time and number and I'll reach out.

Either way, looking forward to it.

James
ImproveYourSite
hello@improveyoursite.com
"""


def _maybe_send_booking_reply(
    to_email: str,
    biz_name: str,
    subject: str,
    body_text: str,
    gmail_user: str,
    gmail_pass: str,
) -> bool:
    """
    Send a single auto-reply with the booking link if the email body
    contains booking intent keywords. Returns True if email was sent.
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not gmail_user or not gmail_pass:
        return False

    combined = (subject + " " + body_text).lower()
    if not any(kw in combined for kw in _BOOKING_INTENT_KEYWORDS):
        return False

    name = biz_name or "there"
    reply_body = _BOOKING_REPLY_TEMPLATE.format(
        name=name,
        booking_url=BOOKING_URL,
    )
    reply_subject = f"Re: {subject}" if not subject.lower().startswith("re:") else subject

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"]  = reply_subject
        msg["From"]     = f"{FROM_NAME} <{gmail_user}>"
        msg["To"]       = f"{biz_name} <{to_email}>"
        msg["Reply-To"] = REPLY_TO
        msg.attach(MIMEText(reply_body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
        return True
    except Exception:
        return False


# ── Email reply checker ───────────────────────────────────────────────────────

def _decode_subject(raw: str) -> str:
    parts = _decode_header(raw)
    out = ""
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out += chunk.decode(enc or "utf-8", errors="ignore")
        else:
            out += chunk
    return out


def _check_email_replies() -> int:
    """
    Connect to hello@improveyoursite.com via IMAP and check for replies
    from leads in our database. For each match:
      - Update lead status to 'replied' in SQLite
      - Add a calendar entry to leads_calendar.json and push to GitHub

    Supports Gmail (App Password) and Microsoft 365 / Outlook accounts.
    IMAP server is auto-detected from the email address domain.

    Env vars:
      HELLO_EMAIL_USER / HELLO_EMAIL_PASS  — hello@improveyoursite.com (Gmail)
      ADMIN_EMAIL_USER / ADMIN_EMAIL_PASS  — admin@improveyoursite.com (Outlook/M365)
    """
    import sqlite3

    # Prefer admin@ if configured, fall back to hello@
    user   = os.environ.get("ADMIN_EMAIL_USER") or os.environ.get("HELLO_EMAIL_USER", "")
    passwd = os.environ.get("ADMIN_EMAIL_PASS") or os.environ.get("HELLO_EMAIL_PASS", "")
    if not user or not passwd:
        return 0

    # Auto-detect IMAP server
    domain = user.split("@")[-1].lower()
    if domain in ("gmail.com",) or "google" in domain:
        imap_host = "imap.gmail.com"
    else:
        # Microsoft 365 / Outlook (covers custom domains on M365 too)
        imap_host = "outlook.office365.com"

    added = 0
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(user, passwd)
        mail.select("INBOX")

        # Only look at unseen (new) emails
        _, data = mail.search(None, "UNSEEN")
        msg_ids = data[0].split()
        if not msg_ids:
            mail.logout()
            return 0

        cal_leads = _read_calendar()

        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = message_from_bytes(msg_data[0][1])

            # Extract sender address
            from_raw = msg.get("From", "")
            m = re.search(r"<([^>]+)>", from_raw)
            sender = m.group(1).lower() if m else from_raw.lower().strip()

            subject = _decode_subject(msg.get("Subject", ""))
            today = date.today().isoformat()

            # Extract plain-text body for intent analysis
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body_text = part.get_payload(decode=True).decode(charset, errors="ignore")
                        except Exception:
                            pass
                        break
            else:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    body_text = msg.get_payload(decode=True).decode(charset, errors="ignore")
                except Exception:
                    pass

            # Is this sender a known lead?
            conn = sqlite3.connect(db.DB_PATH)
            row = conn.execute(
                "SELECT id, business_name, industry, city, phone, status "
                "FROM leads WHERE LOWER(email)=?",
                (sender,),
            ).fetchone()

            if row:
                lead_id, biz_name, industry, city, phone, lead_status = row
                # Update status → replied (only if still in contacted/new state)
                conn.execute(
                    "UPDATE leads SET status='replied' WHERE id=? AND status IN ('contacted','new')",
                    (lead_id,),
                )
                conn.commit()

                # Add to calendar (one entry per lead per day)
                cal_id = f"reply_{lead_id}_{today}"
                if not any(c.get("id") == cal_id for c in cal_leads):
                    cal_leads.append({
                        "id": cal_id,
                        "date": today,
                        "business_name": biz_name,
                        "industry": industry or "",
                        "city": city or "",
                        "phone": phone or "",
                        "email": sender,
                        "status": "replied",
                        "notes": f'Replied to outreach email — "{subject[:80]}"',
                    })
                    added += 1

                # Auto-reply with booking link if this looks like booking intent
                # Only send once — skip if lead was already beyond 'contacted'/'new'
                if lead_status in ("contacted", "new"):
                    _maybe_send_booking_reply(sender, biz_name, subject, body_text, user, passwd)

            conn.close()

        if added:
            _write_calendar(cal_leads)

        mail.logout()

    except Exception:
        pass  # Don't crash the agent if inbox check fails

    return added


def _check_bounces() -> int:
    """
    Scan the outreach Gmail inbox for bounce-backs and delivery failures.
    Marks the lead as 'bounced' in the DB and logs the bad email address.
    Also scans hello@ inbox for any misdirected bounce notifications.

    Bounce signals detected:
      - From: MAILER-DAEMON, postmaster, Mail Delivery Subsystem
      - Subject: Undeliverable, Delivery failed, Returned mail, Mail delivery failed,
                 Delivery Status Notification, bounce
    """
    import sqlite3
    import smtplib
    from email.mime.text import MIMEText

    BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail delivery subsystem",
                      "delivery subsystem", "auto-submitted")
    BOUNCE_SUBJECTS = ("undeliverable", "delivery failed", "returned mail",
                       "mail delivery failed", "delivery status notification",
                       "failure notice", "could not be delivered", "bounced mail",
                       "bad gateway", "smtp error", "address not found",
                       "user unknown", "no such user")

    inboxes = []
    # Outreach Gmail — where sent emails originate
    if os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASS"):
        inboxes.append((os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASS"], "imap.gmail.com"))
    # hello@ inbox as secondary check
    if os.environ.get("HELLO_EMAIL_USER") and os.environ.get("HELLO_EMAIL_PASS"):
        user = os.environ["HELLO_EMAIL_USER"]
        host = "imap.gmail.com" if "gmail" in user else "outlook.office365.com"
        inboxes.append((user, os.environ["HELLO_EMAIL_PASS"], host))

    bounced_count = 0
    bad_emails: list[dict] = []

    for imap_user, imap_pass, imap_host in inboxes:
        try:
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")

            # Search recent unseen
            _, data = mail.search(None, "UNSEEN")
            msg_ids = data[0].split()

            for msg_id in msg_ids:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                msg = message_from_bytes(msg_data[0][1])

                from_raw = msg.get("From", "").lower()
                subject  = _decode_subject(msg.get("Subject", "")).lower()

                is_bounce = (
                    any(s in from_raw for s in BOUNCE_SENDERS) or
                    any(s in subject   for s in BOUNCE_SUBJECTS)
                )
                if not is_bounce:
                    continue

                # Extract the failed recipient from body
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct in ("text/plain", "message/delivery-status"):
                            try:
                                charset = part.get_content_charset() or "utf-8"
                                body_text += part.get_payload(decode=True).decode(charset, errors="ignore") + "\n"
                            except Exception:
                                pass
                else:
                    try:
                        body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                # Find email addresses in bounce body — the failed recipient
                found_emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", body_text)
                # Filter out our own domains
                failed_addrs = [
                    e for e in found_emails
                    if "improveyoursite" not in e and "google" not in e and "mailer" not in e
                ]

                for bad_email in set(failed_addrs):
                    bad_email = bad_email.lower().strip()
                    # Mark in DB using shared thread-local connection
                    with db.transaction() as _conn:
                        rows_updated = _conn.execute(
                            "UPDATE leads SET status='bounced' WHERE LOWER(email)=? AND status NOT IN ('bounced','cold')",
                            (bad_email,),
                        ).rowcount
                        if rows_updated:
                            biz = _conn.execute(
                                "SELECT business_name FROM leads WHERE LOWER(email)=?", (bad_email,)
                            ).fetchone()
                            biz_name = biz[0] if biz else "Unknown"
                            bad_emails.append({"email": bad_email, "business": biz_name, "reason": subject[:120]})
                            bounced_count += 1
                    if rows_updated:
                        db.event_log("leads", "warn",
                            f"Bounce detected — {bad_email} ({biz_name}): marked bounced. Subject: {subject[:80]}")

                # Mark the bounce email as seen so we don't re-process
                mail.store(msg_id, "+FLAGS", "\\Seen")

            mail.logout()
        except Exception as exc:
            db.event_log("leads", "warn", f"Bounce check failed for {imap_user}: {exc}")

    # Email James a summary of new bad emails
    if bad_emails:
        lines = "\n".join(
            f"  • {b['email']}  ({b['business']})  —  {b['reason']}"
            for b in bad_emails
        )
        _send_notification_email(
            to=os.environ.get("HELLO_EMAIL_USER", os.environ.get("GMAIL_USER", "")),
            subject=f"[IYS Leads] {len(bad_emails)} bounce(s) detected",
            body=(
                f"The leads agent detected {len(bad_emails)} bounced/failed email(s):\n\n"
                f"{lines}\n\n"
                f"These leads have been marked 'bounced' in the database and will not be contacted again."
            ),
        )

    return bounced_count


def _send_notification_email(to: str, subject: str, body: str):
    """Send a plain-text notification email via the outreach Gmail account."""
    import smtplib
    from email.mime.text import MIMEText
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASS", "")
    if not gmail_user or not gmail_pass or not to:
        return
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"]    = gmail_user
        msg["To"]      = to
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(gmail_user, gmail_pass)
            s.sendmail(gmail_user, [to], msg.as_string())
    except Exception:
        pass


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

GOOGLE RANKING PENALTY RULES (use when PageSpeed scores are provided):
- Google made Core Web Vitals an official ranking factor in 2021 — this is not a theory,
  it is documented Google policy. Sites that fail are penalised in search results right now.
- A performance score under 90 means Google is already ranking them below faster competitors
  for the same search terms. Under 50 is classified as "poor" by Google — active penalty.
- LCP (Largest Contentful Paint) over 2.5s = "needs improvement", over 4s = "poor" — Google
  uses this to decide if a site deserves to be on page 1.
- Frame it as: their competitors with better scores are taking the calls that should be theirs.
  Not hypothetical — it is happening every day their site stays at that score.
- Say the actual score number. "Your site scored 34/100 on Google's own mobile speed test"
  is far more credible than anything vague.
- One sentence max on the ranking mechanic — then pivot to: here's what we'd fix on the call.

TONE RULES (critical):
- Write like a real person dashing off a quick email, NOT a marketing template
- Vary sentence length — mix short punchy lines with slightly longer ones
- Never use phrases like: "I came across", "I noticed your business", "I hope to connect",
  "leverage", "optimise", "solutions", "pain points", "reach out", "touch base",
  "synergy", "digital presence", "online footprint", "moving forward"
- No buzzwords, no corporate speak, no AI-flavoured phrasing
- If you mention the website issue, say it plainly — "your site scores 34/100 on mobile"
  not "your website's performance metrics may be impacting search visibility"
- The goal is: a real person at a real agency who ran their site through Google's own tool
  and has something honest and specific to say about it. Get them more customers.
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

_SYSTEM_REENGAGE = """\
You are writing a 3-month re-engagement email for ImproveYourSite, an Australian web agency.

Three months ago you sent this business a cold email AND a personalised PDF score sheet
showing their actual Google PageSpeed scores with a breakdown of specific issues.
They never responded. You're checking back in.

Persona: Straight-talking sales manager — honest, zero pressure, just calling it straight.

RULES:
- MAX 90 words, 2 short paragraphs
- Reference that you sent them a website score report 3 months ago with their actual numbers
- Core message: frame what could have changed by now if they'd acted — be specific to their
  industry. Phrase it as "we could have had X fixed by now" or "by now you'd likely be seeing..."
  — not a guilt trip, just an honest observation about the missed window
- One concrete, believable outcome relevant to their industry (more calls, page 1 ranking,
  faster load time) — nothing exaggerated
- Remind them the free 20-min health check is still available whenever timing works
- No pressure, no hard sell, no grovelling
- Australian English, no emojis
- Sign off: James Burke, ImproveYourSite
- Body only, no subject line
"""


def _build_prompt(
    business_name: str, industry: str, city: str,
    audit_issues: list[str], follow_up_num: int = 0,
    psi: dict | None = None,
) -> tuple[str, str]:
    """Return (system, prompt) for the given email type."""
    issue = audit_issues[0] if audit_issues else "the website could do more to convert visitors"

    # Derive a natural greeting name — use first name if person-named business,
    # otherwise address as the business owner or manager
    greeting = _greeting_name(business_name)
    # Single capitalised word → likely a person's first name (e.g. "Jake", "Scott")
    if len(greeting.split()) == 1 and greeting[0].isupper():
        greeting_instruction = f'Open with "Hi {greeting}"'
    else:
        greeting_instruction = (
            f'Open with "Hi" — then address the email to the business owner or manager. '
            f'Do NOT use the full business name as the greeting.'
        )

    if follow_up_num == 0:
        system = _SYSTEM

        # Build a PSI context block if we have real scores
        psi_block = ""
        if psi and psi.get("perf_score") is not None:
            perf = psi["perf_score"]
            seo  = psi.get("seo_score", "")
            lcp  = psi.get("lcp", "")
            tbt  = psi.get("tbt", "")
            failed = psi.get("failed", [])
            psi_block = f"""
Google PageSpeed audit results (run today, mobile):
- Performance score: {perf}/100{" — Google flags anything under 50 as poor" if perf < 50 else " — Google flags anything under 90 as needing improvement" if perf < 90 else ""}
- Largest Contentful Paint (LCP): {lcp}s{" — Google's threshold for 'poor' is 4s, 'needs improvement' is 2.5s" if lcp else ""}
- Total Blocking Time: {tbt}ms{" — blocks interaction while the page loads" if tbt and int(tbt) > 200 else ""}
- SEO score: {seo}/100{" — active ranking signals are missing" if seo and int(str(seo)) < 90 else ""}
{"- Specific failures: " + "; ".join(failed) if failed else ""}

WHY THIS MATTERS FOR THEIR RANKING (use this context — don't quote it verbatim):
Google's Core Web Vitals (which these scores measure) became an official ranking factor
in 2021. A score of {perf}/100 means Google is already using this against them in search
results — their competitors with faster, better-optimised sites are ranking above them
for the same search terms. This isn't a future risk — it's happening now.
Google is transparent about this: sites that fail Core Web Vitals get a ranking penalty.
For a local {industry} in {city}, ranking on page 2 instead of page 1 can mean the
difference between 0 inbound calls and 10 a week — all from the same search.
"""

        prompt = f"""\
Business name: {business_name}
Industry: {industry}
City: {city}, Australia
Specific website issue found: {issue}
Our booking URL: {BOOKING_URL}
{psi_block}
Important context to weave in naturally:
- Most {industry}s in {city} rely on word of mouth or Google search for new work
- A weak website costs them real jobs — customers search, find a competitor with a better
  site, and never call
- IYS offers a free 20-min website health check — they get a real written report, not a sales pitch
- Pricing is a guide only, James works flexibly with different budgets

Greeting format: {greeting_instruction}

Logic check: Make sure the email makes sense for a {industry} business in {city}.
If PageSpeed scores are provided, reference the actual numbers — they are real and were
run today. Explain plainly why Google is already penalising the site in search results
based on these scores. Don't use jargon — say it like a mate who checked their site.

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

    elif follow_up_num == 98:  # 3-month re-engagement
        system = _SYSTEM_REENGAGE
        prompt = f"""\
Business: {business_name}
Industry: {industry}
City: {city}
Issue spotted 3 months ago: {issue}
Booking URL: {BOOKING_URL}

Write the re-engagement email body. The message: here's what could have improved
by now — the door's still open for a free 20-min health check."""

    else:  # win-back (99)
        system = _SYSTEM_WIN_BACK
        prompt = f"""\
Business: {business_name}
Industry: {industry}
City: {city}
Original issue: {issue}
Booking URL: {BOOKING_URL}

Write the win-back email body."""

    return system, prompt


def _greeting_name(business_name: str) -> str:
    """
    Derive a natural opener from the business name.
    'Wagga City Auto Centre' → 'Wagga City Auto Centre'
    'Jake's Plumbing' → 'Jake'
    'Smith & Sons Builders' → 'Smith & Sons'
    Strips generic suffixes like Pty Ltd, NSW, QLD etc.
    """
    if not business_name:
        return "there"
    name = business_name.strip()
    # Remove trailing state/country tags
    name = re.sub(r'\s*[\|,]\s*(NSW|VIC|QLD|WA|SA|NT|ACT|TAS|Australia).*$', '', name, flags=re.IGNORECASE)
    # Strip legal suffixes
    name = re.sub(r'\s+(Pty\.?\s*Ltd\.?|Pty|Ltd|Pty Limited|Limited|& Co\.?|Co\.)$', '', name, flags=re.IGNORECASE).strip()
    # If name looks like "First Last" (person, not business), extract first name
    parts = name.split()
    if len(parts) == 2 and parts[0][0].isupper() and parts[1][0].isupper():
        # Probably a person's name e.g. "Dan O'Neill" — use first name
        if not any(c in parts[1] for c in ['&', 'and', 'Co', 'Sons', 'Bros']):
            return parts[0]
    return name


def _subject(business_name: str, issues: list[str], follow_up: int = 0) -> str:
    if follow_up == 1:
        return f"Re: {business_name} — following up"
    if follow_up == 2:
        return f"Last one from me — {business_name}"
    if follow_up == 98:  # 3-month re-engagement
        return f"{business_name} — checked in 3 months ago"
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
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name     TEXT NOT NULL,
            industry          TEXT,
            city              TEXT,
            email             TEXT,
            website           TEXT,
            phone             TEXT,
            place_id          TEXT UNIQUE,
            audit_issues      TEXT,
            status            TEXT DEFAULT 'new',
            email_count       INTEGER DEFAULT 0,
            last_emailed      TEXT,
            notes             TEXT,
            reengagement_date TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
        maps_verified     INTEGER DEFAULT 0,
        maps_confidence   TEXT,
        maps_source       TEXT
        )
    """)
    # Migrate existing DB: add columns if missing
    for col, typedef in [
        ("reengagement_date", "TEXT"),
        ("maps_verified",     "INTEGER DEFAULT 0"),
        ("maps_confidence",   "TEXT"),
        ("maps_source",       "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # already exists
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
            audit_issues,status,email_count,last_emailed,
            maps_verified,maps_confidence,maps_source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            lead["business_name"], lead.get("industry",""), lead.get("city",""),
            lead.get("email",""), lead.get("website",""), lead.get("phone",""),
            lead.get("place_id",""), json.dumps(lead.get("audit_issues",[])),
            "contacted", 1, date.today().isoformat(),
            1 if lead.get("maps_verified") else 0,
            lead.get("maps_confidence",""),
            lead.get("maps_source",""),
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
    # When a lead first goes cold, schedule a 3-month re-engagement
    if status == "cold" and email_count < 98:
        reengagement_date = (date.today() + timedelta(days=90)).isoformat()
        conn.execute(
            "UPDATE leads SET email_count=?,last_emailed=?,status=?,reengagement_date=? WHERE id=?",
            (email_count, date.today().isoformat(), status, reengagement_date, lead_id),
        )
    else:
        conn.execute(
            "UPDATE leads SET email_count=?,last_emailed=?,status=? WHERE id=?",
            (email_count, date.today().isoformat(), status, lead_id),
        )
    conn.commit()
    conn.close()


def _leads_due_reengagement() -> list[dict]:
    """Cold leads whose 90-day re-engagement date has arrived."""
    import sqlite3
    today = date.today().isoformat()
    conn = sqlite3.connect(db.DB_PATH)
    rows = conn.execute(
        """SELECT id,business_name,industry,city,email,audit_issues
           FROM leads
           WHERE status='cold'
             AND reengagement_date IS NOT NULL
             AND reengagement_date <= ?
             AND email_count < 98""",
        (today,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "business_name": r[1], "industry": r[2],
         "city": r[3], "email": r[4], "audit_issues": json.loads(r[5] or "[]")}
        for r in rows
    ]


# ── Agent ─────────────────────────────────────────────────────────────────────

class LeadsAgent(BaseAgent):
    agent_id = "leads"
    name     = "Leads"

    def run(self):
        _ensure_leads_table()
        # 1. Bounce detection — mark bad emails before doing anything else
        bounced = _check_bounces()
        if bounced:
            self.log_warn(f"Bounce check: {bounced} failed delivery/bad email(s) marked — James notified")

        # 2. Check inbox for replies
        new_replies = _check_email_replies()
        if new_replies:
            self.log_info(f"{new_replies} new reply/replies found — added to leads calendar")

        # 3. Outreach pipeline
        self._run_new_outreach()
        self._run_followups()
        self._run_winbacks()
        self._run_reengagements()

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

            industry = prospect.get("industry", "business")
            city     = prospect.get("city", "Australia")
            name     = (prospect.get("business_name") or prospect.get("name") or "").strip()
            website  = prospect.get("website", "") or ""
            phone    = prospect.get("phone", "") or ""

            if not name:
                continue  # no business name — nothing to send to

            # ── Maps verification — confirm business exists and is operational ──
            verification = _verify_business(name, city, website=website, phone=phone)
            if not verification["verified"]:
                self.log_info(
                    f"Maps: skipped {name} ({city}) — {verification['reason']} "
                    f"[{verification['maps_source']}]"
                )
                continue

            # Use Maps-corrected data if available (more reliable than scraped data)
            if verification["corrected_website"]:
                self.log_info(
                    f"Maps: corrected website for {name}: "
                    f"{website or '(none)'} → {verification['corrected_website']}"
                )
                website = verification["corrected_website"]
            if verification["corrected_phone"] and not phone:
                phone = verification["corrected_phone"]

            # ── Safe Browsing — skip malware/phishing sites ──────────────────
            if website and not _safe_browsing_check(website):
                self.log_warn(f"Safe Browsing: flagged {website} ({name}) — skipping")
                continue

            # ── Find email — scrape website if needed ────────────────────────
            email = prospect.get("email", "").strip()
            if not email and website:
                email = _find_email_on_website(website)

            if not email:
                self.log_info(
                    f"No email found for {name} ({city}) "
                    f"[maps:{verification['confidence']}] — skipping"
                )
                continue

            audit    = _audit_website(website)
            issues   = audit["issues"] or _generic_issues(industry, city)
            psi_data = audit.get("psi") or {}

            system, prompt = _build_prompt(name, industry, city, issues,
                                           follow_up_num=0, psi=psi_data)
            body    = _claude(prompt, system=system)
            subject = _subject(name, issues, follow_up=0)

            # Build branded score sheet PDF if we have PSI data
            pdf_bytes = None
            pdf_name  = None
            if psi_data:
                pdf_bytes = self._build_score_sheet(name, website, psi_data, issues)
                if pdf_bytes:
                    slug = re.sub(r"[^\w]", "-", name.lower())[:30]
                    pdf_name = f"website-audit-{slug}.pdf"

            self._send(email, name, subject, body,
                       pdf_attachment=pdf_bytes, pdf_filename=pdf_name or "website-audit.pdf")

            _insert_lead({
                "business_name":  name,
                "industry":       industry,
                "city":           city,
                "email":          email,
                "website":        website,
                "phone":          phone,
                "place_id":       place_id,
                "audit_issues":   issues,
                "maps_verified":  verification["verified"],
                "maps_confidence": verification["confidence"],
                "maps_source":    verification["maps_source"],
            })

            self.log_info(
                f"Outreach → {name} <{email}> "
                f"[maps:{verification['confidence']}/{verification['maps_source']}] "
                f"| {issues[0][:55]}"
            )
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

    # ── 3-month re-engagement ─────────────────────────────────────────────

    def _run_reengagements(self):
        """Send a 'here's what you missed' email to cold leads at the 90-day mark."""
        leads = _leads_due_reengagement()
        if not leads:
            return
        tid  = self.create_task("leads", "3-month re-engagement emails")
        sent = 0
        for lead in leads:
            system, prompt = _build_prompt(
                lead["business_name"], lead["industry"], lead["city"],
                lead["audit_issues"], follow_up_num=98,
            )
            body    = _claude(prompt, system=system)
            subject = _subject(lead["business_name"], lead["audit_issues"], follow_up=98)
            self._send(lead["email"], lead["business_name"], subject, body)
            # email_count=98 flags that re-engagement has been sent — never contact again
            _update_lead(lead["id"], email_count=98, status="cold")
            self.log_info(f"3-month re-engagement → {lead['business_name']}")
            sent += 1
            time.sleep(3)
        self.complete_task(tid, preview=f"{sent} re-engagement email(s) sent")

    # ── Score sheet (PDF attachment) ──────────────────────────────────────

    def _build_score_sheet(
        self,
        business_name: str,
        website: str,
        psi: dict,
        issues: list[str],
    ) -> bytes | None:
        """
        Render a branded PDF score sheet using Playwright → HTML → PNG → PDF.
        Returns raw PDF bytes, or None if Playwright is unavailable.

        Layout:
          - IYS header bar (indigo + mint gradient)
          - Business name + website + date
          - 4 score gauges: Performance, SEO, Best Practices, LCP
          - Issues list with traffic-light indicators
          - Footer CTA: "Book your free 20-min audit"
        """
        if not psi:
            return None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        perf = psi.get("perf_score", 0)
        seo  = psi.get("seo_score", 0)
        bp   = psi.get("bp_score", 0)
        lcp  = psi.get("lcp", 0.0)
        tbt  = psi.get("tbt", 0)
        issues_list = issues[:5]

        def _score_colour(score: int) -> str:
            if score >= 90: return "#22c55e"   # green
            if score >= 50: return "#f59e0b"   # amber
            return "#ef4444"                   # red

        def _lcp_colour(lcp_val: float) -> str:
            if lcp_val <= 2.5: return "#22c55e"
            if lcp_val <= 4.0: return "#f59e0b"
            return "#ef4444"

        def _gauge(label: str, score: int, suffix: str = "/100") -> str:
            colour = _score_colour(score)
            pct    = min(score, 100)
            return f"""
            <div style="text-align:center;flex:1;min-width:120px;">
              <svg width="100" height="100" viewBox="0 0 100 100" style="display:block;margin:0 auto 8px;">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#e2e8f0" stroke-width="10"/>
                <circle cx="50" cy="50" r="42" fill="none" stroke="{colour}" stroke-width="10"
                  stroke-dasharray="{int(2*3.14159*42*pct/100)} {int(2*3.14159*42*(100-pct)/100)}"
                  stroke-dashoffset="{int(2*3.14159*42*0.25)}"
                  stroke-linecap="round" transform="rotate(-90 50 50)"/>
                <text x="50" y="46" text-anchor="middle"
                  style="font-family:Inter,sans-serif;font-size:22px;font-weight:900;fill:{colour};">{score}</text>
                <text x="50" y="62" text-anchor="middle"
                  style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;fill:#64748b;">{suffix}</text>
              </svg>
              <div style="font-family:Inter,sans-serif;font-size:13px;font-weight:700;color:#0f172a;">{label}</div>
            </div>"""

        def _lcp_gauge() -> str:
            colour  = _lcp_colour(lcp)
            display = f"{lcp}s"
            rating  = "Good" if lcp <= 2.5 else "Needs work" if lcp <= 4.0 else "Poor"
            return f"""
            <div style="text-align:center;flex:1;min-width:120px;">
              <svg width="100" height="100" viewBox="0 0 100 100" style="display:block;margin:0 auto 8px;">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#e2e8f0" stroke-width="10"/>
                <circle cx="50" cy="50" r="42" fill="none" stroke="{colour}" stroke-width="10"
                  stroke-dasharray="{int(2*3.14159*42*min(lcp/10,1)*100/100)} {int(2*3.14159*42*(1-min(lcp/10,1)))}"
                  stroke-dashoffset="{int(2*3.14159*42*0.25)}"
                  stroke-linecap="round" transform="rotate(-90 50 50)"/>
                <text x="50" y="46" text-anchor="middle"
                  style="font-family:Inter,sans-serif;font-size:18px;font-weight:900;fill:{colour};">{display}</text>
                <text x="50" y="62" text-anchor="middle"
                  style="font-family:Inter,sans-serif;font-size:10px;font-weight:600;fill:#64748b;">{rating}</text>
              </svg>
              <div style="font-family:Inter,sans-serif;font-size:13px;font-weight:700;color:#0f172a;">Page Load (LCP)</div>
            </div>"""

        # Map each issue to a plain-English fix + business outcome
        _FIX_MAP = [
            (
                ["performance", "speed", "load", "slow", "/100"],
                "Speed & performance optimisation",
                "We compress images, remove unused code, and configure caching so the site loads fast on any device.",
                "Faster sites rank higher, keep visitors on the page longer, and convert more browsers into enquiries. A site that loads in under 2 seconds can see 2–3x more contact form submissions than one that takes 5+ seconds.",
            ),
            (
                ["lcp", "largest contentful paint", "content"],
                "Core Web Vitals — LCP fix",
                "We identify and optimise the largest element on each page (usually the hero image or headline block) so it renders immediately.",
                "Fixing LCP moves the site from Google's 'Poor' category into 'Good', removing the active ranking penalty. More customers find the business on page 1 instead of scrolling past to a competitor.",
            ),
            (
                ["structured data", "schema", "google can't read"],
                "Structured data & local schema markup",
                "We add JSON-LD schema markup so Google can clearly read the business name, address, phone, hours, and services.",
                "Google shows richer search results — star ratings, address, opening hours — directly in search. This increases click-through rates by up to 30% for local searches.",
            ),
            (
                ["mobile", "viewport", "phone", "responsive"],
                "Mobile-first rebuild",
                "We rebuild the layout to work properly on all screen sizes — the way 70%+ of local search traffic arrives.",
                "A site that looks broken on phones loses the majority of potential customers before they've even read a word. Fixing mobile typically doubles the time visitors spend on the site.",
            ),
            (
                ["call-to-action", "cta", "visitors don't know", "no clear"],
                "Clear calls-to-action on every page",
                "We add prominent, specific CTAs — 'Call now', 'Get a quote', 'Book online' — in the right places so visitors know exactly what to do next.",
                "Most websites lose leads not because the visitor wasn't interested, but because there was no obvious next step. A well-placed CTA can increase contact rate by 40–80%.",
            ),
            (
                ["local", "suburb", "area", "nsw", "vic", "qld", "wa", "sa"],
                "Local SEO — suburb & area targeting",
                "We add suburb-specific content, location pages, and Google Business Profile optimisation so the site appears for local searches.",
                "For most local businesses, appearing in the top 3 Google results for their suburb drives 5–10 new enquiries per month from people actively searching for exactly what they offer.",
            ),
            (
                ["review", "testimonial", "social proof", "rating"],
                "Social proof integration",
                "We pull in Google reviews, add a testimonials section, and display trust signals that visitors look for before making contact.",
                "Businesses with visible reviews convert 3–4x more website visitors into enquiries. For service businesses, seeing real reviews from local customers is often the deciding factor.",
            ),
            (
                ["content", "thin", "words", "information"],
                "Content depth & authority",
                "We build out service pages with specific, helpful content that answers the questions customers actually search for.",
                "Google rewards sites with real, useful information. More content depth also means the site ranks for a wider range of search terms — more entry points, more leads.",
            ),
            (
                ["seo", "meta", "title", "description", "crawl", "index"],
                "Technical SEO & on-page optimisation",
                "We audit and fix all on-page SEO signals — page titles, meta descriptions, heading structure, internal links, and crawlability.",
                "Even a technically sound business website loses ranking to competitors who have the SEO basics properly configured. Small fixes compound into significantly more organic traffic over time.",
            ),
            (
                ["security", "https", "browser", "best practices"],
                "Security & best practices audit",
                "We resolve any HTTPS issues, fix browser console errors, and update any outdated code that modern browsers flag.",
                "Visitors who see a security warning in their browser almost always leave immediately — before reading anything. A secure, error-free site builds trust passively, just by loading correctly.",
            ),
        ]

        def _match_fix(issue_text: str) -> tuple:
            text_lower = issue_text.lower()
            for keywords, fix_title, what_we_do, business_impact in _FIX_MAP:
                if any(kw in text_lower for kw in keywords):
                    return fix_title, what_we_do, business_impact
            # Fallback
            return (
                "Website audit & optimisation",
                "We review and fix the specific issues flagged, optimising each element for speed, search visibility, and conversion.",
                "A fully optimised website consistently generates more enquiries, ranks higher for local searches, and converts more visitors into paying customers.",
            )

        def _fix_card(issue_text: str, idx: int) -> str:
            fix_title, what_we_do, impact = _match_fix(issue_text)
            return f"""
            <div style="background:#ffffff;border:1px solid #e8edf2;border-radius:10px;
              padding:16px 20px;margin-bottom:10px;">
              <div style="display:flex;align-items:flex-start;gap:14px;">
                <div style="width:24px;height:24px;border-radius:50%;background:#5b4dff;
                  flex-shrink:0;display:flex;align-items:center;justify-content:center;
                  font-size:11px;font-weight:800;color:#ffffff;margin-top:1px;">{idx}</div>
                <div style="flex:1;">
                  <div style="font-size:12.5px;font-weight:800;color:#0f172a;
                    margin-bottom:5px;">{fix_title}</div>
                  <div style="font-size:11px;font-weight:600;color:#ef4444;
                    margin-bottom:8px;line-height:1.5;">Issue: {issue_text}</div>
                  <div style="display:flex;gap:12px;">
                    <div style="flex:1;background:#f8fafc;border-radius:7px;padding:10px 13px;">
                      <div style="font-size:10px;font-weight:700;letter-spacing:.08em;
                        text-transform:uppercase;color:#5b4dff;margin-bottom:5px;">What we fix</div>
                      <div style="font-size:11.5px;color:#475569;line-height:1.6;">{what_we_do}</div>
                    </div>
                    <div style="flex:1;background:#f0fdf4;border:1px solid #bbf7d0;
                      border-radius:7px;padding:10px 13px;">
                      <div style="font-size:10px;font-weight:700;letter-spacing:.08em;
                        text-transform:uppercase;color:#16a34a;margin-bottom:5px;">Business impact</div>
                      <div style="font-size:11.5px;color:#15803d;line-height:1.6;">{impact}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>"""

        today   = date.today().strftime("%-d %B %Y")
        domain  = re.sub(r"https?://(www\.)?", "", website).rstrip("/") if website else "—"
        gauges  = (
            _gauge("Performance", perf) +
            _gauge("SEO", seo) +
            _gauge("Best Practices", bp) +
            _lcp_gauge()
        )
        # issue_rows no longer used — page 2 uses _fix_card() directly

        def _metric_card(label: str, score_html: str, bar_html: str, rating: str,
                         rating_colour: str, body: str) -> str:
            return f"""
            <div style="width:calc(50% - 8px);box-sizing:border-box;background:#ffffff;
              border:1px solid #e8edf2;border-radius:10px;padding:16px 18px;">
              <div style="display:flex;align-items:baseline;justify-content:space-between;
                margin-bottom:6px;">
                <div style="font-size:12px;font-weight:700;color:#0f172a;
                  letter-spacing:-.01em;">{label}</div>
                <div style="font-size:19px;font-weight:900;
                  color:{rating_colour};line-height:1;">{score_html}</div>
              </div>
              {bar_html}
              <div style="font-size:11px;font-weight:700;color:{rating_colour};
                text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;">{rating}</div>
              <div style="font-size:11.5px;color:#64748b;line-height:1.65;">{body}</div>
            </div>"""

        def _bar(pct: int, colour: str) -> str:
            return f"""<div style="height:5px;background:#e8edf2;border-radius:3px;margin-bottom:6px;">
              <div style="height:5px;width:{min(pct,100)}%;background:{colour};
                border-radius:3px;"></div></div>"""

        def _lcp_bar() -> str:
            c1 = "#22c55e" if lcp <= 2.5 else "#e8edf2"
            c2 = "#f59e0b" if 2.5 < lcp <= 4.0 else "#e8edf2"
            c3 = "#ef4444" if lcp > 4.0 else "#e8edf2"
            return f"""<div style="display:flex;gap:4px;margin-bottom:4px;">
              <div style="flex:1;height:5px;border-radius:3px;background:{c1};"></div>
              <div style="flex:1;height:5px;border-radius:3px;background:{c2};"></div>
              <div style="flex:1;height:5px;border-radius:3px;background:{c3};"></div>
            </div>
            <div style="display:flex;justify-content:space-between;
              font-size:9.5px;font-weight:600;color:#94a3b8;margin-bottom:6px;">
              <span>&lt;2.5s Good</span><span>2.5–4s Needs work</span><span>&gt;4s Poor</span>
            </div>"""

        lcp_rating        = "Poor" if lcp > 4 else "Needs Improvement" if lcp > 2.5 else "Good"
        perf_rating       = "Poor" if perf < 50 else "Needs Improvement" if perf < 90 else "Good"
        seo_rating        = "Needs Improvement" if seo < 90 else "Good"
        bp_rating         = "Needs Improvement" if bp < 90 else "Good"

        _perf_note = (
            "Under 50 is classified as Poor — these sites are actively penalised in search."
            if perf < 50 else
            "Under 90 means competitors scoring higher rank above this site for the same searches."
            if perf < 90 else
            "Within Google's good range."
        )
        _seo_note = (
            "Missing signals mean Google gets an incomplete picture, limiting how well it ranks the site locally."
            if seo < 90 else
            "SEO fundamentals are in place."
        )
        _bp_note = (
            "Issues here can trigger browser security warnings, damaging trust before a visitor even reads the page."
            if bp < 90 else
            "Meeting modern technical standards, which supports trust and ranking."
        )

        card_perf = _metric_card(
            "Performance", f"{perf}/100", _bar(perf, _score_colour(perf)),
            perf_rating, _score_colour(perf),
            f"Google's overall mobile speed score. {_perf_note} "
            f"Every 0.1s improvement in load time increases conversions by up to 8%."
        )
        card_lcp = _metric_card(
            "LCP — Page Load Speed", f"{lcp}s", _lcp_bar(),
            lcp_rating, _lcp_colour(lcp),
            f"How long the main content takes to appear after a visitor opens the page — "
            f"Google's most heavily weighted speed signal. "
            f"At {lcp}s this site is in the {lcp_rating} range. "
            f"53% of mobile visitors leave if a page takes over 3 seconds — "
            f"each one goes back and clicks a competitor instead."
        )
        card_seo = _metric_card(
            "SEO Score", f"{seo}/100", _bar(seo, _score_colour(seo)),
            seo_rating, _score_colour(seo),
            f"Whether Google can fully read and index the site — page titles, meta descriptions, "
            f"structured data, crawlability. {_seo_note} "
            f"Gaps compound: a competitor who ticks every box consistently outranks a site that doesn't."
        )
        card_bp = _metric_card(
            "Best Practices", f"{bp}/100", _bar(bp, _score_colour(bp)),
            bp_rating, _score_colour(bp),
            f"How securely and correctly the site is built — HTTPS, no browser errors, "
            f"correct image sizing, privacy-safe scripts. {_bp_note} "
            f"Low scores compound the impact of a poor Performance or LCP result."
        )

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,sans-serif;">
<div style="width:680px;margin:0 auto;background:#f1f5f9;padding-bottom:0;">

  <!-- Header -->
  <div style="background:#0f172a;padding:26px 36px;display:flex;
    align-items:center;justify-content:space-between;">
    <div>
      <span style="font-size:20px;font-weight:900;color:rgba(255,255,255,.92);
        letter-spacing:-.02em;">Improve<span style="color:#2dd4bf;">YourSite</span></span>
      <div style="font-size:10.5px;font-weight:600;color:rgba(255,255,255,.35);
        letter-spacing:.1em;text-transform:uppercase;margin-top:3px;">Website Performance Report</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:11px;color:rgba(255,255,255,.35);">{today}</div>
      <div style="font-size:12px;font-weight:600;color:rgba(255,255,255,.55);
        margin-top:2px;">{domain}</div>
    </div>
  </div>
  <div style="height:3px;background:linear-gradient(90deg,#5b4dff 0%,#2dd4bf 100%);"></div>

  <!-- Business + summary strip -->
  <div style="background:#ffffff;padding:20px 36px 18px;
    border-bottom:1px solid #e8edf2;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
      color:#5b4dff;margin-bottom:4px;">Audited for</div>
    <div style="display:flex;align-items:baseline;justify-content:space-between;">
      <div style="font-size:22px;font-weight:900;color:#0f172a;
        letter-spacing:-.025em;">{business_name}</div>
      <div style="font-size:11px;color:#94a3b8;">Google PageSpeed Insights · mobile</div>
    </div>
  </div>

  <!-- 4 Score gauges -->
  <div style="background:#ffffff;padding:20px 36px 22px;border-bottom:1px solid #e8edf2;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
      color:#94a3b8;margin-bottom:16px;">Google Scores</div>
    <div style="display:flex;justify-content:space-between;gap:12px;">
      {gauges}
    </div>
  </div>

  <!-- Ranking penalty banner -->
  <div style="margin:14px 36px;background:#fffbeb;border:1px solid #fcd34d;
    border-left:4px solid #f59e0b;border-radius:8px;padding:14px 18px;">
    <div style="font-size:12px;font-weight:800;color:#92400e;margin-bottom:4px;">
      Google Core Web Vitals — Active Ranking Penalty
    </div>
    <div style="font-size:12px;color:#78350f;line-height:1.65;">
      Since 2021, Google uses these scores as a direct ranking factor. A performance score
      of <strong>{perf}/100</strong> means faster competitors are currently ranked above this
      site for the same local searches — this is happening now, not a future risk.
    </div>
  </div>

  <!-- 4 Metric cards — 2x2 grid -->
  <div style="margin:0 36px 14px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
      color:#94a3b8;margin-bottom:12px;">What Each Score Means for Your Ranking</div>
    <div style="display:flex;flex-wrap:wrap;gap:12px;">
      {card_perf}
      {card_lcp}
      {card_seo}
      {card_bp}
    </div>
  </div>

  <!-- Issues & what we fix — continues below scores -->
  <div style="background:#f1f5f9;padding-top:0;">

    <!-- Page 2 header -->
    <div style="background:#0f172a;padding:20px 36px;display:flex;
      align-items:center;justify-content:space-between;">
      <span style="font-size:16px;font-weight:900;color:rgba(255,255,255,.9);
        letter-spacing:-.02em;">Improve<span style="color:#2dd4bf;">YourSite</span></span>
      <div style="text-align:right;">
        <div style="font-size:11px;font-weight:600;color:rgba(255,255,255,.4);">{business_name}</div>
        <div style="font-size:10px;color:rgba(255,255,255,.3);margin-top:2px;">Issues &amp; Recommendations</div>
      </div>
    </div>
    <div style="height:3px;background:linear-gradient(90deg,#5b4dff 0%,#2dd4bf 100%);"></div>

    <!-- Intro copy -->
    <div style="background:#ffffff;padding:20px 36px 16px;border-bottom:1px solid #e8edf2;">
      <div style="font-size:18px;font-weight:900;color:#0f172a;letter-spacing:-.02em;
        margin-bottom:6px;">What's holding the site back</div>
      <div style="font-size:12.5px;color:#64748b;line-height:1.65;max-width:560px;">
        Below are the specific issues found during the audit, what we'd do to fix each one,
        and what that fix typically means for a local business in terms of more enquiries,
        better rankings, and stronger conversions.
      </div>
    </div>

    <!-- Fix cards -->
    <div style="padding:16px 36px 16px;">
      {"".join(_fix_card(issue, i + 1) for i, issue in enumerate(issues_list))}
    </div>

    <!-- What a fixed site looks like -->
    <div style="margin:0 36px 16px;background:#0f172a;border-radius:10px;padding:22px 24px;">
      <div style="font-size:13px;font-weight:800;color:#ffffff;margin-bottom:12px;
        letter-spacing:-.01em;">What this looks like once it's done</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,.06);
          border-radius:8px;padding:12px 14px;">
          <div style="font-size:20px;font-weight:900;color:#2dd4bf;margin-bottom:4px;">90+</div>
          <div style="font-size:11px;color:rgba(255,255,255,.6);line-height:1.5;">
            Google performance score — out of the penalty zone and competing for page 1
          </div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,.06);
          border-radius:8px;padding:12px 14px;">
          <div style="font-size:20px;font-weight:900;color:#2dd4bf;margin-bottom:4px;">&lt;2.5s</div>
          <div style="font-size:11px;color:rgba(255,255,255,.6);line-height:1.5;">
            Page load time — keeps visitors on the page instead of bouncing to a competitor
          </div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,.06);
          border-radius:8px;padding:12px 14px;">
          <div style="font-size:20px;font-weight:900;color:#2dd4bf;margin-bottom:4px;">More calls</div>
          <div style="font-size:11px;color:rgba(255,255,255,.6);line-height:1.5;">
            Clear CTAs and local SEO turn search traffic into actual enquiries every week
          </div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,.06);
          border-radius:8px;padding:12px 14px;">
          <div style="font-size:20px;font-weight:900;color:#2dd4bf;margin-bottom:4px;">Page 1</div>
          <div style="font-size:11px;color:rgba(255,255,255,.6);line-height:1.5;">
            Local suburb ranking for the searches customers are already doing right now
          </div>
        </div>
      </div>
    </div>

    <!-- Page 2 footer CTA -->
    <div style="background:#5b4dff;padding:20px 36px;display:flex;align-items:center;
      justify-content:space-between;">
      <div>
        <div style="font-size:14px;font-weight:800;color:#ffffff;letter-spacing:-.01em;">
          See exactly what we'd fix — book a free 20-min call
        </div>
        <div style="font-size:11.5px;color:rgba(255,255,255,.65);margin-top:3px;">
          No obligation. You get a written summary of every recommendation.
        </div>
      </div>
      <div style="background:#ffffff;color:#5b4dff;font-size:12px;font-weight:800;
        padding:10px 20px;border-radius:7px;white-space:nowrap;">
        improveyoursite.com
      </div>
    </div>

  </div><!-- end page 2 -->

</div>
</body></html>"""

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page    = browser.new_page(viewport={"width": 720, "height": 1080})
                page.set_content(html, wait_until="networkidle")
                pdf_bytes = page.pdf(
                    width="720px",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                )
                browser.close()
            return pdf_bytes
        except Exception:
            return None

    # ── Email sender ──────────────────────────────────────────────────────

    def _send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        pdf_attachment: bytes | None = None,
        pdf_filename: str = "website-audit.pdf",
    ):
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication

        gmail_user = os.environ.get("GMAIL_USER", "")
        gmail_pass = os.environ.get("GMAIL_APP_PASS", "")

        if not gmail_user or not gmail_pass:
            self.log_warn(f"Email skipped (no Gmail creds) — {to_name} <{to_email}>")
            return

        msg = MIMEMultipart("mixed")
        msg["Subject"]  = subject
        msg["From"]     = f"{FROM_NAME} <{gmail_user}>"
        msg["To"]       = f"{to_name} <{to_email}>"
        msg["Reply-To"] = REPLY_TO
        msg.attach(MIMEText(body, "plain"))

        if pdf_attachment:
            part = MIMEApplication(pdf_attachment, Name=pdf_filename)
            part["Content-Disposition"] = f'attachment; filename="{pdf_filename}"'
            msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
