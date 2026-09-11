"""
Per-device auth sessions -- Stage 7 prep (2026-09-10), additive to
app/auth.py's single shared token, not a replacement of it. Real gap
found during the Infrastructure Independence audit: auth.py's one
token has existed unrotated since 2026-07-24, is stored in plaintext,
has no expiry, and the only way to revoke it is deleting the file and
re-pasting the new value into iOS's Keychain by hand.

Genuinely separate domain, same reasoning as automations.db/
triggers.db getting their own file rather than living in db.py's
app_state (reserved for true global singleton values, not per-item
records -- one row per device here is exactly a per-item record).

The token itself is never stored, only its SHA-256 hash -- a stolen
copy of this database doesn't hand over a live credential the way
auth.py's plaintext auth_token file does. create_device_session()
returns the real plaintext token exactly once; there is no function
anywhere in this file that can recover it afterward.

Dual-backend dispatchers (2026-09-11, iPhone independence pass): auth
becomes a 13th migrated "domain" -- a device session minted through
either the Mac or a cloud instance is then valid against both, since
they'd share the same real Postgres, and it survives Render's ephemeral
disk (today, a session registered directly against Render would vanish
on the next redeploy). `expires_at`/`last_used_at`/`revoked_at` are
already computed in Python (`datetime.now()`, local time, not UTC) in
the existing SQLite path -- the exact same Python-computed values are
reused verbatim for the Postgres path too, so there's no timezone
discrepancy to introduce between backends for those three columns.
`created_at`'s SQLite DEFAULT (`datetime('now')`) returns real UTC,
unlike the other three -- a real, harmless, pre-existing inconsistency
in this file, replicated faithfully via `(now() AT TIME ZONE 'utc')` on
the Postgres side rather than silently "fixed" to match the other three.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "auth.db"

SESSION_LIFETIME_DAYS = 90


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def init_auth_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS device_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )
            """
        )
        await db.commit()


async def create_device_session(device_name: str, postgres_conn: Any = None) -> str:
    """Mints a new per-device token, returned in plaintext exactly once.
    Only its hash is ever persisted."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = (datetime.now() + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat()
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO auth.device_sessions (device_name, token_hash, expires_at, created_at) "
                "VALUES (%s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (device_name, token_hash, expires_at),
            )
        await postgres_conn.commit()
        return token
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO device_sessions (device_name, token_hash, expires_at) VALUES (?, ?, ?)",
            (device_name, token_hash, expires_at),
        )
        await db.commit()
    return token


async def verify_device_session(token: str, postgres_conn: Any = None) -> bool:
    """Hashes the incoming token and looks for a matching, non-revoked,
    non-expired session. On a match, slides the expiry forward another
    SESSION_LIFETIME_DAYS from now -- an actively-used device never needs
    manual renewal; an abandoned one lapses on its own."""
    token_hash = _hash_token(token)
    now = datetime.now()
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, expires_at FROM auth.device_sessions WHERE token_hash = %s AND revoked_at IS NULL",
                (token_hash,),
            )
            row = await cur.fetchone()
            if row is None:
                # Real bug found live (2026-09-11): this used to return
                # without ever committing/rolling back, leaving the one
                # shared connection sitting in an open transaction --
                # holding whatever locks that SELECT implied -- for as
                # long as the connection lived. verify_token() runs this
                # on nearly every request, so any invalid/expired/revoked
                # token check (not just this success path) needed to end
                # its transaction too. Confirmed live: a stuck ALTER
                # TABLE queued for minutes behind exactly this.
                await postgres_conn.rollback()
                return False
            if datetime.fromisoformat(row[1]) < now:
                await postgres_conn.rollback()
                return False
            new_expiry = (now + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat()
            await cur.execute(
                "UPDATE auth.device_sessions SET last_used_at = %s, expires_at = %s WHERE id = %s",
                (now.isoformat(), new_expiry, row[0]),
            )
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, expires_at FROM device_sessions WHERE token_hash = ? AND revoked_at IS NULL",
            (token_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False
        if datetime.fromisoformat(row["expires_at"]) < now:
            return False
        new_expiry = (now + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat()
        await db.execute(
            "UPDATE device_sessions SET last_used_at = ?, expires_at = ? WHERE id = ?",
            (now.isoformat(), new_expiry, row["id"]),
        )
        await db.commit()
        return True


async def revoke_device_session(device_name: str, postgres_conn: Any = None) -> bool:
    """Revokes every non-revoked session for a given device name (usually
    just one). Returns whether anything was actually revoked."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE auth.device_sessions SET revoked_at = (now() AT TIME ZONE 'utc') "
                "WHERE device_name = %s AND revoked_at IS NULL",
                (device_name,),
            )
            revoked = cur.rowcount > 0
        await postgres_conn.commit()
        return revoked
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE device_sessions SET revoked_at = datetime('now') "
            "WHERE device_name = ? AND revoked_at IS NULL",
            (device_name,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def list_device_sessions(postgres_conn: Any = None) -> list[dict]:
    """For a future device-management UI -- never returns the token or its
    hash, only what's needed to show and manage a device's session."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT device_name, created_at, last_used_at, expires_at, revoked_at "
                "FROM auth.device_sessions ORDER BY id DESC"
            )
            cols = ["device_name", "created_at", "last_used_at", "expires_at", "revoked_at"]
            rows = []
            for r in await cur.fetchall():
                d = dict(zip(cols, r))
                if d["created_at"] is not None:
                    d["created_at"] = str(d["created_at"])
                rows.append(d)
            return rows
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT device_name, created_at, last_used_at, expires_at, revoked_at "
            "FROM device_sessions ORDER BY id DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]
