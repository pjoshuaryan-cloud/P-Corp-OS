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

`deleted_at` is a soft-delete, not a real DELETE — "forgetting" (app/memory.py's
`forget_memory` tool, or a manual delete in the UI) marks a record as no
longer active rather than destroying it. Reversible in principle (matches
SECURITY.md's "regular" tier reasoning for both save_memory and
forget_memory), and gives a rudimentary audit trail for free — the row and
its original content still exist, just excluded from what Frank sees and
what the UI shows. "Versioning" is deliberately just forget-then-resave, not
a separate update mechanism or version-history schema — no evidence yet that
reviewing historical versions matters enough to justify that complexity.

Deliberately NOT here yet: semantic/vector search over memory_records, an
"undo"/view-forgotten-records UI, and any context-window management for a
single conversation that gets very long.
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
        # Migration path: messages existed before image_path did (2026-08-05,
        # image upload support). Nullable -- most messages have no image.
        # Stores a filename under data/attachments/, not the image bytes
        # themselves -- keeps this TEXT column cheap regardless of image size.
        if "image_path" not in columns:
            await db.execute("ALTER TABLE messages ADD COLUMN image_path TEXT")

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

        # Migration path: app_state existed before Focus Lock's objective
        # columns did (2026-08-10). Nullable -- no objective set is a real,
        # honest state (shown as an empty state in the UI), not an error.
        cursor = await db.execute("PRAGMA table_info(app_state)")
        columns = {row[1] async for row in cursor}
        if "current_objective" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN current_objective TEXT")
            await db.execute("ALTER TABLE app_state ADD COLUMN objective_set_at TEXT")

        # Migration path: app_state existed before "The Brief"'s (2026-08-20)
        # last-viewed tracking did. Nullable -- never viewed is a real,
        # honest state (app/brief.py treats it as "show everything," not
        # an error), same reasoning as objective_set_at above.
        if "last_brief_viewed_at" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN last_brief_viewed_at TEXT")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK (type IN ('user', 'feedback', 'project', 'reference')),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                sensitive INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        # Migration path: memory_records existed before deleted_at did.
        cursor = await db.execute("PRAGMA table_info(memory_records)")
        columns = {row[1] async for row in cursor}
        if "deleted_at" not in columns:
            await db.execute("ALTER TABLE memory_records ADD COLUMN deleted_at TEXT")

        # Decision Journal (2026-08-10) -- lives alongside memory_records
        # rather than its own SQLite file: this is core Frank knowledge
        # like memory, not a separate-retention-pattern concern like
        # audit.db/automations.db. Capture-only first pass, same shape as
        # audit logging's first pass -- reasoning/alternatives are
        # optional since not every decision has a fleshed-out "why" worth
        # recording, and this shouldn't create friction that discourages
        # logging anything at all.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision TEXT NOT NULL,
                reasoning TEXT,
                alternatives TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Memory Graph (2026-08-10) -- linking-only first pass: an edge
        # table over the two existing capture tables (memory_records,
        # decisions). from_type/to_type keep it a plain column pair
        # rather than two separate FK schemes per combination, since more
        # linkable record types (tasks, projects) are a plausible future
        # addition and shouldn't need a schema change to add.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_type TEXT NOT NULL CHECK (from_type IN ('memory', 'decision')),
                from_id INTEGER NOT NULL,
                to_type TEXT NOT NULL CHECK (to_type IN ('memory', 'decision')),
                to_id INTEGER NOT NULL,
                relationship TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Shadow Mode (2026-08-10) -- passive activity awareness, scoped
        # to app name only (never window titles, URLs, or file contents).
        # One row per frontmost-app change, not a fixed-interval poll --
        # ActivityTracker.swift only calls POST /activity/log when the
        # frontmost app actually changes, so this is already a segmented
        # history, not raw samples.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Legacy Vault (2026-08-10) -- succession/emergency info meant for
        # someone else if something happens to Joshua (instructions,
        # account locations, who to contact), never credentials/passwords
        # themselves. Deliberately its own table, not a memory_records
        # type: entries here must never get folded into build_memory_block
        # and casually surface in an unrelated conversation the way
        # regular memories do -- see app/legacy_vault.py's docstring.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS legacy_vault (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
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


