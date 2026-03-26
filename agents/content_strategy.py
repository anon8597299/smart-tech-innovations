"""
agents/content_strategy.py — Content Strategy Agent

Plans the full week of Instagram content every Sunday 8 PM AEST.
Reads market intelligence + past performance, then uses Claude to produce
a 7-day content calendar (carousels, stories, Wednesday reel) and saves it
to social/weekly_strategy.json for the other agents to consume.

Schedule: Sunday 8:00 PM AEST (set in scheduler.py)

Required in builder/.env:
  ANTHROPIC_API_KEY — Claude claude-opus-4-6 for strategy quality

Reads:
  social/intel_report.json      — market intelligence (competitor themes, gaps, angles)
  social/instagram_insights.json — recent post performance (optional)
  social/cover_rotation.json    — current carousel cover colour state

Outputs:
  social/weekly_strategy.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT  = Path(__file__).parent.parent
SOCIAL_DIR    = PROJECT_ROOT / "social"
INTEL_FILE    = SOCIAL_DIR / "intel_report.json"
INSIGHTS_FILE = SOCIAL_DIR / "instagram_insights.json"
ROTATION_FILE = SOCIAL_DIR / "cover_rotation.json"
STRATEGY_FILE = SOCIAL_DIR / "weekly_strategy.json"

# Content pillar rotation — 7 days
PILLAR_ROTATION = [
    "education",
    "social_proof",
    "pain_point",
    "offer",
    "authority",
    "entertainment",
    "behind_scenes",
]

# City/suburb names to flag in brand validation
_CITY_NAMES = {
    "sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra",
    "darwin", "hobart", "gold coast", "newcastle", "wollongong", "geelong",
    "townsville", "cairns", "toowoomba", "ballarat", "bendigo", "launceston",
    "mackay", "rockhampton", "sunshine coast", "nsw", "vic", "qld", "wa",
    "sa", "tas", "nt", "act",
}


def _validate_hook(text: str) -> bool:
    """
    Returns True if hook passes brand rules, False if it fails any check.
    Rules:
      - No hyphens (en dash, em dash, or ASCII hyphen in a word context)
      - Maximum 6 words
      - No city or suburb names (case-insensitive)
    """
    if not text:
        return False

    # Check hyphens: any literal hyphen character
    if "-" in text or "\u2013" in text or "\u2014" in text:
        return False

    # Check word count
    words = text.strip().split()
    if len(words) > 6:
        return False

    # Check city names
    lower = text.lower()
    for city in _CITY_NAMES:
        if city in lower:
            return False

    return True


def _validate_and_fix(hook: str, client) -> str:
    """
    If a hook fails brand validation, ask Claude to fix it.
    Returns the fixed hook (or the original if the fix also fails).
    """
    if _validate_hook(hook):
        return hook

    issues = []
    if "-" in hook or "\u2013" in hook or "\u2014" in hook:
        issues.append("contains a hyphen — remove it entirely, rewrite without")
    words = hook.strip().split()
    if len(words) > 6:
        issues.append(f"too long ({len(words)} words) — must be 6 words or fewer")
    lower = hook.lower()
    for city in _CITY_NAMES:
        if city in lower:
            issues.append(f"contains city/state name '{city}' — remove it, keep language national")
            break

    problems = "; ".join(issues)
    try:
        r = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": (
                    f"Fix this Instagram carousel hook so it passes these rules: {problems}\n\n"
                    f"Original: \"{hook}\"\n\n"
                    f"Rules: no hyphens, max 6 words, no city names, must be punchy and on-brand "
                    f"for an Australian web agency. Return ONLY the fixed hook text, no quotes, "
                    f"no explanation."
                ),
            }],
        )
        fixed = r.content[0].text.strip().strip('"').strip("'")
        if _validate_hook(fixed):
            return fixed
    except Exception:
        pass

    # Last resort: strip hyphens and truncate
    cleaned = hook.replace("-", " ").replace("\u2013", " ").replace("\u2014", " ")
    words = cleaned.strip().split()
    return " ".join(words[:6])


class ContentStrategyAgent(BaseAgent):
    agent_id = "content_strategy"
    name     = "Content Strategy"

    def run(self):
        today     = date.today()
        week_num  = today.isocalendar()[1]
        # Strategy covers the upcoming week (Mon-Sun starting next day)
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)

        self.log_info(f"ContentStrategy: planning week of {next_monday.isoformat()} (week {week_num})")
        tid = self.create_task("strategy_plan", f"Weekly content strategy — week of {next_monday}")
        self.update_progress(tid, 5)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.fail_task(tid, "ANTHROPIC_API_KEY not set — cannot run strategy")
            self.log_warn("ContentStrategy: ANTHROPIC_API_KEY missing — skipping")
            return

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # ── 1. Load intel report ─────────────────────────────────────────────
        intel = self._load_intel()
        self.update_progress(tid, 15)

        # ── 2. Load insights ─────────────────────────────────────────────────
        insights = self._load_insights()
        self.update_progress(tid, 25)

        # ── 3. Load cover rotation ───────────────────────────────────────────
        cover_idx = self._load_cover_rotation()

        # ── 4. Analyse performance and build strategy prompt ─────────────────
        performance_context = self._summarise_insights(insights)
        intel_context       = self._summarise_intel(intel)
        self.update_progress(tid, 35)

        # ── 5. Call Claude for full 7-day plan ───────────────────────────────
        self.log_info("ContentStrategy: calling Claude claude-opus-4-6 for weekly plan...")
        tid2 = self.create_task("claude_strategy", "Claude generating 7-day content calendar")
        self.update_progress(tid2, 10)

        # Build date map for the week
        days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day_dates = {}
        for i, day in enumerate(days_of_week):
            day_dates[day] = (next_monday + timedelta(days=i)).isoformat()

        # Assign pillars in rotation order starting from Monday
        # Use week_num to offset so pillars don't repeat the same each week
        pillar_map = {}
        for i, day in enumerate(days_of_week):
            pillar_map[day] = PILLAR_ROTATION[(week_num + i) % len(PILLAR_ROTATION)]

        strategy_json = self._call_claude_strategy(
            client, today, next_monday, day_dates, pillar_map,
            intel_context, performance_context,
        )
        self.update_progress(tid2, 80)

        if not strategy_json:
            self.fail_task(tid2, "Claude returned no valid strategy")
            self.fail_task(tid, "Strategy generation failed")
            return

        # ── 6. Validate and fix all hooks ────────────────────────────────────
        tid3 = self.create_task("hook_validation", "Validating and fixing carousel hooks")
        fix_count = 0
        for day_name, day_data in strategy_json.get("days", {}).items():
            carousel = day_data.get("carousel", {})
            hook = carousel.get("hook", "")
            if hook and not _validate_hook(hook):
                fixed = _validate_and_fix(hook, client)
                if fixed != hook:
                    carousel["hook"] = fixed
                    fix_count += 1
                    self.log_info(f"ContentStrategy: fixed hook [{day_name}]: '{hook}' → '{fixed}'")
            # Also validate story headline
            story = day_data.get("story", {})
            s_headline = story.get("headline", "")
            if s_headline and not _validate_hook(s_headline):
                fixed_s = _validate_and_fix(s_headline, client)
                if fixed_s != s_headline:
                    story["headline"] = fixed_s
                    fix_count += 1
            # Wednesday reel hook
            if day_name == "wednesday":
                reel = day_data.get("reel", {})
                r_hook = reel.get("hook", "")
                if r_hook and not _validate_hook(r_hook):
                    fixed_r = _validate_and_fix(r_hook, client)
                    if fixed_r != r_hook:
                        reel["hook"] = fixed_r
                        fix_count += 1

        self.complete_task(tid3, f"Hooks validated — {fix_count} fixed")
        self.update_progress(tid2, 100)
        self.complete_task(tid2, f"7-day strategy ready for week of {next_monday.isoformat()}")

        # ── 7. Attach metadata ───────────────────────────────────────────────
        strategy_json["week_of"]      = next_monday.isoformat()
        strategy_json["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Ensure day dates are set
        for day_name, day_data in strategy_json.get("days", {}).items():
            if "date" not in day_data:
                day_data["date"] = day_dates.get(day_name, "")
            if "pillar" not in day_data:
                day_data["pillar"] = pillar_map.get(day_name, "education")

        # ── 8. Save to file ──────────────────────────────────────────────────
        SOCIAL_DIR.mkdir(exist_ok=True)
        STRATEGY_FILE.write_text(json.dumps(strategy_json, indent=2))
        self.log_info(f"ContentStrategy: weekly_strategy.json saved → {STRATEGY_FILE}")

        # ── 9. Log to DB ─────────────────────────────────────────────────────
        db.content_add(
            content_type="weekly_strategy",
            title=f"Weekly strategy — {next_monday.isoformat()}",
            preview_path=str(STRATEGY_FILE),
            status="delivered",
        )

        summary = (
            f"7-day calendar planned · theme: {strategy_json.get('weekly_theme', '?')} · "
            f"{fix_count} hooks fixed · saved to weekly_strategy.json"
        )
        self.complete_task(tid, summary)
        self.log_info(f"ContentStrategy: complete — {summary}")

    # ── Data loaders ─────────────────────────────────────────────────────────

    def _load_intel(self) -> dict:
        """Load intel_report.json. Falls back to empty dict if missing or stale (>2 days)."""
        if not INTEL_FILE.exists():
            self.log_warn("ContentStrategy: intel_report.json not found — running with defaults")
            return {}
        try:
            data = json.loads(INTEL_FILE.read_text())
            report_date_str = data.get("date", "")
            if report_date_str:
                report_date = date.fromisoformat(report_date_str)
                age_days = (date.today() - report_date).days
                if age_days > 2:
                    self.log_warn(
                        f"ContentStrategy: intel_report.json is {age_days} days old — "
                        f"using cached fallback data"
                    )
            return data
        except Exception as exc:
            self.log_warn(f"ContentStrategy: failed to load intel_report.json: {exc}")
            return {}

    def _load_insights(self) -> list:
        """Load instagram_insights.json (list of daily reports). Returns empty list if missing."""
        if not INSIGHTS_FILE.exists():
            return []
        try:
            data = json.loads(INSIGHTS_FILE.read_text())
            if isinstance(data, list):
                return data[-7:]  # last 7 days
            return []
        except Exception as exc:
            self.log_warn(f"ContentStrategy: failed to load instagram_insights.json: {exc}")
            return []

    def _load_cover_rotation(self) -> int:
        """Return current cover rotation index."""
        try:
            if ROTATION_FILE.exists():
                return json.loads(ROTATION_FILE.read_text()).get("index", 0)
        except Exception:
            pass
        return 0

    # ── Context summarisers ──────────────────────────────────────────────────

    def _summarise_insights(self, insights: list) -> str:
        """Summarise recent Instagram performance into a short text block."""
        if not insights:
            return "No performance data available yet. Optimise for reach and saves."

        lines = ["RECENT INSTAGRAM PERFORMANCE (last 7 days):"]
        total_reach = 0
        total_eng   = 0.0
        count       = 0
        for entry in insights:
            reach    = entry.get("reach_7d", 0)
            eng_rate = entry.get("engagement_rate", 0)
            total_reach += reach
            total_eng   += eng_rate
            count += 1

        if count:
            avg_reach = total_reach // count
            avg_eng   = round(total_eng / count, 2)
            lines.append(f"  Average weekly reach: {avg_reach:,}")
            lines.append(f"  Average engagement rate: {avg_eng}%")

        # Top posts
        top_posts = []
        for entry in insights:
            top_posts.extend(entry.get("top_posts", []))
        if top_posts:
            top_posts.sort(key=lambda p: p.get("like_count", 0) + p.get("saved", 0), reverse=True)
            lines.append(f"  Best performing posts this period: {len(top_posts)} tracked")
            for p in top_posts[:2]:
                lines.append(
                    f"    - Likes: {p.get('like_count', 0)}, "
                    f"Saves: {p.get('saved', 0)}, "
                    f"Type: {p.get('media_type', '?')}"
                )

        return "\n".join(lines)

    def _summarise_intel(self, intel: dict) -> str:
        """Summarise intel_report into a prompt-ready block."""
        if not intel:
            return (
                "No fresh market intelligence. Default strategy: target Australian SMB pain points "
                "around slow websites, poor Google rankings, and wasted Google Ads spend."
            )

        lines = ["MARKET INTELLIGENCE:"]

        gaps = intel.get("content_gaps", [])
        if gaps:
            lines.append("\nContent gaps (what competitors are NOT doing):")
            for g in gaps[:4]:
                lines.append(f"  - {g}")

        angles = intel.get("recommended_angles", [])
        if angles:
            lines.append("\nRecommended angles (prioritise these):")
            for a in angles[:4]:
                if isinstance(a, dict):
                    lines.append(
                        f"  - Hook: \"{a.get('hook', '')}\" | "
                        f"Why: {a.get('why_it_wins', '')} | "
                        f"Urgency: {a.get('urgency', 'evergreen')}"
                    )

        trending = intel.get("trending_topics", [])
        if trending:
            lines.append("\nTrending topics this week:")
            for t in trending[:4]:
                lines.append(f"  - {t}")

        pulse = intel.get("market_pulse", "")
        if pulse:
            lines.append(f"\nMarket pulse: {pulse}")

        return "\n".join(lines)

    # ── Main Claude call ──────────────────────────────────────────────────────

    def _call_claude_strategy(
        self,
        client,
        today: date,
        next_monday: date,
        day_dates: dict,
        pillar_map: dict,
        intel_context: str,
        performance_context: str,
    ) -> Optional[dict]:

        days_block = "\n".join(
            f'  "{day}": date={day_dates[day]}, pillar={pillar_map[day]}'
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        )

        system = """You are the content strategy brain for ImproveYourSite.com — an Australian web agency
