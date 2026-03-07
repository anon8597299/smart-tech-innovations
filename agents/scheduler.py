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
from dashboard       import db

# ── Agent instances (singletons) ─────────────────────────────────────────────
_manager  = ManagerAgent()
_social   = SocialAgent()
_ads      = AdsAgent()
_content  = ContentAgent()
_builder  = BuilderAgent()
_analyst  = AnalystAgent()
_leads    = LeadsAgent()

# Map used by dashboard /api/trigger endpoint
AGENT_MAP = {
    "manager": _manager,
    "social":  _social,
    "ads":     _ads,
    "content": _content,
    "builder": _builder,
    "analyst": _analyst,
    "leads":   _leads,
}

TIMEZONE = "Australia/Sydney"


def _run(agent, run_analyst_after: bool = False):
    """Execute an agent and optionally follow with the analyst."""
    agent.execute()
    if run_analyst_after:
        _analyst.execute()


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

    # Leads — new outreach 10:00 AM daily, follow-ups Tuesday 11:00 AM
    scheduler.add_job(
        lambda: _run(_leads),
        CronTrigger(hour=10, minute=0, timezone=TIMEZONE),
        id="leads", name="Leads outreach",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: _run(_leads),
        CronTrigger(day_of_week="tue", hour=11, minute=0, timezone=TIMEZONE),
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
