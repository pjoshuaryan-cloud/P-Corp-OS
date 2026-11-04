"""The on-set tracker's live list (Shoot Logger Phase 3, 2026-11-04): two shooters run one job off one list, on their phones, at a venue.

Phones can't reach this Mac from a venue, so the page and these tables are served from the cloud backend, and the Mac and the cloud share them through Postgres. A coverage plan itself stays
on the Mac: only a copy of its shot list comes here, and only when the DOP makes a phone link.

This is P Corp's first thing on the public internet that doesn't need the main token, so the rules are strict:
  - A link is a long random token that opens one list and nothing else. It isn't a login: verify_token never accepts it, and the routes here accept nothing but it.
  - It's looked up by its hash, and it travels in a header, and in the page address after a "#", so it never lands in a server log. The full link is also kept here, readable only by the
    owner's phone login and the Mac, so a list can be re-sent from either one.
  - The routes can read that list and add ticks to it. They can't edit the list, reach a plan, a file, a brief or a cost, or spend money on Claude.
  - Stopping a link or reaching its end date takes effect on the phone's next request. An unknown, stopped and expired link all get the same answer.
  - Ticks only ever get added. A tick never decides whether a shot is covered: that comes from the footage.

The tables are made the first time a link is made, not at startup: startup DDL has caused an outage here before, and a Mac or cloud backend that has never made a link shouldn't need them.

The owner's phone (app/on_set_manage.py) gets its own login, a "manager key", from a one-time QR code on the Mac. It can make and change shot lists, and draft one from a brief up to a daily spending limit, and
nothing else. It isn't a phone link, and neither one is the main token. Only the Mac and that login can start or stop a link: a crew link can't, and the login lives in a cookie on the phone, so no forwarded address can carry it."""
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
NOT_SET_UP = "This phone isn't set up. On the Mac, open Coverage Plans and click My phone."
SETUP_MINUTES = 15
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


def _table(conn: Any, name: str) -> str:
    return f"on_set.{name}" if conn is not None else f"on_set_{name}"


async def _missing_table(exc: Exception, conn: Any) -> bool:
    """True if this is only the tables not being made yet, which isn't a fault. Anything else shouldn't be hidden."""
    if "does not exist" not in str(exc) and "no such table" not in str(exc):
        return False
    if conn is not None:
        await conn.rollback()
    return True


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
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "meta")} (plan_id TEXT PRIMARY KEY, share_token TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "managers")} (
        id TEXT PRIMARY KEY, label TEXT NOT NULL, setup_hash TEXT UNIQUE, setup_expires TEXT, key_hash TEXT UNIQUE, created_at TEXT NOT NULL, claimed_at TEXT, last_used_at TEXT, revoked_at TEXT)""")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "templates")} (id TEXT PRIMARY KEY, name TEXT NOT NULL, items_json TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "drafts")} (event_id TEXT PRIMARY KEY, manager_id TEXT NOT NULL, plan_id TEXT NOT NULL, usd_micros INTEGER NOT NULL, calls INTEGER NOT NULL, created_at TEXT NOT NULL)""")


def _link(row: tuple) -> dict[str, Any]:
    out = dict(zip(_LINK_COLUMNS, row))
    out["items"] = json.loads(out.pop("items_json"))
    out["settings"] = json.loads(out.pop("settings_json"))
    return out


async def publish(plan_id: str, token: str, name: str, client: str, shoot_date: str, items: list[dict[str, Any]], settings: dict[str, Any], expires_at: str, conn: Any = None, source: str = "mac") -> dict[str, Any]:
    """Makes the link, or sends a new list to one that exists. Ticks already made on this plan stay."""
    links, _ = _names(conn)
    await _run(conn, f"""INSERT INTO {links} AS l (plan_id, token_hash, name, client, shoot_date, items_json, settings_json, list_version, created_at, expires_at, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
        ON CONFLICT (plan_id) DO UPDATE SET token_hash = excluded.token_hash, name = excluded.name, client = excluded.client, shoot_date = excluded.shoot_date, items_json = excluded.items_json,
        settings_json = excluded.settings_json, list_version = l.list_version + 1, expires_at = excluded.expires_at, revoked_at = NULL""",
                (plan_id, token_hash(token), name, client, shoot_date, json.dumps(items), json.dumps(settings), now_iso(), expires_at))
    await _run(conn, f"""INSERT INTO {_table(conn, "meta")} (plan_id, share_token, source, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT (plan_id) DO UPDATE SET share_token = excluded.share_token, updated_at = excluded.updated_at""", (plan_id, token, source, now_iso()))
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


