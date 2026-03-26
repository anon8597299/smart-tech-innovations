from typing import Optional
"""
agents/ads.py — Google Ads Super Agent (multi-tenant)

Capabilities:
  1. Keyword-level performance breakdown (not just aggregate totals)
  2. Auto-pause dead keywords (spent above threshold, zero conversions)
  3. Search term mining — converting queries → keyword suggestions,
     wasted spend → potential negatives
  4. Week-over-week comparison (spend, CTR, conversions, conv rate)
  5. Budget pacing — alert if today's spend is on track to blow the daily budget
  6. Full KPI assessment vs AU professional services benchmarks
  7. Comprehensive email report covering all of the above

Single-client usage (owner account — reads from builder/.env):
    AdsAgent().execute()

Multi-client usage (external client — reads from client_config dict):
    AdsAgent(client_config={"slug": "acme", "company_name": "Acme Plumbing", ...}).execute()

Run all active clients (called by scheduler):
    run_all_clients()

Onboard a new client interactively:
    python agents/ads_onboard.py

Default schedule: Daily 9:00 AM AEST  (see agents/scheduler.py)
"""

import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent, GMAIL_USER, GMAIL_PASS, JAMES_EMAIL
from dashboard import db

# ── Default KPI targets — AU professional services benchmarks ─────────────────
_DEFAULT_TARGET_CTR         = 2.5    # %
_DEFAULT_TARGET_CONV_RATE   = 4.0    # %
_DEFAULT_TARGET_COST_CONV   = 80.0   # AUD max cost per conversion
_DEFAULT_TARGET_LEADS_DAILY = 1.5    # avg leads/day over 7 days
_DEFAULT_SPEND_ALERT_AUD    = 50.0   # alert if 7-day total spend exceeds this
INDUSTRY_CTR                = 2.1
INDUSTRY_CONV_RATE          = 3.75

# ── Default auto-pause thresholds ────────────────────────────────────────────
_DEFAULT_AUTO_PAUSE_MIN_SPEND  = 15.0   # AUD spent in last 7 days
_DEFAULT_AUTO_PAUSE_MIN_CLICKS = 20     # minimum clicks before auto-pause

# ── Budget pacing ─────────────────────────────────────────────────────────────
_DEFAULT_BUDGET_OVERPACE_PCT = 0.15   # alert if projected EOD > budget × 1.15

# ── Learning period ───────────────────────────────────────────────────────────
LEARNING_PERIOD_DAYS = 14   # Google Ads needs this long to collect data & train


