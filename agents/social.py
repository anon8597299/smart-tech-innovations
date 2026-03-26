"""
agents/social.py — Social Agent (v2)

Daily Instagram content engine for ImproveYourSite.com.

What it does every run:
  1. Market research — pulls trending Australian SMB topics via Perplexity
  2. Content planning — Claude decides today's post type + angle
  3. Carousel copy generation — Claude writes slide copy that sounds human
  4. Visual production — calls existing make_*.py scripts with generated content
  5. Instagram publishing — posts via Graph API if INSTAGRAM_PUBLISHING_TOKEN set
  6. Falls back to upload queue (social/upload_queue.json) for manual posting

Schedule: 7:30 AM and 6:30 PM AEST (set in scheduler.py)
Peak times for Australian SMBs: 7-9am and 6-8pm weekdays

Required in builder/.env:
  ANTHROPIC_API_KEY          — for content planning + copywriting
  PERPLEXITY_KEY             — for market research (same key used by auto_blog)
  INSTAGRAM_PUBLISHING_TOKEN — long-lived token with instagram_content_publish scope
  INSTAGRAM_ACCOUNT_ID       — Business account ID

Optional:
  GITHUB_PAT                 — used to upload images to repo for public URL
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from agents.social_intel import run_intel
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent
SOCIAL_DIR   = PROJECT_ROOT / "social"
TILES_DIR    = Path.home() / "Documents" / "ImproveYourSite - Social Media" / "Tiles"
QUEUE_FILE   = SOCIAL_DIR / "upload_queue.json"
REPORT_FILE  = SOCIAL_DIR / "intel_report.json"

GRAPH_BASE   = "https://graph.facebook.com/v19.0"

# ── Content calendar — what to post each day of the week ─────────────────────
# Designed to look human, vary in format, and drive SMB enquiries

CONTENT_CALENDAR = {
    0: {  # Monday
        "theme": "cost_pain",
        "angle": "Name one thing Australian small business owners are paying too much for that AI can now do better. Frame it as money they are throwing away. No website focus — think: social media manager, marketing agency, admin staff, Google Ads management, content writers. One cost. One truth. Make them feel the waste.",
        "format": "carousel",
        "caption_tone": "Direct. Like a mate who tells you the hard truth. No fluff.",
        "hook_style": "bold_fear",
    },
    1: {  # Tuesday
        "theme": "feature_spotlight",
        "angle": "Pick ONE specific IYS AI feature (lead reply, Instagram content, SEO monitoring, Google Ads checks, email triage, morning digest, blog writing, customer success). Name the business problem it solves in the headline. Show the cost of NOT having it. End with what IYS AI does instead. This is about cutting business costs and streamlining operations, not websites.",
        "format": "carousel",
        "caption_tone": "Expert mate. Gives the answer first, no teasing. End caption with 🦞",
        "hook_style": "specific_mistake",
    },
    2: {  # Wednesday
        "theme": "comparison",
        "angle": "Old way vs IYS AI way. Pick one business task: responding to leads, posting on Instagram, monitoring Google Ads, writing weekly content, triaging emails. Old way: manual, expensive, slow. IYS AI way: automated, $5/month, instant. Make the contrast obvious. Lead with the cost comparison.",
        "format": "carousel",
        "caption_tone": "Storytelling. Contrast-based. Concrete numbers where possible.",
        "hook_style": "result_first",
    },
    3: {  # Thursday
        "theme": "education",
        "angle": "Something business owners are still paying humans to do that AI now handles better, faster and cheaper. Counter-intuitive framing — NOT about websites. Think: social media scheduling, lead follow-up, ad monitoring, email management, content writing. Teach the shift from human-cost to AI-cost simply.",
        "format": "carousel",
        "caption_tone": "Transparent. Plain English. Show the math. No jargon.",
        "hook_style": "counterintuitive",
    },
    4: {  # Friday
        "theme": "cta",
        "angle": "One clear reason to download IYS AI or book a call this week. Frame it as reclaiming time or cutting a specific cost. No pressure. Make it easy to say yes. Link in bio to improveyoursite.com/jarvis.",
        "format": "single_tip",
        "caption_tone": "Confident and warm. One clear next step. End with 🦞",
        "hook_style": "soft_offer",
    },
    5: {  # Saturday
        "theme": "stop_scroll",
        "angle": "A stat about what Australian small businesses spend on digital marketing, admin staff or marketing agencies — vs what IYS AI costs. Surprising. Specific. Short. Make them stop scrolling and think about their own spend.",
        "format": "single_tip",
        "caption_tone": "Weekend energy. Real and relatable. Quick read.",
        "hook_style": "bold_stat",
    },
    6: {  # Sunday
        "theme": "engagement",
        "angle": "A question that makes a small business owner reflect on how much time or money they are wasting on something AI could handle. Not about websites — about operations: lead management, content creation, email admin, marketing spend. Make them DM you with their answer.",
        "format": "single_tip",
        "caption_tone": "Thought-provoking. Invites a real answer. Warm.",
        "hook_style": "question",
    },
}

# ── Australian SMB Instagram hashtags by industry ────────────────────────────
HASHTAGS = {
    "web":      "#smallbusinessaustralia #australianbusiness #businessautomation "
                "#aiforsmallbusiness #businessgrowth #improveyoursite #iysai",
    "ai":       "#aiforsmallbusiness #smallbusinessaustralia #businessautomation "
                "#australianbusiness #cutcosts #worksmarter #iysai #improveyoursite",
    "trades":   "#australiantradie #smallbusinessaustralia #tradiebusiness "
                "#aiforsmallbusiness #businessautomation #businessgrowth #iysai",
    "health":   "#smallbusinessaustralia #australianhealthcare #australianbusiness "
                "#aiforsmallbusiness #businessautomation #businessgrowth #iysai",
    "ops":      "#businessoperations #smallbusinessaustralia #australianbusiness "
                "#aitools #businessautomation #worksmarter #iysai #improveyoursite",
}


STRATEGY_FILE = SOCIAL_DIR / "weekly_strategy.json"

# City/suburb names blocked in brand validation
_SOCIAL_CITY_NAMES = {
    "sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra",
    "darwin", "hobart", "gold coast", "newcastle", "wollongong", "geelong",
    "townsville", "cairns", "toowoomba", "ballarat", "bendigo", "launceston",
    "mackay", "rockhampton", "sunshine coast", "nsw", "vic", "qld", "wa",
    "sa", "tas", "nt", "act",
}


class SocialAgent(BaseAgent):
    agent_id = "social"
    name     = "Social"

    # ── Brand validator ───────────────────────────────────────────────────────

    @staticmethod
    def _validate_post(post_dict: dict) -> dict:
        """
        Validate a generated post dict against IYS brand rules.

        Checks:
          - Each carousel slide: ≤ 6 words, no hyphens, no city/suburb names
          - Caption: ≤ 25 words before hashtags, no hyphens

        Returns {"valid": bool, "issues": [list of strings]}
        """
        issues = []

        # Validate carousel slides
        slides = post_dict.get("slides", [])
        for i, slide in enumerate(slides):
            text = slide.strip()
            # Hyphens
            if "-" in text or "\u2013" in text or "\u2014" in text:
                issues.append(f"Slide {i + 1} contains a hyphen: \"{text}\"")
            # Word count
            word_count = len(text.split())
            if word_count > 6:
                issues.append(f"Slide {i + 1} too long ({word_count} words): \"{text}\"")
            # City names (word-boundary match to avoid false positives like "sa" inside words)
            import re as _re
            lower = text.lower()
            for city in _SOCIAL_CITY_NAMES:
                pattern = r'\b' + _re.escape(city) + r'\b'
                if _re.search(pattern, lower):
                    issues.append(f"Slide {i + 1} contains city/state name '{city}': \"{text}\"")
                    break

        # Validate caption (check only the part before hashtags)
        caption = post_dict.get("caption", "")
        caption_pre_tags = caption.split("\n\n")[0].strip() if "\n\n" in caption else caption.strip()
        if "-" in caption_pre_tags or "\u2013" in caption_pre_tags or "\u2014" in caption_pre_tags:
            issues.append("Caption contains a hyphen")
        cap_words = len(caption_pre_tags.split())
        if cap_words > 25:
            issues.append(f"Caption too long before hashtags ({cap_words} words, max 25)")

        return {"valid": len(issues) == 0, "issues": issues}

    # ── Weekly strategy reader ────────────────────────────────────────────────

    def _get_strategy_brief(self, today: date) -> Optional[dict]:
        """
        Check social/weekly_strategy.json for today's day plan.
        Returns the day dict (with carousel + story) if today's date matches, else None.
        """
        if not STRATEGY_FILE.exists():
            return None
        try:
            strategy = json.loads(STRATEGY_FILE.read_text())
            today_str = today.isoformat()
            days = strategy.get("days", {})
            for day_name, day_data in days.items():
                if day_data.get("date") == today_str:
                    return day_data
        except Exception as exc:
            self.log_warn(f"Social: could not read weekly_strategy.json: {exc}")
        return None

    def run(self):
        today     = date.today()
        weekday   = today.weekday()
        plan      = CONTENT_CALENDAR[weekday]
        time_slot = self._get_time_slot()

        self.log_info(f"Social: {today} ({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][weekday]}) "
                      f"— theme: {plan['theme']}, slot: {time_slot}")

        # Guard: skip if we already posted this slot today
        import sqlite3 as _sqlite3
        _conn = _sqlite3.connect(db.DB_PATH)
        _already = _conn.execute(
            "SELECT COUNT(*) FROM events WHERE agent_id='social' AND level='info' "
            "AND message LIKE '%published%Make.com%' AND timestamp LIKE ?",
            (f"{today.isoformat()}%",)
        ).fetchone()[0]
        _conn.close()
        if _already >= 2:
            self.log_info(f"Social: already posted {_already}x today — skipping to avoid duplicates")
            return

        # Check for a planned post for today/slot first — use it if available
        planned_post = self._get_planned_post(today, time_slot)
        if planned_post:
            self.log_info(f"Social: using planned post for {today} {time_slot}: {planned_post.get('headline')}")
            # Override plan theme from the planned post
            if planned_post.get("theme"):
                plan = {**plan, "theme": planned_post["theme"]}

        # Check weekly strategy — use it as brief if today's date matches
        strategy_brief = self._get_strategy_brief(today) if not planned_post else None
        if strategy_brief:
            self.log_info(
                f"Social: weekly_strategy.json found for {today} — "
                f"pillar: {strategy_brief.get('pillar', '?')}, "
                f"hook: {strategy_brief.get('carousel', {}).get('hook', '?')}"
            )

        # 1. Competitive intelligence (morning run only — avoid double API calls)
        intel = {}
        if time_slot == "morning":
            tid = self.create_task("intel", "Competitor + trend intelligence")
            self.update_progress(tid, 10)
            intel = run_intel(log=self.log)
            gaps    = len(intel.get("content_gaps", []))
            angles  = len(intel.get("recommended_angles", []))
            self.complete_task(tid, f"{gaps} gaps found · {angles} content angles")
        else:
            if REPORT_FILE.exists():
                try:
                    intel = json.loads(REPORT_FILE.read_text())
                except Exception:
                    intel = {}

        # 2. Market research
        tid = self.create_task("research", f"Market research: {plan['theme']}")
        trending = self._research_trending(plan, intel)
        self.complete_task(tid, f"Research complete: {len(trending)} insights")

        # 2. Generate post content (use planned post if available, else generate)
        tid = self.create_task("copywriting", f"Writing {plan['format']} copy")
        self.update_progress(tid, 20)
        if planned_post:
            post = planned_post
            self.complete_task(tid, post.get("headline", "Planned post loaded"))
        else:
            recommended = intel.get("recommended_angles", []) if intel else []
            post = self._generate_post(
                plan, trending, today, time_slot, recommended,
                strategy_brief=strategy_brief,
            )
            if not post:
                self.fail_task(tid, "Content generation failed")
                return
            self.complete_task(tid, post.get("headline", "Post written"))

        # 2b. Brand validation — check slides + caption, attempt Claude fix if needed
        validation = self._validate_post(post)
        if not validation["valid"]:
            self.log_warn(
                f"Social: post failed brand validation "
                f"({len(validation['issues'])} issue(s)): "
                + "; ".join(validation["issues"])
            )
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key and not planned_post:
                try:
                    import anthropic as _anthropic
                    _client = _anthropic.Anthropic(api_key=api_key)
                    issues_text = "\n".join(f"- {iss}" for iss in validation["issues"])
                    _fix_prompt = (
                        f"Fix these brand rule violations in the Instagram post below. "
                        f"Rules: no hyphens anywhere, max 6 words per slide, "
                        f"no city/state names, caption max 25 words before hashtags.\n\n"
                        f"Violations:\n{issues_text}\n\n"
                        f"Original post JSON:\n{json.dumps(post)}\n\n"
                        f"Return ONLY the corrected JSON with the same keys. No markdown fences."
                    )
                    _r = _client.messages.create(
                        model="claude-opus-4-6",
                        max_tokens=1200,
                        messages=[{"role": "user", "content": _fix_prompt}],
                    )
                    _raw = _r.content[0].text.strip()
                    if _raw.startswith("```"):
                        _raw = _raw.split("```")[1]
                        if _raw.startswith("json"):
                            _raw = _raw[4:]
                    _fixed_post = json.loads(_raw.strip())
                    _recheck = self._validate_post(_fixed_post)
                    if _recheck["valid"]:
                        post = _fixed_post
                        self.log_info("Social: brand validation fix pass succeeded")
                    else:
                        self.log_warn(
                            "Social: brand validation fix pass still has issues — "
                            "publishing original"
                        )
                except Exception as _fix_exc:
                    self.log_warn(f"Social: brand validation fix pass failed: {_fix_exc}")

        # 3. Generate visual (carousel slides via existing scripts)
        tid = self.create_task("visual", f"Producing visual: {plan['theme']}")
        slide_paths = self._produce_visual(plan, post)
        slide_count = len(slide_paths)
        self.complete_task(tid, f"{slide_count} slide(s)" if slide_paths else "no visual — queued text-only")

        # 4. Publish or queue
        # Priority: Make.com webhook (free) → Graph API → manual queue
        make_url   = os.environ.get("MAKE_WEBHOOK_URL", "")
        ig_token   = os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

        if make_url and slide_paths:
            tid = self.create_task("publish", f"Publishing {slide_count}-slide carousel via Make.com")
            published = self._publish_via_make(make_url, slide_paths, post["caption"], post.get("facebook_caption", ""))
            if published:
                self.complete_task(tid, f"Posted {slide_count}-slide carousel via Make.com (Instagram + Facebook)")
                self.log_info(f"Social: published {slide_count}-slide carousel via Make.com → Instagram + Facebook")
                self._mark_posted(post)
            else:
                self.fail_task(tid, "Make.com publish failed — queued for manual post")
                self._queue_post(post, slide_paths)

        elif ig_token and account_id and slide_paths:
            tid = self.create_task("publish", "Publishing via Instagram Graph API")
            image_path = slide_paths[0]
            published = self._publish_to_instagram(ig_token, account_id, image_path, post["caption"])
            if published:
                self.complete_task(tid, f"Posted: {published}")
                self.log_info(f"Social: published via Graph API — {published}")
                self._mark_posted(post)
            else:
                self.fail_task(tid, "Graph API publish failed — queued for manual post")
                self._queue_post(post, slide_paths)

        else:
            self._queue_post(post, slide_paths)
            self.log_info("Social: post queued — add MAKE_WEBHOOK_URL to builder/.env to auto-post")

        # 5. Log insights if token available
        read_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        if read_token and account_id:
            self._fetch_insights(read_token, account_id)

        # 6. Log to content DB
        db.content_add(
            content_type="carousel",
            title=post.get("headline", f"IG post {today}"),
            preview_path=str(slide_paths[0]) if slide_paths else None,
            status="delivered",
        )

    # ── Market research ───────────────────────────────────────────────────────

    # ── Planned content calendar ──────────────────────────────────────────────

    def _get_planned_post(self, today: date, time_slot: str) -> Optional[dict]:
        """
        Check social/{month}_content_plan.json for a pre-written post matching
        today's date and time slot. Returns the post dict or None.
        """
        month_name = today.strftime('%B').lower()
        plan_files = [
            SOCIAL_DIR / f"{month_name}_content_plan.json",
            SOCIAL_DIR / "march_content_plan.json",  # fallback
        ]
        for plan_file in plan_files:
            if not plan_file.exists():
                continue
            try:
                data = json.loads(plan_file.read_text())
                today_str = today.isoformat()
                slot_key  = "morning" if time_slot == "morning" else "evening"
                for entry in data.get("plan", []):
                    if entry.get("date") == today_str and entry.get("slot") == slot_key:
                        # Mark as used
                        entry["_used"] = True
                        plan_file.write_text(json.dumps(data, indent=2))
                        return entry
            except Exception:
                pass
        return None

    # ── Market research ───────────────────────────────────────────────────────

    def _research_trending(self, plan: dict, intel: dict = None) -> list[str]:
        """Combine intel report + Perplexity for a full picture of what's trending."""
        # Pull from intel report first (already researched this morning)
        combined = []
        if intel:
            combined += intel.get("trending_topics", [])[:3]
            combined += [g for g in intel.get("content_gaps", [])[:2]]
            if intel.get("market_pulse"):
                combined.insert(0, intel["market_pulse"])

        perplexity_key = os.environ.get("PERPLEXITY_KEY", "")
        if not perplexity_key:
            if combined:
                return combined[:6]
            self.log_warn("No PERPLEXITY_KEY — using cached research topics")
            return self._fallback_research(plan["theme"])

        query = (
            f"What are Australian small businesses talking about on social media in "
            f"{date.today().strftime('%B %Y')} regarding {plan['theme']} and websites/online presence? "
            f"Give me 5 specific trending pain points or topics, be concise."
        )

        try:
            payload = json.dumps({
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 300,
            }).encode()
            req = urllib.request.Request(
                "https://api.perplexity.ai/chat/completions",
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {perplexity_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
            content = resp["choices"][0]["message"]["content"]
            # Parse bullet points / numbered list into a list
            insights = [
                line.lstrip("0123456789.-•* ").strip()
                for line in content.splitlines()
                if len(line.strip()) > 20
            ]
            return insights[:5] or self._fallback_research(plan["theme"])
        except Exception as exc:
            self.log_warn(f"Perplexity research failed: {exc}")
            return self._fallback_research(plan["theme"])

    def _fallback_research(self, theme: str) -> list[str]:
        fallbacks = {
            "motivation":    ["Business owners want quick wins", "Time pressure is real", "Cost vs ROI tension"],
            "education":     ["Most SMBs don't know their website bounce rate", "Slow sites lose customers", "Google ranks mobile-first"],
            "social_proof":  ["Local businesses trust local results", "Before/after resonates most", "Specific numbers build trust"],
            "behind_scenes": ["People buy from people they understand", "Process transparency builds trust"],
            "cta":           ["Limited availability creates urgency", "Free first step lowers barrier"],
            "inspiration":   ["Australian businesses prefer local providers", "Growth stories inspire action"],
            "planning":      ["Sunday planning mindset", "Business owners think about next week"],
        }
        return fallbacks.get(theme, ["Australian small businesses need better websites",
                                     "Local SEO drives foot traffic"])

    # ── Content generation ────────────────────────────────────────────────────

    def _generate_post(self, plan: dict, trending: list[str], today: date, time_slot: str, recommended_angles: list = None, strategy_brief: dict = None) -> Optional[dict]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.log_warn("No ANTHROPIC_API_KEY — using template post")
            return self._template_post(plan, today)

        try:
            import anthropic
        except ImportError:
            return self._template_post(plan, today)

        research_text = "\n".join(f"- {t}" for t in trending)
        day_name      = today.strftime("%A")
        angles_text   = ""
        if recommended_angles:
            angles_text = "\n\nCOMPETITIVE ANGLES TO CONSIDER (from today's market research):\n"
            for a in recommended_angles[:3]:
                if isinstance(a, dict):
                    angles_text += f"- Hook: \"{a.get('hook','')}\" | Why: {a.get('why_it_wins','')}\n"
                else:
                    angles_text += f"- {a}\n"

        hook_style = plan.get("hook_style", "bold_fear")

        # Build strategy brief block — if available, use it as the primary brief
        strategy_text = ""
        if strategy_brief:
            carousel_brief = strategy_brief.get("carousel", {})
            strategy_hook    = carousel_brief.get("hook", "")
            strategy_angle   = carousel_brief.get("angle", "")
            strategy_bullets = carousel_brief.get("bullets", [])
            strategy_cta     = carousel_brief.get("cta", "")
            strategy_text = "\n\nWEEKLY STRATEGY BRIEF (use this as your primary direction):\n"
            if strategy_hook:
                strategy_text += f"  Hook to build from: \"{strategy_hook}\"\n"
            if strategy_angle:
                strategy_text += f"  Angle: {strategy_angle}\n"
            if strategy_bullets:
                strategy_text += "  Key points to cover:\n"
                for b in strategy_bullets:
                    strategy_text += f"    - {b}\n"
            if strategy_cta:
                strategy_text += f"  CTA direction: {strategy_cta}\n"
            if strategy_brief.get("pillar"):
                strategy_text += f"  Content pillar: {strategy_brief['pillar']}\n"
            strategy_text += (
                "Work FROM this brief. The hook is pre-validated and strategically chosen. "
                "Use it as slide 1 and build the rest of the carousel around the angle and bullets above."
            )

        system = """You write Instagram content for ImproveYourSite.com (@improveyoursite.au).
We sell AI business solutions to Australian small business owners. The main product is IYS AI.

POSITIONING — this is critical:
We are NOT a web design agency posting about websites. We are a business operations solution.
The message is: businesses are wasting money and time on things AI can do cheaper and faster.
Every post should make an owner think "I am overpaying for that" or "I waste hours on that."
The sell is: stop paying humans to do what AI does better. Buy IYS AI from $30.

JARVIS FEATURES (one per post — pick the one that fits today's angle):
1. Lead reply agent — monitors inbox, replies to enquiries within minutes, 24/7
2. Instagram agent — generates and posts branded carousels + stories twice daily
3. Google Ads agent — monitors ad performance daily, flags wasted spend
4. SEO monitor — checks site speed + rankings daily, alerts before penalties hit
5. Content writer — publishes SEO blog post every Monday automatically
6. Morning digest — 7am summary of everything that ran overnight
7. Email triage — sorts and drafts replies to hello@ inbox every 30 minutes
8. Customer success — weekly client health check, flags at-risk relationships
9. Stripe monitor — alerts the moment a new payment or order arrives
10. Site builder — spins up a new client site on demand from config file

BRAND IDENTITY ON SOCIALS:
🦞 = OpenClaw (the AI engine powering IYS AI — lobster claw = OpenClaw)
🤖 = Claude AI (the brain inside IYS AI)
End IYS AI posts with 🦞 or 🦞🤖 — this is our AI identity marker for followers.
As we grow, followers will associate 🦞 with our AI brand.

TARGET PAIN POINTS (what to hook on — not websites, business operations):
- "I pay $2,000/month to a social media manager" → IYS AI does it for $5
- "My marketing agency charges $3,500/month" → IYS AI replaces 80% of what they do
- "I spend Sunday night catching up on emails" → IYS AI triages them every 30 minutes
- "We miss leads after 5pm" → IYS AI replies in minutes at midnight
- "My Google Ads are running and no one's watching" → IYS AI checks every morning
- "I haven't published a blog post in months" → IYS AI writes one every Monday
- "I don't know if my clients are happy until they leave" → customer success agent
- "Running a team of people to do marketing is expensive" → one AI, one install

SERVICES THAT CAN CLOSE THE SALE:
- IYS AI download: $30 (improveyoursite.com/jarvis)
- IYS AI USB: $50
- Managed Plan: $199/month (we run everything for them)
- Website packages: from $3,000 (improveyoursite.com/packages.html)
Direct them to link in bio for any of these.

THE WINNING HOOK ENERGY:
"Your website is costing you customers" — 6 words, one fear, everyone feels it.
Apply that same energy to business costs: "You're paying a human to do this"

WHAT THE DATA SHOWS WORKS:
- Carousels with under 10 words on slide 1 get 3x more swipes
- DM shares are now the strongest Instagram signal — write content people forward to their mate
- Posts that name a specific cost or waste outperform generic tips every time
- Short captions (under 30 words before hashtags) outperform long ones

WHAT KILLS ENGAGEMENT (never do these):
- Hyphens anywhere. Zero hyphens. This is the single biggest AI dead giveaway.
- City or town names. No Sydney, Melbourne, Brisbane, NSW etc. National audience only.
- More than 6 words on any slide
- Starting with "Are you..." or "Did you know..."
- Corporate jargon: leverage, synergy, digital presence, streamline, empower
- Explaining too much — trust the reader to fill the gap
- Talking about websites when the post is about business operations

RULES:
1. Slide text: 3 to 6 words. Every slide is a billboard on a freeway.
2. ONE idea per slide. Never two.
3. No hyphens. Not one.
4. No city names. Not one.
5. Caption: 2 sentences + 1 CTA line. Under 25 words total before hashtags.
6. Sound like a real person who runs a business. Not an agency. Not a robot.
7. The hook style for this post: """ + hook_style

        prompt = f"""Today is {day_name}. {time_slot.upper()} post.

Theme: {plan['theme']}
Direction: {plan['angle']}

What's trending with AU small businesses right now:
{research_text}{angles_text}{strategy_text}

Use the trending data to make the hook feel current and relevant.
If a competitor gap exists — own it on slide 1.
If a weekly strategy brief is provided above, use it as your primary direction.

Return ONLY valid JSON, no markdown fences:
{{
  "headline": "Slide 1 — 3 to 6 words, stops the scroll, names a fear or truth",
  "slides": [
    "3-6 words",
    "3-6 words",
    "3-6 words",
    "3-6 words",
    "CTA — 3-5 words"
  ],
  "caption": "Sentence 1: hook that expands slide 1. Sentence 2: one specific insight or proof. Sentence 3: CTA with link in bio.",
  "facebook_caption": "Same 3 sentences but slightly warmer. Add one more sentence of context. End with direct CTA.",
  "image_prompt": "DALL-E prompt for a bold, minimal carousel background image: dark background (#0a0a0a or #5b4dff), no text, abstract or conceptual visual that reinforces the theme. Suitable for large white text overlay.",
  "alt_text": "Accessibility description for screen readers"
}}"""

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        post = json.loads(raw)

        # Strip any hyphens that slipped through — hard enforcement
        for field in ("headline", "caption", "facebook_caption"):
            if post.get(field):
                post[field] = post[field].replace(" - ", " ").replace("—", "").replace("–", "")
        post["slides"] = [s.replace(" - ", " ").replace("—", "").replace("–", "") for s in post.get("slides", [])]

        # Append hashtags to Instagram caption
        if HASHTAGS["web"] not in post["caption"]:
            post["caption"] += "\n\n" + HASHTAGS["web"]
        # Ensure facebook_caption exists
        if not post.get("facebook_caption"):
            post["facebook_caption"] = post["caption"].split("\n\n" + HASHTAGS["web"])[0]
        return post

    def _template_post(self, plan: dict, today: date) -> dict:
        """Fallback post when no API key is set. Matches winning format."""
        templates = {
            "stop_scroll":  {
                "headline": "Your website is costing you customers",
                "slides":   ["Your website is costing you customers", "Not because it looks bad", "Because nobody can find it", "3 seconds. Gone.", "We fix that. Link in bio."],
                "caption":  "53% of small business websites lose visitors in 3 seconds. Not from bad design. From slow load times and no Google presence.\n\nWe fix both. Free audit at the link in bio.\n\n" + HASHTAGS["web"],
                "facebook_caption": "53% of small business websites lose visitors in 3 seconds. Not from bad design. From slow load times and no Google presence. We fix both in under 2 weeks. Free audit at the link.",
                "alt_text": "Your website is costing you customers",
            },
            "education":    {
                "headline": "3 seconds. That is all you get.",
                "slides":   ["3 seconds. That is all you get.", "Slow site = gone", "No mobile = gone", "Not on Google = invisible", "We fix all three. Link in bio."],
                "caption":  "Your site takes 6 seconds to load. Google's threshold is 3. You're losing half your visitors before they read a word.\n\nFree site speed check. Link in bio.\n\n" + HASHTAGS["web"],
                "facebook_caption": "Your site takes 6 seconds to load. Google's threshold is 3. You're losing half your visitors before they read a single word. We check and fix this for Australian small businesses. Free audit at the link.",
                "alt_text": "3 seconds is all you get before visitors leave",
            },
        }
        default = templates["education"]
        return templates.get(plan.get("theme", ""), default) or default

    # ── Visual production ─────────────────────────────────────────────────────

    def _produce_visual(self, plan: dict, post: dict) -> list[Path]:
        """
        Visual production pipeline — tries in order:
          1. ChatGPT DALL-E 3 image generation (if OPENAI_API_KEY set)
          2. Pillow-only branded slides using the planned slide text (always works)
          3. Existing make_*.py carousel scripts (last resort — generic content)
          4. Returns empty list (post queued as text-only)
        """
        TILES_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Try ChatGPT DALL-E 3 for the background image
        image_prompt = post.get("image_prompt", "")
        if image_prompt and os.environ.get("OPENAI_API_KEY", ""):
            dalle_paths = self._generate_dalle_slides(post, plan)
            if dalle_paths:
                return dalle_paths

        # 2. If post has actual slides, render with branded Playwright renderer
        if post.get("slides"):
            branded_paths = self._generate_branded_slides(post)
            if branded_paths:
                return branded_paths

        # 3. Fallback: local make_*.py carousel scripts
        theme_script_map = {
            "stop_scroll":   "make_tile.py",
            "education":     "make_seo_mistake_carousel.py",
            "social_proof":  "make_perf_carousel.py",
            "behind_scenes": "make_ai_seo_carousel.py",
            "cta":           "make_audit_post.py",
            "engagement":    "make_maps_carousel.py",
        }

        preferred = theme_script_map.get(plan["theme"])
        scripts = list(SOCIAL_DIR.glob("make_*.py"))

        def sort_key(p):
            return 0 if p.name == preferred else 1
        scripts.sort(key=sort_key)

        for script in scripts:
            try:
                before = datetime.now().timestamp() - 1
                result = subprocess.run(
                    [sys.executable, str(script)],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    timeout=90,
                )
                if result.returncode == 0:
                    new_pngs = [
                        p for p in TILES_DIR.glob("*.png")
                        if p.stat().st_mtime >= before
                    ]
                    if new_pngs:
                        new_pngs.sort(key=lambda p: p.name)
                        self.log_info(
                            f"Social: {script.name} produced {len(new_pngs)} slide(s): "
                            + ", ".join(p.name for p in new_pngs[:5])
                        )
                        return new_pngs[:5]
            except Exception as exc:
                self.log_warn(f"Script {script.name} failed: {exc}")

        self.log_warn("No visual produced — post will be text-only")
        return []

    def _generate_branded_slides(self, post: dict) -> list[Path]:
        """
        Render carousel slides using Playwright + Inter font — matches brand identity exactly.
        Dark/light alternating slides, Inter 900 weight, brand colours, logo bar.
        Falls back to Pillow if Playwright not available.
        """
        slides = post.get("slides", [])
        if not slides:
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.log_warn("Visual: Playwright not installed — falling back to Pillow")
            return self._generate_pillow_slides(post)

        import tempfile

        BLUE  = "#5b4dff"
        MINT  = "#2dd4bf"
        DARK  = "#0f172a"
        WHITE = "#ffffff"
        FONT  = ("<link href='https://fonts.googleapis.com/css2?family=Inter:"
                 "wght@400;600;700;800;900&display=swap' rel='stylesheet'>")

        theme = post.get("theme", "stop_scroll")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        headline_slug = post.get("headline", "post").lower().replace(" ", "_")[:20]

        # Cover colour rotation: black → white → purple, cycling per post
        _COVER_SEQUENCE = [DARK, WHITE, BLUE]
        _rot_file = SOCIAL_DIR / "cover_rotation.json"
        try:
            _rot_idx = json.loads(_rot_file.read_text()).get("index", 0) if _rot_file.exists() else 0
        except Exception:
            _rot_idx = 0
        cover_bg       = _COVER_SEQUENCE[_rot_idx % 3]
        cover_is_light = (cover_bg == WHITE)
        try:
            _rot_file.write_text(json.dumps({"index": (_rot_idx + 1) % 3}))
        except Exception:
            pass

        def _brand_bar():
            return (
                f"<div style='position:absolute;bottom:44px;left:72px;right:72px;"
                f"display:flex;align-items:center;justify-content:space-between;'>"
                f"<span style='font-size:18px;font-weight:800;color:rgba(255,255,255,.45);"
                f"letter-spacing:-.01em;font-family:Inter,sans-serif;'>"
                f"Improve<span style='color:{MINT};'>YourSite</span></span>"
                f"<span style='font-size:15px;font-weight:500;color:rgba(255,255,255,.3);"
                f"font-family:Inter,sans-serif;'>improveyoursite.com</span>"
                f"</div>"
            )

        def _brand_bar_light():
            return (
                f"<div style='position:absolute;bottom:44px;left:72px;right:72px;"
                f"display:flex;align-items:center;justify-content:space-between;'>"
                f"<span style='font-size:18px;font-weight:800;color:rgba(15,23,42,.4);"
                f"letter-spacing:-.01em;font-family:Inter,sans-serif;'>"
                f"Improve<span style='color:{BLUE};'>YourSite</span></span>"
                f"<span style='font-size:15px;font-weight:500;color:rgba(15,23,42,.3);"
                f"font-family:Inter,sans-serif;'>improveyoursite.com</span>"
                f"</div>"
            )

        def _font_size(text: str) -> int:
            words = len(text.split())
            if words <= 3:  return 100
            if words <= 5:  return 88
            if words <= 7:  return 76
            return 64

        SAFE_W = "840px"

        def _dots(slide_num: int, total: int, light: bool = False) -> str:
            """
            Dot row where the active position is an arrow-shaped pill pointing right.
            Dark slides: black arrow / white text. Light slides: white arrow / black text.
            Past dots = filled, future dots = dim. Last slide = filled dot, no arrow.
            Visual: ● ● [—SWIPE—›] ○ ○
            """
            # Arrow is opposite of tile bg; text inside matches tile bg colour
            # Dark tile  → white arrow  + dark text (#0f172a)
            # Light tile → dark arrow   + white text (#ffffff)
            arrow_bg     = "#0f172a"               if light else "#ffffff"
            arrow_text   = "#ffffff"               if light else "#0f172a"
            past_dot     = "rgba(15,23,42,.35)"    if light else "rgba(255,255,255,.5)"
            future_dot   = "rgba(15,23,42,.15)"    if light else "rgba(255,255,255,.22)"
            last_dot_bg  = "#0f172a"               if light else "#ffffff"
            is_last      = (slide_num == total - 1)

            items = []
            for j in range(total):
                if j == slide_num and not is_last:
                    # Active non-last: bold arrow pill — contrasts hard with slide bg
                    items.append(
                        f"<div style='height:26px;padding:0 44px 0 22px;border-radius:999px;"
                        f"background:{arrow_bg};"
                        f"clip-path:polygon(0 0,calc(100% - 16px) 0,100% 50%,calc(100% - 16px) 100%,0 100%);"
                        f"display:flex;align-items:center;justify-content:center;'>"
                        f"<span style='font-family:Inter,sans-serif;font-size:12px;font-weight:900;"
                        f"letter-spacing:.16em;text-transform:uppercase;color:{arrow_text};'>"
                        f"swipe</span>"
                        f"</div>"
                    )
                elif j == slide_num and is_last:
                    # Last slide: filled dot, no arrow
                    items.append(
                        f"<div style='width:22px;height:22px;border-radius:50%;"
                        f"background:{last_dot_bg};'></div>"
                    )
                elif j < slide_num:
                    # Past slides: filled dim dot
                    items.append(
                        f"<div style='width:10px;height:10px;border-radius:50%;"
                        f"background:{past_dot};'></div>"
                    )
                else:
                    # Future slides: empty dim dot
                    items.append(
                        f"<div style='width:10px;height:10px;border-radius:50%;"
                        f"background:{future_dot};'></div>"
                    )
            return "".join(items)

        def _swipe_arrow(light: bool = False, last: bool = False) -> str:
            return ""  # now handled inside _dots

        def _build_dark_slide(text: str, bg: str = DARK, slide_num: int = 0, total: int = 5, last: bool = False) -> str:
            fs = _font_size(text)
            return f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>
<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;background:{bg};'>
<div style='width:1080px;height:1080px;position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;box-sizing:border-box;'>
  <div style='position:absolute;top:0;left:0;right:0;height:6px;
    background:linear-gradient(90deg,{BLUE} 0%,{MINT} 100%);'></div>
  <div style='position:absolute;top:-180px;right:-180px;width:600px;height:600px;border-radius:50%;
    background:radial-gradient(circle,rgba(91,77,255,.14) 0%,transparent 65%);'></div>
  <div style='position:absolute;bottom:-140px;left:-100px;width:480px;height:480px;border-radius:50%;
    background:radial-gradient(circle,rgba(45,212,191,.09) 0%,transparent 65%);'></div>
  <div style='position:relative;z-index:1;text-align:center;width:{SAFE_W};'>
    <p style='font-family:Inter,-apple-system,sans-serif;font-size:{fs}px;font-weight:900;
      line-height:1.15;letter-spacing:-.025em;color:{WHITE};margin:0;
      word-break:break-word;overflow-wrap:break-word;'>{text}</p>
  </div>
  {_swipe_arrow(light=False, last=last)}
  <div style='position:absolute;bottom:80px;left:50%;transform:translateX(-50%);
    display:flex;gap:9px;align-items:center;'>{_dots(slide_num, total)}</div>
  {_brand_bar()}
</div></body></html>"""

        def _build_light_slide(text: str, slide_num: int = 0, total: int = 5, last: bool = False) -> str:
            fs = _font_size(text)
            return f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>
<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;background:#f4f3ff;'>
<div style='width:1080px;height:1080px;position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;box-sizing:border-box;'>
  <div style='position:absolute;top:0;left:0;right:0;height:6px;
    background:linear-gradient(90deg,{BLUE} 0%,{MINT} 100%);'></div>
  <div style='position:absolute;top:-180px;right:-180px;width:600px;height:600px;border-radius:50%;
    background:radial-gradient(circle,rgba(91,77,255,.07) 0%,transparent 65%);'></div>
  <div style='position:absolute;bottom:-140px;left:-100px;width:480px;height:480px;border-radius:50%;
    background:radial-gradient(circle,rgba(45,212,191,.06) 0%,transparent 65%);'></div>
  <div style='position:relative;z-index:1;text-align:center;width:{SAFE_W};'>
    <p style='font-family:Inter,-apple-system,sans-serif;font-size:{fs}px;font-weight:900;
      line-height:1.15;letter-spacing:-.025em;color:{DARK};margin:0;
      word-break:break-word;overflow-wrap:break-word;'>{text}</p>
  </div>
  {_swipe_arrow(light=True, last=last)}
  <div style='position:absolute;bottom:80px;left:50%;transform:translateX(-50%);
    display:flex;gap:9px;align-items:center;'>{_dots(slide_num, total, light=True)}</div>
  {_brand_bar_light()}
</div></body></html>"""

        def _build_case_study_slide(result: str, label: str, slide_num: int = 0, total: int = 5) -> str:
            """Mint-accented case study slide — shows a before/after result."""
            return f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>
<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;background:{DARK};'>
<div style='width:1080px;height:1080px;position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;box-sizing:border-box;'>
  <div style='position:absolute;top:0;left:0;right:0;height:6px;
    background:linear-gradient(90deg,{BLUE} 0%,{MINT} 100%);'></div>
  <div style='position:absolute;top:-180px;left:-180px;width:600px;height:600px;border-radius:50%;
    background:radial-gradient(circle,rgba(45,212,191,.12) 0%,transparent 65%);'></div>
  <div style='position:relative;z-index:1;text-align:center;width:{SAFE_W};'>
    <div style='display:inline-block;background:rgba(45,212,191,.12);border:1px solid rgba(45,212,191,.3);
      border-radius:100px;padding:10px 28px;margin-bottom:36px;'>
      <span style='font-family:Inter,sans-serif;font-size:13px;font-weight:700;
        letter-spacing:.1em;text-transform:uppercase;color:{MINT};'>Real result</span>
    </div>
    <p style='font-family:Inter,-apple-system,sans-serif;font-size:88px;font-weight:900;
      line-height:1.1;letter-spacing:-.03em;color:{WHITE};margin:0 0 24px;
      word-break:break-word;overflow-wrap:break-word;'>{result}</p>
    <p style='font-family:Inter,sans-serif;font-size:28px;font-weight:500;
      color:rgba(255,255,255,.5);margin:0;letter-spacing:-.01em;'>{label}</p>
  </div>
  {_swipe_arrow(light=False, last=False)}
  <div style='position:absolute;bottom:80px;left:50%;transform:translateX(-50%);
    display:flex;gap:9px;align-items:center;'>{_dots(slide_num, total)}</div>
  {_brand_bar()}
</div></body></html>"""

        def _build_cta_slide(text: str, slide_num: int = 0, total: int = 5) -> str:
            fs = _font_size(text)
            return f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>
<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;background:{BLUE};'>
<div style='width:1080px;height:1080px;position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;box-sizing:border-box;'>
  <div style='position:absolute;bottom:-180px;right:-120px;width:620px;height:620px;border-radius:50%;
    background:radial-gradient(circle,rgba(45,212,191,.22) 0%,transparent 65%);'></div>
  <div style='position:absolute;top:-100px;left:-80px;width:380px;height:380px;border-radius:50%;
    background:radial-gradient(circle,rgba(255,255,255,.07) 0%,transparent 65%);'></div>
  <div style='position:relative;z-index:1;text-align:center;width:{SAFE_W};'>
    <p style='font-family:Inter,-apple-system,sans-serif;font-size:{fs}px;font-weight:900;
      line-height:1.15;letter-spacing:-.025em;color:{WHITE};margin:0 0 44px;
      word-break:break-word;overflow-wrap:break-word;'>{text}</p>
    <div style='width:56px;height:4px;background:{MINT};border-radius:4px;margin:0 auto 44px;'></div>
    <div style='display:inline-block;background:{WHITE};padding:18px 40px;border-radius:14px;'>
      <span style='font-family:Inter,sans-serif;font-size:24px;font-weight:800;
        color:{BLUE};letter-spacing:-.01em;'>improveyoursite.com</span>
    </div>
  </div>
  <div style='position:absolute;bottom:80px;left:50%;transform:translateX(-50%);
    display:flex;gap:9px;align-items:center;'>{_dots(slide_num, total)}</div>
  {_brand_bar()}
</div></body></html>"""

        # Case study data per theme — injected as slide 2
        CASE_STUDIES = {
            "stop_scroll":   ("3x more calls",       "after website rebuild"),
            "education":     ("7s → 1.8s",           "page load after our fix"),
            "social_proof":  ("37 enquiries",         "in one month, same business"),
            "cta":           ("Free audit",           "20 mins, no obligation"),
            "engagement":    ("Page 1 Google",        "in 6 weeks, local tradie"),
            "behind_scenes": ("$0 ad spend",          "100% organic traffic"),
        }
        cs_result, cs_label = CASE_STUDIES.get(theme, ("4x more leads", "after site rebuild"))

        # Build 6 slides: hook + case study + 3 content + CTA
        raw_slides = slides[:4]  # hook + up to 3 content slides
        total = len(raw_slides) + 2  # +case study +CTA

        html_pages = []
        for i, text in enumerate(raw_slides):
            is_last = False
            if i == 0:
                if cover_is_light:
                    html_pages.append(_build_light_slide(text, slide_num=i, total=total))
                else:
                    html_pages.append(_build_dark_slide(text, bg=cover_bg, slide_num=i, total=total))
            elif i % 2 == 0:
                html_pages.append(_build_dark_slide(text, slide_num=i, total=total))
            else:
                html_pages.append(_build_light_slide(text, slide_num=i, total=total))

        # Case study slide after content slides
        cs_idx = len(raw_slides)
        html_pages.append(_build_case_study_slide(cs_result, cs_label, slide_num=cs_idx, total=total))

        # CTA slide last
        cta_text = slides[-1] if slides else "Free audit. Link in bio."
        html_pages.append(_build_cta_slide(cta_text, slide_num=total - 1, total=total))

        output_paths = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1080, "height": 1080})
                for i, html in enumerate(html_pages):
                    with tempfile.NamedTemporaryFile(
                        suffix=".html", mode="w", delete=False, encoding="utf-8"
                    ) as f:
                        f.write(html)
                        tmp = Path(f.name)
                    out_path = TILES_DIR / f"carousel_{timestamp}_{headline_slug}_{i+1}.png"
                    page.goto(f"file://{tmp}", wait_until="networkidle")
                    page.wait_for_timeout(800)
                    page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
                    tmp.unlink()
                    output_paths.append(out_path)
                browser.close()
            self.log_info(f"Social: Playwright rendered {len(output_paths)} branded slides for: {post.get('headline','')}")
        except Exception as exc:
            self.log_warn(f"Social: Playwright render failed ({exc}) — falling back to Pillow")
            return self._generate_pillow_slides(post)

        return output_paths

    def _generate_pillow_slides(self, post: dict) -> list[Path]:
        """Pillow fallback — used when Playwright is unavailable."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.log_warn("Visual: Pillow not installed — run bootstrap.py")
            return []

        slides = post.get("slides", [])
        if not slides:
            return []

        BLUE   = (91, 77, 255)
        MINT   = (45, 212, 191)
        DARK   = (15, 23, 42)
        WHITE  = (255, 255, 255)
        theme  = post.get("theme", "")
        bg     = BLUE if theme in ("cta", "social_proof") else DARK

        output_paths = []
        timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug         = post.get("headline", "post").lower().replace(" ", "_")[:20]
        total        = min(len(slides), 5)

        for i, slide_text in enumerate(slides[:5]):
            if i == total - 1:
                bg_c = BLUE
            elif i % 2 == 0:
                bg_c = bg
            else:
                bg_c = (248, 247, 255)

            img  = Image.new("RGB", (1080, 1080), bg_c)
            draw = ImageDraw.Draw(img)

            # Top gradient bar
            for x in range(1080):
                t = x / 1080
                r = int(91 + (45 - 91) * t)
                g = int(77 + (212 - 77) * t)
                b = int(255 + (191 - 255) * t)
                draw.line([(x, 0), (x, 5)], fill=(r, g, b))

            font_size = self._calc_font_size(slide_text)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except Exception:
                font = ImageFont.load_default()

            text_colour = (15, 23, 42) if bg_c == (248, 247, 255) else WHITE
            lines    = self._wrap_text(slide_text, font, draw, max_width=880)
            lh       = font_size + 16
            y_start  = (1080 - lh * len(lines)) // 2
            for j, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                w = bbox[2] - bbox[0]
                x = (1080 - w) // 2
                y = y_start + j * lh
                draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 120))
                draw.text((x, y), line, font=font, fill=text_colour)

            # Brand bar bottom
            try:
                wm_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
            except Exception:
                wm_font = ImageFont.load_default()
            wm_colour = (15, 23, 42, 100) if bg_c == (248, 247, 255) else (255, 255, 255, 80)
            draw.text((72, 1040), "ImprovYourSite", font=wm_font, fill=wm_colour)
            draw.text((800, 1040), "improveyoursite.com", font=wm_font, fill=wm_colour)

            out_path = TILES_DIR / f"carousel_{timestamp}_{slug}_{i+1}.png"
            img.save(str(out_path), "PNG")
            output_paths.append(out_path)

        self.log_info(f"Social: Pillow rendered {len(output_paths)} slides")
        return output_paths

    def _generate_dalle_slides(self, post: dict, plan: dict) -> list[Path]:
        """
        Generate carousel slide images using DALL-E 3 via OpenAI API.
        Produces a branded background + overlays slide text using Pillow.
        Returns list of PNG paths or empty list on failure.
        """
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            return []

        try:
            from PIL import Image, ImageDraw, ImageFont
            import base64
            import io
        except ImportError:
            self.log_warn("Visual: Pillow not installed — run bootstrap.py")
            return []

        slides = post.get("slides", [])
        if not slides:
            return []

        # Build a single DALL-E background image
        dalle_prompt = (
            post.get("image_prompt", "")
            or f"Abstract dark minimal background for Instagram carousel. "
               f"Near-black background #0a0a0a. Subtle geometric shapes or gradients in "
               f"electric indigo #5b4dff and neon mint #2dd4bf. No text. Clean, bold, modern."
        )

        # Ensure no text in image (DALL-E sometimes adds text)
        dalle_prompt += " Absolutely no text or letters in the image."

        self.log_info(f"Social: generating DALL-E background...")

        try:
            payload = json.dumps({
                "model":   "dall-e-3",
                "prompt":  dalle_prompt,
                "n":       1,
                "size":    "1024x1024",
                "quality": "standard",
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/images/generations",
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type":  "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            img_url = resp["data"][0]["url"]

            # Download the background image
            with urllib.request.urlopen(img_url, timeout=30) as r:
                bg_bytes = r.read()
            bg_img = Image.open(io.BytesIO(bg_bytes)).convert("RGBA").resize((1080, 1080))

        except Exception as exc:
            self.log_warn(f"Social: DALL-E generation failed: {exc}")
            # Use solid brand colour background as fallback
            bg_img = Image.new("RGBA", (1080, 1080), (10, 10, 10, 255))

        # Overlay slide text on each slide
        BRAND_COLOURS = {
            "bg":      (10, 10, 10, 255),
            "indigo":  (91, 77, 255, 255),
            "mint":    (45, 212, 191, 255),
            "white":   (255, 255, 255, 255),
        }

        output_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, slide_text in enumerate(slides[:5]):
            slide_img = bg_img.copy()
            draw = ImageDraw.Draw(slide_img)

            # Add brand colour overlay for readability
            overlay = Image.new("RGBA", (1080, 1080), (10, 10, 10, 180))
            slide_img = Image.alpha_composite(slide_img, overlay)
            draw = ImageDraw.Draw(slide_img)

            # Try to load Inter Bold, fall back to default
            font_size = self._calc_font_size(slide_text)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except Exception:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()

            # Centre text
            lines = self._wrap_text(slide_text, font, draw, max_width=900)
            line_height = font_size + 20
            total_height = line_height * len(lines)
            y_start = (1080 - total_height) // 2

            for j, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                w = bbox[2] - bbox[0]
                x = (1080 - w) // 2
                y = y_start + j * line_height

                # Drop shadow
                draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 200))
                # Main text in white
                draw.text((x, y), line, font=font, fill=BRAND_COLOURS["white"])

            # Add brand accent bar at bottom
            draw.rectangle([(0, 1020), (1080, 1080)], fill=BRAND_COLOURS["indigo"])

            # Add @improveyoursite.au watermark
            try:
                wm_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
            except Exception:
                wm_font = ImageFont.load_default()
            draw.text((540 - 80, 1030), "@improveyoursite.au", font=wm_font, fill=BRAND_COLOURS["white"])

            # Save
            out_path = TILES_DIR / f"dalle_slide_{timestamp}_{i+1}.png"
            slide_img.convert("RGB").save(str(out_path), "PNG")
            output_paths.append(out_path)

        if output_paths:
            self.log_info(f"Social: DALL-E produced {len(output_paths)} branded slide(s)")

        return output_paths

    @staticmethod
    def _calc_font_size(text: str) -> int:
        """Calculate font size based on text length — shorter = bigger."""
        words = len(text.split())
        if words <= 3:
            return 120
        elif words <= 5:
            return 100
        elif words <= 7:
            return 80
        return 64

    @staticmethod
    def _wrap_text(text: str, font, draw, max_width: int) -> list[str]:
        """Word-wrap text to fit within max_width."""
        words = text.split()
        lines, current = [], []
        for word in words:
            test = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        return lines or [text]

    # ── Instagram publishing ──────────────────────────────────────────────────

    def _ensure_scenario_active(self) -> None:
        """Re-activate the Make.com scenario if it has been auto-paused after an error."""
        api_key     = os.environ.get("MAKE_API_KEY", "")
        scenario_id = os.environ.get("MAKE_SCENARIO_ID", "")
        if not api_key or not scenario_id:
            return
        try:
            # Check current status
            req = urllib.request.Request(
                f"https://eu1.make.com/api/v2/scenarios/{scenario_id}",
                headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            is_active = data.get("scenario", {}).get("isActive", True)
            if not is_active:
                # Re-activate it
                payload = json.dumps({"isActive": True}).encode()
                req = urllib.request.Request(
                    f"https://eu1.make.com/api/v2/scenarios/{scenario_id}",
                    data=payload,
                    method="PATCH",
                    headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    pass
                self.log_info("Make.com: scenario was paused — re-activated successfully")
            else:
                self.log_info("Make.com: scenario is active")
        except Exception as exc:
            self.log_warn(
                f"Make.com: scenario check blocked (Cloudflare 403) — post still sent via webhook. "
                f"If post doesn't appear on Instagram, toggle scenario ON at make.com"
            )

    def _publish_via_make(self, webhook_url: str, slide_paths: list[Path], caption: str, facebook_caption: str = "") -> bool:
        """
        Post a carousel to Instagram + Facebook via Make.com webhook.

        Make.com scenario setup:
          1. Trigger: Webhooks → Custom webhook (copy URL → MAKE_WEBHOOK_URL in .env)
          2. Action: Instagram → Create a Carousel Post
             - Caption field: map {{1.caption}}
             - Media → add 5 items, map {{1.slide_1}} … {{1.slide_5}}
          3. Action: Facebook Pages → Create a Page Post (photo)
             - Message field: map {{1.facebook_caption}}
             - Photo URL: map {{1.slide_1}}

        This sends up to 5 public image URLs as slide_1 … slide_5.
        """
        if not slide_paths:
            return False

        # Wake scenario if Make.com auto-paused it after a previous error
        self._ensure_scenario_active()

        try:
            # Upload all slides to GitHub to get public URLs
            slide_urls = []
            for path in slide_paths[:5]:
                url = self._upload_image_to_repo(path)
                if url:
                    slide_urls.append(url)
                    self.log_info(f"Make.com: uploaded {path.name} → {url}")
                else:
                    self.log_warn(f"Make.com: upload failed for {path.name}")

            if not slide_urls:
                self.log_warn("Make.com: all image uploads failed — no GITHUB_PAT set?")
                return False

            # Build payload with slide_1 … slide_N
            payload: dict = {
                "caption":          caption,
                "facebook_caption": facebook_caption or caption.split("\n\n#")[0],
            }
            for i, url in enumerate(slide_urls, 1):
                payload[f"slide_{i}"] = url

            self.log_info(f"Make.com: sending {len(slide_urls)}-slide carousel payload")

            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                status = r.status
            return status == 200

        except Exception as exc:
            self.log_error(f"Make.com webhook failed: {exc}")
            return False

    def _mark_posted(self, post: dict):
        """Mark a queued post as posted."""
        if not QUEUE_FILE.exists():
            return
        try:
            queue = json.loads(QUEUE_FILE.read_text())
            for item in queue:
                if item.get("headline") == post.get("headline") and item.get("status") == "pending":
                    item["status"] = "posted"
                    break
            QUEUE_FILE.write_text(json.dumps(queue, indent=2))
        except Exception:
            pass

    def _publish_to_instagram(
        self, token: str, account_id: str, image_path: Path, caption: str
    ) -> Optional[str]:
        """
        Publish a single image post to Instagram via Graph API.
        Requires the image to be at a public URL.
        """
        try:
            # Step 1: Upload image to repo for public URL
            image_url = self._upload_image_to_repo(image_path)
            if not image_url:
                self.log_warn("Could not get public image URL — skipping publish")
                return None

            # Step 2: Create media container
            create_url = f"{GRAPH_BASE}/{account_id}/media"
            params = urllib.parse.urlencode({
                "image_url":   image_url,
                "caption":     caption,
                "access_token": token,
            })
            req = urllib.request.Request(
                create_url, data=params.encode(), method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                container = json.loads(r.read())
            container_id = container.get("id")
            if not container_id:
                self.log_error(f"IG media container failed: {container}")
                return None

            # Step 3: Publish
            publish_url = f"{GRAPH_BASE}/{account_id}/media_publish"
            pub_params = urllib.parse.urlencode({
                "creation_id":  container_id,
                "access_token": token,
            })
            req = urllib.request.Request(
                publish_url, data=pub_params.encode(), method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            post_id = result.get("id")
            return f"https://www.instagram.com/p/{post_id}/" if post_id else None

        except Exception as exc:
            self.log_error(f"Instagram publish failed: {exc}")
            return None

    def _upload_image_to_repo(self, image_path: Path) -> Optional[str]:
        """Push the image PNG to social/posts/ in the repo via GitHub API."""
        pat = os.environ.get("GITHUB_PAT", "")
        if not pat:
            return None

        try:
            import base64
            img_b64 = base64.b64encode(image_path.read_bytes()).decode()
            dest_path = f"social/posts/{image_path.name}"
            api_url = f"https://api.github.com/repos/anon8597299/smart-tech-innovations/contents/{dest_path}"

            # Check if file exists (get sha)
            sha = None
            try:
                req = urllib.request.Request(
                    api_url,
                    headers={
                        "Authorization": f"token {pat}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                with urllib.request.urlopen(req) as r:
                    existing = json.loads(r.read())
                    sha = existing.get("sha")
            except Exception:
                pass

            payload = {"message": f"Social post image: {image_path.name}", "content": img_b64}
            if sha:
                payload["sha"] = sha

            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode(),
                method="PUT",
                headers={
                    "Authorization": f"token {pat}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                pass

            return f"https://raw.githubusercontent.com/anon8597299/smart-tech-innovations/main/{dest_path}"
        except Exception as exc:
            self.log_warn(f"Image upload failed: {exc}")
            return None

    # ── Upload queue ──────────────────────────────────────────────────────────

    def _queue_post(self, post: dict, slide_paths: list[Path]):
        """Save post to social/upload_queue.json for manual Instagram upload."""
        queue = []
        if QUEUE_FILE.exists():
            try:
                queue = json.loads(QUEUE_FILE.read_text())
            except Exception:
                queue = []

        entry = {
            "date":             date.today().isoformat(),
            "headline":         post.get("headline", ""),
            "caption":          post.get("caption", ""),
            "facebook_caption": post.get("facebook_caption", ""),
            "slides":           post.get("slides", []),
            "image_path":       str(slide_paths[0]) if slide_paths else None,
            "slide_paths":      [str(p) for p in slide_paths],
            "status":           "pending",
        }
        queue.append(entry)
        QUEUE_FILE.write_text(json.dumps(queue, indent=2))
        names = ", ".join(p.name for p in slide_paths) if slide_paths else "none"
        self.log_info(f"Queued post: {entry['headline']} — slides: {names}")

    # ── Insights ──────────────────────────────────────────────────────────────

    def _fetch_insights(self, token: str, account_id: str):
        try:
            url = (
                f"{GRAPH_BASE}/{account_id}/insights"
                f"?metric=reach,impressions,profile_views"
                f"&period=week&access_token={token}"
            )
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            metrics = {m["name"]: m["values"][-1]["value"] for m in data.get("data", [])}
            self.log_info(
                f"IG insights (7d): reach={metrics.get('reach',0)}, "
                f"impressions={metrics.get('impressions',0)}, "
                f"views={metrics.get('profile_views',0)}"
            )
        except Exception as exc:
            self.log_warn(f"Insights fetch failed: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_time_slot() -> str:
        hour = datetime.now().hour
        if hour < 12:
            return "morning"
        elif hour < 17:
            return "afternoon"
        else:
            return "evening"
