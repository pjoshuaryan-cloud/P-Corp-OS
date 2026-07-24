"""
Persistence for the backend: two tables, two different lifecycles.

`messages` is the single, ever-continuing conversation (confirmed decision:
not multiple conversation threads, per "there is only ever one Frank") —
deliberately just one table, no conversations table, since a multi-
conversation schema would be premature complexity for a model already
decided against.

`memory_records` is durable, typed memory — facts/preferences/context Frank
retains across conversations, not tied to any single exchange. Uses the same
four types (user/feedback/project/reference) MEMORY_SYSTEM.md flagged,
written via a single hardcoded `save_memory` tool (see app/memory.py), not
free-form agent access. `sensitive` is a plain flag, not encryption — there's
no sync yet, so nothing new leaves the device; it exists so the eventual
encrypt-before-sync work (flagged in TECH_STACK.md) has something to filter
on later.

Deliberately NOT here yet: semantic/vector search over memory_records,
forgetting/versioning (no auto-expiry — manual update/delete only), and any
context-window management for when the single conversation gets very long.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "pcorp.db"


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK (type IN ('user', 'feedback', 'project', 'reference')),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                sensitive INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def load_history() -> list[dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content FROM messages ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]


async def save_message(role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (role, content) VALUES (?, ?)",
            (role, content),
        )
        await db.commit()


async def load_memory_records() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT type, title, content, sensitive FROM memory_records ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "type": row["type"],
                "title": row["title"],
                "content": row["content"],
                "sensitive": bool(row["sensitive"]),
            }
            for row in rows
        ]


async def save_memory_record(
    type: str, title: str, content: str, sensitive: bool = False
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO memory_records (type, title, content, sensitive) VALUES (?, ?, ?, ?)",
            (type, title, content, int(sensitive)),
        )
        await db.commit()
