"""
agents/ads.py — Ads Agent

Reads Google Ads performance data and logs stats to the dashboard.
Sends an alert if spend exceeds daily budget threshold.

Requires in builder/.env:
  GOOGLE_ADS_DEVELOPER_TOKEN=<developer token>
  GOOGLE_ADS_CLIENT_ID=<OAuth client id>
  GOOGLE_ADS_CLIENT_SECRET=<OAuth client secret>
  GOOGLE_ADS_REFRESH_TOKEN=<refresh token>
  GOOGLE_ADS_CUSTOMER_ID=<customer id, no dashes>

Schedule: Daily 9:00 AM AEST
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

SPEND_ALERT_AUD = 50.0   # alert if daily spend exceeds this


class AdsAgent(BaseAgent):
    agent_id = "ads"
    name     = "Ads"

    def run(self):
        dev_token     = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
        customer_id   = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")
        client_id     = os.environ.get("GOOGLE_ADS_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")
        refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", "")

        if not all([dev_token, customer_id, client_id, client_secret, refresh_token]):
            self.log_warn(
                "Google Ads credentials not fully set — skipping "
                "(add GOOGLE_ADS_* vars to builder/.env)"
            )
            return

        tid = self.create_task("ads_report", "Google Ads — daily performance pull")
        self.update_progress(tid, 20)

        try:
            stats = self._fetch_stats(
                dev_token, customer_id, client_id, client_secret, refresh_token
            )
            self.update_progress(tid, 70)

            spend = stats.get("spend", 0.0)
            ctr   = stats.get("ctr", 0.0)
            conv  = stats.get("conversions", 0)

            self.log_info(
                f"Ads (7d): spend=${spend:.2f} AUD, CTR={ctr:.2f}%, conversions={conv}"
            )

            db.event_log("ads", "info",
                f"Ads metrics — spend:${spend:.2f} CTR:{ctr:.2f}% conv:{conv}")

            if spend > SPEND_ALERT_AUD:
                self.log_warn(f"Ads spend alert: ${spend:.2f} exceeds ${SPEND_ALERT_AUD:.2f} threshold")
                self.send_email(
                    subject=f"[IYS] Ads spend alert — ${spend:.2f} AUD (7d)",
                    body=(
                        f"Google Ads 7-day spend is ${spend:.2f} AUD — "
                        f"above the ${SPEND_ALERT_AUD:.2f} threshold.\n\n"
                        f"CTR: {ctr:.2f}%\nConversions: {conv}\n\n"
                        f"Review at: https://ads.google.com"
                    ),
                )

            self.complete_task(tid, f"${spend:.2f} spend · {ctr:.2f}% CTR · {conv} conv")

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Ads fetch failed: {exc}")

    def _fetch_stats(
        self,
        dev_token: str,
        customer_id: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> dict:
        """Fetch 7-day aggregate stats via Google Ads API (REST)."""
        import json
        import urllib.parse
        import urllib.request

        # ── Step 1: Refresh access token ────────────────────────────────
        token_resp = urllib.request.urlopen(
            urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=urllib.parse.urlencode({
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type":    "refresh_token",
                }).encode(),
                method="POST",
            ),
            timeout=10,
        )
        access_token = json.loads(token_resp.read())["access_token"]

        # ── Step 2: GAQL query — 7-day totals ────────────────────────────
        query = (
            "SELECT metrics.cost_micros, metrics.ctr, metrics.conversions "
            "FROM campaign "
            "WHERE segments.date DURING LAST_7_DAYS"
        )

        url = f"https://googleads.googleapis.com/v19/customers/{customer_id}/googleAds:search"
        req = urllib.request.Request(
            url,
            data=json.dumps({"query": query}).encode(),
            method="POST",
            headers={
                "Authorization":         f"Bearer {access_token}",
                "developer-token":       dev_token,
                "Content-Type":          "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        spend = 0.0
        ctr   = 0.0
        conv  = 0.0
        rows  = data.get("results", [])

        for row in rows:
            m = row.get("metrics", {})
            spend += float(m.get("costMicros", 0)) / 1_000_000
            conv  += float(m.get("conversions", 0))

        if rows:
            ctr = sum(float(r.get("metrics", {}).get("ctr", 0)) for r in rows) / len(rows) * 100

        return {"spend": spend, "ctr": ctr, "conversions": int(conv)}