async def get_share(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    """The full link and where the list was made. Only for the owner's phone login and the Mac: no route a phone link can reach ever returns this."""
    try:
        rows = await _run(conn, f"SELECT share_token, source FROM {_table(conn, 'meta')} WHERE plan_id = ?", (plan_id,))
    except Exception as exc:
        if await _missing_table(exc, conn):
            return None
        raise
    return {"token": rows[0][0], "source": rows[0][1]} if rows else None


async def all_lists(conn: Any = None, limit: int = 60) -> list[dict[str, Any]]:
    """Every list, latest shoot first, each with its link and where it was made if those are known."""
    links = _names(conn)[0]
    cols = ", ".join(f"l.{c}" for c in _LINK_COLUMNS)
    try:
        rows = await _run(conn, f"SELECT {cols}, m.share_token, m.source FROM {links} l LEFT JOIN {_table(conn, 'meta')} m ON m.plan_id = l.plan_id ORDER BY l.shoot_date DESC, l.created_at DESC LIMIT {int(limit)}")
    except Exception as exc:
        if await _missing_table(exc, conn):
            return []
        raise
    return [{**_link(r[:len(_LINK_COLUMNS)]), "share_token": r[-2], "source": r[-1]} for r in rows]


async def change_list(plan_id: str, change: Any, conn: Any = None) -> dict[str, Any] | None:
    """Reads a list, lets `change` alter it, and writes it back as one step, so two edits at once can't lose one. Phones see the new list on their next check."""
    links = _names(conn)[0]
    select = f"SELECT {', '.join(_LINK_COLUMNS)} FROM {links} WHERE plan_id = ?"
    update = f"UPDATE {links} SET name = ?, client = ?, shoot_date = ?, items_json = ?, list_version = list_version + 1, expires_at = ? WHERE plan_id = ?"
    values = lambda link: (link["name"], link["client"], link["shoot_date"], json.dumps(link["items"]), link["expires_at"], plan_id)
    if conn is not None:
        try:
            async with conn.cursor() as cur:
                await cur.execute(select.replace("?", "%s") + " FOR UPDATE", (plan_id,))
                row = await cur.fetchone()
                if row is None:
                    await conn.rollback()
                    return None
                link = _link(row)
                change(link)
                await cur.execute(update.replace("?", "%s"), values(link))
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        return await get_link(plan_id, conn)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(select, (plan_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        link = _link(tuple(row))
        change(link)
        await db.execute(update, values(link))
        await db.commit()
    return await get_link(plan_id, conn)


async def new_address(plan_id: str, token: str, expires_at: str, conn: Any = None) -> None:
    """A new link for a list, for after one's been stopped. The old address stays dead."""
    links = _names(conn)[0]
    await _run(conn, f"UPDATE {links} SET token_hash = ?, expires_at = ?, revoked_at = NULL WHERE plan_id = ?", (token_hash(token), expires_at, plan_id))
    await _run(conn, f"UPDATE {_table(conn, 'meta')} SET share_token = ?, updated_at = ? WHERE plan_id = ?", (token, now_iso(), plan_id))


async def set_expiry(plan_id: str, expires_at: str, conn: Any = None) -> None:
    await _run(conn, f"UPDATE {_names(conn)[0]} SET expires_at = ? WHERE plan_id = ?", (expires_at, plan_id))


# ============================================================================================================================================ the owner's phone
async def new_setup(label: str, conn: Any = None) -> tuple[str, str]:
    """(manager id, setup code). The code is for one QR scan, in the next few minutes. A photo of the QR code is worthless once it's been used or has run out."""
    manager_id, code = "m" + secrets.token_hex(6), secrets.token_urlsafe(24)
    expires = _iso(datetime.now(timezone.utc) + timedelta(minutes=SETUP_MINUTES))
    await _run(conn, f"INSERT INTO {_table(conn, 'managers')} (id, label, setup_hash, setup_expires, created_at) VALUES (?, ?, ?, ?, ?)", (manager_id, label, token_hash(code), expires, now_iso()))
    return manager_id, code


async def claim_setup(code: str, conn: Any = None) -> str | None:
    """Swaps a setup code for the phone's lasting key, once. The update is one step, so two scans at once can't both get it."""
    key = secrets.token_urlsafe(32)
    try:
        rows = await _run(conn, f"""UPDATE {_table(conn, 'managers')} SET key_hash = ?, claimed_at = ?, setup_hash = NULL, setup_expires = NULL
            WHERE setup_hash = ? AND setup_expires > ? AND revoked_at IS NULL RETURNING id""", (token_hash(key), now_iso(), token_hash(code), now_iso()))
    except Exception as exc:
        if await _missing_table(exc, conn):
            return None
        raise
    if not rows:
        return None
    _remember(token_hash(key))
    return key


async def find_manager(key: str, conn: Any = None) -> dict[str, Any] | None:
    hashed = token_hash(key)
    managers = _table(conn, "managers")
    try:
        rows = await _run(conn, f"SELECT id, label, last_used_at FROM {managers} WHERE key_hash = ? AND revoked_at IS NULL", (hashed,))
    except Exception as exc:
        if await _missing_table(exc, conn):
            return None
        raise
    if not rows:
        return None
    _remember(hashed)
    stamp = now_iso()
    if not rows[0][2] or rows[0][2][:13] != stamp[:13]:   # at most hourly, so a phone checking in every few seconds doesn't write each time
        await _run(conn, f"UPDATE {managers} SET last_used_at = ? WHERE id = ?", (stamp, rows[0][0]))
    return {"id": rows[0][0], "label": rows[0][1]}


async def list_managers(conn: Any = None) -> list[dict[str, Any]]:
    """Phones with a login, and setups still waiting to be scanned. Never a key or code."""
    try:
        rows = await _run(conn, f"SELECT id, label, created_at, claimed_at, last_used_at, setup_expires FROM {_table(conn, 'managers')} WHERE revoked_at IS NULL ORDER BY created_at")
    except Exception as exc:
        if await _missing_table(exc, conn):
            return []
        raise
    stamp = now_iso()
    return [{"id": r[0], "label": r[1], "created_at": r[2], "claimed_at": r[3], "last_used_at": r[4]} for r in rows if r[3] or (r[5] and r[5] > stamp)]


async def revoke_manager(manager_id: str, conn: Any = None) -> None:
    await _run(conn, f"UPDATE {_table(conn, 'managers')} SET revoked_at = ?, setup_hash = NULL, setup_expires = NULL WHERE id = ?", (now_iso(), manager_id))


async def record_draft(manager_id: str, plan_id: str, usd: float, calls: int, conn: Any = None) -> None:
    """What a draft from a phone really cost, for the daily limit and for anyone asking where the money went."""
    await _run(conn, f"INSERT INTO {_table(conn, 'drafts')} (event_id, manager_id, plan_id, usd_micros, calls, created_at) VALUES (?, ?, ?, ?, ?, ?)", (secrets.token_hex(8), manager_id, plan_id, int(round(usd * 1e6)), calls, now_iso()))


async def drafts_last_day(conn: Any = None) -> dict[str, float]:
    """Drafts and spend in the last 24 hours, across all phones."""
    since = _iso(datetime.now(timezone.utc) - timedelta(days=1))
    rows = await _run(conn, f"SELECT COUNT(*), COALESCE(SUM(usd_micros), 0) FROM {_table(conn, 'drafts')} WHERE created_at > ?", (since,))
    return {"count": int(rows[0][0]), "usd": int(rows[0][1]) / 1e6}


async def replace_templates(templates: list[dict[str, Any]], conn: Any = None) -> None:
    """The Mac's saved shot lists, copied up so a phone can start from them."""
    table = _table(conn, "templates")
    await _run(conn, f"DELETE FROM {table}")
    for t in templates:
        await _run(conn, f"INSERT INTO {table} (id, name, items_json, updated_at) VALUES (?, ?, ?, ?)", (t["id"], t["name"], json.dumps(t["items"]), now_iso()))


async def load_templates(conn: Any = None) -> list[dict[str, Any]]:
    try:
        rows = await _run(conn, f"SELECT id, name, items_json FROM {_table(conn, 'templates')} ORDER BY name")
    except Exception as exc:
        if await _missing_table(exc, conn):
            return []
        raise
    return [{"id": r[0], "name": r[1], "items": json.loads(r[2])} for r in rows]


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
