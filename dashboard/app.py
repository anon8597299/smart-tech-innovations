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
