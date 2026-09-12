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

Dual-backend dispatchers (2026-09-10, iPhone independence pass): every
function gains a postgres_conn: Any = None parameter, same pattern proven
in personal_db.py/operations_db.py -- SQLite body renamed _<name>_sqlite,
untouched; a new _<name>_postgres sibling added; the public function
dispatches on whether postgres_conn is not None. pcorp is the highest-
priority domain to convert since it holds conversation history and
memory -- without it, a cloud-hosted Frank has no context at all.
"""

import json
from pathlib import Path
from typing import Any

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
        # Migration path: multi-attach documents (2026-09-05) generalize
        # single-image_path to N attachments of any kind. New column, not
        # a rework of image_path -- old rows keep reading correctly via
        # image_path (never written again going forward), new rows write
        # this instead. Nullable -- most messages have no attachments.
        # JSON-encoded list of {filename, original_name, media_type} --
        # filenames under data/attachments/, never the bytes themselves,
        # same reasoning as image_path above.
        if "attachments" not in columns:
            await db.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")

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

        # Migration path: app_state existed before Connected Apps' Gmail
        # sync tracking did (2026-09-04). Nullable -- Gmail has only ever
        # synced on demand (email_tools.py's search_emails-style tool
        # call), never on a periodic tick like Calendar's, so "never
        # synced yet" is a real, honest state for a fresh install or one
        # where that tool has simply never run -- not an error to hide.
        if "last_gmail_sync_at" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN last_gmail_sync_at TEXT")

        # Migration path: app_state existed before the reliability pass's
        # credit-exhaustion tracking did (2026-09-07). Nullable -- NULL means
        # credits are fine (the real, common state), a timestamp means
        # Frank's last Anthropic call failed with a real billing error and
        # hasn't succeeded since. Persisted (not in-memory) deliberately: it
        # must survive a process restart -- including the reliability pass's
        # own hang-watchdog restart -- so the Situation Room alert doesn't go
        # silent mid-outage exactly when nobody's watching.
        if "credits_exhausted_since" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN credits_exhausted_since TEXT")

        # Migration path: app_state existed before Stage 8's Mac Local Node
        # liveness signal did (2026-09-10). Nullable -- "never seen" is a
        # real, honest state (a fresh install, or before this shipped), not
        # an error. Updated by both the dedicated /local-node/heartbeat
        # route and /activity/log's existing handler -- either one is real
        # evidence the Local Node process is alive.
        if "local_node_last_seen_at" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN local_node_last_seen_at TEXT")

        # Migration path: app_state existed before Google's OAuth grant
        # became shared, cloud-visible state (2026-09-11). Previously
        # lived only in a local JSON file on the Mac's disk
        # (google_oauth.py's own TOKEN_PATH) -- real gap found live: a
        # phone pointed at the cloud instance had no way to see it at
        # all, so Gmail/Calendar always read as disconnected there.
        # `google_oauth.py`'s SQLite/file path is untouched; these
        # columns back the new Postgres path only. `google_token_expires_at`
        # stores the same raw epoch-seconds float google_oauth.py's own
        # `time.time() + expires_in` already produces -- deliberately not
        # a formatted timestamp string, sidestepping the exact class of
        # date-separator bug just found and fixed in get_price_change.
        if "google_refresh_token" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN google_refresh_token TEXT")
            await db.execute("ALTER TABLE app_state ADD COLUMN google_access_token TEXT")
            await db.execute("ALTER TABLE app_state ADD COLUMN google_token_expires_at REAL")

        # Migration path: app_state existed before HF Markets' live P&L
        # became shared, cloud-visible state (2026-09-12). Previously only
        # ever read straight from hf_markets_client.py's local MT5 file --
        # real gap found live: a phone pointed at the cloud instance saw
        # only the once-a-day snapshot, never live floating P&L, since
        # that file only exists on Josh's Mac disk. These columns back the
        # new Postgres push-from-Mac path only; hf_markets_client.py's own
        # local-file read is untouched and still wins whenever it's
        # actually available (i.e. running on the Mac itself).
        # hf_markets_live_updated_at is an opaque passthrough of whatever
        # the MT5 Expert Advisor's own JSON puts there -- never parsed,
        # same as get_hf_markets_live_status() already does today.
        # hf_markets_live_synced_at is this server's own UTC write time
        # (same naive-UTC-string style as local_node_last_seen_at, not a
        # native timestamptz) -- what staleness is actually measured
        # against, not the EA's own clock.
        if "hf_markets_live_balance" not in columns:
            await db.execute("ALTER TABLE app_state ADD COLUMN hf_markets_live_balance REAL")
            await db.execute("ALTER TABLE app_state ADD COLUMN hf_markets_live_equity REAL")
            await db.execute("ALTER TABLE app_state ADD COLUMN hf_markets_live_currency TEXT")
            await db.execute("ALTER TABLE app_state ADD COLUMN hf_markets_live_updated_at TEXT")
            await db.execute("ALTER TABLE app_state ADD COLUMN hf_markets_live_synced_at TEXT")

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


async def get_active_conversation_id(postgres_conn: Any = None) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT active_conversation_id FROM pcorp.app_state WHERE id = 1")
            (conversation_id,) = await cur.fetchone()
            return conversation_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT active_conversation_id FROM app_state WHERE id = 1")
        (conversation_id,) = await cursor.fetchone()
        return conversation_id


async def set_active_conversation(conversation_id: int, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE pcorp.app_state SET active_conversation_id = %s WHERE id = 1", (conversation_id,)
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET active_conversation_id = ? WHERE id = 1", (conversation_id,))
        await db.commit()


async def get_focus_objective(postgres_conn: Any = None) -> dict:
    """Focus Lock (2026-08-10) -- a real, settable "current objective,"
    deliberately scoped to just this: no on/off mode, no context-switch
    detection, no automatic deprioritization of anything. Joshua can
    always override by asking Frank to change it (or a future direct UI
    affordance) -- there's no enforcement mechanism to override."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT current_objective, objective_set_at FROM pcorp.app_state WHERE id = 1")
            row = await cur.fetchone()
            return {"objective": row[0], "set_at": str(row[1]) if row[1] is not None else None}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT current_objective, objective_set_at FROM app_state WHERE id = 1")
        row = await cursor.fetchone()
        return {"objective": row["current_objective"], "set_at": row["objective_set_at"]}


