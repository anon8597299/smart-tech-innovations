"""
dashboard/app.py — FastAPI application for IYS Agent Dashboard.

Routes:
  GET  /                  → serves dashboard/index.html
  GET  /api/state         → full initial state (agents, tasks, events, content)
  GET  /api/stream        → SSE real-time event stream
  GET  /api/agents        → agent list
  GET  /api/tasks         → recent tasks
  GET  /api/events        → recent events
  GET  /api/content       → delivered content
  POST /api/trigger/{id}  → run an agent immediately
  POST /api/pause         → pause all (sets a flag agents check)
  POST /api/clear         → clear completed tasks

Start: uvicorn dashboard.app:app --port 8080 --reload
       (or via run.py which also starts APScheduler)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

# Ensure dashboard dir + project root on path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
try:
    import agents.base as agent_base
except ImportError:
    agent_base = None  # Gracefully handle if agents module unavailable

app = FastAPI(title="IYS Agent Dashboard", docs_url=None, redoc_url=None)

# ── Basic Auth ────────────────────────────────────────────────────────────────
security = HTTPBasic()
AUTH_ENABLED = os.environ.get("DASHBOARD_AUTH", "true").lower() == "true"

def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """Basic auth middleware — username: james, password from DASHBOARD_PASSWORD env var"""
    if not AUTH_ENABLED:
        return "bypass"
    correct_username = secrets.compare_digest(credentials.username, "james")
    correct_password = secrets.compare_digest(
        credentials.password, 
        os.environ.get("DASHBOARD_PASSWORD", "changeme123")
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Apply auth to all routes except /health
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if AUTH_ENABLED and not request.url.path.startswith("/health"):
        try:
            credentials = await security(request)
            verify_auth(credentials)
        except HTTPException:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": "Basic"},
                content="Unauthorized"
            )
    response = await call_next(request)
    return response

# ── SSE broadcast queue (shared with agents) ─────────────────────────────────
_sse_clients: list[asyncio.Queue] = []
_master_queue: asyncio.Queue | None = None
_paused = False

DASHBOARD_DIR = Path(__file__).parent
PROJECT_ROOT  = DASHBOARD_DIR.parent


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_db()
    # Give base.py access to a thread-safe queue bridge (only if agents module available)
    if agent_base:
        import queue
        sync_q: queue.Queue = queue.Queue()
        agent_base.set_sse_queue(sync_q)
        # Background task that drains sync_q → async SSE clients
        asyncio.create_task(_bridge_queue(sync_q))


async def _bridge_queue(sync_q):
    """Drain the thread-safe queue and broadcast to all SSE clients."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            msg = await loop.run_in_executor(None, _blocking_get, sync_q)
            if msg:
                for client_q in list(_sse_clients):
                    try:
                        client_q.put_nowait(msg)
                    except asyncio.QueueFull:
                        pass
        except Exception:
            await asyncio.sleep(0.1)


def _blocking_get(q, timeout: float = 0.2):
    import queue
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint (no auth required)"""
    return {"status": "ok", "service": "IYS Dashboard"}

@app.get("/")
async def index():
    html_path = DASHBOARD_DIR / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/state")
async def state():
    return {
        "agents":  db.agents_all(),
        "tasks":   db.tasks_recent(50),
        "events":  db.events_recent(100),
        "content": db.content_recent(30),
        "paused":  _paused,
    }


@app.get("/api/agents")
async def agents():
    return db.agents_all()


@app.get("/api/tasks")
async def tasks():
    return db.tasks_recent(50)


@app.get("/api/events")
async def events():
    return db.events_recent(100)


@app.get("/api/content")
async def content():
    return db.content_recent(30)


@app.get("/api/stream")
async def stream():
    """SSE endpoint — clients connect and receive live events."""
    client_q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_clients.append(client_q)

    async def event_gen():
        # Send initial ping so client knows it's connected
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(client_q.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"ping\"}\n\n"
        finally:
            _sse_clients.remove(client_q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/trigger/{agent_id}")
async def trigger(agent_id: str):
    global _paused
    if _paused:
        raise HTTPException(status_code=409, detail="System is paused")
    # Import agent map lazily to avoid circular imports at module load
    from agents.scheduler import AGENT_MAP
    if agent_id not in AGENT_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    import threading
    t = threading.Thread(target=AGENT_MAP[agent_id].execute, daemon=True)
    t.start()
    return {"status": "triggered", "agent_id": agent_id}


@app.post("/api/pause")
async def pause(body: dict = {}):
    global _paused
    _paused = body.get("paused", not _paused)
    return {"paused": _paused}


@app.post("/api/clear")
async def clear_completed():
    conn = db.get_conn()
    with db.transaction() as c:
        c.execute("DELETE FROM tasks WHERE status IN ('completed', 'failed')")
    return {"status": "cleared"}


# ── Chat memory ───────────────────────────────────────────────────────────────

_MEMORY_FILE = Path(__file__).parent.parent / "social" / "chat_memory.json"
_chat_history: list[dict] = []


def _load_memory() -> list[dict]:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text())
        except Exception:
            pass
    return []


def _save_memory(memories: list[dict]):
    _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MEMORY_FILE.write_text(json.dumps(memories[-60:], indent=2))  # keep last 60


def _memory_context() -> str:
    memories = _load_memory()
    if not memories:
        return ""
    lines = "\n".join(f"- [{m['date']}] {m['text']}" for m in memories[-15:])
    return f"\n\nPERSISTENT MEMORY (what you've discussed previously):\n{lines}"


# ── Chat endpoint ─────────────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """You are the IYS (ImproveYourSite.com) operations assistant built into the agent dashboard.

