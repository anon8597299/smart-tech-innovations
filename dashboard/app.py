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
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard import db
import agents.base as agent_base

app = FastAPI(title="IYS Agent Dashboard", docs_url=None, redoc_url=None)

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
    # Give base.py access to a thread-safe queue bridge
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


# ── Chat endpoint ─────────────────────────────────────────────────────────────

# Persistent conversation history (in-memory, resets on restart)
_chat_history: list[dict] = []

CHAT_SYSTEM_PROMPT = """You are the IYS (ImproveYourSite.com) operations assistant built into the agent dashboard.

You help James Burke manage his web agency's automated systems. You have full knowledge of:
- 6 agents: Manager (daily digest 7am), Social (Instagram + carousels 8am), Ads (Google Ads 9am),
  Content (auto-blog Monday 6am), Builder (on-demand site generation), Analyst (quality review)
- The dashboard at http://localhost:8080

When James asks you to trigger an agent, respond with JSON action block:
{"action": "trigger", "agent_id": "<id>"}

When James asks you to queue a site build, respond with:
{"action": "queue_build", "config": "<path>"}

Otherwise, just answer helpfully and concisely. Keep responses short — this is a chat panel.

Current system context will be provided in each message."""


@app.post("/api/chat")
async def chat(body: dict):
    """Chat with Claude about the agent system. Can trigger agents, answer questions."""
    import os
    global _chat_history

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

    # Build system context snapshot
    agents_state = db.agents_all()
    summary = db.digest_summary()
    agent_state_str = ', '.join(a['name'] + ':' + a['status'] for a in agents_state)
    context = (
        f"\nAgent states: {agent_state_str}"
        f"\nToday — tasks completed: {summary['tasks_completed']}, errors: {summary['errors']}, "
        f"content delivered: {summary['content_delivered']}"
    )

    _chat_history.append({"role": "user", "content": message})

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=CHAT_SYSTEM_PROMPT + context,
        messages=_chat_history[-20:],  # keep last 20 turns
    )

    reply_text = response.content[0].text.strip()
    _chat_history.append({"role": "assistant", "content": reply_text})

    # Check for action blocks
    action_taken = None
    import re as _re
    action_match = _re.search(r'\{[^{}]*"action"\s*:\s*"([^"]+)"[^{}]*\}', reply_text)
    if action_match:
        import json as _json
        try:
            action = _json.loads(action_match.group(0))
            if action.get("action") == "trigger":
                agent_id = action.get("agent_id", "")
                from agents.scheduler import AGENT_MAP
                if agent_id in AGENT_MAP and not _paused:
                    import threading
                    threading.Thread(target=AGENT_MAP[agent_id].execute, daemon=True).start()
                    action_taken = f"Triggered {agent_id} agent."
            elif action.get("action") == "queue_build":
                from agents.builder import BuilderAgent
                BuilderAgent.enqueue(action.get("config", ""))
                action_taken = "Build job queued."
        except Exception:
            pass

    return {
        "reply": reply_text,
        "action_taken": action_taken,
    }


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

    return {"year": y, "month": m, "tasks": tasks, "posts": posts}


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
            model="claude-haiku-4-5-20251001",
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
