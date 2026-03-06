"""
agents/social_intel.py — Competitive Intelligence Engine

Runs as part of the Social agent. Produces a daily intel report:
  - What competitors in the AU web space are posting
  - What topics are trending in target hashtags
  - Emerging market conversations (Australian SMBs)
  - Content gaps (what nobody is talking about yet)
  - Recommended angles for IYS to own

Uses:
  - Perplexity (real-time web search) for competitor + trend research
  - Instagram Graph API (hashtag search) for top performing content
  - Claude for synthesis, gap analysis, and strategic recommendations

Output: social/intel_report.json — updated every morning run
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SOCIAL_DIR   = PROJECT_ROOT / "social"
CONFIG_FILE  = SOCIAL_DIR / "intel_config.json"
REPORT_FILE  = SOCIAL_DIR / "intel_report.json"
GRAPH_BASE   = "https://graph.facebook.com/v19.0"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"competitors": [], "monitor_hashtags": [], "target_keywords": [],
            "industry_verticals": [], "content_pillars": []}


def run_intel(log=None) -> dict:
    """
    Main entry point. Returns the intel report dict.
    log: optional callable(level, message) for dashboard logging.
    """
    def _log(level, msg):
        if log:
            log(level, msg)

    config    = load_config()
    today     = date.today().isoformat()
    perp_key  = os.environ.get("PERPLEXITY_KEY", "")
    ant_key   = os.environ.get("ANTHROPIC_API_KEY", "")
    ig_token  = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "") or os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
    ig_user   = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

    report = {
        "date":              today,
        "competitor_themes": [],
        "trending_topics":   [],
        "hashtag_insights":  [],
        "content_gaps":      [],
        "recommended_angles": [],
        "market_pulse":      "",
        "sources":           [],
    }

    # ── 1. Competitor + trend research via Perplexity ────────────────────────
    if perp_key:
        _log("info", "Intel: researching competitor activity + trends")
        comp_research = _research_competitors(perp_key, config)
        trend_research = _research_trends(perp_key, config)
        report["competitor_themes"] = comp_research.get("themes", [])
        report["trending_topics"]   = trend_research.get("topics", [])
        report["market_pulse"]      = trend_research.get("pulse", "")
        report["sources"]           = comp_research.get("sources", []) + trend_research.get("sources", [])
        _log("info", f"Intel: found {len(report['trending_topics'])} trending topics, "
                     f"{len(report['competitor_themes'])} competitor themes")
    else:
        _log("warn", "Intel: no PERPLEXITY_KEY — using cached trend data")
        report["trending_topics"]   = _cached_trends()
        report["competitor_themes"] = _cached_competitor_themes()

    # ── 2. Instagram hashtag insights ────────────────────────────────────────
    if ig_token and ig_user:
        _log("info", "Intel: pulling Instagram hashtag data")
        hashtag_insights = _research_hashtags(ig_token, ig_user, config)
        report["hashtag_insights"] = hashtag_insights
        _log("info", f"Intel: {len(hashtag_insights)} hashtag insights gathered")
    else:
        _log("info", "Intel: no IG token — skipping hashtag research")

    # ── 3. Gap analysis + content recommendations via Claude ─────────────────
    if ant_key:
        _log("info", "Intel: running gap analysis with Claude")
        analysis = _analyze_gaps(ant_key, report, config)
        report["content_gaps"]       = analysis.get("gaps", [])
        report["recommended_angles"] = analysis.get("angles", [])
        _log("info", f"Intel: {len(report['recommended_angles'])} content opportunities identified")
    else:
        report["content_gaps"]       = _cached_gaps()
        report["recommended_angles"] = _cached_angles()

    # ── Save report ──────────────────────────────────────────────────────────
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    _log("info", f"Intel: report saved to social/intel_report.json")

    return report


# ── Research functions ────────────────────────────────────────────────────────

def _research_competitors(perp_key: str, config: dict) -> dict:
    """What are AU web design competitors talking about on Instagram/social?"""
    handles  = [c["handle"] for c in config.get("competitors", [])]
    pillars  = config.get("content_pillars", [])
    month    = datetime.now().strftime("%B %Y")

    query = (
        f"In {month}, what content themes and topics are Australian web design agencies "
        f"and small business website providers posting about on Instagram and social media? "
        f"Focus on: engagement patterns, popular post formats, recurring topics, "
        f"what's getting the most comments and shares. "
        f"Also note any gaps — topics the industry is ignoring."
    )

    raw = _perplexity_search(perp_key, query)
    if not raw:
        return {"themes": _cached_competitor_themes(), "sources": []}

    # Parse into themes
    themes = [
        line.lstrip("0123456789.-•* ").strip()
        for line in raw.get("content", "").splitlines()
        if len(line.strip()) > 15
    ]
    return {
        "themes":  themes[:8],
        "sources": raw.get("sources", []),
    }


def _research_trends(perp_key: str, config: dict) -> dict:
    """What are Australian SMBs actually searching for and talking about right now?"""
    verticals = ", ".join(config.get("industry_verticals", []))
    month     = datetime.now().strftime("%B %Y")

    query = (
        f"What are Australian small business owners in {verticals} industries "
        f"most concerned about regarding their online presence and websites in {month}? "
        f"Include: trending pain points, questions being asked on Reddit/Facebook groups, "
        f"emerging topics in digital marketing for SMBs, seasonal factors for Australian businesses. "
        f"Be specific and current."
    )

    raw = _perplexity_search(perp_key, query)
    if not raw:
        return {"topics": _cached_trends(), "pulse": "", "sources": []}

    content = raw.get("content", "")
    topics = [
        line.lstrip("0123456789.-•* ").strip()
        for line in content.splitlines()
        if len(line.strip()) > 20
    ]

    # Get a one-sentence market pulse summary
    pulse_query = (
        f"In one sentence, what is the single biggest online marketing concern "
        f"for Australian small businesses right now in {month}?"
    )
    pulse_raw = _perplexity_search(perp_key, pulse_query)
    pulse = pulse_raw.get("content", "").strip()[:200] if pulse_raw else ""

    return {
        "topics":  topics[:8],
        "pulse":   pulse,
        "sources": raw.get("sources", []),
    }


def _research_hashtags(token: str, user_id: str, config: dict) -> list[dict]:
    """Get top performing posts from key Instagram hashtags."""
    insights = []
    hashtags = config.get("monitor_hashtags", [])[:5]  # limit API calls

    for tag in hashtags:
        try:
            # Step 1: get hashtag ID
            search_url = (
                f"{GRAPH_BASE}/ig-hashtag-search"
                f"?user_id={user_id}&q={urllib.parse.quote(tag)}&access_token={token}"
            )
            with urllib.request.urlopen(search_url, timeout=8) as r:
                result = json.loads(r.read())
            tag_id = result.get("data", [{}])[0].get("id")
            if not tag_id:
                continue

            # Step 2: get top media
            media_url = (
                f"{GRAPH_BASE}/{tag_id}/top_media"
                f"?user_id={user_id}"
                f"&fields=like_count,comments_count,caption,media_type,timestamp"
                f"&access_token={token}"
            )
            with urllib.request.urlopen(media_url, timeout=8) as r:
                media = json.loads(r.read())

            posts = media.get("data", [])
            if posts:
                top = sorted(posts, key=lambda p: p.get("like_count", 0), reverse=True)[:3]
                insights.append({
                    "hashtag":   tag,
                    "top_likes": top[0].get("like_count", 0) if top else 0,
                    "avg_likes": sum(p.get("like_count", 0) for p in posts) // max(len(posts), 1),
                    "top_captions": [
                        (p.get("caption", "")[:120] + "…") if p.get("caption") else ""
                        for p in top
                    ],
                })
        except Exception:
            pass  # silently skip — hashtag search rate-limits aggressively

    return insights


def _analyze_gaps(api_key: str, report: dict, config: dict) -> dict:
    """Use Claude to identify content gaps and recommend specific post angles."""
    try:
        import anthropic
    except ImportError:
        return {"gaps": _cached_gaps(), "angles": _cached_angles()}

    competitor_themes = "\n".join(f"- {t}" for t in report.get("competitor_themes", [])[:6])
    trending_topics   = "\n".join(f"- {t}" for t in report.get("trending_topics", [])[:6])
    pillars           = "\n".join(f"- {p}" for p in config.get("content_pillars", []))
    market_pulse      = report.get("market_pulse", "")

    prompt = f"""You are a content strategist for ImproveYourSite.com — an Australian web agency
