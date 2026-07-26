"""
Persistence for the backend: three tables, three different lifecycles.

`conversations` + `messages` — reopened from the earlier "one continuous
conversation, no conversations table" decision, based on real usage: once
Joshua actually used the chat thread, he wanted to start fresh ones. The
reconciliation, not a reversal — the thing that actually makes "there is
only ever one Frank" (FOUNDER_BRIEF.md) true is durable memory, not an
unbroken transcript. `memory_records` already carries identity/continuity
forward; conversations can now start and end like they do in any normal
chat app.

`app_state` tracks which conversation is active. Originally this was just
"whichever conversation is newest" (no separate state needed) — revisited
almost immediately once Joshua asked how to get back to an older
conversation: reopening one has to make IT active without needing to be the
newest row, so "newest" stopped being able to mean "active." A single-row
table is the simplest honest fix — one authoritative value, no ambiguity
about which of several flags might be stale.

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
context-window management for a single conversation that gets very long.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "pcorp.db"


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM conversations")
        (conversation_count,) = await cursor.fetchone()
        if conversation_count == 0:
            await db.execute("INSERT INTO conversations DEFAULT VALUES")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Migration path: messages existed before conversation_id did.
        # Backfill every pre-existing row to conversation #1 — correct by
        # construction, since there was only ever one conversation before
        # this change (the earlier "one continuous conversation" model).
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = {row[1] async for row in cursor}
        if "conversation_id" not in columns:
            await db.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER NOT NULL DEFAULT 1")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                active_conversation_id INTEGER NOT NULL REFERENCES conversations(id)
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM app_state")
        (state_count,) = await cursor.fetchone()
        if state_count == 0:
            # Bootstrap to whatever was newest under the old "active =
            # newest" model, so existing installs don't silently jump to a
            # different conversation the first time this runs.
            cursor = await db.execute("SELECT id FROM conversations ORDER BY id DESC LIMIT 1")
            (newest_id,) = await cursor.fetchone()
            await db.execute("INSERT INTO app_state (id, active_conversation_id) VALUES (1, ?)", (newest_id,))

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


async def get_active_conversation_id() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT active_conversation_id FROM app_state WHERE id = 1")
        (conversation_id,) = await cursor.fetchone()
        return conversation_id


async def set_active_conversation(conversation_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET active_conversation_id = ? WHERE id = 1", (conversation_id,))
        await db.commit()


async def create_new_conversation() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO conversations DEFAULT VALUES")
        new_id = cursor.lastrowid
        await db.execute("UPDATE app_state SET active_conversation_id = ? WHERE id = 1", (new_id,))
        await db.commit()
        return new_id


async def list_conversations() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                c.id,
                c.created_at,
                (SELECT content FROM messages m WHERE m.conversation_id = c.id
                 AND m.role = 'user' ORDER BY m.id ASC LIMIT 1) AS first_message,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY c.id DESC
            """
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "first_message": row["first_message"],
                "message_count": row["message_count"],
            }
            for row in rows
        ]


async def load_history(conversation_id: int) -> list[dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]


async def save_message(conversation_id: int, role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )
        await db.commit()


async def load_memory_records() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, type, title, content, sensitive, created_at "
            "FROM memory_records ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
                "content": row["content"],
                "sensitive": bool(row["sensitive"]),
                "created_at": row["created_at"],
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
