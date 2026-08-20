"""
Goals and habits -- the deliberately narrow slice of AGENTS_VISION.md's
Personal Division scoped for real (2026-08-17), after Joshua explicitly
chose this over the full Life Agent vision (which also covers marriage,
health, family, journal, reflection -- all still fenced off, per
ROADMAP.md's "sensitive-material policy" note and PERSONALITY_SPEC.md's
Phase 1 privacy caveat). No delegation layer here on purpose: unlike
Operations/Alpha Mode, there's no consult_personal_agent tool and no
personal_agent.py -- just plain CRUD tools (personal_tools.py), same
shape as memory.py's save_memory/forget_memory. A persona giving
commentary or encouragement on goals/habits risks drifting toward
advice, which wasn't the ask; Frank (or this data layer) just remembers
and displays what it's told.

Its own SQLite file (personal.db), same "genuinely separate domain"
reasoning as alpha_mode.db/operations.db. Like every file under
backend/data/, this is gitignored -- nothing written here ever reaches
GitHub.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "personal.db"


async def init_personal_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                target_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                cadence TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.commit()


async def add_goal(title: str, target_date: str | None = None, notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO goals (title, target_date, notes) VALUES (?, ?, ?)",
            (title, target_date, notes),
        )
        await db.commit()
        return title


async def _find_goal_id(db: aiosqlite.Connection, identifier: str) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM goals WHERE title = ? COLLATE NOCASE AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (identifier,),
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await db.execute(
            "SELECT id FROM goals WHERE title LIKE ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (f"%{identifier}%",),
        )
        row = await cursor.fetchone()
    return row["id"] if row else None


async def update_goal_status(identifier: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        goal_id = await _find_goal_id(db, identifier)
        if goal_id is None:
            return False
        await db.execute("UPDATE goals SET status = ? WHERE id = ?", (new_status, goal_id))
        await db.commit()
        return True


async def delete_goal(identifier: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        goal_id = await _find_goal_id(db, identifier)
        if goal_id is None:
            return None
        cursor = await db.execute("SELECT title FROM goals WHERE id = ?", (goal_id,))
        row = await cursor.fetchone()
        await db.execute("UPDATE goals SET deleted_at = datetime('now') WHERE id = ?", (goal_id,))
        await db.commit()
        return row["title"]


async def add_habit(title: str, cadence: str | None = None, notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO habits (title, cadence, notes) VALUES (?, ?, ?)",
            (title, cadence, notes),
        )
        await db.commit()
        return title


async def delete_habit(identifier: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title FROM habits WHERE title = ? COLLATE NOCASE AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (identifier,),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id, title FROM habits WHERE title LIKE ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                (f"%{identifier}%",),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("UPDATE habits SET deleted_at = datetime('now') WHERE id = ?", (row["id"],))
        await db.commit()
        return row["title"]


async def dashboard_snapshot() -> dict:
    """Backs GET /personal/dashboard (the desktop tab)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, status, target_date, notes, created_at FROM goals "
            "WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        goals = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, title, cadence, notes, created_at FROM habits "
            "WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        habits = [dict(r) for r in await cursor.fetchall()]

    return {"goals": goals, "habits": habits}


async def summarize() -> str:
    """Plain-text snapshot, same style as operations_db.summarize_open_tasks()
    -- not currently injected into Frank's own system prompt (this stays
    display-only for now, no consult agent to feed), kept for parity with
    the other domains' summarize() functions and available if that
    changes later."""
    snapshot = await dashboard_snapshot()
    if not snapshot["goals"] and not snapshot["habits"]:
        return ""
    lines: list[str] = []
    if snapshot["goals"]:
        active = [g for g in snapshot["goals"] if g["status"] == "active"]
        lines.append(f"Goals ({len(active)} active of {len(snapshot['goals'])} total):")
        for g in active:
            due = f", target {g['target_date']}" if g["target_date"] else ""
            lines.append(f"  - {g['title']}{due}")
    if snapshot["habits"]:
        lines.append(f"Habits tracked ({len(snapshot['habits'])}):")
        for h in snapshot["habits"]:
            cadence = f" ({h['cadence']})" if h["cadence"] else ""
            lines.append(f"  - {h['title']}{cadence}")
    return "\n".join(lines)
