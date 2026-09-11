"""
Calendar cache (2026-08-27) -- normalizes the existing AppleScript path
(system_calendar.py) and the new Google Calendar path
(google_calendar_client.py) into one table, refreshed on a periodic
background tick (main.py's _calendar_sync_loop). calendar_tools.py's
existing list_calendar_events tool reads from here instead of calling
system_calendar.list_events() directly -- Frank's existing "what's on my
calendar" question now sees both sources with no new tool needed.

AppleScript rows get a synthetic id (hash of title+start) since
system_calendar.py confirmed there is no real event UID available through
AppleScript at all -- a disclosed limitation: a renamed AppleScript event
won't match its old cached row, it'll just appear as a new one and the
old one will drop out on the next sync. Google rows use Google's own
real, stable event id.

Each sync fully replaces that source's rows rather than diffing/
upserting -- simpler, and correct for a read-only mirror refreshed every
15 minutes: a deleted event lingering for at most one sync interval is an
acceptable, bounded staleness for a personal calendar view, not a real
correctness problem.

Dual-backend dispatchers (2026-09-11, iPhone independence pass): the
AppleScript half of sync_calendar_cache() only ever runs on the Mac (the
scheduler loop that calls it is never started in cloud mode -- see
main.py's run()), but it still needs to write to shared Postgres when
DATA_BACKEND=postgres so the cloud instance's own reads (GET routes,
list_calendar_events) see the same fresh data, not a Mac-only-visible
cache.
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from app.google_calendar_client import fetch_upcoming_events
from app.system_calendar import list_events as list_applescript_events

DB_PATH = Path(__file__).parent.parent / "data" / "calendar.db"
# Wider than any single list_calendar_events query window so the cache
# stays useful regardless of what days= a caller later asks for.
SYNC_WINDOW_DAYS = 30


async def init_calendar_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                start TEXT,
                end TEXT,
                calendar_name TEXT,
                location TEXT,
                attendees TEXT,
                synced_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


def _applescript_id(title: str, start: str) -> str:
    return "applescript:" + hashlib.sha256(f"{title}|{start}".encode()).hexdigest()[:16]


async def sync_calendar_cache(postgres_conn: Any = None) -> None:
    applescript_events = await list_applescript_events(SYNC_WINDOW_DAYS)
    google_events = await fetch_upcoming_events(SYNC_WINDOW_DAYS, postgres_conn=postgres_conn)
    if postgres_conn is not None:
        await _sync_calendar_cache_postgres(postgres_conn, applescript_events, google_events)
        return
    await _sync_calendar_cache_sqlite(applescript_events, google_events)


async def _sync_calendar_cache_sqlite(applescript_events: list[dict], google_events: list[dict]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM calendar_events WHERE source = 'applescript'")
        for e in applescript_events:
            await db.execute(
                "INSERT OR REPLACE INTO calendar_events "
                "(id, source, title, start, end, calendar_name, location, attendees) "
                "VALUES (?, 'applescript', ?, ?, ?, ?, NULL, NULL)",
                (_applescript_id(e["title"], e["start"]), e["title"], e["start"], e["end"], e["calendar"]),
            )

        await db.execute("DELETE FROM calendar_events WHERE source = 'google'")
        for e in google_events:
            await db.execute(
                "INSERT OR REPLACE INTO calendar_events "
                "(id, source, title, start, end, calendar_name, location, attendees) "
                "VALUES (?, 'google', ?, ?, ?, 'Google Calendar', ?, ?)",
                ("google:" + e["id"], e["title"], e["start"], e["end"], e["location"], e["attendees"]),
            )
        await db.commit()


async def _sync_calendar_cache_postgres(conn: Any, applescript_events: list[dict], google_events: list[dict]) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM calendar.calendar_events WHERE source = 'applescript'")
        for e in applescript_events:
            await cur.execute(
                "INSERT INTO calendar.calendar_events "
                "(id, source, title, start, \"end\", calendar_name, location, attendees, synced_at) "
                "VALUES (%s, 'applescript', %s, %s, %s, %s, NULL, NULL, (now() AT TIME ZONE 'utc')) "
                "ON CONFLICT (id) DO UPDATE SET "
                "title = EXCLUDED.title, start = EXCLUDED.start, \"end\" = EXCLUDED.\"end\", "
                "calendar_name = EXCLUDED.calendar_name, synced_at = EXCLUDED.synced_at",
                (_applescript_id(e["title"], e["start"]), e["title"], e["start"], e["end"], e["calendar"]),
            )

        await cur.execute("DELETE FROM calendar.calendar_events WHERE source = 'google'")
        for e in google_events:
            await cur.execute(
                "INSERT INTO calendar.calendar_events "
                "(id, source, title, start, \"end\", calendar_name, location, attendees, synced_at) "
                "VALUES (%s, 'google', %s, %s, %s, 'Google Calendar', %s, %s, (now() AT TIME ZONE 'utc')) "
                "ON CONFLICT (id) DO UPDATE SET "
                "title = EXCLUDED.title, start = EXCLUDED.start, \"end\" = EXCLUDED.\"end\", "
                "location = EXCLUDED.location, attendees = EXCLUDED.attendees, synced_at = EXCLUDED.synced_at",
                ("google:" + e["id"], e["title"], e["start"], e["end"], e["location"], e["attendees"]),
            )
    await conn.commit()


def _parse_start(value: str) -> datetime | None:
    """Handles all three shapes this table can hold: AppleScript's naive
    local isoformat, Google's RFC3339 dateTime (with a 'Z' or offset), and
    Google's all-day 'date' (no time component)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


async def get_cached_events(days: int = 7, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT source, title, start, \"end\", calendar_name, location, attendees "
                "FROM calendar.calendar_events"
            )
            rows = [
                {
                    "source": r[0],
                    "title": r[1],
                    "start": r[2],
                    "end": r[3],
                    "calendar_name": r[4],
                    "location": r[5],
                    "attendees": r[6],
                }
                for r in await cur.fetchall()
            ]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT source, title, start, end, calendar_name, location, attendees FROM calendar_events"
            )
            rows = [dict(r) for r in await cursor.fetchall()]

    cutoff = datetime.now() + timedelta(days=days)
    windowed = []
    for row in rows:
        start = _parse_start(row["start"])
        if start is not None and start > cutoff:
            continue
        windowed.append((start or datetime.max, row))
    windowed.sort(key=lambda pair: pair[0])
    return [row for _, row in windowed]


async def get_last_google_calendar_sync_at(postgres_conn: Any = None) -> str | None:
    """MAX(synced_at) restricted to source='google' -- the AppleScript
    source's own synced_at isn't a Google signal. Honest edge case, not
    hidden: if Google is connected but genuinely has zero upcoming events
    inside the sync window, sync_calendar_cache() writes no 'google' rows
    to take a MAX of, so this returns None even though a sync attempt just
    ran cleanly -- this table mirrors events, not sync attempts."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT MAX(synced_at) FROM calendar.calendar_events WHERE source = 'google'")
            (last_synced,) = await cur.fetchone()
            return str(last_synced) if last_synced is not None else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT MAX(synced_at) FROM calendar_events WHERE source = 'google'")
        (last_synced,) = await cursor.fetchone()
        return last_synced
