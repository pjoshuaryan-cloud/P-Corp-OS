"""
First real persistence in the backend — a single, ever-continuing
conversation (confirmed decision: not multiple conversation threads, per
"there is only ever one Frank"). Deliberately just a messages table, no
conversations table at all — a multi-conversation schema would be premature
complexity for a model we just decided against.

Deliberately NOT here yet: typed "memory records" (facts/preferences Frank
retains long-term, mirroring the user/feedback/project/reference scheme
MEMORY_SYSTEM.md flagged), semantic/vector search, and any context-window
management for when this single conversation gets very long. All real, all
separate, later work — this just proves conversation persistence itself.
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