You help James Burke manage his web agency's automated systems. You have full knowledge of:
- 6 agents: Manager (daily digest 7am), Social (Instagram + carousels 8am), Ads (Google Ads 9am),
  Content (auto-blog Monday 6am), Builder (on-demand site generation), Analyst (quality review)
- The calendar where scheduled tasks appear by date

ACTIONS — when the user wants something done, reply with the matching JSON block:

Trigger an agent now:
{"action": "trigger", "agent_id": "<manager|social|ads|content|builder|analyst>"}

Schedule a task on the calendar:
{"action": "schedule", "agent_id": "<id>", "title": "<title>", "date": "<YYYY-MM-DD>", "notes": "<optional>"}

Save something important to memory (decisions, plans, client info):
{"action": "remember", "text": "<what to remember>"}

Queue a site build:
{"action": "queue_build", "config": "<path>"}

You can combine a natural reply with an action block on the same response.
When the user mentions a task for a specific date or agent, proactively schedule it without being asked.
When important business information is shared (client names, decisions, plans), save it to memory automatically.

Keep responses concise — this is a chat panel, not an essay."""


@app.post("/api/chat")
async def chat(body: dict):
    global _chat_history
    from datetime import date as _date

    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"reply": "ANTHROPIC_API_KEY not set in builder/.env — add it to enable chat."}

    try:
        import anthropic
    except ImportError:
        return {"reply": "anthropic package not installed. Run: pip install anthropic"}

    # Build live context
    agents_state = db.agents_all()
    summary      = db.digest_summary()
    agent_str    = ', '.join(a['name'] + ':' + a['status'] for a in agents_state)
    today_str    = _date.today().isoformat()

    # Upcoming scheduled tasks for next 7 days (so Claude knows the calendar)
    upcoming = db.scheduled_tasks_for_month(_date.today().year, _date.today().month)
    upcoming_str = ""
    if upcoming:
        upcoming_str = "\nUpcoming scheduled tasks:\n" + "\n".join(
            f"  {t['scheduled_for']} → [{t['agent_id']}] {t['title']}"
            for t in upcoming[:8]
        )

    context = (
        f"\nToday: {today_str}"
        f"\nAgent states: {agent_str}"
        f"\nTasks completed today: {summary['tasks_completed']}, errors: {summary['errors']}"
        + upcoming_str
        + _memory_context()
    )

    _chat_history.append({"role": "user", "content": message})

    client   = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=CHAT_SYSTEM_PROMPT + context,
        messages=_chat_history[-20:],
    )

    reply_text = response.content[0].text.strip()
    _chat_history.append({"role": "assistant", "content": reply_text})

    # ── Process all action blocks in the reply ────────────────────────────────
    actions_taken = []
    for match in re.finditer(r'\{[^{}]{10,400}\}', reply_text):
        try:
            action = json.loads(match.group(0))
            act = action.get("action", "")

            if act == "trigger":
                agent_id = action.get("agent_id", "")
                from agents.scheduler import AGENT_MAP
                if agent_id in AGENT_MAP and not _paused:
                    import threading
                    threading.Thread(target=AGENT_MAP[agent_id].execute, daemon=True).start()
                    actions_taken.append(f"Triggered {agent_id} agent")

            elif act == "schedule":
                agent_id = action.get("agent_id", "")
                title    = action.get("title", "")
                date_s   = action.get("date", "")
                notes    = action.get("notes", "")
                if agent_id and title and date_s:
                    task_id = db.scheduled_task_create(agent_id, title, notes, date_s)
                    actions_taken.append(f"Scheduled [{agent_id}] '{title}' on {date_s}")

            elif act == "remember":
                text = action.get("text", "").strip()
                if text:
                    memories = _load_memory()
                    memories.append({"date": today_str, "text": text})
                    _save_memory(memories)
                    actions_taken.append(f"Remembered: {text[:60]}")

            elif act == "queue_build":
                from agents.builder import BuilderAgent
                BuilderAgent.enqueue(action.get("config", ""))
                actions_taken.append("Build job queued")

        except Exception:
            pass

    return {
        "reply":        reply_text,
        "action_taken": " · ".join(actions_taken) if actions_taken else None,
        "actions":      actions_taken,
    }


@app.get("/api/memory")
async def get_memory():
    return {"memories": _load_memory()}


@app.delete("/api/memory")
async def clear_memory():
    _save_memory([])
    return {"status": "cleared"}


@app.get("/api/calendar")
async def calendar(year: int = 0, month: int = 0):
    """Return tasks + social posts for a given month for the calendar view."""
    from datetime import date
    import json as _json
    today = date.today()
    y = year  or today.year
    m = month or today.month

    tasks = db.tasks_for_month(y, m)

    # Load social posts from upload_queue.json, filtered to this month
    queue_file = Path(__file__).parent.parent / "social" / "upload_queue.json"
    posts = []
    if queue_file.exists():
        try:
            prefix = f"{y:04d}-{m:02d}"
            all_posts = _json.loads(queue_file.read_text())
            posts = [p for p in all_posts if str(p.get("date", "")).startswith(prefix)]
        except Exception:
            posts = []

    scheduled = db.scheduled_tasks_for_month(y, m)
    return {"year": y, "month": m, "tasks": tasks, "posts": posts, "scheduled": scheduled}


@app.post("/api/schedule")
async def create_schedule(body: dict):
    agent_id = (body.get("agent_id") or "").strip()
    title    = (body.get("title") or "").strip()
    notes    = (body.get("notes") or "").strip()
    date_str = (body.get("date") or "").strip()
    if not agent_id or not title or not date_str:
        raise HTTPException(status_code=400, detail="agent_id, title, date required")
    task_id = db.scheduled_task_create(agent_id, title, notes, date_str)
    return {"id": task_id, "status": "scheduled"}


@app.delete("/api/schedule/{task_id}")
async def cancel_schedule(task_id: int):
    db.scheduled_task_cancel(task_id)
    return {"status": "cancelled"}


@app.delete("/api/chat")
async def clear_chat():
    global _chat_history
    _chat_history = []
    return {"status": "cleared"}


# ── Instagram comment reply endpoint ──────────────────────────────────────────
# Called by Make.com when a new comment arrives.
# Make.com scenario: Instagram Watch Comments → HTTP POST here → Instagram Reply

_REPLY_SYSTEM = """You write short Instagram comment replies for ImproveYourSite.com,
an Australian web agency that builds websites for small businesses.