class AdsAgent(BaseAgent):
    agent_id = "ads"
    name     = "Ads"

    def __init__(self, client_config: Optional[dict] = None):
        """
        client_config — if provided, uses these credentials instead of env vars.
        Expected keys: slug, company_name, contact_email, customer_id,
                       login_customer_id, dev_token, oauth_client_id,
                       oauth_client_secret, refresh_token, kpi_config (optional dict).
        """
        super().__init__() if hasattr(super(), "__init__") else None
        self._client_config = client_config
        self._company_name  = (client_config or {}).get("company_name", "IYS Owner Account")
        self._report_to     = (client_config or {}).get("contact_email", None)

    # ── Learning period ───────────────────────────────────────────────────────

    @property
    def _learning_day(self) -> Optional[int]:
        """
        Returns how many days since this client was onboarded (1-based),
        or None for the owner account (no created_at in env-based config).
        """
        created_at = (self._client_config or {}).get("created_at")
        if not created_at:
            return None
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - created
            return delta.days + 1   # day 1 = day of onboarding
        except Exception:
            return None

    @property
    def _in_learning_period(self) -> bool:
        day = self._learning_day
        return day is not None and day <= LEARNING_PERIOD_DAYS

    # ── KPI helpers (per-client overrides fall back to defaults) ──────────────

    def _kpi(self, key: str, default):
        cfg = (self._client_config or {}).get("kpi_config") or {}
        return cfg.get(key, default)

    @property
    def _target_ctr(self):         return self._kpi("target_ctr",         _DEFAULT_TARGET_CTR)
    @property
    def _target_conv_rate(self):   return self._kpi("target_conv_rate",   _DEFAULT_TARGET_CONV_RATE)
    @property
    def _target_cost_conv(self):   return self._kpi("target_cost_conv",   _DEFAULT_TARGET_COST_CONV)
    @property
    def _target_leads_daily(self): return self._kpi("target_leads_daily", _DEFAULT_TARGET_LEADS_DAILY)
    @property
    def _spend_alert(self):        return self._kpi("spend_alert_aud",    _DEFAULT_SPEND_ALERT_AUD)
    @property
    def _pause_min_spend(self):    return self._kpi("auto_pause_min_spend",  _DEFAULT_AUTO_PAUSE_MIN_SPEND)
    @property
    def _pause_min_clicks(self):   return self._kpi("auto_pause_min_clicks", _DEFAULT_AUTO_PAUSE_MIN_CLICKS)
    @property
    def _overpace_pct(self):       return self._kpi("budget_overpace_pct",   _DEFAULT_BUDGET_OVERPACE_PCT)

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self):
        creds = self._get_creds()
        if not creds:
            return

        label = f"Google Ads — {self._company_name}"
        tid = self.create_task("ads_report", f"{label} — full performance audit")
        self.update_progress(tid, 5)

        try:
            import warnings
            warnings.filterwarnings("ignore")
            from google.ads.googleads.client import GoogleAdsClient

            client = GoogleAdsClient.load_from_dict({
                "developer_token": creds["dev_token"],
                "client_id":       creds["client_id"],
                "client_secret":   creds["client_secret"],
                "refresh_token":   creds["refresh_token"],
                "use_proto_plus":  True,
            })
            cid = creds["customer_id"]

            self.update_progress(tid, 15)
            keyword_stats = self._fetch_keyword_stats(client, cid)

            self.update_progress(tid, 30)
            if self._in_learning_period:
                paused = []   # never auto-pause during learning period
                self.log_info(
                    f"[{self._company_name}] Learning period day "
                    f"{self._learning_day}/{LEARNING_PERIOD_DAYS} — auto-pause skipped"
                )
            else:
                paused = self._auto_pause_dead_keywords(client, cid, keyword_stats)

            self.update_progress(tid, 50)
            search_terms = self._fetch_search_terms(client, cid)

            self.update_progress(tid, 65)
            wow = self._fetch_week_comparison(client, cid)

            self.update_progress(tid, 80)
            pacing_alerts = self._check_budget_pacing(client, cid)

            self.update_progress(tid, 92)
            self._report(tid, keyword_stats, paused, search_terms, wow, pacing_alerts)

        except Exception as exc:
            self.fail_task(tid, str(exc))
            self.log_error(f"Google Ads agent failed ({self._company_name}): {exc}")

    # ── Credentials ───────────────────────────────────────────────────────────

    def _get_creds(self) -> Optional[dict]:
        """Return credential dict from client_config or env vars."""
        if self._client_config:
            cfg = self._client_config
            required = ["dev_token", "oauth_client_id", "oauth_client_secret",
                        "refresh_token", "customer_id"]
            missing = [k for k in required if not cfg.get(k)]
            if missing:
                self.log_warn(f"Ads client '{cfg.get('slug')}' missing fields: {missing}")
                return None
            return {
                "dev_token":    cfg["dev_token"],
                "client_id":    cfg["oauth_client_id"],
                "client_secret":cfg["oauth_client_secret"],
                "refresh_token":cfg["refresh_token"],
                "customer_id":  cfg["customer_id"],
            }

        # Owner account — read from env
        required = [
            "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",   "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_CUSTOMER_ID",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            self.log_warn(f"Google Ads: missing env vars {missing} — skipping")
            return None
        return {
            "dev_token":    os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id":    os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret":os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token":os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "customer_id":  os.environ["GOOGLE_ADS_CUSTOMER_ID"],
        }

    # ── Email (sends to client or James) ─────────────────────────────────────

    def _send_report_email(self, subject: str, body: str):
        """Send the ads report to the configured recipient."""
        to = self._report_to or JAMES_EMAIL
        if not GMAIL_USER or not GMAIL_PASS:
            self.log_warn("Email skipped — GMAIL_USER / GMAIL_APP_PASS not set")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = GMAIL_USER
            msg["To"]      = to
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_USER, GMAIL_PASS)
                server.sendmail(GMAIL_USER, to, msg.as_string())
            self.log_info(f"Report sent to {to}: {subject}")
        except Exception as exc:
            self.log_warn(f"Report email failed: {exc}")

    # ── 1. Keyword-level stats ────────────────────────────────────────────────

    def _fetch_keyword_stats(self, client, customer_id: str) -> list[dict]:
        """
        Return aggregated 7-day stats per keyword (all non-removed keywords).
        Filtering by LAST_7_DAYS in WHERE without selecting segments.date
        gives one aggregated row per keyword.
        """
        ga = client.get_service("GoogleAdsService")
        query = """
            SELECT
                ad_group_criterion.resource_name,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group.name,
                campaign.name,
                campaign.id,
                metrics.cost_micros,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.ctr
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = KEYWORD
              AND segments.date DURING LAST_7_DAYS
              AND campaign.status != REMOVED
              AND ad_group.status != REMOVED
              AND ad_group_criterion.status != REMOVED
            ORDER BY metrics.cost_micros DESC
        """
        results = []
        for row in ga.search(customer_id=customer_id, query=query):
            c = row.ad_group_criterion
            m = row.metrics
            results.append({
                "resource_name": c.resource_name,
                "text":          c.keyword.text,
                "match_type":    c.keyword.match_type.name,
                "status":        c.status.name,
                "ad_group":      row.ad_group.name,
                "campaign":      row.campaign.name,
                "campaign_id":   row.campaign.id,
                "spend":         m.cost_micros / 1_000_000,
                "clicks":        m.clicks,
                "impressions":   m.impressions,
                "conversions":   m.conversions,
                "ctr":           m.ctr * 100,
            })
        return results

    # ── 2. Auto-pause dead keywords ───────────────────────────────────────────

    def _auto_pause_dead_keywords(
        self, client, customer_id: str, keyword_stats: list[dict]
    ) -> list[dict]:
        """
        Pause any ENABLED keyword that has:
          - spent >= _pause_min_spend AUD
          - clicks >= _pause_min_clicks
          - 0 conversions
        """
        candidates = [
            k for k in keyword_stats
            if k["status"] == "ENABLED"
            and k["spend"] >= self._pause_min_spend
            and k["clicks"] >= self._pause_min_clicks
            and k["conversions"] == 0
        ]
        if not candidates:
            return []

        agc = client.get_service("AdGroupCriterionService")
        ops = []
        for k in candidates:
            op = client.get_type("AdGroupCriterionOperation")
            op.update.resource_name = k["resource_name"]
            op.update.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
            op.update_mask.paths.append("status")
            ops.append(op)

        agc.mutate_ad_group_criteria(customer_id=customer_id, operations=ops)

        for k in candidates:
            msg = (f"Auto-paused: '{k['text']}' [{k['match_type'][:2]}] "
                   f"— ${k['spend']:.2f} / {k['clicks']} clicks / 0 conv")
            self.log_warn(msg)
            db.event_log("ads", "warn", msg)

        return candidates

    # ── 3. Search term mining ─────────────────────────────────────────────────

    def _fetch_search_terms(self, client, customer_id: str) -> dict:
        """
        Pull last-7-day search terms.
        converting — terms that generated conversions (add as exact/phrase keywords)
        wasted     — terms with meaningful spend/clicks but zero conversions (negatives)
        """
        ga = client.get_service("GoogleAdsService")
        query = """
            SELECT
                search_term_view.search_term,
                search_term_view.status,
                metrics.cost_micros,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions
            FROM search_term_view
            WHERE segments.date DURING LAST_7_DAYS
              AND metrics.impressions > 0
            ORDER BY metrics.conversions DESC, metrics.cost_micros DESC
            LIMIT 200
        """
        converting, wasted = [], []
        for row in ga.search(customer_id=customer_id, query=query):
            sv    = row.search_term_view
            m     = row.metrics
            spend = m.cost_micros / 1_000_000
            entry = {
                "term":        sv.search_term,
                "status":      sv.status.name,
                "spend":       spend,
                "clicks":      m.clicks,
                "impressions": m.impressions,
                "conversions": m.conversions,
            }
            if m.conversions > 0:
                converting.append(entry)
            elif spend > 5.0 and m.clicks > 5:
                wasted.append(entry)

        converting.sort(key=lambda x: x["conversions"], reverse=True)
        wasted.sort(key=lambda x: x["spend"], reverse=True)
        return {"converting": converting[:15], "wasted": wasted[:15]}

    # ── 4. Week-over-week comparison ──────────────────────────────────────────

    def _fetch_week_comparison(self, client, customer_id: str) -> dict:
        """Compare this 7-day window vs the previous 7-day window."""
        ga    = client.get_service("GoogleAdsService")
        today = datetime.utcnow().date()

        this_end   = today - timedelta(days=1)
        this_start = today - timedelta(days=7)
        last_end   = today - timedelta(days=8)
        last_start = today - timedelta(days=14)

        def _fetch(start, end) -> dict:
            q = f"""
                SELECT metrics.cost_micros, metrics.clicks,
                       metrics.impressions, metrics.conversions
                FROM campaign
                WHERE segments.date BETWEEN '{start}' AND '{end}'
            """
            spend = clicks = impressions = convs = 0
            for row in ga.search(customer_id=customer_id, query=q):
                m = row.metrics
                spend       += m.cost_micros / 1_000_000
                clicks      += m.clicks
                impressions += m.impressions
                convs       += m.conversions
            ctr       = (clicks / impressions * 100) if impressions else 0.0
            conv_rate = (convs  / clicks      * 100) if clicks      else 0.0
            return {"spend": spend, "clicks": clicks, "impressions": impressions,
                    "conversions": convs, "ctr": ctr, "conv_rate": conv_rate}

        def _delta(a, b):
            return ((a - b) / b * 100) if b else 0.0

        this = _fetch(this_start, this_end)
        last = _fetch(last_start, last_end)
        return {
            "this":  this,
            "last":  last,
            "delta": {k: _delta(this[k], last[k]) for k in this},
        }

    # ── 5. Budget pacing ──────────────────────────────────────────────────────

    def _check_budget_pacing(self, client, customer_id: str) -> list[dict]:
        """
        For each enabled campaign, project end-of-day spend based on
        today's spend so far. Alert if projected > budget × (1 + _overpace_pct).
        """
        ga        = client.get_service("GoogleAdsService")
        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        today_spend: dict[int, float] = {}
        for row in ga.search(customer_id=customer_id, query=f"""
            SELECT campaign.id, metrics.cost_micros
            FROM campaign
            WHERE segments.date = '{today_str}'
              AND campaign.status = ENABLED
        """):
            today_spend[row.campaign.id] = row.metrics.cost_micros / 1_000_000

        now  = datetime.utcnow()
        frac = max(0.01, (now.hour * 60 + now.minute) / 1440)

        alerts = []
        for row in ga.search(customer_id=customer_id, query="""
            SELECT campaign.id, campaign.name, campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.status = ENABLED
        """):
            budget = row.campaign_budget.amount_micros / 1_000_000
            if budget <= 0:
                continue
            spent     = today_spend.get(row.campaign.id, 0.0)
            projected = (spent / frac) if frac > 0 else 0.0
            if projected > budget * (1 + self._overpace_pct):
                alerts.append({
                    "campaign":  row.campaign.name,
                    "budget":    budget,
                    "spent":     spent,
                    "projected": projected,
                })
        return alerts

    # ── 6. Report + email ─────────────────────────────────────────────────────

    def _report(
        self, tid,
        keyword_stats:  list[dict],
        paused:         list[dict],
        search_terms:   dict,
        wow:            dict,
        pacing_alerts:  list[dict],
    ):
        TARGET_CTR        = self._target_ctr
        TARGET_CONV_RATE  = self._target_conv_rate
        TARGET_COST_CONV  = self._target_cost_conv
        TARGET_LEADS_DAILY = self._target_leads_daily
        SPEND_ALERT_AUD   = self._spend_alert

        # ── Aggregate totals ──────────────────────────────────────────────
        total_spend  = sum(k["spend"]       for k in keyword_stats)
        total_clicks = sum(k["clicks"]      for k in keyword_stats)
        total_impr   = sum(k["impressions"] for k in keyword_stats)
        total_conv   = sum(k["conversions"] for k in keyword_stats)

        ctr        = (total_clicks / total_impr   * 100) if total_impr   else 0.0
        conv_rate  = (total_conv   / total_clicks * 100) if total_clicks else 0.0
        cost_conv  = (total_spend  / total_conv)         if total_conv   else 0.0
        daily_leads = total_conv / 7.0

        # ── Learning period ───────────────────────────────────────────────
        learning = self._in_learning_period
        learning_day = self._learning_day
        days_remaining = max(0, LEARNING_PERIOD_DAYS - (learning_day or 0)) if learning else 0

        # ── KPI issues ────────────────────────────────────────────────────
        # During the learning period, KPI misses are observations only — not
        # actionable alerts. Google Ads hasn't had enough data to optimise yet.
        issues = []
        observations = []   # learning-period-only notes (informational, no alarm)

        def _flag(msg, budget_related=False):
            """Route to issues or observations depending on learning period."""
            if learning and not budget_related:
                observations.append(msg)
            else:
                issues.append(msg)

        if ctr < TARGET_CTR:
            _flag(
                f"CTR {ctr:.2f}% below target {TARGET_CTR}% "
                f"(AU avg {INDUSTRY_CTR}%) — improve ad headlines/CTAs"
            )
        if conv_rate < TARGET_CONV_RATE and total_clicks >= 10:
            _flag(
                f"Conv rate {conv_rate:.1f}% below target {TARGET_CONV_RATE}% "
                f"(AU avg {INDUSTRY_CONV_RATE}%) — review landing page"
            )
        if cost_conv > TARGET_COST_CONV and total_conv > 0:
            _flag(
                f"Cost/conv ${cost_conv:.2f} above target ${TARGET_COST_CONV:.2f} "
                f"— tighten keyword targeting"
            )
        if daily_leads < TARGET_LEADS_DAILY and total_clicks >= 5:
            _flag(
                f"{daily_leads:.1f} leads/day below target {TARGET_LEADS_DAILY} "
                f"— increase budget or improve bids"
            )
        if total_spend > SPEND_ALERT_AUD:
            # Spend alerts always go to issues — budget is always actionable
            _flag(
                f"7-day spend ${total_spend:.2f} above alert threshold ${SPEND_ALERT_AUD:.2f}",
                budget_related=True,
            )
        for p in pacing_alerts:
            _flag(
                f"Budget overpacing: '{p['campaign']}' — projected "
                f"${p['projected']:.2f} vs ${p['budget']:.2f}/day budget "
                f"(${p['spent']:.2f} spent so far today)",
                budget_related=True,
            )

        # ── DB event ──────────────────────────────────────────────────────
        db.event_log("ads", "warn" if issues else "info",
            f"[{self._company_name}] Ads 7d: ${total_spend:.2f} | CTR {ctr:.2f}% | "
            f"{int(total_conv)} conv | {len(paused)} auto-paused | "
            f"{len(issues)} KPI issues")

        # ── Format helpers ────────────────────────────────────────────────
        def _arrow(v): return "▲" if v > 2 else ("▼" if v < -2 else "→")
        def _wow(v):   return f"{_arrow(v)} {abs(v):.1f}%"

        top_kw = sorted(keyword_stats, key=lambda x: x["spend"], reverse=True)[:15]
        kw_rows = "\n".join(
            "  {status}  {text:<38} [{mt}]  ${spend:>6.2f}  "
            "{clicks:>4}clk  {ctr:>5.1f}%CTR  {conv:.0f}conv".format(
                status="✓" if k["status"] == "ENABLED" else "⏸",
                text=k["text"][:38],
                mt=k["match_type"][:2],
                **{x: k[x] for x in ("spend", "clicks", "ctr")},
                conv=k["conversions"],
            )
            for k in top_kw
        )

        def _term_lines(terms, icon):
            if not terms:
                return "  None"
            return "\n".join(
                f"  {icon}  \"{t['term']}\"  "
                f"${t['spend']:.2f} / {t['clicks']} clicks / {t['conversions']:.0f} conv"
                for t in terms
            )

        paused_lines = (
            "\n".join(
                f"  ⏸  {p['text']} [{p['match_type'][:2]}]  "
                f"${p['spend']:.2f} / {p['clicks']} clicks / 0 conv"
                for p in paused
            ) if paused else "  None"
        )

        issues_block = (
            "\n".join(f"  • {i}" for i in issues)
            if issues else "  All KPIs on target ✓"
        )

        observations_block = (
            "\n".join(f"  · {o}" for o in observations)
            if observations else "  None"
        )

        w = wow["this"]
        d = wow["delta"]

        if learning:
            subject = (
                f"[Ads — {self._company_name}] "
                f"📚 Learning period day {learning_day}/{LEARNING_PERIOD_DAYS} "
                f"— ${total_spend:.2f} / {int(total_conv)} conv"
                + (f" | ⚠ {len(issues)} budget alert(s)" if issues else "")
            )
        else:
            subject = (
                f"[Ads — {self._company_name}] "
                f"{'⚠ ' + str(len(issues)) + ' issue(s)' if issues else '✓ On target'}"
                f" — ${total_spend:.2f} / {int(total_conv)} conv / {daily_leads:.1f}/day"
            )

        learning_banner = ""
        if learning:
            learning_banner = f"""
⚠  LEARNING PERIOD — Day {learning_day} of {LEARNING_PERIOD_DAYS}
{'─' * 62}
Google Ads is still collecting data and training its algorithm.
KPI targets below are for reference only — do not pause keywords
or make major changes until day {LEARNING_PERIOD_DAYS + 1} ({days_remaining} day{'s' if days_remaining != 1 else ''} remaining).
Auto-pause is disabled until the learning period ends.
{'─' * 62}
"""

        body = f"""Google Ads — 7-Day Performance Report
{self._company_name}
{'═' * 62}
{learning_banner}
OVERVIEW (last 7 days)
  Spend:        ${total_spend:.2f} AUD
  Impressions:  {total_impr:,}
  Clicks:       {total_clicks:,}
  CTR:          {ctr:.2f}%     (target {TARGET_CTR}%+ │ AU avg {INDUSTRY_CTR}%)
  Conversions:  {int(total_conv)}
  Conv rate:    {conv_rate:.1f}%     (target {TARGET_CONV_RATE}%+ │ AU avg {INDUSTRY_CONV_RATE}%)
  Cost/conv:    ${cost_conv:.2f}   (target ≤${TARGET_COST_CONV:.2f})
  Leads/day:    {daily_leads:.1f}      (target {TARGET_LEADS_DAILY}+)

WEEK-OVER-WEEK
  Spend:        ${w['spend']:.2f}        {_wow(d['spend'])} vs prev week
  Clicks:       {w['clicks']}           {_wow(d['clicks'])}
  CTR:          {w['ctr']:.2f}%        {_wow(d['ctr'])}
  Conversions:  {w['conversions']:.0f}           {_wow(d['conversions'])}
  Conv rate:    {w['conv_rate']:.1f}%        {_wow(d['conv_rate'])}

AUTO-PAUSED THIS RUN  ({len(paused)} keyword{'s' if len(paused) != 1 else ''})
{paused_lines}

TOP KEYWORDS BY SPEND
  ✓=enabled  ⏸=paused  MT=match type (BR/PH/EX)
{kw_rows}

CONVERTING SEARCH TERMS  (consider adding as exact/phrase keywords)
{_term_lines(search_terms['converting'], '✓')}

WASTED SEARCH TERMS  (consider adding as negatives)
{_term_lines(search_terms['wasted'], '✗')}

KPI STATUS  {"(Learning period — observations only, no action needed)" if learning else ""}
{issues_block}
{(chr(10) + "LEARNING PERIOD OBSERVATIONS  (informational — revisit after day " + str(LEARNING_PERIOD_DAYS) + ")" + chr(10) + observations_block) if learning and observations else ""}

{'─' * 62}
Manage: https://ads.google.com
"""

        # Always send during learning period so client gets regular updates.
        # After learning: only send if there are issues or paused keywords.
        should_email = learning or issues or paused
        if should_email:
            self._send_report_email(subject=subject, body=body)

        if learning:
            self.log_info(
                f"[{self._company_name}] Google Ads: learning period day "
                f"{learning_day}/{LEARNING_PERIOD_DAYS} | "
                f"${total_spend:.2f} / {int(total_conv)} conv | "
                f"{len(observations)} observations | "
                f"{'⚠ ' + str(len(issues)) + ' budget alert(s)' if issues else 'no budget alerts'}"
            )
        elif issues:
            self.log_warn(
                f"[{self._company_name}] Google Ads: {len(issues)} KPI issue(s), "
                f"{len(paused)} auto-paused — email sent"
            )
        else:
            self.log_info(
                f"[{self._company_name}] Google Ads: all KPIs on target ✓ "
                f"(${total_spend:.2f} / {int(total_conv)} conv / "
                f"{len(paused)} auto-paused)"
            )

        learning_note = f"📚 learning day {learning_day}/{LEARNING_PERIOD_DAYS}" if learning else ""
        self.complete_task(
            tid,
            f"[{self._company_name}] ${total_spend:.2f} · {ctr:.2f}% CTR · "
            f"{int(total_conv)} conv · {daily_leads:.1f}/day · "
            + (learning_note if learning else
               f"{len(paused)} paused · "
               f"{'⚠ ' + str(len(issues)) + ' KPI issue(s)' if issues else '✓ on target'}")
        )