targeting small business owners (tradies, GP clinics, accountants, boutiques, consultants).

Today's market intelligence:

WHAT COMPETITORS ARE POSTING ABOUT:
{competitor_themes or "No data — assume generic web design tips, testimonials, before/afters"}

WHAT AUSTRALIAN SMBs ARE TALKING ABOUT:
{trending_topics}

MARKET PULSE: {market_pulse}

IYS CONTENT PILLARS:
{pillars}

Analyse this and return ONLY valid JSON:
{{
  "gaps": [
    "Topic or angle competitors are ignoring that IYS could own (max 6, specific)"
  ],
  "angles": [
    {{
      "hook": "Opening line or post hook (under 10 words, punchy)",
      "angle": "The specific point of view or argument to take",
      "why_it_wins": "Why this will outperform competitors right now (1 sentence)",
      "format": "carousel | single_image | reel_idea",
      "urgency": "evergreen | trending_now | seasonal"
    }}
  ]
}}

Provide 3-5 gaps and 4-6 angles. Make them specific to the Australian market.
Angles must be contrarian or add genuine value — not generic tips everyone posts."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    result = json.loads(raw.strip())
    return {
        "gaps":   result.get("gaps", []),
        "angles": result.get("angles", []),
    }


# ── Perplexity helper ────────────────────────────────────────────────────────