Rules:
- Max 2 sentences. Sound human and warm, not corporate.
- If the comment is a question about price, services, or websites → invite a DM.
- If it's a compliment or positive → thank them and plant curiosity (e.g. "Let us know if you ever want to chat about yours").
- If it's generic/vague → acknowledge warmly and ask a question back.
- Never use exclamation marks excessively. No emojis unless the commenter used them.
- Always sign off naturally, never with "ImproveYourSite" — keep it personal.
- If the comment is spam, negative/abusive, or irrelevant — return exactly: SKIP"""


@app.post("/api/instagram/generate-reply")
async def instagram_generate_reply(body: dict):
    """
    Called by Make.com to generate a Claude reply to an Instagram comment.

    Request body:
      { "comment": "...", "commenter": "username", "post_caption": "..." }

    Returns:
      { "reply": "...", "skip": false }
    """
    comment      = (body.get("comment") or "").strip()
    commenter    = (body.get("commenter") or "").strip()
    post_caption = (body.get("post_caption") or "").strip()[:200]

    if not comment:
        return {"reply": "", "skip": True}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"reply": "Thanks for your comment! Feel free to DM us if you have any questions.", "skip": False}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"Instagram comment"
        if commenter:
            prompt += f" from @{commenter}"
        if post_caption:
            prompt += f" on a post about: \"{post_caption}\""
        prompt += f":\n\n\"{comment}\"\n\nWrite the reply."

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            system=_REPLY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = response.content[0].text.strip()

        if reply == "SKIP":
            return {"reply": "", "skip": True}

        db.event_log("social", "info", f"IG reply generated for @{commenter}: {reply[:60]}…")
        return {"reply": reply, "skip": False}

    except Exception as exc:
        return {"reply": "Thanks for the comment! DM us if you'd like to chat.", "skip": False}
