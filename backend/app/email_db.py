"""
Email log (2026-08-27) -- own SQLite file (email.db), same "genuinely
separate domain" reasoning as people.db/joshx.db/alpha_mode.db. Read/log
only, per the original brief's constraint: there is no send/compose path
anywhere in this module or email_tools.py, and never will be.

sync_recent_emails() is the only writer. It matches each message's sender
against the two real email-bearing fields that exist anywhere in this
app -- people.email (people_db.py) and Joshx clients.email (joshx_db.py,
confirmed via grep the only other one; Alpha Mode Media has no email
column anywhere in its schema, real Supabase included, so it's not
checked). `linked_person_id`/`linked_client_name` are plain-text cross-
references across separate SQLite files, not real foreign keys -- same
convention already established for people.linked_client_name.
"""

from pathlib import Path

import aiosqlite

from app import google_oauth
from app.db import mark_gmail_synced
from app.gmail_client import fetch_recent_messages

DB_PATH = Path(__file__).parent.parent / "data" / "email.db"
PEOPLE_DB_PATH = Path(__file__).parent.parent / "data" / "people.db"
JOSHX_DB_PATH = Path(__file__).parent.parent / "data" / "joshx.db"


async def init_email_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                sender_email TEXT,
                sender_name TEXT,
                subject TEXT,
                snippet TEXT,
                received_at TEXT,
                linked_person_id INTEGER,
                linked_client_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def _match_person(sender_email: str) -> int | None:
    if not Path(PEOPLE_DB_PATH).exists():
        return None
    async with aiosqlite.connect(PEOPLE_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM people WHERE email = ? COLLATE NOCASE", (sender_email,)
        )
        row = await cursor.fetchone()
        if row:
            return row[0]
        return None


async def _match_client(sender_email: str) -> str | None:
    if not Path(JOSHX_DB_PATH).exists():
        return None
    async with aiosqlite.connect(JOSHX_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name FROM clients WHERE email = ? COLLATE NOCASE AND deleted_at IS NULL", (sender_email,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def _bump_person_contact(person_id: int, received_at: str) -> None:
    async with aiosqlite.connect(PEOPLE_DB_PATH) as db:
        await db.execute(
            "UPDATE people SET last_contact_date = ? "
            "WHERE id = ? AND (last_contact_date IS NULL OR last_contact_date < ?)",
            (received_at, person_id, received_at),
        )
        await db.commit()


async def _bump_client_contact(client_name: str, received_at: str) -> None:
    async with aiosqlite.connect(JOSHX_DB_PATH) as db:
        await db.execute(
            "UPDATE clients SET last_contact_date = ? "
            "WHERE name = ? AND (last_contact_date IS NULL OR last_contact_date < ?)",
            (received_at, client_name, received_at),
        )
        await db.commit()


async def sync_recent_emails(max_results: int = 20) -> int:
    """Pulls recent Gmail messages and inserts only the genuinely new ones
    (by Gmail's own message id), matching sender against people.email and
    Joshx clients.email. Returns the count of newly-inserted messages.
    Safe to call repeatedly (on the periodic tick or on demand) -- already-
    seen messages are silently skipped, not re-processed."""
    messages = await fetch_recent_messages(max_results)
    if google_oauth.is_connected():
        # Marks "we attempted this sync while actually holding a Google
        # grant," not "Gmail definitely returned fresh data" -- matches
        # is_connected()'s own scope (a token presence check, not a live
        # probe). fetch_recent_messages() returns [] indistinguishably for
        # "no new messages" and "API/token failure" (its own docstring),
        # so gating on message count would overclaim precision that
        # doesn't exist here.
        await mark_gmail_synced()
    if not messages:
        return 0
    inserted = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for message in messages:
            cursor = await db.execute("SELECT 1 FROM emails WHERE id = ?", (message["id"],))
            if await cursor.fetchone() is not None:
                continue

            linked_person_id = None
            linked_client_name = None
            if message["sender_email"]:
                linked_person_id = await _match_person(message["sender_email"])
                if linked_person_id is not None and message["received_at"]:
                    await _bump_person_contact(linked_person_id, message["received_at"])
                else:
                    linked_client_name = await _match_client(message["sender_email"])
                    if linked_client_name and message["received_at"]:
                        await _bump_client_contact(linked_client_name, message["received_at"])

            await db.execute(
                "INSERT INTO emails "
                "(id, thread_id, sender_email, sender_name, subject, snippet, received_at, "
                "linked_person_id, linked_client_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message["id"],
                    message["thread_id"],
                    message["sender_email"],
                    message["sender_name"],
                    message["subject"],
                    message["snippet"],
                    message["received_at"],
                    linked_person_id,
                    linked_client_name,
                ),
            )
            inserted += 1
        await db.commit()
    return inserted


async def get_recent_emails(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, sender_email, sender_name, subject, snippet, received_at, "
            "linked_person_id, linked_client_name FROM emails ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def search_emails(query: str, limit: int = 10) -> list[dict]:
    """Searches the local synced log only -- never hits Gmail live, so
    this only ever finds what a prior sync already pulled in."""
    like = f"%{query}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, sender_email, sender_name, subject, snippet, received_at, "
            "linked_person_id, linked_client_name FROM emails "
            "WHERE subject LIKE ? OR snippet LIKE ? OR sender_email LIKE ? OR sender_name LIKE ? "
            "ORDER BY rowid DESC LIMIT ?",
            (like, like, like, like, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]