# ── Campaign creation ─────────────────────────────────────────────────────────

    def create_campaign(self, brief: dict) -> dict:
        """
        Build a complete Google Search campaign from scratch.

        brief keys:
          campaign_name   str   — e.g. "Acme Plumbing — Sydney"
          daily_budget    float — AUD, e.g. 30.0
          location        str   — e.g. "Sydney,NSW,Australia"
          ad_group_name   str   — e.g. "Emergency Plumbing"
          keywords        list  — [{"text": "plumber sydney", "match": "PHRASE"}, ...]
          headlines       list  — 3–15 strings (max 30 chars each)
          descriptions    list  — 2–4 strings (max 90 chars each)
          final_url       str   — landing page URL

        Returns dict with created resource names.
        """
        import warnings
        warnings.filterwarnings("ignore")
        from google.ads.googleads.client import GoogleAdsClient

        creds = self._get_creds()
        if not creds:
            raise RuntimeError("No credentials available")

        client = GoogleAdsClient.load_from_dict({
            "developer_token": creds["dev_token"],
            "client_id":       creds["client_id"],
            "client_secret":   creds["client_secret"],
            "refresh_token":   creds["refresh_token"],
            "use_proto_plus":  True,
        })
        cid = creds["customer_id"]

        # ── 1. Campaign budget ────────────────────────────────────────────
        budget_service = client.get_service("CampaignBudgetService")
        budget_op      = client.get_type("CampaignBudgetOperation")
        budget         = budget_op.create
        budget.name               = f"{brief['campaign_name']} Budget"
        budget.amount_micros      = int(brief["daily_budget"] * 1_000_000)
        budget.delivery_method    = client.enums.BudgetDeliveryMethodEnum.STANDARD

        budget_response   = budget_service.mutate_campaign_budgets(
            customer_id=cid, operations=[budget_op]
        )
        budget_rn = budget_response.results[0].resource_name
        self.log_info(f"[{self._company_name}] Budget created: {budget_rn}")

        # ── 2. Campaign ───────────────────────────────────────────────────
        campaign_service = client.get_service("CampaignService")
        campaign_op      = client.get_type("CampaignOperation")
        campaign         = campaign_op.create
        campaign.name              = brief["campaign_name"]
        campaign.status            = client.enums.CampaignStatusEnum.PAUSED  # start paused — human reviews first
        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.campaign_budget   = budget_rn
        campaign.network_settings.target_google_search       = True
        campaign.network_settings.target_search_network      = True
        campaign.network_settings.target_content_network     = False

        # Manual CPC — safest default; client can switch to Smart Bidding after learning
        campaign.manual_cpc.enhanced_cpc_enabled = False

        # Geo targeting (criterion added separately below)
        campaign_response = campaign_service.mutate_campaigns(
            customer_id=cid, operations=[campaign_op]
        )
        campaign_rn = campaign_response.results[0].resource_name
        self.log_info(f"[{self._company_name}] Campaign created: {campaign_rn}")

        # ── 3. Geo targeting ──────────────────────────────────────────────
        # Australia geo constant = 2036; Sydney = 1000567 (Google geo IDs)
        geo_map = {
            "australia":     "geoTargetConstants/2036",
            "sydney":        "geoTargetConstants/1000567",
            "melbourne":     "geoTargetConstants/1000567",   # placeholder
            "brisbane":      "geoTargetConstants/1011798",
            "perth":         "geoTargetConstants/1012680",
            "adelaide":      "geoTargetConstants/1000719",
        }
        location_key = brief.get("location", "australia").lower().split(",")[0].strip()
        geo_rn = geo_map.get(location_key, geo_map["australia"])

        crit_service = client.get_service("CampaignCriterionService")
        geo_op       = client.get_type("CampaignCriterionOperation")
        geo          = geo_op.create
        geo.campaign               = campaign_rn
        geo.location.geo_target_constant = geo_rn
        crit_service.mutate_campaign_criteria(customer_id=cid, operations=[geo_op])

        # ── 4. Ad group ───────────────────────────────────────────────────
        ag_service = client.get_service("AdGroupService")
        ag_op      = client.get_type("AdGroupOperation")
        ag         = ag_op.create
        ag.name     = brief["ad_group_name"]
        ag.campaign = campaign_rn
        ag.status   = client.enums.AdGroupStatusEnum.ENABLED
        ag.cpc_bid_micros = 1_000_000   # $1.00 default CPC — client adjusts after data

        ag_response = ag_service.mutate_ad_groups(customer_id=cid, operations=[ag_op])
        ag_rn = ag_response.results[0].resource_name
        self.log_info(f"[{self._company_name}] Ad group created: {ag_rn}")

        # ── 5. Keywords ───────────────────────────────────────────────────
        match_enum = client.enums.KeywordMatchTypeEnum
        match_map  = {
            "BROAD":  match_enum.BROAD,
            "PHRASE": match_enum.PHRASE,
            "EXACT":  match_enum.EXACT,
        }
        agc_service = client.get_service("AdGroupCriterionService")
        kw_ops = []
        for kw in brief.get("keywords", []):
            op = client.get_type("AdGroupCriterionOperation")
            c  = op.create
            c.ad_group           = ag_rn
            c.status             = client.enums.AdGroupCriterionStatusEnum.ENABLED
            c.keyword.text       = kw["text"]
            c.keyword.match_type = match_map.get(kw.get("match", "PHRASE").upper(),
                                                  match_enum.PHRASE)
            kw_ops.append(op)

        if kw_ops:
            agc_service.mutate_ad_group_criteria(customer_id=cid, operations=kw_ops)
        self.log_info(f"[{self._company_name}] {len(kw_ops)} keywords added")

        # ── 6. Responsive Search Ad ───────────────────────────────────────
        ad_service = client.get_service("AdGroupAdService")
        ad_op      = client.get_type("AdGroupAdOperation")
        ad_group_ad            = ad_op.create
        ad_group_ad.ad_group   = ag_rn
        ad_group_ad.status     = client.enums.AdGroupAdStatusEnum.ENABLED
        rsa = ad_group_ad.ad.responsive_search_ad

        for i, text in enumerate(brief.get("headlines", [])[:15]):
            asset = client.get_type("AdTextAsset")
            asset.text = text[:30]
            # Pin first two headlines to positions 1 & 2 for consistency
            if i == 0:
                asset.pinned_field = client.enums.ServedAssetFieldTypeEnum.HEADLINE_1
            elif i == 1:
                asset.pinned_field = client.enums.ServedAssetFieldTypeEnum.HEADLINE_2
            rsa.headlines.append(asset)

        for text in brief.get("descriptions", [])[:4]:
            asset = client.get_type("AdTextAsset")
            asset.text = text[:90]
            rsa.descriptions.append(asset)

        rsa.path1 = brief.get("path1", "")
        rsa.path2 = brief.get("path2", "")
        ad_group_ad.ad.final_urls.append(brief["final_url"])

        ad_service.mutate_ad_group_ads(customer_id=cid, operations=[ad_op])
        self.log_info(f"[{self._company_name}] Responsive Search Ad created")

        result = {
            "budget_rn":   budget_rn,
            "campaign_rn": campaign_rn,
            "ad_group_rn": ag_rn,
            "keywords":    len(kw_ops),
            "status":      "PAUSED",   # always starts paused — review before enabling
        }
        db.event_log("ads", "info",
            f"[{self._company_name}] Campaign created from scratch: "
            f"'{brief['campaign_name']}' | ${brief['daily_budget']:.2f}/day | "
            f"{len(kw_ops)} keywords | Status: PAUSED (awaiting review)")
        return result


# ── Multi-tenant entry point (called by scheduler) ────────────────────────────

def run_all_clients():
    """
    Run the ads agent for the owner account, then for every active client in DB.
    Called by the scheduler instead of AdsAgent().execute() directly.
    """
    # Owner account first
    AdsAgent().execute()

    # All active external clients
    for client_cfg in db.ads_client_list(active_only=True):
        try:
            AdsAgent(client_config=client_cfg).execute()
        except Exception as exc:
            db.event_log("ads", "error",
                f"run_all_clients failed for '{client_cfg.get('slug')}': {exc}")
