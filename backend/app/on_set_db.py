"""The on-set tracker's live list (Shoot Logger Phase 3, 2026-11-04): two shooters run one job off one list, on their phones, at a venue.

Phones can't reach this Mac from a venue, so the page and these tables are served from the cloud backend, and the Mac and the cloud share them through Postgres. A coverage plan itself stays
on the Mac: only a copy of its shot list comes here, and only when the DOP makes a phone link.

This is P Corp's first thing on the public internet that doesn't need the main token, so the rules are strict:
  - A link is a long random token that opens one list and nothing else. It isn't a login: verify_token never accepts it, and the routes here accept nothing but it.
  - Only its hash is stored here. It travels in a header, and in the page address after a "#", so it never lands in a server log.
  - The routes can read that list and add ticks to it. They can't edit the list, reach a plan, a file, a brief or a cost, or spend money on Claude.
  - Stopping a link or reaching its end date takes effect on the phone's next request. An unknown, stopped and expired link all get the same answer.
  - Ticks only ever get added. A tick never decides whether a shot is covered: that comes from the footage.

The tables are made the first time a link is made, not at startup: startup DDL has caused an outage here before, and a Mac or cloud backend that has never made a link shouldn't need them."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "on_set.db"

NOT_ACTIVE = "This link isn't active. Ask whoever sent it for a new one."
MAX_TICKS_PER_LINK = 5000
MAX_BODY_BYTES = 64 * 1024
REQUESTS_PER_LINK_PER_MINUTE = 300     # a phone polling every 5 s is 12, so this is 25 phones
UNKNOWN_LINKS_PER_MINUTE = 120         # all phones together: a flood of made-up links can't tie up the database
_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_LINK_COLUMNS = ("plan_id", "name", "client", "shoot_date", "items_json", "settings_json", "list_version", "created_at", "expires_at", "revoked_at")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ========================================================================================================================================== keeping floods out
class RateLimit:
    """A sliding window per key. In memory, so it resets when the server restarts, and that's fine: it's here to protect the database, not to count anything."""
    MAX_KEYS = 2000

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, now: float | None = None, per: float = 60.0) -> bool:
        now = time.monotonic() if now is None else now
        window = self.hits.get(key)
        if window is None:
            if len(self.hits) >= self.MAX_KEYS:
                self.hits.pop(next(iter(self.hits)))
            window = self.hits[key] = deque()
        while window and window[0] <= now - per:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


_limits = RateLimit()
_known: dict[str, float] = {}


def admit(token: str) -> str:
    """Before any database work: "ok", "no" (can't be a link of ours) or "slow" (too many requests)."""
    if not 32 <= len(token or "") <= 100:
        return "no"
    hashed = token_hash(token)
    if not _limits.allow(hashed, REQUESTS_PER_LINK_PER_MINUTE):
        return "slow"
    if hashed not in _known and not _limits.allow("unknown links", UNKNOWN_LINKS_PER_MINUTE):
        return "slow"
    return "ok"


def _remember(hashed: str) -> None:
    if len(_known) >= RateLimit.MAX_KEYS:
        _known.pop(next(iter(_known)))
    _known[hashed] = time.monotonic()


# =============================================================================================================================================== the database
def _names(conn: Any) -> tuple[str, str]:
    return ("on_set.links", "on_set.ticks") if conn is not None else ("on_set_links", "on_set_ticks")


async def _run(conn: Any, sql: str, params: tuple = ()) -> list[tuple]:
    """One statement, the same SQL on both databases, committed."""
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute(sql.replace("?", "%s"), params)
            rows = await cur.fetchall() if cur.description else []
        await conn.commit()
        return rows
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        await db.commit()
        return [tuple(r) for r in rows]


async def ensure_tables(conn: Any = None) -> None:
    links, ticks = _names(conn)
    identity = "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if conn is not None else "INTEGER PRIMARY KEY AUTOINCREMENT"
    if conn is not None:
        await _run(conn, "CREATE SCHEMA IF NOT EXISTS on_set")
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {links} (
        plan_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL, client TEXT NOT NULL, shoot_date TEXT NOT NULL, items_json TEXT NOT NULL, settings_json TEXT NOT NULL,
        list_version INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT)""")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {ticks} (
        id {identity}, plan_id TEXT NOT NULL REFERENCES {links}(plan_id), event_id TEXT NOT NULL, item_id TEXT NOT NULL, done INTEGER NOT NULL CHECK (done IN (0, 1)), by_name TEXT NOT NULL,
        note TEXT NOT NULL, happened_at TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (plan_id, event_id))""")