async def get_focus_objective() -> dict:
    """Focus Lock (2026-08-10) -- a real, settable "current objective,"
    deliberately scoped to just this: no on/off mode, no context-switch
    detection, no automatic deprioritization of anything. Joshua can
    always override by asking Frank to change it (or a future direct UI
    affordance) -- there's no enforcement mechanism to override."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT current_objective, objective_set_at FROM app_state WHERE id = 1")
        row = await cursor.fetchone()
        return {"objective": row["current_objective"], "set_at": row["objective_set_at"]}


async def set_focus_objective(objective: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE app_state SET current_objective = ?, objective_set_at = datetime('now') WHERE id = 1",
            (objective,),
        )
        await db.commit()


async def get_brief_last_viewed_at() -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_brief_viewed_at FROM app_state WHERE id = 1")
        (last_viewed,) = await cursor.fetchone()
        return last_viewed


async def mark_brief_viewed() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET last_brief_viewed_at = datetime('now') WHERE id = 1")
        await db.commit()


async def create_new_conversation() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO conversations DEFAULT VALUES")
        new_id = cursor.lastrowid
        await db.execute("UPDATE app_state SET active_conversation_id = ? WHERE id = 1", (new_id,))
        await db.commit()
        return new_id


async def list_conversations(query: str | None = None) -> list[dict]:
    # Excludes conversations with zero messages — an abandoned "new chat"
    # click (started but never used) would otherwise sit above real
    # conversations in the newest-first ordering, burying the ones that
    # actually matter. Confirmed real: this is exactly what made an actual
    # past conversation hard to find after a couple of empty test chats.
    #
    # Sorted by last_message_at (most recent activity), not created_at
    # (when the conversation was first started) — a conversation reopened
    # and continued today should surface above one merely created more
    # recently but never touched since. `query`, when given, searches real
    # message CONTENT across the whole conversation (not just the preview),
    # so "find where I discussed X" actually works, not just matching
    # against whatever happened to be the first message.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = """
            SELECT
                c.id,
                c.created_at,
                (SELECT content FROM messages m WHERE m.conversation_id = c.id
                 AND m.role = 'user' ORDER BY m.id ASC LIMIT 1) AS first_message,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
                (SELECT MAX(created_at) FROM messages m WHERE m.conversation_id = c.id) AS last_message_at
            FROM conversations c
            WHERE EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
        """
        params: list[str] = []
        if query:
            sql += """
                AND EXISTS (
                    SELECT 1 FROM messages m2
                    WHERE m2.conversation_id = c.id AND m2.content LIKE ?
                )
            """
            params.append(f"%{query}%")
        sql += " ORDER BY last_message_at DESC"

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "first_message": row["first_message"],
                "message_count": row["message_count"],
                "last_message_at": row["last_message_at"],
            }
            for row in rows
        ]


async def load_history(conversation_id: int) -> list[dict]:
    # image_path is included for the UI (GET /history — the "📎 image
    # attached" placeholder for a reopened old conversation) but is
    # deliberately stripped back out before this shape reaches Claude's own
    # message history (see main.py's websocket handler) -- a reopened old
    # image is shown, not re-sent as real vision context every reload,
    # confirmed decision 2026-08-05 (cost vs. Frank genuinely "re-seeing"
    # it every time).
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, image_path FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"], "image_path": row["image_path"]} for row in rows]


async def save_message(conversation_id: int, role: str, content: str, image_path: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, image_path) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, image_path),
        )
        await db.commit()


async def load_memory_records() -> list[dict]:
    # Excludes forgotten (soft-deleted) records — both for the system-prompt
    # memory block (app/memory.py's build_memory_block) and the UI list.
    # Forgetting something should mean it stops influencing Frank, not just
    # disappears from a list.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, type, title, content, sensitive, created_at "
            "FROM memory_records WHERE deleted_at IS NULL ORDER BY id ASC"
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


async def log_decision(decision: str, reasoning: str | None = None, alternatives: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO decisions (decision, reasoning, alternatives) VALUES (?, ?, ?)",
            (decision, reasoning, alternatives),
        )
        await db.commit()


async def list_decisions(limit: int = 100) -> list[dict]:
    # Not wired to any endpoint or tool yet -- capture-only first pass,
    # same reasoning as audit_db.list_recent_calls: get real data flowing
    # before deciding what surfaces it (a UI view, a recall tool, both).
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, decision, reasoning, alternatives, created_at "
            "FROM decisions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def _resolve_memory_id(title: str) -> tuple[int, str] | None:
    # Same exact-then-substring, most-recent-first matching as
    # forget_memory_by_title -- Frank never sees a memory's raw row ID.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title FROM memory_records WHERE deleted_at IS NULL AND title = ? ORDER BY id DESC LIMIT 1",
            (title,),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id, title FROM memory_records WHERE deleted_at IS NULL AND title LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{title}%",),
            )
            row = await cursor.fetchone()
        return (row["id"], row["title"]) if row else None


async def _resolve_decision_id(text: str) -> tuple[int, str] | None:
    # Same matching as _resolve_memory_id, against a decision's own
    # wording instead of a title -- decisions have no separate title field.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, decision FROM decisions WHERE decision = ? ORDER BY id DESC LIMIT 1",
            (text,),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id, decision FROM decisions WHERE decision LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{text}%",),
            )
            row = await cursor.fetchone()
        return (row["id"], row["decision"]) if row else None


async def link_records(from_type: str, from_text: str, to_type: str, to_text: str, relationship: str) -> str | None:
    """Resolves both sides by the text Frank already has (a memory's title
    or a decision's own wording), then records the edge. Returns a
    human-readable confirmation of what got linked, or None if either
    side couldn't be resolved."""
    resolve_from = _resolve_memory_id if from_type == "memory" else _resolve_decision_id
    resolve_to = _resolve_memory_id if to_type == "memory" else _resolve_decision_id
    from_match = await resolve_from(from_text)
    to_match = await resolve_to(to_text)
    if from_match is None or to_match is None:
        return None
    from_id, from_label = from_match
    to_id, to_label = to_match
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO memory_links (from_type, from_id, to_type, to_id, relationship) VALUES (?, ?, ?, ?, ?)",
            (from_type, from_id, to_type, to_id, relationship),
        )
        await db.commit()
    return f'"{from_label}" {relationship} "{to_label}"'


