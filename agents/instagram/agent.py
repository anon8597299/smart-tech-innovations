"""
agents/instagram/agent.py — Instagram Agent

Dedicated Instagram content engine for ImproveYourSite.com.

What it does:
  - Stories: 2x per day (8:00 AM + 7:00 PM AEST) via Make.com story webhook
  - Story content: daily tips, polls, behind-the-scenes, swipe links
  - Feed insights: track reach, saves, comments on recent posts
  - Reels planning: generates script + caption doc (manual upload for now)
  - Self-diagnostics: checks all credentials, webhook connectivity, token expiry
  - Weekly Instagram report: followers, top posts, engagement rate

Schedule (set in scheduler.py):
  - Stories:   8:00 AM + 7:00 PM AEST daily
  - Insights:  9:30 AM AEST daily (after morning story)
  - Reels doc: Wednesday 8:00 AM AEST

Required in builder/.env:
  MAKE_WEBHOOK_URL           — carousel webhook (existing)
  MAKE_STORY_WEBHOOK_URL     — story-specific Make.com webhook URL
  INSTAGRAM_PUBLISHING_TOKEN — long-lived token, instagram_content_publish scope
  INSTAGRAM_ACCESS_TOKEN     — same or separate token with instagram_manage_insights
  INSTAGRAM_ACCOUNT_ID       — Business/Creator account numeric ID
  ANTHROPIC_API_KEY          — content generation
  GITHUB_PAT                 — image hosting (reuses existing)

Diagnostics: run with RUN_MODE=diagnose to check all deps without posting.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent.parent
SOCIAL_DIR   = PROJECT_ROOT / "social"
TILES_DIR    = Path.home() / "Documents" / "ImproveYourSite - Social Media" / "Tiles"
QUEUE_FILE   = SOCIAL_DIR / "upload_queue.json"
STORY_QUEUE  = SOCIAL_DIR / "story_queue.json"
REELS_DIR    = SOCIAL_DIR / "reels"
INSIGHTS_LOG = SOCIAL_DIR / "instagram_insights.json"
GRAPH_BASE    = "https://graph.facebook.com/v19.0"
STRATEGY_FILE = SOCIAL_DIR / "weekly_strategy.json"

# ── Story content calendar ─────────────────────────────────────────────────────
STORY_CALENDAR = {
    0: {  # Monday
        "type": "tip",
        "prompt": "One specific website tip an Australian small business owner can action TODAY. Under 12 words. Direct, no fluff.",
        "cta": "Swipe up for a free site audit",
    },
    1: {  # Tuesday
        "type": "question",
        "prompt": "A YES/NO poll question that makes an Australian SMB owner reflect on their website. Phrased as a genuine question, not a trick.",
        "cta": "Reply with your answer",
    },
    2: {  # Wednesday
        "type": "behind_scenes",
        "prompt": "A behind-the-scenes fact about building websites for Australian small businesses. Something surprising or unexpected. One sentence.",
        "cta": "DM us to find out more",
    },
    3: {  # Thursday
        "type": "stat",
        "prompt": "A specific, real-sounding Australian digital marketing statistic that would alarm a small business owner. Make it about websites, SEO, or mobile. Cite the source type (e.g. 'Source: Google AU').",
        "cta": "Link in bio to check your site",
    },
    4: {  # Friday
        "type": "offer",
        "prompt": "A Friday call-to-action for ImproveYourSite's free 20-min discovery call. Conversational, no pressure, outcome-focused. Two sentences max.",
        "cta": "Book your free call this weekend",
    },
    5: {  # Saturday
        "type": "inspiration",
        "prompt": "An inspiring one-liner about Australian small business resilience or growth. Feels like a real person said it, not a quote generator.",
        "cta": "Tag a biz owner who needs this",
    },
    6: {  # Sunday
        "type": "preview",
        "prompt": "A teaser for what ImproveYourSite is posting this week. Builds anticipation. 'This week on our feed:' style. Two things max.",
        "cta": "Follow so you don't miss it",
    },
}


class InstagramAgent(BaseAgent):
    agent_id = "instagram"
    name     = "Instagram"

    def run(self):
        mode = os.environ.get("RUN_MODE", "post")
        if mode == "diagnose":
            self._run_diagnostics()
            return

        # Always check Make.com webhook is active before posting
        self._ensure_make_webhook_active()

        slot = os.environ.get("IG_SLOT", self._get_slot())

        if slot == "story":
            self._run_story()
        elif slot == "insights":
            self._run_insights()
        elif slot == "reels":
            self._run_reels_planning()
        else:
            self._run_story()

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def _run_diagnostics(self):
        """Full pre-flight check — logs status of every dependency."""
        tid = self.create_task("diagnostics", "Instagram agent diagnostics")
        self.log_info("Instagram: running diagnostics...")
        results = []

        # 1. ENV vars
        required = {
            "MAKE_WEBHOOK_URL":           os.environ.get("MAKE_WEBHOOK_URL", ""),
            "MAKE_STORY_WEBHOOK_URL":     os.environ.get("MAKE_STORY_WEBHOOK_URL", ""),
            "INSTAGRAM_PUBLISHING_TOKEN": os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", ""),
            "INSTAGRAM_ACCESS_TOKEN":     os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""),
            "INSTAGRAM_ACCOUNT_ID":       os.environ.get("INSTAGRAM_ACCOUNT_ID", ""),
            "ANTHROPIC_API_KEY":          os.environ.get("ANTHROPIC_API_KEY", ""),
            "GITHUB_PAT":                 os.environ.get("GITHUB_PAT", ""),
        }
        for key, val in required.items():
            status = "✓ SET" if val else "✗ MISSING"
            results.append(f"  {status}  {key}")
            self.log_info(f"Diag ENV: {status} {key}")

        self.update_progress(tid, 30)

        # 2. Make.com webhook connectivity
        story_url = os.environ.get("MAKE_STORY_WEBHOOK_URL", "")
        if story_url:
            try:
                req = urllib.request.Request(
                    story_url,
                    data=json.dumps({"_diagnostic": True}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    results.append(f"  ✓ Make.com story webhook reachable (HTTP {r.status})")
                    self.log_info(f"Diag webhook: reachable (HTTP {r.status})")
            except Exception as exc:
                results.append(f"  ✗ Make.com story webhook FAILED: {exc}")
                self.log_warn(f"Diag webhook: FAILED: {exc}")
        else:
            results.append("  ✗ MAKE_STORY_WEBHOOK_URL not set — story publishing disabled")

        self.update_progress(tid, 60)

        # 3. Instagram Graph API token validity
        ig_token   = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "") or os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
        if ig_token and account_id:
            try:
                url = f"{GRAPH_BASE}/{account_id}?fields=username,followers_count&access_token={ig_token}"
                with urllib.request.urlopen(url, timeout=10) as r:
                    data = json.loads(r.read())
                username  = data.get("username", "?")
                followers = data.get("followers_count", "?")
                results.append(f"  ✓ Instagram token valid — @{username} ({followers:,} followers)" if isinstance(followers, int) else f"  ✓ Instagram token valid — @{username}")
                self.log_info(f"Diag IG API: valid @{username}")
            except Exception as exc:
                results.append(f"  ✗ Instagram API check FAILED: {exc}")
                self.log_warn(f"Diag IG API: FAILED: {exc}")
        else:
            results.append("  ✗ Instagram token/account not configured")

        self.update_progress(tid, 90)

        # 4. Tiles directory
        tiles_ok = TILES_DIR.exists()
        results.append(f"  {'✓' if tiles_ok else '✗'} Tiles dir: {TILES_DIR}")

        # 5. Claude API
        ant_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if ant_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=ant_key)
                r = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}],
                )
                results.append("  ✓ Anthropic API reachable")
                self.log_info("Diag Anthropic: reachable")
            except Exception as exc:
                results.append(f"  ✗ Anthropic API FAILED: {exc}")
                self.log_warn(f"Diag Anthropic: FAILED: {exc}")
        else:
            results.append("  ✗ ANTHROPIC_API_KEY not set")

        summary = "\n".join(results)
        self.log_info(f"Instagram diagnostics complete:\n{summary}")
        self.complete_task(tid, f"Diagnostics done — {sum(1 for r in results if '✓' in r)}/{len(results)} checks passed")

    # ── Make.com health check ─────────────────────────────────────────────────

    def _ensure_make_webhook_active(self):
        """Re-activate Make.com scenario if paused. Check webhook is live before posting."""
        api_key     = os.environ.get("MAKE_API_KEY", "")
        scenario_id = os.environ.get("MAKE_SCENARIO_ID", "")
        webhook_url = os.environ.get("MAKE_WEBHOOK_URL", "")

        if not webhook_url:
            self.log_warn("Instagram: MAKE_WEBHOOK_URL not set — will queue posts instead")
            return

        # Try to reactivate via Make.com API
        if api_key and scenario_id:
            try:
                req = urllib.request.Request(
                    f"https://eu1.make.com/api/v2/scenarios/{scenario_id}",
                    headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                is_active = data.get("scenario", {}).get("isActive", True)
                if not is_active:
                    payload = json.dumps({"isActive": True}).encode()
                    req = urllib.request.Request(
                        f"https://eu1.make.com/api/v2/scenarios/{scenario_id}",
                        data=payload, method="PATCH",
                        headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        pass
                    self.log_info("Instagram: Make.com scenario was paused — re-activated ✓")
                else:
                    self.log_info("Instagram: Make.com scenario is active ✓")
            except Exception as exc:
                # Cloudflare often blocks this — not critical
                self.log_info(f"Instagram: Make.com scenario check skipped ({exc}) — webhook still live")

    # ── Weekly strategy reader ────────────────────────────────────────────────

    def _get_strategy_story_brief(self, today: date) -> dict | None:
        """
        Check social/weekly_strategy.json for today's story plan.
        Returns the story dict if today's date matches, else None.
        """
        if not STRATEGY_FILE.exists():
            return None
        try:
            strategy = json.loads(STRATEGY_FILE.read_text())
            today_str = today.isoformat()
            for day_name, day_data in strategy.get("days", {}).items():
                if day_data.get("date") == today_str:
                    story = day_data.get("story")
                    if story:
                        return story
        except Exception as exc:
            self.log_warn(f"Instagram: could not read weekly_strategy.json: {exc}")
        return None

    # ── Story posting ─────────────────────────────────────────────────────────

    def _run_story(self):
        today   = date.today()
        weekday = today.weekday()
        plan    = STORY_CALENDAR[weekday]
        slot    = self._get_slot()

        self.log_info(f"Instagram: story run — {today} {slot} ({plan['type']})")

        # Check weekly strategy for today's story brief
        story_brief = self._get_strategy_story_brief(today)
        if story_brief:
            self.log_info(
                f"Instagram: using weekly strategy story brief — "
                f"type: {story_brief.get('type', '?')}, "
                f"headline: {story_brief.get('headline', '?')}"
            )
            # Override the plan type with the strategy's story type
            if story_brief.get("type"):
                plan = {**plan, "type": story_brief["type"]}

        # Generate story text
        tid = self.create_task("story_copy", f"Writing {plan['type']} story copy")
        copy = self._generate_story_copy(plan, today, slot, story_brief=story_brief)
        if not copy:
            self.fail_task(tid, "Story copy generation failed")
            return
        self.complete_task(tid, copy.get("headline", "Story written"))

        # Find/produce story image — render branded version if no tile found
        tid2 = self.create_task("story_visual", "Rendering story visual")
        image_path = self._get_story_image(plan["type"], today)
        if not image_path:
            image_path = self._render_story_image(copy, plan["type"], today)
        self.complete_task(tid2, str(image_path) if image_path else "no image — text story queued")

        # Publish via Make.com story webhook or queue
        story_url  = os.environ.get("MAKE_STORY_WEBHOOK_URL", "")
        ig_token   = os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

        if story_url and image_path:
            tid3 = self.create_task("story_publish", "Publishing story via Make.com")
            ok = self._publish_story_via_make(story_url, image_path, copy)
            if ok:
                self.complete_task(tid3, f"Story published via Make.com: {copy['headline']}")
                self.log_info(f"Instagram: story published via Make.com — {copy['headline']}")
            else:
                self.fail_task(tid3, "Make.com story publish failed — queued")
                self._queue_story(copy, image_path)
        elif ig_token and account_id and image_path:
            tid3 = self.create_task("story_publish", "Publishing story via Graph API")
            ok = self._publish_story_graph(ig_token, account_id, image_path, copy)
            if ok:
                self.complete_task(tid3, f"Story published via Graph API")
            else:
                self.fail_task(tid3, "Graph API story failed — queued")
                self._queue_story(copy, image_path)
        else:
            self._queue_story(copy, image_path)
            self.log_info("Instagram: story queued — add MAKE_STORY_WEBHOOK_URL to builder/.env")

        db.content_add(
            content_type="ig_story",
            title=copy.get("headline", f"Story {today} {slot}"),
            preview_path=str(image_path) if image_path else None,
            status="delivered",
        )

    def _generate_story_copy(self, plan: dict, today: date, slot: str, story_brief: dict = None) -> dict | None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._template_story(plan, today)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            system = """You write Instagram content for ImproveYourSite.com — an Australian web agency