that builds websites for small businesses nationwide.

BRAND RULES (non-negotiable — every piece of copy must pass these):
1. No hyphens anywhere. Not one. Hyphens are the biggest AI dead giveaway.
2. No city or town names. National audience. No Sydney, Melbourne, Brisbane, etc.
3. Max 6 words on any carousel hook or story headline. 3-4 is ideal.
4. Caption: max 25 words before hashtags. Short and punchy.
5. Sound like a real expert mate, not an agency or a robot.
6. ONE idea per slide. Never two.
7. No marketing speak: no "leverage", "synergy", "digital presence", "online journey".

WINNING CONTENT FORMULA:
- Name a fear or truth business owners feel → they engage
- Carousels with short, bold slide 1 text get 3x more swipes
- DM shares are the strongest signal → write content people forward to a mate
- Specificity beats generality every time (real numbers, real scenarios)
- Australian small business verticals to reference: tradies, allied health, clinics,
  accountants, retail, hospitality — never use city names, keep language universal

CONTENT PILLARS:
- education: teach something specific and useful
- social_proof: before/after, results, outcomes
- pain_point: name the fear or problem directly
- offer: clear, low-pressure path to getting help
- authority: industry insight or data that builds credibility
- entertainment: relatable, scroll-stopping, shareable
- behind_scenes: humanise the brand, process transparency"""

        prompt = f"""Plan a complete 7-day Instagram content calendar for ImproveYourSite.com.

