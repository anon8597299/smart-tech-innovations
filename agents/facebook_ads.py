"""
agents/facebook_ads.py — Facebook / Meta Ads Agent

Reads Meta Ads Manager performance data, compares against industry KPI
benchmarks for web design/digital agency vertical, and alerts on misses.

Tracks inbound signals from Instagram + Facebook: clicks, messages, link clicks.
Target: 1–2 inbound leads per day via clicks/messages across Meta platforms.

Industry benchmarks (web design/digital services, AU market):
  CTR:         1.5%+ (Meta avg 0.9% for professional services)
  CPC:         ≤$2.50 AUD
  Conv rate:   3%+   (from ad click to contact/DM/enquiry)
  CPL:         ≤$50 AUD (cost per lead)
  ROAS:        3x+  (for service businesses)
  Daily leads: 1–2 (DMs + form fills + link clicks to contact page)

Requires in builder/.env:
  META_ACCESS_TOKEN=<long-lived user access token with ads_read permission>
  META_AD_ACCOUNT_ID=<ad account id, e.g. act_1234567890>
  (optional) META_APP_ID=<your Meta app id>
  (optional) META_APP_SECRET=<your Meta app secret>

To get credentials:
  1. Create a Meta Developer app at developers.facebook.com
  2. Add the Marketing API product
  3. Generate a long-lived User Access Token with ads_read permission
  4. Find your Ad Account ID in Ads Manager → Account Overview

Schedule: Daily 9:15 AM AEST
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

# ── KPI targets (above AU industry avg for professional services on Meta) ──────
SPEND_ALERT_AUD    = 50.0    # alert if 7-day spend exceeds this
TARGET_CTR         = 1.5     # % — Meta industry avg 0.9%, we target above
TARGET_CPC         = 2.50    # AUD max cost per click
TARGET_CPL         = 50.0    # AUD max cost per lead
TARGET_CONV_RATE   = 3.0     # % — clicks that become enquiries/DMs
TARGET_ROAS        = 3.0     # x — return on ad spend
TARGET_LEADS_DAILY = 1.5     # average leads/day over 7 days
INDUSTRY_CTR       = 0.9     # Meta AU professional services benchmark
INDUSTRY_ROAS      = 2.5     # Meta AU professional services benchmark
DATE_RANGE_DAYS    = 7


class FacebookAdsAgent(BaseAgent):
    agent_id = "facebook_ads"
    name     = "Facebook Ads"

    def run(self):
        access_token = os.environ.get("META_ACCESS_TOKEN", "")
        account_id   = os.environ.get("META_AD_ACCOUNT_ID", "")

        if not all([access_token, account_id]):
            self.log_warn(
                "Meta Ads credentials not set — skipping "
                "(add META_ACCESS_TOKEN + META_AD_ACCOUNT_ID to builder/.env)"
            )
            return

        tid = self.create_task("fb_ads_report", "Facebook Ads — daily KPI performance check")
        self.update_progress(tid, 20)

        try:
            stats = self._fetch_stats(access_token, account_id)
            self.update_progress(tid, 70)

            spend       = stats.get("spend", 0.0)
            clicks      = stats.get("clicks", 0)
            impressions = stats.get("impressions", 0)
            reach       = stats.get("reach", 0)
            ctr         = stats.get("ctr", 0.0)
            roas        = stats.get("roas", 0.0)
            leads       = stats.get("leads", 0)
            messages    = stats.get("messages", 0)

            cpc         = (spend / clicks) if clicks > 0 else 0.0
            cpl         = (spend / leads) if leads > 0 else 0.0
            total_inbound = leads + messages
            daily_leads   = total_inbound / 7.0

            # ── Log baseline metrics ─────────────────────────────────────
            self.log_info(
                f"Facebook Ads (7d): spend=${spend:.2f} | "
                f"impressions={impressions:,} | reach={reach:,} | clicks={clicks} | "
                f"CTR={ctr:.2f}% | CPC=${cpc:.2f} | leads={leads} | "
                f"messages={messages} | ROAS={roas:.2f}x | leads/day={daily_leads:.1f}"
            )

            db.event_log("facebook_ads", "info",
                f"FB Ads — spend:${spend:.2f} CTR:{ctr:.2f}% CPC:${cpc:.2f} "
                f"leads:{leads} msgs:{messages} ROAS:{roas:.2f}x leads/day:{daily_leads:.1f}")

            # ── KPI checks — alert on misses ──────────────────────────────
            issues = []

            if ctr < TARGET_CTR:
                issues.append(
                    f"CTR {ctr:.2f}% below target {TARGET_CTR}% "
                    f"(Meta avg: {INDUSTRY_CTR}%). "
                    f"Fix: refresh ad creative, test video vs. static, "
                    f"sharpen hook in first 3 seconds."
                )

            if cpc > TARGET_CPC and clicks >= 10:
                issues.append(
                    f"CPC ${cpc:.2f} exceeds target ${TARGET_CPC:.2f}. "
                    f"Fix: broaden audience slightly, exclude non-AU traffic, "
                    f"pause underperforming ad sets."
                )

            if cpl > TARGET_CPL and leads > 0:
                issues.append(
                    f"CPL ${cpl:.2f} exceeds target ${TARGET_CPL:.2f}. "
                    f"Fix: review lead form questions, improve landing page offer."
                )

            if roas < TARGET_ROAS and spend > 10 and roas > 0:
                issues.append(
                    f"ROAS {roas:.2f}x below target {TARGET_ROAS:.1f}x "
                    f"(industry avg: {INDUSTRY_ROAS:.1f}x). "
                    f"Fix: retarget warm audiences (profile visitors, IG engagers), "
                    f"use testimonial creatives."
                )

            if daily_leads < TARGET_LEADS_DAILY and impressions >= 500:
                issues.append(
                    f"Only {daily_leads:.1f} inbound leads/day — target is {TARGET_LEADS_DAILY:.1f}. "
                    f"Fix: add Instagram DM automation, enable 'Message' CTA on ads, "
                    f"A/B test lead form vs. landing page."
                )

            if spend > SPEND_ALERT_AUD:
                issues.append(
                    f"Spend ${spend:.2f} AUD (7d) exceeds alert threshold ${SPEND_ALERT_AUD:.2f}."
                )

            if issues:
                issue_text = "\n".join(f"  • {i}" for i in issues)
                self.log_warn(f"Facebook Ads KPI misses:\n{issue_text}")
                self.send_email(
                    subject=f"[IYS] Facebook Ads KPI alert — {len(issues)} issue(s) (7d)",
                    body=(
                        f"Facebook Ads 7-day performance review:\n\n"
                        f"  Spend:       ${spend:.2f} AUD\n"
                        f"  Impressions: {impressions:,}\n"
                        f"  Reach:       {reach:,}\n"
                        f"  Clicks:      {clicks}\n"
                        f"  CTR:         {ctr:.2f}%  (target: {TARGET_CTR}%+)\n"
                        f"  CPC:         ${cpc:.2f}  (target: ≤${TARGET_CPC:.2f})\n"
                        f"  Leads:       {leads}\n"
                        f"  Messages:    {messages}\n"
                        f"  CPL:         ${cpl:.2f}  (target: ≤${TARGET_CPL:.2f})\n"
                        f"  ROAS:        {roas:.2f}x  (target: {TARGET_ROAS:.1f}x+)\n"
                        f"  Leads/day:   {daily_leads:.1f}  (target: {TARGET_LEADS_DAILY:.1f}+)\n\n"
                        f"Issues:\n{issue_text}\n\n"
                        f"Review at: https://adsmanager.facebook.com/"
                    ),
                )
            else:
                self.log_info("Facebook Ads: all KPIs on target ✓")

            self.complete_task(
                tid,
                f"${spend:.2f} spend · {ctr:.2f}% CTR · {daily_leads:.1f} leads/day · "
                f"ROAS {roas:.2f}x · {'⚠ ' + str(len(issues)) + ' KPI miss(es)' if issues else '✓ on target'}"
            )

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Facebook Ads fetch failed: {exc}")

    def _fetch_stats(self, access_token: str, account_id: str) -> dict:
        """Fetch 7-day aggregate stats via Meta Marketing API v21."""
        import json
        import urllib.parse
        import urllib.request
        from datetime import date, timedelta

        today = date.today()
        since = (today - timedelta(days=DATE_RANGE_DAYS)).isoformat()
        until = today.isoformat()

        # Ensure account_id has act_ prefix
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"

        # Request all fields including action breakdowns for leads/messages
        fields = (
            "spend,clicks,impressions,reach,ctr,"
            "cost_per_action_type,actions,action_values"
        )
        params = urllib.parse.urlencode({
            "fields":       fields,
            "time_range":   json.dumps({"since": since, "until": until}),
            "level":        "account",
            "access_token": access_token,
        })

        url = f"https://graph.facebook.com/v21.0/{account_id}/insights?{params}"
        with urllib.request.urlopen(
            urllib.request.Request(url, method="GET"), timeout=15
        ) as r:
            data = json.loads(r.read())

        rows = data.get("data", [])
        if not rows:
            return {
                "spend": 0.0, "clicks": 0, "impressions": 0,
                "reach": 0, "ctr": 0.0, "roas": 0.0, "leads": 0, "messages": 0,
            }

        row         = rows[0]
        spend       = float(row.get("spend", 0))
        clicks      = int(row.get("clicks", 0))
        impressions = int(row.get("impressions", 0))
        reach       = int(row.get("reach", 0))
        ctr         = float(row.get("ctr", 0)) * 100  # API decimal → percent

        # Parse actions for leads, messages, purchases
        actions       = row.get("actions", [])
        action_values = row.get("action_values", [])

        lead_types    = {"lead", "leadgen_grouped", "onsite_conversion.lead_grouped"}
        message_types = {"onsite_conversion.messaging_conversation_started_7d",
                         "onsite_conversion.messaging_first_reply"}

        leads    = sum(int(float(a.get("value", 0))) for a in actions
                       if a.get("action_type") in lead_types)
        messages = sum(int(float(a.get("value", 0))) for a in actions
                       if a.get("action_type") in message_types)

        # ROAS: purchase action values / spend
        roas = 0.0
        if spend > 0:
            purchase_value = sum(
                float(av.get("value", 0)) for av in action_values
                if av.get("action_type") in ("purchase", "omni_purchase")
            )
            if purchase_value > 0:
                roas = purchase_value / spend

        return {
            "spend":       spend,
            "clicks":      clicks,
            "impressions": impressions,
            "reach":       reach,
            "ctr":         ctr,
            "roas":        roas,
            "leads":       leads,
            "messages":    messages,
        }
