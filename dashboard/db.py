"""
dashboard/db.py — SQLite schema + all query helpers for IYS Agent System.

DB file: dashboard/iys_agents.db
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "iys_agents.db"

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Return a thread-local connection (create if needed)."""
    if not getattr(_local, "conn", None):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def transaction():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """Create all tables if they don't exist."""
    with transaction() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'idle',
                last_run    TEXT,
                next_run    TEXT,
                task_count  INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        TEXT NOT NULL,
                type            TEXT NOT NULL,
                title           TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                progress        INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                completed_at    TEXT,
                output_preview  TEXT,
                FOREIGN KEY (agent_id) REFERENCES agents(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'info',
                message     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                type            TEXT NOT NULL,
                title           TEXT NOT NULL,
                preview_path    TEXT,
                customer_slug   TEXT,
                status          TEXT NOT NULL DEFAULT 'delivered',
                created_at      TEXT NOT NULL
            );

            INSERT OR IGNORE INTO agents (id, name, status) VALUES
                ('manager',  'Manager',  'idle'),
                ('social',   'Social',   'idle'),
                ('ads',      'Ads',      'idle'),
                ('content',  'Content',  'idle'),
                ('builder',  'Builder',  'idle'),
                ('analyst',  'Analyst',  'idle');
        """)
    _init_scheduled_tasks(get_conn())


# ── Agent helpers ────────────────────────────────────────────────────────────

def agent_set_status(agent_id: str, status: str):
    now = _now()
    with transaction() as conn:
        if status == "running":
            conn.execute(
                "UPDATE agents SET status=?, last_run=? WHERE id=?",
                (status, now, agent_id),
            )
        else:
            conn.execute(
                "UPDATE agents SET status=? WHERE id=?",
                (status, agent_id),
            )


def agent_set_next_run(agent_id: str, next_run: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE agents SET next_run=? WHERE id=?",
            (next_run, agent_id),
        )


def agent_increment_error(agent_id: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE agents SET error_count = error_count + 1 WHERE id=?",
            (agent_id,),
        )


def agent_increment_task(agent_id: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE agents SET task_count = task_count + 1 WHERE id=?",
            (agent_id,),
        )


def agents_all() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def agent_get(agent_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    return dict(row) if row else None


# ── Task helpers ─────────────────────────────────────────────────────────────

def task_create(agent_id: str, task_type: str, title: str) -> int:
    now = _now()
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (agent_id, type, title, status, progress, created_at) "
            "VALUES (?, ?, ?, 'running', 0, ?)",
            (agent_id, task_type, title, now),
        )
        agent_increment_task(agent_id)
        return cur.lastrowid


def task_update_progress(task_id: int, progress: int, preview: str | None = None):
    with transaction() as conn:
        if preview:
            conn.execute(
                "UPDATE tasks SET progress=?, output_preview=? WHERE id=?",
                (progress, preview, task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET progress=? WHERE id=?",
                (progress, task_id),
            )


def task_complete(task_id: int, preview: str | None = None):
    now = _now()
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET status='completed', progress=100, completed_at=?, output_preview=COALESCE(?, output_preview) WHERE id=?",
            (now, preview, task_id),
        )


def task_fail(task_id: int, reason: str):
    now = _now()
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET status='failed', completed_at=?, output_preview=? WHERE id=?",
            (now, reason, task_id),
        )


def tasks_active() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='running' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def tasks_recent(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Event helpers ────────────────────────────────────────────────────────────

def event_log(agent_id: str, level: str, message: str) -> dict:
    now = _now()
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO events (agent_id, level, message, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, level, message, now),
        )
        row_id = cur.lastrowid
    return {"id": row_id, "agent_id": agent_id, "level": level, "message": message, "timestamp": now}


def events_recent(limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def events_since(event_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events WHERE id > ? ORDER BY id ASC", (event_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Content helpers ──────────────────────────────────────────────────────────

def content_add(
    content_type: str,
    title: str,
    preview_path: str | None = None,
    customer_slug: str | None = None,
    status: str = "delivered",
) -> int:
    now = _now()
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO content (type, title, preview_path, customer_slug, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (content_type, title, preview_path, customer_slug, status, now),
        )
        return cur.lastrowid


def content_recent(limit: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM content ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Scheduled tasks ───────────────────────────────────────────────────────────

def _init_scheduled_tasks(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id      TEXT NOT NULL,
            title         TEXT NOT NULL,
            notes         TEXT DEFAULT '',
            scheduled_for TEXT NOT NULL,
            status        TEXT DEFAULT 'pending',
            created_at    TEXT NOT NULL
        )
    """)
    conn.commit()


def scheduled_task_create(agent_id: str, title: str, notes: str, scheduled_for: str) -> int:
    with transaction() as c:
        c.execute(
            "INSERT INTO scheduled_tasks (agent_id, title, notes, scheduled_for, created_at) VALUES (?,?,?,?,?)",
            (agent_id, title, notes, scheduled_for, _now())
        )
        return c.lastrowid


def scheduled_tasks_for_month(year: int, month: int) -> list[dict]:
    conn = get_conn()
    prefix = f"{year:04d}-{month:02d}"
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE scheduled_for LIKE ? AND status != 'cancelled' ORDER BY scheduled_for ASC",
        (f"{prefix}%",)
    ).fetchall()
    return [dict(r) for r in rows]


def scheduled_tasks_for_date(date_str: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE scheduled_for=? AND status='pending' ORDER BY id ASC",
        (date_str,)
    ).fetchall()
    return [dict(r) for r in rows]


def scheduled_task_cancel(task_id: int):
    with transaction() as c:
        c.execute("UPDATE scheduled_tasks SET status='cancelled' WHERE id=?", (task_id,))


def scheduled_task_mark_triggered(task_id: int):
    with transaction() as c:
        c.execute("UPDATE scheduled_tasks SET status='triggered' WHERE id=?", (task_id,))


# ── Calendar helpers ──────────────────────────────────────────────────────────

def tasks_for_month(year: int, month: int) -> list[dict]:
    """Return all tasks created in the given month, grouped by date."""
    conn = get_conn()
    prefix = f"{year:04d}-{month:02d}"
    rows = conn.execute(
        "SELECT id, agent_id, type, title, status, progress, created_at, output_preview "
        "FROM tasks WHERE created_at LIKE ? ORDER BY created_at ASC",
        (f"{prefix}%",)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Digest helpers ───────────────────────────────────────────────────────────

def digest_summary() -> dict:
    """Return counts used by the daily digest email."""
    conn = get_conn()
    tasks_today = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE DATE(created_at)=DATE('now') AND status='completed'"
    ).fetchone()[0]
    errors_today = conn.execute(
        "SELECT COUNT(*) FROM events WHERE DATE(timestamp)=DATE('now') AND level='error'"
    ).fetchone()[0]
    content_today = conn.execute(
        "SELECT COUNT(*) FROM content WHERE DATE(created_at)=DATE('now')"
    ).fetchone()[0]
    recent_errors = conn.execute(
        "SELECT agent_id, message, timestamp FROM events "
        "WHERE DATE(timestamp)=DATE('now') AND level='error' ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return {
        "tasks_completed": tasks_today,
        "errors": errors_today,
        "content_delivered": content_today,
        "recent_errors": [dict(r) for r in recent_errors],
    }


# ── Internal ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