async def set_focus_objective(objective: str, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE pcorp.app_state SET current_objective = %s, objective_set_at = (now() AT TIME ZONE 'utc') WHERE id = 1",
                (objective,),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE app_state SET current_objective = ?, objective_set_at = datetime('now') WHERE id = 1",
            (objective,),
        )
        await db.commit()


async def get_brief_last_viewed_at(postgres_conn: Any = None) -> str | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT last_brief_viewed_at FROM pcorp.app_state WHERE id = 1")
            (last_viewed,) = await cur.fetchone()
            return str(last_viewed) if last_viewed is not None else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_brief_viewed_at FROM app_state WHERE id = 1")
        (last_viewed,) = await cursor.fetchone()
        return last_viewed


async def mark_brief_viewed(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE pcorp.app_state SET last_brief_viewed_at = (now() AT TIME ZONE 'utc') WHERE id = 1")
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET last_brief_viewed_at = datetime('now') WHERE id = 1")
        await db.commit()


async def get_last_gmail_sync_at(postgres_conn: Any = None) -> str | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT last_gmail_sync_at FROM pcorp.app_state WHERE id = 1")
            (last_synced,) = await cur.fetchone()
            return str(last_synced) if last_synced is not None else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_gmail_sync_at FROM app_state WHERE id = 1")
        (last_synced,) = await cursor.fetchone()
        return last_synced


async def mark_gmail_synced(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE pcorp.app_state SET last_gmail_sync_at = (now() AT TIME ZONE 'utc') WHERE id = 1")
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET last_gmail_sync_at = datetime('now') WHERE id = 1")
        await db.commit()


async def get_google_oauth_tokens_postgres(conn: Any) -> dict | None:
    """Postgres-only, deliberately no SQLite sibling here (unlike every
    other function in this file) -- the SQLite-mode equivalent of this
    data isn't a row in this table at all, it's google_oauth.py's own
    pre-existing local JSON file (TOKEN_PATH), which stays completely
    untouched. This function backs only the new cloud-shared path, same
    asymmetry calendar_db.py already has between its AppleScript source
    (Mac-only) and its dispatched cache table."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT google_refresh_token, google_access_token, google_token_expires_at "
            "FROM pcorp.app_state WHERE id = 1"
        )
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    return {"refresh_token": row[0], "access_token": row[1], "expires_at": row[2]}


async def set_google_oauth_tokens_postgres(
    conn: Any, refresh_token: str, access_token: str, expires_at: float
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE pcorp.app_state SET google_refresh_token = %s, google_access_token = %s, "
            "google_token_expires_at = %s WHERE id = 1",
            (refresh_token, access_token, expires_at),
        )
    await conn.commit()


async def get_hf_markets_live_status_postgres(conn: Any) -> dict | None:
    """Postgres-only, same asymmetry as get_google_oauth_tokens_postgres
    above -- the SQLite-mode equivalent isn't a row in this table at all,
    it's hf_markets_client.py's own local MT5 file, untouched. Raw getter
    only: returns whatever was last pushed plus when, with no staleness
    opinion of its own -- app/finance.py's get_hf_markets_live_status_for_dashboard
    is where "is this too old to trust" actually gets decided, same split
    as get_local_node_last_seen_at (raw) vs local_node_online (main.py's
    own freshness check) already established for the same kind of value."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT hf_markets_live_balance, hf_markets_live_equity, hf_markets_live_currency, "
            "hf_markets_live_updated_at, hf_markets_live_synced_at FROM pcorp.app_state WHERE id = 1"
        )
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    return {
        "balance": row[0],
        "equity": row[1],
        "currency": row[2],
        "updated_at": row[3],
        "synced_at": row[4],
    }


async def set_hf_markets_live_status_postgres(
    conn: Any, balance: float, equity: float, currency: str, updated_at: str | None
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE pcorp.app_state SET hf_markets_live_balance = %s, hf_markets_live_equity = %s, "
            "hf_markets_live_currency = %s, hf_markets_live_updated_at = %s, "
            "hf_markets_live_synced_at = (now() AT TIME ZONE 'utc') WHERE id = 1",
            (balance, equity, currency, updated_at),
        )
    await conn.commit()


async def get_credits_exhausted_since(postgres_conn: Any = None) -> str | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT credits_exhausted_since FROM pcorp.app_state WHERE id = 1")
            (exhausted_since,) = await cur.fetchone()
            return str(exhausted_since) if exhausted_since is not None else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT credits_exhausted_since FROM app_state WHERE id = 1")
        (exhausted_since,) = await cursor.fetchone()
        return exhausted_since


async def set_credits_exhausted(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        # now()::text cast required -- COALESCE needs its arguments to be
        # the same type (credits_exhausted_since is TEXT, matching SQLite);
        # a plain assignment (column = now()) casts implicitly, but
        # COALESCE's own type resolution happens before that, found live
        # here when a plain now() raised DatatypeMismatch.
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE pcorp.app_state SET credits_exhausted_since = COALESCE(credits_exhausted_since, (now() AT TIME ZONE 'utc')::text) "
                "WHERE id = 1"
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE app_state SET credits_exhausted_since = COALESCE(credits_exhausted_since, datetime('now')) WHERE id = 1"
        )
        await db.commit()


async def clear_credits_exhausted(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE pcorp.app_state SET credits_exhausted_since = NULL WHERE id = 1")
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET credits_exhausted_since = NULL WHERE id = 1")
        await db.commit()


async def get_local_node_last_seen_at(postgres_conn: Any = None) -> str | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT local_node_last_seen_at FROM pcorp.app_state WHERE id = 1")
            (last_seen,) = await cur.fetchone()
            return str(last_seen) if last_seen is not None else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT local_node_last_seen_at FROM app_state WHERE id = 1")
        (last_seen,) = await cursor.fetchone()
        return last_seen


async def mark_local_node_seen(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE pcorp.app_state SET local_node_last_seen_at = (now() AT TIME ZONE 'utc') WHERE id = 1")
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_state SET local_node_last_seen_at = datetime('now') WHERE id = 1")
        await db.commit()


async def create_new_conversation(postgres_conn: Any = None) -> int:
    if postgres_conn is not None:
        # created_at supplied explicitly -- same missing-DEFAULT gap found
        # repeatedly this migration (Stage 3's replicate.py doesn't carry
        # SQLite DEFAULT clauses into the Postgres DDL).
        async with postgres_conn.cursor() as cur:
            await cur.execute("INSERT INTO pcorp.conversations (created_at) VALUES ((now() AT TIME ZONE 'utc')) RETURNING id")
            (new_id,) = await cur.fetchone()
            await cur.execute("UPDATE pcorp.app_state SET active_conversation_id = %s WHERE id = 1", (new_id,))
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO conversations DEFAULT VALUES")
        new_id = cursor.lastrowid
        await db.execute("UPDATE app_state SET active_conversation_id = ? WHERE id = 1", (new_id,))
        await db.commit()
        return new_id


async def list_conversations(query: str | None = None, postgres_conn: Any = None) -> list[dict]:
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
    if postgres_conn is not None:
        sql = """
            SELECT
                c.id,
                c.created_at,
                (SELECT content FROM pcorp.messages m WHERE m.conversation_id = c.id
                 AND m.role = 'user' ORDER BY m.id ASC LIMIT 1) AS first_message,
                (SELECT COUNT(*) FROM pcorp.messages m WHERE m.conversation_id = c.id) AS message_count,
                (SELECT MAX(created_at) FROM pcorp.messages m WHERE m.conversation_id = c.id) AS last_message_at
            FROM pcorp.conversations c
            WHERE EXISTS (SELECT 1 FROM pcorp.messages m WHERE m.conversation_id = c.id)
        """
        params: list[Any] = []
        if query:
            # ILIKE, not LIKE -- same case-sensitivity fix already proven
            # necessary throughout this migration (SQLite's LIKE is
            # case-insensitive by default; Postgres's is not).
            sql += """
                AND EXISTS (
                    SELECT 1 FROM pcorp.messages m2
                    WHERE m2.conversation_id = c.id AND m2.content ILIKE %s
                )
            """
            params.append(f"%{query}%")
        sql += " ORDER BY last_message_at DESC"
        async with postgres_conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "created_at": str(r[1]) if r[1] is not None else None,
                    "first_message": r[2],
                    "message_count": r[3],
                    "last_message_at": str(r[4]) if r[4] is not None else None,
                }
                for r in rows
            ]
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
        params = []
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


async def load_history(conversation_id: int, postgres_conn: Any = None) -> list[dict]:
    # image_path/attachments are included for the UI (GET /history — the
    # "📎 image attached"/"N files attached" placeholder for a reopened old
    # conversation) but are deliberately stripped back out before this
    # shape reaches Claude's own message history (see main.py's websocket
    # handler) -- a reopened old attachment is shown, not re-sent as real
    # context every reload, confirmed decision 2026-08-05 (cost vs. Frank
    # genuinely "re-seeing" it every time), extended to all attachment
    # kinds 2026-09-05. `attachments` is only populated for messages sent
    # after that migration -- an older row has `image_path` set instead
    # (still read here, never re-written).
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT role, content, image_path, attachments FROM pcorp.messages "
                "WHERE conversation_id = %s ORDER BY id ASC",
                (conversation_id,),
            )
            rows = await cur.fetchall()
            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "image_path": r[2],
                    "attachments": json.loads(r[3]) if r[3] else None,
                }
                for r in rows
            ]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, image_path, attachments FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "image_path": row["image_path"],
                "attachments": json.loads(row["attachments"]) if row["attachments"] else None,
            }
            for row in rows
        ]


