"""
The private journal's storage (2026-11-07). It only ever holds what his
devices have already encrypted. Notes, voice recordings and his category
list arrive sealed with a key that exists only on his iPhone and Mac, so
this server, its database, Frank and anyone reading them see scrambled
bytes, a size, and when each was saved. Nothing here can decrypt, and
nothing here is offered to Frank as a tool or as context: keep it that way.

One table of sealed items, named by the device that made them: "e-..." a
note, "a-..." its recording, "m-categories" his list of categories, and
"h-week-YYYY-MM-DD" / "h-month-YYYY-MM-DD" a highlight his Mac wrote of a
week or month (on the Mac itself, with Apple's on-device model). Each
carries a version the devices count up, so the newer copy wins and a
deletion is remembered as a tombstone for the other device to find. One
more row holds a check value derived from the key, so a second device can
tell its key is the right one before it writes anything.

Tables are made on first use, never at startup, and only ever created,
never altered, so nothing else in P Corp is at risk from them.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "journal.db"

ITEM_ID = re.compile(r"^(?:[ea]-[0-9a-f]{32}|m-categories|h-(?:week|month)-\d{4}-\d{2}-\d{2})$")
KEY_CHECK = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"e": "entry", "a": "audio", "m": "meta", "h": "highlight"}
# Biggest sealed item of each kind. A voice note of about half an hour fits; a note's text is far smaller.
LIMITS = {"e": 512 * 1024, "a": 30 * 1024 * 1024, "m": 64 * 1024, "h": 64 * 1024}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def kind_of(item_id: str) -> str:
    return KINDS[item_id[0]]


def limit_of(item_id: str) -> int:
    return LIMITS[item_id[0]]


def _table(conn: Any, name: str) -> str:
    return f"journal.{name}" if conn is not None else f"journal_{name}"


async def _run(conn: Any, sql: str, params: tuple = ()) -> tuple[list[tuple], int]:
    """One statement, the same SQL on both databases, committed. The rows and how many were changed."""
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute(sql.replace("?", "%s"), params)
            rows = await cur.fetchall() if cur.description else []
            changed = cur.rowcount
        await conn.commit()
        return rows, changed
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            changed = cur.rowcount
        await db.commit()
        return [tuple(r) for r in rows], changed


async def _missing_table(exc: Exception, conn: Any) -> bool:
    """True if this is only the tables not being made yet, which isn't a fault. Anything else shouldn't be hidden."""
    if "does not exist" not in str(exc) and "no such table" not in str(exc):
        return False
    if conn is not None:
        await conn.rollback()
    return True


async def ensure_tables(conn: Any = None) -> None:
    blob = "BYTEA" if conn is not None else "BLOB"
    if conn is not None:
        await _run(conn, "CREATE SCHEMA IF NOT EXISTS journal")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "items")} (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, data {blob}, size INTEGER NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)""")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "key")} (
        id INTEGER PRIMARY KEY CHECK (id = 1), key_check TEXT NOT NULL, created_at TEXT NOT NULL)""")


async def key_check(conn: Any = None) -> str | None:
    """The check value of the journal's key, or None if no device has set one up yet."""
    try:
        rows, _ = await _run(conn, f"SELECT key_check FROM {_table(conn, 'key')} WHERE id = 1")
    except Exception as exc:
        if await _missing_table(exc, conn):
            return None
        raise
    return rows[0][0] if rows else None


async def set_key_check(value: str, conn: Any = None) -> str:
    """Records the first device's check value. Only ever the first: it's what stops a second device starting a journal of its own with a different key. The value now stored."""
    await ensure_tables(conn)
    await _run(conn, f"INSERT INTO {_table(conn, 'key')} (id, key_check, created_at) VALUES (1, ?, ?) ON CONFLICT (id) DO NOTHING", (value, now_iso()))
    return await key_check(conn)


async def index(conn: Any = None) -> list[dict[str, Any]]:
    """Every item's name, kind, size, version and dates: what a device needs to catch up. Never the contents."""
    try:
        rows, _ = await _run(conn, f"SELECT id, kind, size, version, updated_at, deleted_at FROM {_table(conn, 'items')} ORDER BY updated_at")
    except Exception as exc:
        if await _missing_table(exc, conn):
            return []
        raise
    return [{"id": r[0], "kind": r[1], "size": r[2], "version": r[3], "updated_at": r[4], "deleted": r[5] is not None} for r in rows]


async def get_item(item_id: str, conn: Any = None) -> tuple[bytes, int] | None:
    """An item's sealed bytes and version, or None if there's no such item or it was deleted."""
    try:
        rows, _ = await _run(conn, f"SELECT data, version FROM {_table(conn, 'items')} WHERE id = ? AND deleted_at IS NULL", (item_id,))
    except Exception as exc:
        if await _missing_table(exc, conn):
            return None
        raise
    if not rows or rows[0][0] is None:
        return None
    return bytes(rows[0][0]), rows[0][1]


async def _stored_version(item_id: str, conn: Any) -> int:
    rows, _ = await _run(conn, f"SELECT version FROM {_table(conn, 'items')} WHERE id = ?", (item_id,))
    return rows[0][0] if rows else 0


async def put_item(item_id: str, data: bytes, version: int, conn: Any = None) -> tuple[bool, int]:
    """Saves a sealed item if this version is newer than what's stored. (saved, the version now stored)."""
    await ensure_tables(conn)
    _, changed = await _run(
        conn,
        f"INSERT INTO {_table(conn, 'items')} (id, kind, data, size, version, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, NULL) "
        f"ON CONFLICT (id) DO UPDATE SET data = excluded.data, size = excluded.size, version = excluded.version, updated_at = excluded.updated_at, deleted_at = NULL "
        f"WHERE {_table(conn, 'items')}.version < excluded.version",
        (item_id, kind_of(item_id), data, len(data), version, now_iso()),
    )
    return changed > 0, await _stored_version(item_id, conn)


async def delete_item(item_id: str, version: int, conn: Any = None) -> tuple[bool, int]:
    """Deletes an item for good, keeping only a tombstone so the other device learns it's gone. (deleted, the version now stored)."""
    await ensure_tables(conn)
    _, changed = await _run(
        conn,
        f"INSERT INTO {_table(conn, 'items')} (id, kind, data, size, version, updated_at, deleted_at) VALUES (?, ?, NULL, 0, ?, ?, ?) "
        f"ON CONFLICT (id) DO UPDATE SET data = NULL, size = 0, version = excluded.version, updated_at = excluded.updated_at, deleted_at = excluded.deleted_at "
        f"WHERE {_table(conn, 'items')}.version < excluded.version",
        (item_id, kind_of(item_id), version, now_iso(), now_iso()),
    )
    return changed > 0, await _stored_version(item_id, conn)