def _link(row: tuple) -> dict[str, Any]:
    out = dict(zip(_LINK_COLUMNS, row))
    out["items"] = json.loads(out.pop("items_json"))
    out["settings"] = json.loads(out.pop("settings_json"))
    return out


async def publish(plan_id: str, token: str, name: str, client: str, shoot_date: str, items: list[dict[str, Any]], settings: dict[str, Any], expires_at: str, conn: Any = None) -> dict[str, Any]:
    """Makes the link, or sends a new list to one that exists. Ticks already made on this plan stay."""
    links, _ = _names(conn)
    await _run(conn, f"""INSERT INTO {links} AS l (plan_id, token_hash, name, client, shoot_date, items_json, settings_json, list_version, created_at, expires_at, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
        ON CONFLICT (plan_id) DO UPDATE SET token_hash = excluded.token_hash, name = excluded.name, client = excluded.client, shoot_date = excluded.shoot_date, items_json = excluded.items_json,
        settings_json = excluded.settings_json, list_version = l.list_version + 1, expires_at = excluded.expires_at, revoked_at = NULL""",
                (plan_id, token_hash(token), name, client, shoot_date, json.dumps(items), json.dumps(settings), now_iso(), expires_at))
    return await get_link(plan_id, conn)  # type: ignore[return-value]


async def revoke(plan_id: str, conn: Any = None) -> None:
    links, _ = _names(conn)
    await _run(conn, f"UPDATE {links} SET revoked_at = ? WHERE plan_id = ?", (now_iso(), plan_id))


