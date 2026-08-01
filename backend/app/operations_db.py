"""
General, cross-business task tracking — the concrete, trackable-over-time
slice of the Operations Agent's responsibilities (SOPs, workflow advice,
project planning, bottleneck-spotting, and automation suggestions stay
purely conversational for now; see operations_agent.py). Confirmed
decision (2026-07-31): tasks aren't scoped to any one business (not tied
to Alpha Mode Media's clients/projects) — genuinely general, spanning
whatever Joshua is actually working on across all of his businesses.

Its own SQLite file (operations.db), same "genuinely separate domain"
reasoning already applied to alpha_mode.db — not commingled with
pcorp.db's conversations/memory, and not merged into Alpha Mode Media's
own data either, since tasks cut across all businesses, not just one.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "operations.db"


async def init_operations_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                area TEXT,
                due_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def add_task(title: str, area: str | None = None, due_date: str | None = None, notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tasks (title, area, due_date, notes) VALUES (?, ?, ?, ?)",
            (title, area, due_date, notes),
        )
        await db.commit()
        return title


async def update_task_status(identifier: str, new_status: str) -> bool:
    """Matches by title (exact, then substring), most recent first — Frank
    doesn't see raw task IDs, same reasoning as memory's forget-by-title."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id FROM tasks WHERE title = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (identifier,)
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id FROM tasks WHERE title LIKE ? ORDER BY id DESC LIMIT 1", (f"%{identifier}%",)
            )
            row = await cursor.fetchone()
        if row is None:
            return False
        await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, row["id"]))
        await db.commit()
        return True


async def summarize_open_tasks() -> str:
    """Fine to load in full every turn at this scale -- same reasoning as
    memory_records and Alpha Mode Media's snapshot; revisit if this ever
    grows large enough to need real filtering/ranking."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title, area, due_date, notes FROM tasks WHERE status != 'done' ORDER BY id"
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""
        lines = ["Open tasks:"]
        for row in rows:
            area = f" [{row['area']}]" if row["area"] else ""
            due = f", due {row['due_date']}" if row["due_date"] else ""
            notes = f" — {row['notes']}" if row["notes"] else ""
            lines.append(f"  - {row['title']}{area}{due}{notes}")
        return "\n".join(lines)