Today: {today.isoformat()}
Week to plan: {next_monday.isoformat()} to {(next_monday + timedelta(days=6)).isoformat()}

DAYS AND ASSIGNED PILLARS:
{days_block}

{intel_context}

{performance_context}

INSTRUCTIONS:
- Use the market intelligence to choose angles — pick from recommended_angles where relevant
- Wednesday must include a reel concept (hook, 4-scene outline, music mood)
- Hooks must be 3-6 words, no hyphens, no city names
- Every carousel needs 3 content bullets (the substance behind the hook)
- Story types: tip | question | stat | behind_scenes | offer | inspiration | preview
- Hashtag sets: primary (broad reach), secondary (mid-tier), niche (high-intent AU audience)
- performance_notes: one sentence on what to watch this week based on past data

Return ONLY valid JSON matching this exact structure. No markdown fences, no comments:

{{
  "market_pulse": "one sentence on the current Australian SMB online landscape",
  "weekly_theme": "one overarching theme that ties the week together",
  "days": {{
    "monday": {{
      "date": "{day_dates['monday']}",
      "pillar": "{pillar_map['monday']}",
      "carousel": {{
        "hook": "3-6 word hook, no hyphens",
        "angle": "what specific insight or data point drives this",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max, punchy"
      }},
      "story": {{
        "type": "tip",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }},
    "tuesday": {{
      "date": "{day_dates['tuesday']}",
      "pillar": "{pillar_map['tuesday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "question",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }},
    "wednesday": {{
      "date": "{day_dates['wednesday']}",
      "pillar": "{pillar_map['wednesday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "behind_scenes",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }},
      "reel": {{
        "hook": "3-word opener that stops the scroll",
        "concept": "what the reel is about in one sentence",
        "scenes": [
          "Scene 1 [0-5s]: what to say/show",
          "Scene 2 [5-12s]: main content",
          "Scene 3 [12-22s]: proof or detail",
          "Scene 4 [22-30s]: CTA"
        ],
        "music_mood": "energetic",
        "caption": "reel caption under 25 words"
      }}
    }},
    "thursday": {{
      "date": "{day_dates['thursday']}",
      "pillar": "{pillar_map['thursday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "stat",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }},
    "friday": {{
      "date": "{day_dates['friday']}",
      "pillar": "{pillar_map['friday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "offer",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }},
    "saturday": {{
      "date": "{day_dates['saturday']}",
      "pillar": "{pillar_map['saturday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "inspiration",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }},
    "sunday": {{
      "date": "{day_dates['sunday']}",
      "pillar": "{pillar_map['sunday']}",
      "carousel": {{
        "hook": "3-6 word hook",
        "angle": "specific angle",
        "bullets": ["point 1", "point 2", "point 3"],
        "cta": "under 25 words",
        "caption": "3 sentences max"
      }},
      "story": {{
        "type": "preview",
        "headline": "3-5 words",
        "body": "supporting copy",
        "cta": "under 4 words"
      }}
    }}
  }},
  "hashtag_sets": {{
    "primary": ["#websitedesign", "#australianbusiness", "#smallbusiness"],
    "secondary": ["#digitalmarketing", "#websitetips"],
    "niche": ["#tradiesaustralia", "#smallbizau"]
  }},
  "performance_notes": "one sentence on what to watch for this week"
}}"""

        try:
            r = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = r.content[0].text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            return json.loads(raw)

        except json.JSONDecodeError as exc:
            self.log_error(f"ContentStrategy: JSON parse failed: {exc}")
            return None
        except Exception as exc:
            self.log_error(f"ContentStrategy: Claude call failed: {exc}")
            return None