async def save_message(
    conversation_id: int,
    role: str,
    content: str,
    image_path: str | None = None,
    attachments: list[dict] | None = None,
    postgres_conn: Any = None,
) -> None:
    if postgres_conn is not None:
        # created_at supplied explicitly -- same missing-DEFAULT gap as
        # create_new_conversation above.
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.messages (conversation_id, role, content, image_path, attachments, created_at) "
                "VALUES (%s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (conversation_id, role, content, image_path, json.dumps(attachments) if attachments else None),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, image_path, attachments) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, image_path, json.dumps(attachments) if attachments else None),
        )
        await db.commit()


async def find_recent_attachment(conversation_id: int, name_hint: str, postgres_conn: Any = None) -> dict | None:
    """Resolves data_analysis.py's `source` argument to a real stored
    attachment dict ({filename, original_name, media_type}) -- the first
    query against messages.attachments beyond the reopened-conversation
    placeholder load_history already does. Mirrors joshx_db.py's own
    fuzzy-identifier convention: exact case-insensitive match first, then
    substring, scanned most-recent-message-first so a re-attached same-name
    file resolves to the newest copy. The matching itself is plain Python
    string comparison (not SQL LIKE), so no ILIKE fix is needed here --
    only the row-fetch mechanism differs between backends."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT attachments FROM pcorp.messages WHERE conversation_id = %s "
                "AND attachments IS NOT NULL ORDER BY id DESC",
                (conversation_id,),
            )
            rows = await cur.fetchall()
        candidates = [att for (attachments_json,) in rows for att in json.loads(attachments_json)]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT attachments FROM messages WHERE conversation_id = ? "
                "AND attachments IS NOT NULL ORDER BY id DESC",
                (conversation_id,),
            )
            rows = await cursor.fetchall()
        candidates = [att for row in rows for att in json.loads(row["attachments"])]

    needle = name_hint.strip().lower()
    for att in candidates:
        if att["original_name"].strip().lower() == needle:
            return att
    for att in candidates:
        if needle in att["original_name"].lower():
            return att
    return None


async def load_memory_records(postgres_conn: Any = None) -> list[dict]:
    # Excludes forgotten (soft-deleted) records — both for the system-prompt
    # memory block (app/memory.py's build_memory_block) and the UI list.
    # Forgetting something should mean it stops influencing Frank, not just
    # disappears from a list.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, type, title, content, sensitive, created_at "
                "FROM pcorp.memory_records WHERE deleted_at IS NULL ORDER BY id ASC"
            )
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "type": r[1],
                    "title": r[2],
                    "content": r[3],
                    "sensitive": bool(r[4]),
                    "created_at": str(r[5]) if r[5] is not None else None,
                }
                for r in rows
            ]
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
    type: str, title: str, content: str, sensitive: bool = False, postgres_conn: Any = None
) -> None:
    if postgres_conn is not None:
        # int(sensitive), not the raw bool -- sensitive is BIGINT in
        # Postgres (matching SQLite's INTEGER-as-boolean column via the
        # standard INTEGER->BIGINT type mapping); psycopg maps a Python
        # bool to Postgres boolean, which doesn't implicitly cast to
        # bigint, found live here as a real DatatypeMismatch.
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.memory_records (type, title, content, sensitive, created_at) "
                "VALUES (%s, %s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (type, title, content, int(sensitive)),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO memory_records (type, title, content, sensitive) VALUES (?, ?, ?, ?)",
            (type, title, content, int(sensitive)),
        )
        await db.commit()


async def log_decision(
    decision: str, reasoning: str | None = None, alternatives: str | None = None, postgres_conn: Any = None
) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.decisions (decision, reasoning, alternatives, created_at) "
                "VALUES (%s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (decision, reasoning, alternatives),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO decisions (decision, reasoning, alternatives) VALUES (?, ?, ?)",
            (decision, reasoning, alternatives),
        )
        await db.commit()


async def list_decisions(limit: int = 100, postgres_conn: Any = None) -> list[dict]:
    # Not wired to any endpoint or tool yet -- capture-only first pass,
    # same reasoning as audit_db.list_recent_calls: get real data flowing
    # before deciding what surfaces it (a UI view, a recall tool, both).
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, decision, reasoning, alternatives, created_at "
                "FROM pcorp.decisions ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "decision": r[1],
                    "reasoning": r[2],
                    "alternatives": r[3],
                    "created_at": str(r[4]) if r[4] is not None else None,
                }
                for r in rows
            ]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, decision, reasoning, alternatives, created_at "
            "FROM decisions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def _resolve_memory_id(title: str, postgres_conn: Any = None) -> tuple[int, str] | None:
    # Same exact-then-substring, most-recent-first matching as
    # forget_memory_by_title -- Frank never sees a memory's raw row ID.
    # ILIKE, not LIKE -- same case-sensitivity fix proven necessary
    # throughout this migration.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, title FROM pcorp.memory_records WHERE deleted_at IS NULL AND title ILIKE %s "
                "ORDER BY id DESC LIMIT 1",
                (title,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT id, title FROM pcorp.memory_records WHERE deleted_at IS NULL AND title ILIKE %s "
                    "ORDER BY id DESC LIMIT 1",
                    (f"%{title}%",),
                )
                row = await cur.fetchone()
            return (row[0], row[1]) if row else None
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


async def _resolve_decision_id(text: str, postgres_conn: Any = None) -> tuple[int, str] | None:
    # Same matching as _resolve_memory_id, against a decision's own
    # wording instead of a title -- decisions have no separate title field.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, decision FROM pcorp.decisions WHERE decision ILIKE %s ORDER BY id DESC LIMIT 1",
                (text,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT id, decision FROM pcorp.decisions WHERE decision ILIKE %s ORDER BY id DESC LIMIT 1",
                    (f"%{text}%",),
                )
                row = await cur.fetchone()
            return (row[0], row[1]) if row else None
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


async def link_records(
    from_type: str, from_text: str, to_type: str, to_text: str, relationship: str, postgres_conn: Any = None
) -> str | None:
    """Resolves both sides by the text Frank already has (a memory's title
    or a decision's own wording), then records the edge. Returns a
    human-readable confirmation of what got linked, or None if either
    side couldn't be resolved."""
    resolve_from = _resolve_memory_id if from_type == "memory" else _resolve_decision_id
    resolve_to = _resolve_memory_id if to_type == "memory" else _resolve_decision_id
    from_match = await resolve_from(from_text, postgres_conn)
    to_match = await resolve_to(to_text, postgres_conn)
    if from_match is None or to_match is None:
        return None
    from_id, from_label = from_match
    to_id, to_label = to_match
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.memory_links (from_type, from_id, to_type, to_id, relationship, created_at) "
                "VALUES (%s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (from_type, from_id, to_type, to_id, relationship),
            )
        await postgres_conn.commit()
        return f'"{from_label}" {relationship} "{to_label}"'
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO memory_links (from_type, from_id, to_type, to_id, relationship) VALUES (?, ?, ?, ?, ?)",
            (from_type, from_id, to_type, to_id, relationship),
        )
        await db.commit()
    return f'"{from_label}" {relationship} "{to_label}"'


