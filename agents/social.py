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
        "theme": "motivation",
        "angle": "Start of week energy for small business owners. Practical tip they can use today.",
        "format": "single_tip",
        "caption_tone": "Direct and energising. Like talking to a mate who runs a business.",
    },
    1: {  # Tuesday
        "theme": "education",
        "angle": "Website or SEO tip that most small businesses get wrong. Specific and actionable.",
        "format": "carousel",
        "caption_tone": "Conversational expert. Not salesy. Give the value first.",
    },
    2: {  # Wednesday
        "theme": "social_proof",
        "angle": "Result or before/after story. Focus on the outcome for the customer, not the tech.",
        "format": "carousel",
        "caption_tone": "Storytelling. Real problem → real solution → specific result.",
    },
    3: {  # Thursday
        "theme": "behind_scenes",
        "angle": "How we build sites / what goes into a website that actually converts. Demystify it.",
        "format": "carousel",
        "caption_tone": "Transparent and honest. Show the craft. No jargon.",
    },
    4: {  # Friday
        "theme": "cta",
        "angle": "End of week urgency. Limited spots, genuine offer, or a question that makes them reflect.",
        "format": "single_tip",
        "caption_tone": "Confident and direct. Clear next step. Not desperate.",
    },
    5: {  # Saturday
        "theme": "inspiration",
        "angle": "Australian small business story or insight. Something they can relate to on the weekend.",
        "format": "single_tip",
        "caption_tone": "Warm and relatable. Weekend vibes but still useful.",
    },
    6: {  # Sunday
        "theme": "planning",
        "angle": "Question or prompt that makes them think about their business website/growth for the week.",
        "format": "single_tip",
        "caption_tone": "Thought-provoking. Ask a question rather than tell.",
    },
}

# ── Australian SMB Instagram hashtags by industry ────────────────────────────
HASHTAGS = {
    "web":      "#smallbusiness #australianbusiness #sydneybusiness #websitedesign "
                "#localbusiness #digitalmarketing #businessgrowth #seoaustralia "
                "#websitetips #smallbusinessowner #melbournebusiness #brisbanebusiness",
    "trades":   "#tradie #australiantradie #plumber #electrician #smallbusiness "
                "#localbusiness #tradesman #australianbusiness #businesswebsite",
    "health":   "#gpaustralia #healthclinic #medicalpractice #smallbusiness "
                "#australianhealthcare #localdoctor #businesswebsite",
}