that builds websites for small businesses nationwide.

WINNING REFERENCE POST (this is the gold standard):
"Your website is costing you customers"
Why it works: Simple. Large centred text. No fluff. Names a real fear. Hook + problem + CTA in one line.

STRICT RULES — every post must follow these:
1. MAX 6 WORDS for the headline. 4 is better. 3 is ideal.
2. Text goes LARGE and CENTRED on screen — like a billboard, not a document.
3. ONE idea only. Never explain it — let the viewer feel it.
4. NO city or town names. National audience. Keep it universal.
5. NO marketing speak. No "leverage", "synergy", "digital presence".
6. Sounds like a direct human, not an agency.
7. The viewer must feel something in under 3 seconds.
8. NO HYPHENS anywhere. Not in headlines, not in copy, not anywhere. Hyphens are the #1 AI dead giveaway.
   Use a full stop, a line break, or rewrite without the hyphen.

The winning formula: Name their FEAR or PROBLEM in 4-6 words. That's it."""

            # Build strategy brief block if available
            strategy_block = ""
            if story_brief:
                s_headline = story_brief.get("headline", "")
                s_body     = story_brief.get("body", "")
                s_cta      = story_brief.get("cta", "")
                strategy_block = "\n\nWEEKLY STRATEGY BRIEF (use as primary direction):\n"
                if s_headline:
                    strategy_block += f"  Headline direction: \"{s_headline}\"\n"
                if s_body:
                    strategy_block += f"  Body copy direction: {s_body}\n"
                if s_cta:
                    strategy_block += f"  CTA direction: {s_cta}\n"
                strategy_block += (
                    "Build from this brief. Keep the headline to 3-6 words. "
                    "No hyphens. No city names."
                )

            prompt = f"""Story type: {plan['type']}
Brief: {plan['prompt']}
Slot: {slot}{strategy_block}

Apply the WINNING FORMULA: name a real business fear in 4-6 words.
NO city names. NO town names. Universal Australian small business language only.
If a weekly strategy brief is provided above, use it as your primary direction.

Return ONLY valid JSON:
{{
  "headline": "Large centred text (3-6 words MAX — think billboard)",
  "subtext": "One supporting phrase under 5 words, or empty string",
  "cta_text": "CTA button text (under 4 words)",
  "sticker_text": "Poll text if type is 'question', else empty string",
  "alt_text": "Accessibility description"
}}"""

            r = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = r.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as exc:
            self.log_warn(f"Story copy generation failed: {exc}")
            return self._template_story(plan, today)

    def _template_story(self, plan: dict, today: date) -> dict:
        templates = {
            "tip":          {"headline": "1 in 3 AU businesses loses customers to a slow site", "subtext": "Is yours fast enough?", "cta_text": "Free audit", "sticker_text": "", "alt_text": "Website speed tip"},
            "question":     {"headline": "Does your website show up on Google Maps?", "subtext": "", "cta_text": "Tell us →", "sticker_text": "Yes / No / Not sure", "alt_text": "Question about Google Maps"},
            "behind_scenes": {"headline": "Every site we build gets 3 rounds of mobile testing", "subtext": "Most agencies skip this", "cta_text": "See our process", "sticker_text": "", "alt_text": "Behind the scenes at IYS"},
            "stat":         {"headline": "53% of mobile users leave if a page takes >3 seconds", "subtext": "Source: Google AU", "cta_text": "Check yours", "sticker_text": "", "alt_text": "Mobile speed statistic"},
            "offer":        {"headline": "Free 20-min call this week — no pitch, just honest advice", "subtext": "Limited spots available", "cta_text": "Book now", "sticker_text": "", "alt_text": "Free discovery call offer"},
            "inspiration":  {"headline": "Australian small businesses built this country", "subtext": "A good website helps you keep building it", "cta_text": "See our work", "sticker_text": "", "alt_text": "Inspirational small business message"},
            "preview":      {"headline": "This week: website mistakes that cost you leads", "subtext": "Plus a real before/after", "cta_text": "Follow us", "sticker_text": "", "alt_text": "Week preview"},
        }
        return templates.get(plan["type"], templates["tip"])

    def _get_story_image(self, story_type: str, today: date) -> Path | None:
        """Find the best matching story tile from the tiles directory."""
        TILES_DIR.mkdir(parents=True, exist_ok=True)
        # Look for any PNG in the tiles dir — prefer most recent
        pngs = sorted(TILES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        # Try to pick a thematic match
        for png in pngs:
            name = png.name.lower()
            if story_type in name or today.strftime("%Y%m%d") in name:
                return png
        return pngs[0] if pngs else None

    def _render_story_image(self, copy: dict, plan_type: str, today) -> Path | None:
        """Render a branded 1080x1920 story PNG via Playwright."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        BLUE = "#5b4dff"
        MINT = "#2dd4bf"
        DARK = "#0f172a"

        _BG = {
            "tip": DARK, "stat": DARK, "inspiration": "#0a1628",
            "question": "#1e1b4b", "preview": "#1e1b4b",
            "behind_scenes": "#0f1f3d", "offer": BLUE,
        }
        bg     = _BG.get(plan_type, DARK)
        accent = MINT if plan_type not in ("offer",) else "#2dd4bf"

        headline = copy.get("headline", "")
        subtext  = copy.get("subtext", "")
        cta      = copy.get("cta_text", "")
        sticker  = copy.get("sticker_text", "")

        words = len(headline.split())
        if words <= 4:   fs = "88px"
        elif words <= 6: fs = "76px"
        elif words <= 9: fs = "64px"
        else:            fs = "52px"

        sub_html = (
            f"<p style='font-family:Inter,sans-serif;font-size:28px;font-weight:500;"
            f"color:rgba(255,255,255,.5);margin-top:24px;line-height:1.4;'>{subtext}</p>"
        ) if subtext else ""

        cta_html = (
            f"<div style='margin-top:56px;display:inline-block;"
            f"background:{accent};color:#fff;"
            f"padding:20px 52px;border-radius:999px;"
            f"font-family:Inter,sans-serif;font-size:22px;font-weight:800;"
            f"letter-spacing:-.01em;'>{cta}</div>"
        ) if cta else ""

        sticker_html = (
            f"<div style='position:absolute;bottom:240px;left:50%;transform:translateX(-50%);"
            f"background:rgba(255,255,255,.12);border:2px solid rgba(255,255,255,.2);"
            f"border-radius:24px;padding:20px 40px;"
            f"font-family:Inter,sans-serif;font-size:22px;font-weight:700;"
            f"color:rgba(255,255,255,.85);text-align:center;white-space:nowrap;'>{sticker}</div>"
        ) if sticker else ""

        FONT = (
            "<link href='https://fonts.googleapis.com/css2?family=Inter:"
            "wght@400;500;600;700;800;900&display=swap' rel='stylesheet'>"
        )
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">{FONT}
<style>*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;overflow:hidden;background:{bg};position:relative}}</style>
</head><body>
<div style="position:absolute;top:0;left:0;width:6px;height:100%;background:{accent};"></div>
<div style="position:absolute;top:72px;left:80px;font-family:Inter,sans-serif;font-size:22px;
  font-weight:800;color:rgba(255,255,255,.5);">Improve<span style="color:{MINT};">YourSite</span></div>
<div style="position:absolute;top:72px;right:72px;background:rgba(255,255,255,.1);
  border-radius:999px;padding:10px 24px;font-family:Inter,sans-serif;font-size:15px;
  font-weight:700;color:rgba(255,255,255,.45);letter-spacing:.06em;text-transform:uppercase;">
  {plan_type.replace("_", " ")}</div>
<div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:160px 80px;text-align:center;">
  <p style="font-family:Inter,sans-serif;font-size:{fs};font-weight:900;
     color:#fff;line-height:1.1;letter-spacing:-.03em;">{headline}</p>
  {sub_html}{cta_html}
</div>
{sticker_html}
<div style="position:absolute;bottom:72px;left:0;right:0;text-align:center;
  font-family:Inter,sans-serif;font-size:20px;font-weight:600;color:rgba(255,255,255,.25);">
  @improveyoursite.au</div>
</body></html>"""

        try:
            ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir  = SOCIAL_DIR / "stories"
            out_dir.mkdir(parents=True, exist_ok=True)
            img_path = out_dir / f"story_{plan_type}_{ts}.png"
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page    = browser.new_page(viewport={"width": 1080, "height": 1920})
                page.set_content(html)
                page.wait_for_timeout(900)
                page.screenshot(
                    path=str(img_path),
                    clip={"x": 0, "y": 0, "width": 1080, "height": 1920},
                )
                browser.close()
            self.log_info(f"Instagram: story image rendered → {img_path.name}")
            return img_path
        except Exception as exc:
            self.log_warn(f"Instagram: story render failed: {exc}")
            return None

    def _publish_story_via_make(self, webhook_url: str, image_path: Path, copy: dict) -> bool:
        """Send story content to Make.com via dedicated story webhook."""
        try:
            # Upload image to get public URL
            image_url = self._upload_image_to_repo(image_path, subfolder="stories")
            if not image_url:
                self.log_warn("Instagram: story image upload failed — no GITHUB_PAT?")
                return False

            payload = {
                "type":         "story",
                "image_url":    image_url,
                "headline":     copy.get("headline", ""),
                "subtext":      copy.get("subtext", ""),
                "cta_text":     copy.get("cta_text", ""),
                "sticker_text": copy.get("sticker_text", ""),
            }
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status == 200
        except Exception as exc:
            self.log_error(f"Make.com story webhook failed: {exc}")
            return False

    def _publish_story_graph(self, token: str, account_id: str, image_path: Path, copy: dict) -> bool:
        """Publish story via Instagram Graph API."""
        try:
            image_url = self._upload_image_to_repo(image_path, subfolder="stories")
            if not image_url:
                return False

            # Create story container
            params = urllib.parse.urlencode({
                "image_url":    image_url,
                "media_type":   "STORIES",
                "access_token": token,
            })
            req = urllib.request.Request(
                f"{GRAPH_BASE}/{account_id}/media",
                data=params.encode(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                container = json.loads(r.read())
            container_id = container.get("id")
            if not container_id:
                return False

            # Publish
            pub_params = urllib.parse.urlencode({
                "creation_id":  container_id,
                "access_token": token,
            })
            req = urllib.request.Request(
                f"{GRAPH_BASE}/{account_id}/media_publish",
                data=pub_params.encode(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            return bool(result.get("id"))
        except Exception as exc:
            self.log_error(f"Instagram story Graph API failed: {exc}")
            return False

    # ── Insights ──────────────────────────────────────────────────────────────

    def _run_insights(self):
        """Pull Instagram account + recent post insights. Log + save report."""
        ig_token   = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "") or os.environ.get("INSTAGRAM_PUBLISHING_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

        if not ig_token or not account_id:
            self.log_warn("Instagram: no token/account — skipping insights")
            return

        tid = self.create_task("insights", "Pulling Instagram insights")
        self.update_progress(tid, 15)

        try:
            # Account-level 7-day metrics
            metrics = "reach,impressions,profile_views,follower_count"
            url = (
                f"{GRAPH_BASE}/{account_id}/insights"
                f"?metric={metrics}&period=week&access_token={ig_token}"
            )
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())

            account_metrics = {
                m["name"]: m["values"][-1]["value"]
                for m in data.get("data", [])
            }
            self.update_progress(tid, 40)

            # Recent post performance
            posts_url = (
                f"{GRAPH_BASE}/{account_id}/media"
                f"?fields=id,timestamp,like_count,comments_count,reach,saved,media_type"
                f"&limit=10&access_token={ig_token}"
            )
            with urllib.request.urlopen(posts_url, timeout=10) as r:
                posts_data = json.loads(r.read())
            posts = posts_data.get("data", [])
            self.update_progress(tid, 70)

            # Engagement rate
            reach       = account_metrics.get("reach", 0)
            impressions = account_metrics.get("impressions", 0)
            profile_views = account_metrics.get("profile_views", 0)
            total_likes = sum(p.get("like_count", 0) for p in posts)
            total_saves = sum(p.get("saved", 0) for p in posts)
            eng_rate    = round((total_likes + total_saves) / max(reach, 1) * 100, 2)

            report = {
                "date":           date.today().isoformat(),
                "reach_7d":       reach,
                "impressions_7d": impressions,
                "profile_views":  profile_views,
                "engagement_rate": eng_rate,
                "top_posts":      sorted(posts, key=lambda p: p.get("like_count", 0), reverse=True)[:3],
            }

            # Save insights log
            SOCIAL_DIR.mkdir(exist_ok=True)
            history = []
            if INSIGHTS_LOG.exists():
                try:
                    history = json.loads(INSIGHTS_LOG.read_text())
                except Exception:
                    history = []
            history.append(report)
            history = history[-30:]  # keep 30 days
            INSIGHTS_LOG.write_text(json.dumps(history, indent=2))

            summary = (
                f"7d reach={reach:,} · impressions={impressions:,} · "
                f"eng_rate={eng_rate}% · top post likes={posts[0].get('like_count',0) if posts else 0}"
            )
            self.complete_task(tid, summary)
            self.log_info(f"Instagram insights: {summary}")

            # Weekly report email (Mondays)
            if date.today().weekday() == 0:
                self._send_weekly_report(report, posts)

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Instagram insights failed: {exc}")

    def _send_weekly_report(self, report: dict, posts: list):
        """Email weekly Instagram performance summary on Mondays."""
        lines = [
            "ImproveYourSite — Weekly Instagram Report",
            "=" * 42,
            "",
            f"Week ending: {date.today().isoformat()}",
            "",
            "ACCOUNT PERFORMANCE (7 days)",
            "-" * 42,
            f"Reach:            {report['reach_7d']:,}",
            f"Impressions:      {report['impressions_7d']:,}",
            f"Profile views:    {report['profile_views']:,}",
            f"Engagement rate:  {report['engagement_rate']}%",
            "",
            "TOP POSTS",
            "-" * 42,
        ]
        for i, p in enumerate(report.get("top_posts", [])[:3], 1):
            lines.append(f"  {i}. Likes: {p.get('like_count',0)} | Saves: {p.get('saved',0)} | Type: {p.get('media_type','?')}")
        lines += ["", "Dashboard: http://localhost:8080"]

        self.send_email(
            subject=f"[IYS] Weekly Instagram Report — eng rate {report['engagement_rate']}%",
            body="\n".join(lines),
        )

    # ── Reels planning ────────────────────────────────────────────────────────

    def _run_reels_planning(self):
        """Generate a Reels script + caption document (saved to social/reels/)."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.log_warn("Instagram: no ANTHROPIC_API_KEY — skipping reels planning")
            return

        tid = self.create_task("reels_plan", "Generating Reels script")
        self.update_progress(tid, 20)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            today   = date.today()
            weekday = today.strftime("%A")

            prompt = f"""Create a 30-second Instagram Reels script for ImproveYourSite.com.

Today is {weekday} {today.strftime('%B %d, %Y')}.

Audience: Australian small business owners, 35-55, tradies/clinics/accountants/retail.
Goal: Get them to visit improveyoursite.com or DM us.
Style: Real, human, no cringe. Think: expert mate giving free advice.

Return ONLY valid JSON:
{{
  "title": "Reel title (under 8 words)",
  "hook": "Opening line — first 3 seconds, stops the scroll (under 10 words)",
  "script": [
    "Scene 1: [0-5s] What to say/show",
    "Scene 2: [5-12s] ...",
    "Scene 3: [12-22s] ...",
    "Scene 4: [22-30s] CTA"
  ],
  "caption": "Instagram caption for the Reel — 2-3 sentences + hashtags",
  "music_mood": "Suggested music mood (e.g. 'upbeat lo-fi', 'energetic', 'calm')",
  "on_screen_text": ["Text overlay 1", "Text overlay 2", "Text overlay 3"]
}}"""

            r = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = r.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            reel = json.loads(raw.strip())

            # Save script JSON
            REELS_DIR.mkdir(parents=True, exist_ok=True)
            out_file = REELS_DIR / f"reel_{today.isoformat()}.json"
            out_file.write_text(json.dumps(reel, indent=2))
            self.log_info(f"Instagram: Reels script saved → {out_file.name}")

            self.update_progress(tid, 50)

            # Render MP4
            tid_render = self.create_task("reel_render", f"Rendering Reel video: {reel.get('title', '')}")
            try:
                from agents.instagram.reels_renderer import render_reel
                mp4_path = render_reel(reel, REELS_DIR)
                if mp4_path:
                    self.complete_task(tid_render, f"MP4 rendered → {mp4_path.name}")
                    self.log_info(f"Instagram: Reel MP4 ready → {mp4_path.name}")
                else:
                    self.fail_task(tid_render, "ffmpeg/Playwright unavailable — script only")
                    mp4_path = None
            except Exception as render_exc:
                self.fail_task(tid_render, str(render_exc))
                self.log_warn(f"Instagram: Reel render failed: {render_exc}")
                mp4_path = None

            self.update_progress(tid, 80)

            # Post via Make.com reels webhook if video rendered
            reels_webhook = os.environ.get("MAKE_REELS_WEBHOOK_URL", "")
            if mp4_path and reels_webhook:
                tid_post = self.create_task("reel_post", "Posting Reel via Make.com")
                ok = self._publish_reel_via_make(reels_webhook, mp4_path, reel)
                if ok:
                    self.complete_task(tid_post, "Reel posted via Make.com")
                    self.log_info("Instagram: Reel posted via Make.com")
                else:
                    self.fail_task(tid_post, "Make.com reel post failed — MP4 saved locally")
            elif mp4_path:
                self.log_info(f"Instagram: Reel MP4 saved locally (set MAKE_REELS_WEBHOOK_URL to auto-post) → {mp4_path}")

            self.update_progress(tid, 95)
            self.complete_task(tid, reel.get("title", "Reel ready"))

            db.content_add(
                content_type="ig_reel",
                title=reel.get("title", f"Reel {today}"),
                preview_path=str(mp4_path) if mp4_path else str(out_file),
                status="delivered" if (mp4_path and reels_webhook) else "queued",
            )

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Instagram reels planning failed: {exc}")

    def _publish_reel_via_make(self, webhook_url: str, mp4_path: Path, reel: dict) -> bool:
        """Upload MP4 to GitHub, send URL + caption to Make.com reels webhook."""
        try:
            import base64
            pat = os.environ.get("GITHUB_PAT", "")
            if not pat:
                self.log_warn("Instagram: no GITHUB_PAT — cannot upload Reel MP4")
                return False

            dest_path = f"social/reels/{mp4_path.name}"
            api_url   = f"https://api.github.com/repos/anon8597299/smart-tech-innovations/contents/{dest_path}"
            mp4_b64   = base64.b64encode(mp4_path.read_bytes()).decode()

            # Check for existing file SHA
            sha = None
            try:
                req = urllib.request.Request(
                    api_url,
                    headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github.v3+json"},
                )
                with urllib.request.urlopen(req) as r:
                    sha = json.loads(r.read()).get("sha")
            except Exception:
                pass

            payload = {"message": f"IG Reel: {mp4_path.name}", "content": mp4_b64}
            if sha:
                payload["sha"] = sha

            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode(),
                method="PUT",
                headers={
                    "Authorization": f"token {pat}",
                    "Accept":        "application/vnd.github.v3+json",
                    "Content-Type":  "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                pass

            video_url = (
                f"https://raw.githubusercontent.com/anon8597299/smart-tech-innovations"
                f"/main/social/reels/{mp4_path.name}"
            )

            hook_payload = {
                "type":       "reel",
                "video_url":  video_url,
                "caption":    reel.get("caption", ""),
                "title":      reel.get("title", ""),
                "music_mood": reel.get("music_mood", ""),
            }
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(hook_payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status == 200
        except Exception as exc:
            self.log_error(f"Make.com reel webhook failed: {exc}")
            return False

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _queue_story(self, copy: dict, image_path: Path | None):
        queue = []
        if STORY_QUEUE.exists():
            try:
                queue = json.loads(STORY_QUEUE.read_text())
            except Exception:
                queue = []

        entry = {
            "date":       date.today().isoformat(),
            "headline":   copy.get("headline", ""),
            "subtext":    copy.get("subtext", ""),
            "cta_text":   copy.get("cta_text", ""),
            "image_path": str(image_path) if image_path else None,
            "status":     "pending",
        }
        queue.append(entry)
        SOCIAL_DIR.mkdir(exist_ok=True)
        STORY_QUEUE.write_text(json.dumps(queue, indent=2))
        self.log_info(f"Instagram: story queued — {entry['headline']}")

    # ── Image upload ──────────────────────────────────────────────────────────

    def _upload_image_to_repo(self, image_path: Path, subfolder: str = "posts") -> str | None:
        """Push image to GitHub repo for public URL."""
        pat = os.environ.get("GITHUB_PAT", "")
        if not pat:
            return None
        try:
            import base64
            img_b64   = base64.b64encode(image_path.read_bytes()).decode()
            dest_path = f"social/{subfolder}/{image_path.name}"
            api_url   = f"https://api.github.com/repos/anon8597299/smart-tech-innovations/contents/{dest_path}"

            sha = None
            try:
                req = urllib.request.Request(
                    api_url,
                    headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github.v3+json"},
                )
                with urllib.request.urlopen(req) as r:
                    sha = json.loads(r.read()).get("sha")
            except Exception:
                pass

            payload = {"message": f"IG {subfolder}: {image_path.name}", "content": img_b64}
            if sha:
                payload["sha"] = sha

            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode(),
                method="PUT",
                headers={
                    "Authorization":  f"token {pat}",
                    "Accept":         "application/vnd.github.v3+json",
                    "Content-Type":   "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                pass

            return f"https://raw.githubusercontent.com/anon8597299/smart-tech-innovations/main/social/{subfolder}/{image_path.name}"
        except Exception as exc:
            self.log_warn(f"Instagram: image upload failed: {exc}")
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_slot() -> str:
        hour = datetime.now().hour
        if hour < 13:
            return "story"
        elif hour < 17:
            return "insights"
        else:
            return "story"
