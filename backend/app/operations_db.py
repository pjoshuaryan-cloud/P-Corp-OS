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
        # Migration path: tasks existed before deleted_at did. Real gap
        # found 2026-08-10: a test task (bad due date, never real) had no
        # way to be removed -- only add_task/update_task_status existed,
        # and marking a test row "done" would have been dishonest. Soft
        # delete, not a real DELETE, same reasoning as memory_records'
        # deleted_at -- keeps delete_task in SECURITY.md's "Regular"
        # auto-allowed tier (reversible), not "needs confirmation."
        cursor = await db.execute("PRAGMA table_info(tasks)")
        columns = {row[1] async for row in cursor}
        if "deleted_at" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN deleted_at TEXT")
        await db.commit()


async def add_task(title: str, area: str | None = None, due_date: str | None = None, notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tasks (title, area, due_date, notes) VALUES (?, ?, ?, ?)",
            (title, area, due_date, notes),
        )
        await db.commit()
        return title


async def _find_task_id(db: aiosqlite.Connection, identifier: str) -> int | None:
    # Shared by update_task_status/delete_task -- exact title match
    # (case-insensitive), then substring, most recent first. Frank
    # doesn't see raw task IDs, same reasoning as memory's forget-by-title.
    cursor = await db.execute(
        "SELECT id FROM tasks WHERE title = ? COLLATE NOCASE AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (identifier,),
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await db.execute(
            "SELECT id FROM tasks WHERE title LIKE ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (f"%{identifier}%",),
        )
        row = await cursor.fetchone()
    return row["id"] if row else None


async def update_task_status(identifier: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        task_id = await _find_task_id(db, identifier)
        if task_id is None:
            return False
        await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
        await db.commit()
        return True


async def delete_task(identifier: str) -> str | None:
    """Soft delete -- for tasks that shouldn't have existed at all (test
    data, a mistaken entry), distinct from update_task_status's "done"/
    "blocked"/etc., which is for tasks that genuinely happened. Returns
    the deleted task's real title (so Frank can confirm what happened),
    or None if nothing matched."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        task_id = await _find_task_id(db, identifier)
        if task_id is None:
            return None
        cursor = await db.execute("SELECT title FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        await db.execute("UPDATE tasks SET deleted_at = datetime('now') WHERE id = ?", (task_id,))
        await db.commit()
        return row["title"]


async def list_open_tasks() -> list[dict]:
    """Structured form of the same data summarize_open_tasks() formats as
    text -- for the real GET /operations/tasks endpoint (the new "Agents"
    nav section), not the system-prompt block."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, status, area, due_date, notes, created_at FROM tasks "
            "WHERE status != 'done' AND deleted_at IS NULL ORDER BY id DESC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "area": row["area"],
                "due_date": row["due_date"],
                "notes": row["notes"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def summarize_open_tasks() -> str:
    """Fine to load in full every turn at this scale -- same reasoning as
    memory_records and Alpha Mode Media's snapshot; revisit if this ever
    grows large enough to need real filtering/ranking."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title, area, due_date, notes FROM tasks WHERE status != 'done' AND deleted_at IS NULL ORDER BY id"
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