def _perplexity_search(key: str, query: str) -> dict | None:
    try:
        payload = json.dumps({
            "model":    "sonar",
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 400,
            "return_citations": True,
        }).encode()
        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions",
            data=payload, method="POST",
            headers={
                "Authorization":  f"Bearer {key}",
                "Content-Type":   "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        content  = resp["choices"][0]["message"]["content"]
        sources  = [
            c.get("url", "") for c in resp.get("citations", [])
            if c.get("url")
        ]
        return {"content": content, "sources": sources}
    except Exception:
        return None


# ── Cached fallbacks (no API keys needed) ────────────────────────────────────

def _cached_trends() -> list[str]:
    return [
        "Australian SMBs worried about AI-built sites undercutting their web investment",
        "Rising cost of Google Ads pushing SMBs to focus on organic/SEO",
        "Tradies increasingly aware they need websites, not just word of mouth",
        "Regional businesses (outside Sydney/Melbourne) underserved by local agencies",
        "GPT-built sites flooding the market — business owners can't tell quality apart",
        "Instagram and TikTok driving referral traffic more than Google for some verticals",
        "End of financial year (June) driving website refresh decisions",
    ]


def _cached_competitor_themes() -> list[str]:
    return [
        "Generic 'before and after' website screenshots",
        "Price comparison posts (usually vague)",
        "Testimonial carousels with stock photos",
        "Platform feature posts (Wix vs Squarespace debates)",
        "Generic '5 tips for your website' lists",
    ]


def _cached_gaps() -> list[str]:
    return [
        "Nobody is showing what a high-converting website looks like for REGIONAL Australian businesses",
        "No competitor is addressing the 'my nephew built it' website problem with empathy",
        "AI website fear content — nobody is demystifying it for SMBs",
        "Industry-specific website ROI — what does a GP clinic website actually earn?",
        "The 'set and forget' problem — sites that were built in 2019 and never touched",
    ]


def _cached_angles() -> list[str]:
    return [
        "Your 2019 website is costing you customers — here's exactly how",
        "What a tradie website needs that no template gives you",
        "Regional business? Here's why SEO is actually easier for you",
        "The real reason your website isn't converting (it's not the design)",
    ]
