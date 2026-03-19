"""
agents/scheduler.py — APScheduler cron definitions for all IYS agents.

All times in AEST (Australia/Sydney).
Scheduler is started from run.py alongside the FastAPI app.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from agents.manager  import ManagerAgent
from agents.social   import SocialAgent
from agents.ads      import AdsAgent
from agents.content  import ContentAgent
from agents.builder  import BuilderAgent
from agents.analyst  import AnalystAgent
from agents.leads    import LeadsAgent
from agents.instagram.agent       import InstagramAgent
from agents.stripe_monitor.agent  import StripeMonitorAgent
from agents.customer_success.agent import CustomerSuccessAgent
from agents.seo_monitor.agent     import SEOMonitorAgent
from agents.inbox.agent           import InboxAgent
from dashboard       import db

# ── Agent instances (singletons) ─────────────────────────────────────────────
_manager          = ManagerAgent()
_social           = SocialAgent()
_ads              = AdsAgent()
_content          = ContentAgent()
_builder          = BuilderAgent()
_analyst          = AnalystAgent()
_leads            = LeadsAgent()
_instagram        = InstagramAgent()
_stripe_monitor   = StripeMonitorAgent()
_customer_success = CustomerSuccessAgent()
_seo_monitor      = SEOMonitorAgent()
_inbox            = InboxAgent()

# Map used by dashboard /api/trigger endpoint
AGENT_MAP = {
    "manager":          _manager,
    "social":           _social,
    "ads":              _ads,
    "content":          _content,
    "builder":          _builder,
    "analyst":          _analyst,
    "leads":            _leads,
    "instagram":        _instagram,
    "stripe_monitor":   _stripe_monitor,
    "customer_success": _customer_success,
    "seo_monitor":      _seo_monitor,
    "inbox":            _inbox,
}

TIMEZONE = "Australia/Sydney"


def _run(agent, run_analyst_after: bool = False):
    """Execute an agent and optionally follow with the analyst."""
    agent.execute()
    if run_analyst_after:
        _analyst.execute()


def _run_with_mode(agent, mode: str):
    """Execute an agent with a specific RUN_MODE env override."""
    import os
    prev = os.environ.get("RUN_MODE", "")
    os.environ["RUN_MODE"] = mode
    try:
        agent.execute()
    finally:
        if prev:
            os.environ["RUN_MODE"] = prev
        else:
            os.environ.pop("RUN_MODE", None)


def _run_scheduled_tasks():
    """Check for any tasks scheduled for today and trigger the assigned agents."""
    from datetime import date
    today = date.today().isoformat()
    tasks = db.scheduled_tasks_for_date(today)
    for t in tasks:
        agent = AGENT_MAP.get(t["agent_id"])
        if agent:
            db.event_log("manager", "info", f"Running scheduled task: {t['title']} → {t['agent_id']}")
            db.scheduled_task_mark_triggered(t["id"])
            import threading
            threading.Thread(target=agent.execute, daemon=True).start()


def build_scheduler() -> BackgroundScheduler:
    """Create and configure the scheduler. Call .start() in run.py."""
    scheduler = BackgroundScheduler(timezone=TIMEZONE)

    # Manager — daily 7:00 AM
    scheduler.add_job(
        lambda: _run(_manager),
        CronTrigger(hour=7, minute=0, timezone=TIMEZONE),
        id="manager", name="Manager digest",
        misfire_grace_time=300,
    )

    # Social — 7:30 AM morning post (peak engagement: commute/coffee)
    scheduler.add_job(
        lambda: _run(_social, run_analyst_after=True),
        CronTrigger(hour=7, minute=30, timezone=TIMEZONE),
        id="social", name="Social morning post",
        misfire_grace_time=300,
    )

    # Social — 6:30 PM evening post (peak engagement: after work)
    scheduler.add_job(
        lambda: _run(_social),
        CronTrigger(hour=18, minute=30, timezone=TIMEZONE),
        id="social_evening", name="Social evening post",
        misfire_grace_time=300,
    )

    # Ads — daily 9:00 AM
    scheduler.add_job(
        lambda: _run(_ads),
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="ads", name="Google Ads report",
        misfire_grace_time=300,
    )

    # Content — Monday 6:00 AM, run analyst after
    scheduler.add_job(
        lambda: _run(_content, run_analyst_after=True),
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=TIMEZONE),
        id="content", name="Auto-blog content",
        misfire_grace_time=600,
    )

    # Leads — new outreach 9:00 AM daily, follow-ups 2:00 PM daily
    scheduler.add_job(
        lambda: _run(_leads),
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="leads", name="Leads outreach",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: _run(_leads),
        CronTrigger(hour=14, minute=0, timezone=TIMEZONE),
        id="leads_followup", name="Leads follow-up",
        misfire_grace_time=300,
    )

    # Scheduled tasks — check at 6:00 AM daily and trigger assigned agents
    scheduler.add_job(
        _run_scheduled_tasks,
        CronTrigger(hour=6, minute=0, timezone=TIMEZONE),
        id="scheduled_tasks", name="Scheduled task runner",
        misfire_grace_time=300,
    )

    # ── Instagram agent ──────────────────────────────────────────────────
    # Morning story: 8:00 AM
    scheduler.add_job(
        lambda: _run(_instagram),
        CronTrigger(hour=8, minute=0, timezone=TIMEZONE),
        id="instagram_morning", name="Instagram morning story",
        misfire_grace_time=300,
    )
    # Evening story: 7:00 PM
    scheduler.add_job(
        lambda: _run(_instagram),
        CronTrigger(hour=19, minute=0, timezone=TIMEZONE),
        id="instagram_evening", name="Instagram evening story",
        misfire_grace_time=300,
    )
    # Insights pull: 9:30 AM
    scheduler.add_job(
        lambda: _run_with_mode(_instagram, "insights"),
        CronTrigger(hour=9, minute=30, timezone=TIMEZONE),
        id="instagram_insights", name="Instagram insights",
        misfire_grace_time=300,
    )
    # Reels planning: Wednesday 8:00 AM
    scheduler.add_job(
        lambda: _run_with_mode(_instagram, "reels"),
        CronTrigger(day_of_week="wed", hour=8, minute=0, timezone=TIMEZONE),
        id="instagram_reels", name="Instagram Reels planning",
        misfire_grace_time=600,
    )

    # ── Stripe Monitor ───────────────────────────────────────────────────
    # Every 30 minutes
    scheduler.add_job(
        lambda: _run(_stripe_monitor),
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        id="stripe_monitor", name="Stripe order monitor",
        misfire_grace_time=120,
    )

    # ── Customer Success ─────────────────────────────────────────────────
    # Lifecycle check: 10:30 AM daily
    scheduler.add_job(
        lambda: _run(_customer_success),
        CronTrigger(hour=10, minute=30, timezone=TIMEZONE),
        id="customer_success", name="Customer lifecycle check",
        misfire_grace_time=300,
    )
    # Site health audit: Sunday 9:00 AM
    scheduler.add_job(
        lambda: _run_with_mode(_customer_success, "health"),
        CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=TIMEZONE),
        id="customer_health", name="Customer site health audit",
        misfire_grace_time=600,
    )

    # ── SEO Monitor ──────────────────────────────────────────────────────
    # Daily check: 8:30 AM
    scheduler.add_job(
        lambda: _run(_seo_monitor),
        CronTrigger(hour=8, minute=30, timezone=TIMEZONE),
        id="seo_monitor", name="SEO daily check",
        misfire_grace_time=300,
    )
    # PageSpeed: Wednesday 9:00 AM
    scheduler.add_job(
        lambda: _run_with_mode(_seo_monitor, "pagespeed"),
        CronTrigger(day_of_week="wed", hour=9, minute=0, timezone=TIMEZONE),
        id="seo_pagespeed", name="PageSpeed audit",
        misfire_grace_time=300,
    )

    # ── Inbox ────────────────────────────────────────────────────────────
    # Triage: every 30 minutes
    scheduler.add_job(
        lambda: _run(_inbox),
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        id="inbox", name="Inbox triage",
        misfire_grace_time=120,
    )

    # ── TAG Projects photo watcher ───────────────────────────────────────
    # Polls hello@ every 30 minutes for Tim's photos — self-cancels once done
    import threading as _threading
    from agents.tag_projects_watcher import run_once as _tag_run_once, WATCH_PASS as _tag_pass
    _tag_done = {"v": False}
    def _run_tag_watcher():
        if _tag_done["v"] or not _tag_pass:
            return
        found = _tag_run_once()
        if found:
            _tag_done["v"] = True
            db.event_log("inbox", "info", "TAG Projects: Tim's photos received and published live")
    scheduler.add_job(
        _run_tag_watcher,
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        id="tag_photo_watcher", name="TAG Projects photo watcher",
        misfire_grace_time=120,
    )

    # ── South Coast Solar reply watcher ─────────────────────────────────
    # Polls outreach@ every 30 min for SCS reply — removes demo if negative
    from agents.scs_reply_watcher import run_once as _scs_run_once
    def _run_scs_watcher():
        _scs_run_once()
    scheduler.add_job(
        _run_scs_watcher,
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        id="scs_reply_watcher", name="SCS reply watcher",
        misfire_grace_time=120,
    )

    # Update next_run timestamps in DB after schedule is built
    _update_next_runs(scheduler)

    return scheduler


def _update_next_runs(scheduler: BackgroundScheduler):
    """Write the next scheduled run time for each agent into the DB.
    Must be called after scheduler.start() so next_run_time is populated.
    """
    for job in scheduler.get_jobs():
        agent_id = job.id
        if agent_id not in AGENT_MAP:
            continue
        try:
            next_run = getattr(job, "next_run_time", None)
            if next_run:
                db.agent_set_next_run(agent_id, next_run.strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            pass