async def get_link(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    links, _ = _names(conn)
    rows = await _run(conn, f"SELECT {', '.join(_LINK_COLUMNS)} FROM {links} WHERE plan_id = ?", (plan_id,))
    return _link(rows[0]) if rows else None


async def find_link(token: str, conn: Any = None) -> dict[str, Any] | None:
    """The live list a token opens, or None for one that's unknown, stopped or past its date."""
    links, _ = _names(conn)
    hashed = token_hash(token)
    try:
        rows = await _run(conn, f"SELECT {', '.join(_LINK_COLUMNS)} FROM {links} WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?", (hashed, now_iso()))
    except Exception as exc:
        # No link has ever been made, so the table isn't there yet. Anything else is a real fault and shouldn't read as a dead link.
        if "does not exist" in str(exc) or "no such table" in str(exc):
            if conn is not None:
                await conn.rollback()
            return None
        raise
    if not rows:
        return None
    _remember(hashed)
    return _link(rows[0])


def _clean_text(raw: Any, limit: int) -> str:
    """Text from a phone, with control characters out (Postgres refuses some of them, and nobody needs them)."""
    return "".join(ch for ch in str(raw or "") if ch >= " " and ch != "\x7f").strip()[:limit]


def _clean_when(raw: Any, link: dict[str, Any]) -> str:
    """When a tick really happened, as the phone says, since it may have been waiting for signal. Never in the future, and never before the link existed, so a wrong phone clock can't win."""
    now = datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError
    except (ValueError, OverflowError):
        return _iso(now)
    created = datetime.fromisoformat(link["created_at"].replace("Z", "+00:00"))
    return _iso(max(min(when, now), created))


async def add_ticks(link: dict[str, Any], events: list[dict[str, Any]], conn: Any = None) -> dict[str, int]:
    """Adds what a phone sent. Sending the same tick twice counts once, so a phone can safely retry after losing signal.

    On Postgres the link's row is locked first. Ids are handed out before commit, so without this a phone reading "everything after id 6" could miss an id 5 that committed a moment later."""
    links, ticks = _names(conn)
    known = {i["id"] for i in link["items"]}
    plan_id = link["plan_id"]
    good = [{**e, "by": _clean_text(e.get("by"), 40)} for e in events if e["item"] in known and _EVENT_ID.match(e.get("event_id") or "")]
    good = [e for e in good if e["by"]]
    out = {"accepted": 0, "duplicates": 0, "rejected": len(events) - len(good), "full": 0}
    stamp = now_iso()
    rows = [(plan_id, e["event_id"], e["item"], 1 if e["done"] else 0, e["by"], _clean_text(e.get("note"), 200), _clean_when(e.get("at"), link), stamp) for e in good]
    insert = f"""INSERT INTO {ticks} (plan_id, event_id, item_id, done, by_name, note, happened_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (plan_id, event_id) DO NOTHING RETURNING id"""
    count_sql = f"SELECT COUNT(*) FROM {ticks} WHERE plan_id = ?"
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT plan_id FROM {links} WHERE plan_id = %s FOR UPDATE", (plan_id,))
            await cur.execute(count_sql.replace("?", "%s"), (plan_id,))
            have = (await cur.fetchone())[0]
            for row in rows:
                if have >= MAX_TICKS_PER_LINK:
                    out["full"] += 1
                    continue
                await cur.execute(insert.replace("?", "%s"), row)
                if await cur.fetchone():
                    out["accepted"] += 1
                    have += 1
                else:
                    out["duplicates"] += 1
        await conn.commit()
        return out
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(count_sql, (plan_id,)) as cur:
            have = (await cur.fetchone())[0]
        for row in rows:
            if have >= MAX_TICKS_PER_LINK:
                out["full"] += 1
                continue
            async with db.execute(insert, row) as cur:
                if await cur.fetchone():
                    out["accepted"] += 1
                    have += 1
                else:
                    out["duplicates"] += 1
        await db.commit()
    return out


async def ticks_since(plan_id: str, after_id: int, conn: Any = None) -> list[dict[str, Any]]:
    _, ticks = _names(conn)
    rows = await _run(conn, f"SELECT id, item_id, done, by_name, note, happened_at FROM {ticks} WHERE plan_id = ? AND id > ? ORDER BY id LIMIT {MAX_TICKS_PER_LINK}", (plan_id, max(0, int(after_id))))
    return [{"id": r[0], "item": r[1], "done": bool(r[2]), "by": r[3], "note": r[4], "at": r[5]} for r in rows]


def current_ticks(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Where each shot stands: the latest thing anyone did to it, by when they did it. The phone page works this out the same way, so everyone lands on the same answer."""
    out: dict[str, dict[str, Any]] = {}
    for e in sorted(events, key=lambda x: (x["at"], x["id"])):
        previous = out.get(e["item"])
        note = e["note"] or (previous["note"] if previous and e["done"] and previous["done"] else "")
        out[e["item"]] = {"done": e["done"], "by": e["by"], "at": e["at"], "note": note}
    return out


def state_payload(link: dict[str, Any], events: list[dict[str, Any]], since: int, version: int) -> dict[str, Any]:
    """What a phone gets. The list only comes when it has changed, because a phone asks every few seconds, often on poor signal."""
    out: dict[str, Any] = {"list_version": link["list_version"], "ticks": events, "last_id": max([since, *[e["id"] for e in events]]), "server_time": now_iso()}
    if version != link["list_version"]:
        out["list"] = {"name": link["name"], "client": link["client"], "shoot_date": link["shoot_date"], "items": link["items"], "settings": link["settings"]}
    return out


def expiry_for(shoot_date: str, days_after: int) -> str:
    """The end of the day, some days after the shoot, and always at least a day from now."""
    end = datetime.fromisoformat(shoot_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) + timedelta(days=days_after)
    return _iso(max(end, datetime.now(timezone.utc) + timedelta(days=1)))