class SocialAgent(BaseAgent):
    agent_id = "social"
    name     = "Social"

    def run(self):
        today     = date.today()
        weekday   = today.weekday()
        plan      = CONTENT_CALENDAR[weekday]
        time_slot = self._get_time_slot()

        self.log_info(f"Social: {today} ({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][weekday]}) "
                      f"— theme: {plan['theme']}, slot: {time_slot}")

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
            # Evening run: use this morning's report if available
            if REPORT_FILE.exists():
                try:
                    intel = json.loads(REPORT_FILE.read_text())
                except Exception:
                    intel = {}

        # 2. Market research (legacy — now supplemented by intel)
        tid = self.create_task("research", f"Market research: {plan['theme']}")
        trending = self._research_trending(plan, intel)
        self.complete_task(tid, f"Research complete: {len(trending)} insights")

        # 2. Generate post content
        tid = self.create_task("copywriting", f"Writing {plan['format']} copy")
        self.update_progress(tid, 20)
        recommended = intel.get("recommended_angles", []) if intel else []
        post = self._generate_post(plan, trending, today, time_slot, recommended)
        if not post:
            self.fail_task(tid, "Content generation failed")
            return
        self.complete_task(tid, post.get("headline", "Post written"))

        # 3. Generate visual (carousel PNG via existing scripts)
        tid = self.create_task("visual", f"Producing visual: {plan['theme']}")
        image_path = self._produce_visual(plan, post)
        self.complete_task(tid, f"Visual: {image_path.name if image_path else 'queued'}")

        # 4. Publish or queue
        # Priority: Make.com webhook (free) → Graph API → manual queue
        make_url   = os.environ.get("MAKE_WEBHOOK_URL", "")
        ig_token   = os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

        if make_url and image_path:
            tid = self.create_task("publish", "Publishing via Make.com → Instagram")
            published = self._publish_via_make(make_url, image_path, post["caption"])
            if published:
                self.complete_task(tid, "Posted to Instagram via Make.com")
                self.log_info("Social: published to Instagram via Make.com webhook")
                self._mark_posted(post)
            else:
                self.fail_task(tid, "Make.com publish failed — queued for manual post")
                self._queue_post(post, image_path)

        elif ig_token and account_id and image_path:
            tid = self.create_task("publish", "Publishing via Instagram Graph API")
            published = self._publish_to_instagram(ig_token, account_id, image_path, post["caption"])
            if published:
                self.complete_task(tid, f"Posted: {published}")
                self.log_info(f"Social: published via Graph API — {published}")
                self._mark_posted(post)
            else:
                self.fail_task(tid, "Graph API publish failed — queued for manual post")
                self._queue_post(post, image_path)

        else:
            self._queue_post(post, image_path)
            self.log_info("Social: post queued — add MAKE_WEBHOOK_URL to builder/.env to auto-post")

        # 5. Log insights if token available
        read_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        if read_token and account_id:
            self._fetch_insights(read_token, account_id)

        # 6. Log to content DB
        db.content_add(
            content_type="carousel",
            title=post.get("headline", f"IG post {today}"),
            preview_path=str(image_path) if image_path else None,
            status="delivered",
        )

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

    def _generate_post(self, plan: dict, trending: list[str], today: date, time_slot: str, recommended_angles: list = None) -> dict | None:
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

        system = """You write Instagram content for ImproveYourSite.com, an Australian web agency
that builds websites for small businesses (tradies, GP clinics, accountants, boutiques, consultants).

The audience is Australian small business owners, typically 35-55, time-poor, skeptical of marketing fluff.
They respond to: specific numbers, real examples, direct language, local references (e.g. "in Bathurst",
"regional NSW"), and content that treats them like intelligent adults.

They do NOT respond to: corporate speak, buzzwords like "leverage synergies", excessive exclamation marks,
obvious AI-sounding copy, or content that's clearly just trying to sell them something.

Always write as if you're a smart local who genuinely knows business websites, not a marketer."""

        prompt = f"""Today is {day_name}. Create an Instagram post for the {time_slot} slot.

Theme: {plan['theme']}
Angle: {plan['angle']}
Format: {plan['format']}
Tone: {plan['caption_tone']}

Current trending insights (from market research today):
{research_text}{angles_text}

If a competitive angle above fits today's theme better than a generic post — use it.
Prioritise angles that competitors are NOT covering.

Return ONLY valid JSON with these exact keys:
{{
  "headline": "The main hook (under 8 words, no punctuation at end)",
  "slides": ["slide 1 text (under 12 words)", "slide 2", "slide 3", "slide 4", "slide 5"],
  "caption": "The full Instagram caption (2-4 sentences, conversational, ends with a question or CTA). Include relevant Australian hashtags at the end.",
  "alt_text": "Image description for accessibility"
}}

For the caption: use a line break between the main copy and hashtags. Max 3 paragraphs.
Do not start with 'Are you' or 'Did you know'. Start with a statement or a number."""

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
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
        # Append hashtags if not present
        if HASHTAGS["web"] not in post["caption"]:
            post["caption"] += "\n\n" + HASHTAGS["web"]
        return post

    def _template_post(self, plan: dict, today: date) -> dict:
        """Fallback post when no API key is set."""
        templates = {
            "motivation":   {
                "headline": "Your website works while you sleep",
                "slides":   ["Your website works 24/7", "Customers search at 11pm", "Is yours ready?", "improveyoursite.com", "Free audit available"],
                "caption":  "Most small business owners don't realise their website is losing them customers every day. Not because it's ugly — because it's slow, unclear, or doesn't show up on Google.\n\nWe fix that. Results in 2–4 weeks.\n\n" + HASHTAGS["web"],
                "alt_text": "Text: Your website works while you sleep",
            },
            "education":    {
                "headline": "3 website mistakes costing you customers",
                "slides":   ["Slow load time = lost sales", "No clear CTA = confused visitors", "Not mobile-first = 60% gone", "No Google Business = invisible", "We fix all of these"],
                "caption":  "Checked your website speed lately? Most small business sites take 6+ seconds to load on mobile. Google penalises anything over 3.\n\nFast site = more enquiries. Simple as that.\n\n" + HASHTAGS["web"],
                "alt_text": "3 website mistakes costing small businesses customers",
            },
        }
        base = templates.get(plan["theme"], templates["education"])
        return base

    # ── Visual production ─────────────────────────────────────────────────────

    def _produce_visual(self, plan: dict, post: dict) -> Path | None:
        """
        Tries to produce a carousel PNG using existing make_*.py scripts.
        Picks the script most relevant to today's theme.
        Falls back to any available script.
        """
        TILES_DIR.mkdir(parents=True, exist_ok=True)

        theme_script_map = {
            "education":     "make_seo_mistake_carousel.py",
            "motivation":    "make_tile.py",
            "social_proof":  "make_perf_carousel.py",
            "behind_scenes": "make_ai_seo_carousel.py",
            "cta":           "make_audit_post.py",
            "inspiration":   "make_llm_carousel.py",
            "planning":      "make_maps_carousel.py",
        }

        preferred = theme_script_map.get(plan["theme"])
        scripts = list(SOCIAL_DIR.glob("make_*.py"))

        # Sort: preferred first
        def sort_key(p):
            return 0 if p.name == preferred else 1
        scripts.sort(key=sort_key)

        for script in scripts:
            try:
                result = subprocess.run(
                    [sys.executable, str(script)],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    timeout=60,
                )
                if result.returncode == 0:
                    # Find the most recently created PNG in Tiles dir
                    pngs = sorted(TILES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if pngs:
                        return pngs[0]
            except Exception as exc:
                self.log_warn(f"Script {script.name} failed: {exc}")

        self.log_warn("No carousel scripts succeeded — post will be text-only")
        return None

    # ── Instagram publishing ──────────────────────────────────────────────────

    def _publish_via_make(self, webhook_url: str, image_path: Path, caption: str) -> bool:
        """
        Post to Instagram via Make.com (free tier covers ~60 posts/month).

        Setup:
          1. make.com → New Scenario
          2. Trigger: Webhooks → Custom webhook → copy URL
          3. Action: Instagram → Create a Photo Post
          4. Map caption={{caption}}, image_url={{image_url}}
          5. Add MAKE_WEBHOOK_URL to builder/.env

        Make receives the JSON, fetches the image, posts to Instagram.
        """
        try:
            # Image needs to be at a public URL
            image_url = self._upload_image_to_repo(image_path)
            if not image_url:
                self.log_warn("Make.com: could not get public image URL — no GITHUB_PAT set?")
                return False

            payload = json.dumps({
                "caption":   caption,
                "image_url": image_url,
            }).encode()

            req = urllib.request.Request(
                webhook_url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                # Make.com returns "Accepted" (200) on success
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
    ) -> str | None:
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

    def _upload_image_to_repo(self, image_path: Path) -> str | None:
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

            return f"https://improveyoursite.com/{dest_path}"
        except Exception as exc:
            self.log_warn(f"Image upload failed: {exc}")
            return None

    # ── Upload queue ──────────────────────────────────────────────────────────

    def _queue_post(self, post: dict, image_path: Path | None):
        """Save post to social/upload_queue.json for manual Instagram upload."""
        queue = []
        if QUEUE_FILE.exists():
            try:
                queue = json.loads(QUEUE_FILE.read_text())
            except Exception:
                queue = []

        entry = {
            "date":       date.today().isoformat(),
            "headline":   post.get("headline", ""),
            "caption":    post.get("caption", ""),
            "slides":     post.get("slides", []),
            "image_path": str(image_path) if image_path else None,
            "status":     "pending",
        }
        queue.append(entry)
        QUEUE_FILE.write_text(json.dumps(queue, indent=2))
        self.log_info(f"Queued post: {entry['headline']} — image: {image_path.name if image_path else 'none'}")

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