async def log_activity(app_name: str, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.activity_log (app_name, started_at) VALUES (%s, (now() AT TIME ZONE 'utc'))", (app_name,)
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO activity_log (app_name) VALUES (?)", (app_name,))
        await db.commit()


async def get_recent_activity(limit: int = 20, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT app_name, started_at FROM pcorp.activity_log ORDER BY id DESC LIMIT %s", (limit,)
            )
            rows = await cur.fetchall()
            return [{"app_name": r[0], "started_at": str(r[1]) if r[1] is not None else None} for r in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT app_name, started_at FROM activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def save_legacy_entry(title: str, content: str, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO pcorp.legacy_vault (title, content, created_at) VALUES (%s, %s, (now() AT TIME ZONE 'utc'))",
                (title, content),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO legacy_vault (title, content) VALUES (?, ?)", (title, content))
        await db.commit()


async def list_legacy_entries(postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, title, content, created_at FROM pcorp.legacy_vault "
                "WHERE deleted_at IS NULL ORDER BY id ASC"
            )
            rows = await cur.fetchall()
            return [
                {"id": r[0], "title": r[1], "content": r[2], "created_at": str(r[3]) if r[3] is not None else None}
                for r in rows
            ]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, content, created_at FROM legacy_vault WHERE deleted_at IS NULL ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def forget_legacy_entry(title: str, postgres_conn: Any = None) -> str | None:
    # Same exact-then-substring, most-recent-first matching as
    # forget_memory_by_title -- Frank never sees a vault entry's raw row ID.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, title FROM pcorp.legacy_vault WHERE deleted_at IS NULL AND title ILIKE %s "
                "ORDER BY id DESC LIMIT 1",
                (title,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT id, title FROM pcorp.legacy_vault WHERE deleted_at IS NULL AND title ILIKE %s "
                    "ORDER BY id DESC LIMIT 1",
                    (f"%{title}%",),
                )
                row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute("UPDATE pcorp.legacy_vault SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (row[0],))
        await postgres_conn.commit()
        return row[1]
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


async def forget_memory_by_id(memory_id: int, postgres_conn: Any = None) -> bool:
    # Manual path (FrankView's delete affordance) — the UI already has the
    # real ID, no title-matching ambiguity to resolve.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE pcorp.memory_records SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s AND deleted_at IS NULL",
                (memory_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE memory_records SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def forget_memory_by_title(title: str, postgres_conn: Any = None) -> str | None:
    # Frank's forget_memory tool path — he only has the title he originally
    # gave it, not the row ID (never surfaced to him). Exact match preferred;
    # falls back to a substring match, most recent first, since he may not
    # recall the exact original wording. Returns the real title that got
    # forgotten (so he can confirm what happened), or None if nothing matched.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, title FROM pcorp.memory_records WHERE deleted_at IS NULL AND title ILIKE %s "
                "ORDER BY id DESC LIMIT 1",
                (title,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT id, title FROM pcorp.memory_records WHERE deleted_at IS NULL AND title ILIKE %s "
                    "ORDER BY id DESC LIMIT 1",
                    (f"%{title}%",),
                )
                row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute("UPDATE pcorp.memory_records SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (row[0],))
        await postgres_conn.commit()
        return row[1]
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