async def log_activity(app_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO activity_log (app_name) VALUES (?)", (app_name,))
        await db.commit()


async def get_recent_activity(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT app_name, started_at FROM activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def save_legacy_entry(title: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO legacy_vault (title, content) VALUES (?, ?)", (title, content))
        await db.commit()


async def list_legacy_entries() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, content, created_at FROM legacy_vault WHERE deleted_at IS NULL ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def forget_legacy_entry(title: str) -> str | None:
    # Same exact-then-substring, most-recent-first matching as
    # forget_memory_by_title -- Frank never sees a vault entry's raw row ID.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title FROM legacy_vault WHERE deleted_at IS NULL AND title = ? ORDER BY id DESC LIMIT 1",
            (title,),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id, title FROM legacy_vault WHERE deleted_at IS NULL AND title LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{title}%",),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("UPDATE legacy_vault SET deleted_at = datetime('now') WHERE id = ?", (row["id"],))
        await db.commit()
        return row["title"]


async def forget_memory_by_id(memory_id: int) -> bool:
    # Manual path (FrankView's delete affordance) — the UI already has the
    # real ID, no title-matching ambiguity to resolve.
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE memory_records SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def forget_memory_by_title(title: str) -> str | None:
    # Frank's forget_memory tool path — he only has the title he originally
    # gave it, not the row ID (never surfaced to him). Exact match preferred;
    # falls back to a substring match, most recent first, since he may not
    # recall the exact original wording. Returns the real title that got
    # forgotten (so he can confirm what happened), or None if nothing matched.
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title FROM memory_records WHERE deleted_at IS NULL AND title = ? ORDER BY id DESC LIMIT 1",
            (title,),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await db.execute(
                "SELECT id, title FROM memory_records WHERE deleted_at IS NULL AND title LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{title}%",),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("UPDATE memory_records SET deleted_at = datetime('now') WHERE id = ?", (row["id"],))
        await db.commit()
        return row["title"]
