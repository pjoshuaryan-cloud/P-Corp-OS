"""Frank's hands on the Mac (2026-11-20). Josh: "if I ask it to airdrop me something ... open up a certain folder ... for Mac and for iPhone".

A FIXED list of actions, never a terminal: find files, open a folder/file, open an app, open a website (no approval); send a file to the phone,
copy/move/rename, move to the Bin (each needs Josh's tap on the approval card first, on whichever device he asked from -- mac_tools.py). An email or a web
page can carry hidden instructions, so Frank never gets a shell here.

Where they run: on the Mac's own backend directly. A request from the phone reaches the cloud backend, which can't touch the Mac, so it is queued in the
shared database (schema "mac") and the Mac's loop (main._mac_actions_loop, Mac-only) runs it within a couple of seconds and writes the result back; the
cloud waits for it. The Mac beats every few seconds so the phone can say plainly when the Mac is off. Tables are made on first use, not at startup.

Folders: the home folder and plugged-in drives, never system folders, ~/Library (except iCloud Drive), hidden files and folders, keys, .env files or
P Corp's own data. "Send me this": a file up to INBOX_MAX_BYTES goes to the shared cloud storage and shows in the phone's chat as an attachment it can open
and share (removed after 24 hours); bigger files are copied into iCloud Drive > P Corp Inbox. True AirDrop can't pick the receiving device by itself.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
ICLOUD = HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
ICLOUD_INBOX = ICLOUD / "P Corp Inbox"
REPO_DATA = Path(__file__).resolve().parent.parent / "data"
REPO_ENV = Path(__file__).resolve().parent.parent / ".env"
INBOX_MAX_BYTES = 45 * 1024 * 1024      # the cloud storage plan's per-file limit is 50 MB
INBOX_HOURS = 24
FIND_LIMIT = 25
WALK_SECONDS = 6.0
_SECRET_NAME = re.compile(r"(^\.env)|(\.pem$)|(\.key$)|(^id_rsa)|(^id_ed25519)|(\.keychain)|(^AUTH_TOKEN)", re.I)
APPLE_APP_DIRS = (Path("/Applications"), Path("/System/Applications"), Path("/System/Applications/Utilities"), HOME / "Applications")


class MacActionError(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------------- the folder rules
def _roots() -> list[Path]:
    roots = [HOME]
    volumes = Path("/Volumes")
    if volumes.is_dir():
        for v in volumes.iterdir():
            try:
                if v.is_dir() and not v.is_symlink() and v.resolve() != Path("/"):
                    roots.append(v)
            except OSError:
                continue
    return roots


def safe_path(raw: str, *, must_exist: bool = True) -> Path:
    """The real path, or MacActionError saying plainly why it's off limits."""
    if not raw or not str(raw).strip():
        raise MacActionError("No path given.")
    p = Path(os.path.expanduser(str(raw).strip()))
    if not p.is_absolute():
        p = HOME / p
    try:
        resolved = p.resolve(strict=must_exist)
    except FileNotFoundError:
        raise MacActionError(f"Nothing at {p}.")
    except OSError as exc:
        raise MacActionError(f"Can't reach {p} ({exc.strerror or exc}).")
    if not any(resolved == r or r in resolved.parents for r in _roots()):
        raise MacActionError(f"{resolved} is outside your home folder and plugged-in drives, so Frank can't touch it.")
    rel_parts = resolved.relative_to(HOME).parts if HOME in resolved.parents or resolved == HOME else resolved.parts[3:]
    in_icloud = ICLOUD == resolved or ICLOUD in resolved.parents
    if rel_parts[:1] == ("Library",) and not in_icloud:
        raise MacActionError("Your Library folder holds app data and settings, so Frank can't touch it (iCloud Drive is fine).")
    if any(part.startswith(".") for part in rel_parts if part not in ("..",)):
        raise MacActionError("Hidden files and folders are off limits.")
    if _SECRET_NAME.search(resolved.name) or resolved == REPO_ENV or REPO_DATA == resolved or REPO_DATA in resolved.parents:
        raise MacActionError("That holds keys or P Corp's private data, so Frank can't touch it.")
    return resolved


def _describe(p: Path) -> dict[str, Any]:
    try:
        st = p.stat()
        return {"path": str(p), "name": p.name, "folder": p.is_dir(), "size": None if p.is_dir() else st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")}
    except OSError:
        return {"path": str(p), "name": p.name}


# ----------------------------------------------------------------------------------------------------------------- the actions
def find_files(query: str, folder: str | None = None) -> dict[str, Any]:
    """Files and folders whose NAME contains the words, newest first. Spotlight for the home folder; a short timed walk for drives (Spotlight often skips
    external drives)."""
    words = [w for w in re.split(r"\s+", (query or "").strip().lower()) if w]
    if not words:
        raise MacActionError("Say what to look for.")
    base = safe_path(folder) if folder else None
    hits: list[Path] = []
    use_spotlight = base is None or HOME == base or HOME in base.parents
    if use_spotlight:
        cmd = ["mdfind", "-onlyin", str(base or HOME), "-name", words[0]]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.splitlines()
        except subprocess.TimeoutExpired:
            out = []
        for line in out:
            name = Path(line).name.lower()
            if all(w in name for w in words):
                try:
                    hits.append(safe_path(line))
                except MacActionError:
                    continue
    if base is not None and not use_spotlight or (base is None and len(hits) < FIND_LIMIT):
        starts = [base] if base is not None else [r for r in _roots() if r != HOME]
        deadline = time.monotonic() + WALK_SECONDS
        for start in starts:
            for dirpath, dirnames, filenames in os.walk(start):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("Library",)]
                for name in dirnames + filenames:
                    if all(w in name.lower() for w in words):
                        hits.append(Path(dirpath) / name)
                if time.monotonic() > deadline or len(hits) > 200:
                    break
    seen, out_list = set(), []
    for h in hits:
        if str(h) not in seen:
            seen.add(str(h))
            out_list.append(_describe(h))
    out_list.sort(key=lambda d: d.get("modified") or "", reverse=True)
    return {"query": query, "results": out_list[:FIND_LIMIT], "more": max(0, len(out_list) - FIND_LIMIT)}


def open_path(path: str, reveal: bool = False) -> dict[str, Any]:
    p = safe_path(path)
    subprocess.run(["open", "-R", str(p)] if reveal else ["open", str(p)], check=True, timeout=20)
    return {"opened": str(p), "how": "shown in Finder" if reveal else ("opened in Finder" if p.is_dir() else "opened in its app")}


def open_app(app: str) -> dict[str, Any]:
    name = (app or "").strip().removesuffix(".app")
    if not name or "/" in name:
        raise MacActionError("Give the app's name, e.g. Premiere Pro.")
    found = None
    for d in APPLE_APP_DIRS:
        if not d.is_dir():
            continue
        for candidate in list(d.glob("*.app")) + list(d.glob("*/*.app")):
            if candidate.stem.lower() == name.lower():
                found = candidate
                break
        if found:
            break
    if found is None:
        for d in APPLE_APP_DIRS:
            if d.is_dir():
                matches = [c for c in list(d.glob("*.app")) + list(d.glob("*/*.app")) if name.lower() in c.stem.lower()]
                if matches:
                    found = sorted(matches, key=lambda c: len(c.stem))[0]
                    break
    if found is None:
        raise MacActionError(f"No app called {name} in Applications.")
    subprocess.run(["open", str(found)], check=True, timeout=20)
    return {"opened_app": found.stem}


def open_url(url: str) -> dict[str, Any]:
    u = (url or "").strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", u, re.I) else ""
    if not u:
        raise MacActionError("Give a web address, e.g. render.com.")
    subprocess.run(["open", u], check=True, timeout=20)
    return {"opened_url": u}


def copy_move(source: str, destination: str, mode: str) -> dict[str, Any]:
    if mode not in ("copy", "move", "rename"):
        raise MacActionError("mode must be copy, move or rename.")
    src = safe_path(source)
    if mode == "rename":
        new_name = (destination or "").strip()
        if not new_name or "/" in new_name or new_name in (".", ".."):
            raise MacActionError("For a rename, give just the new name (no folders).")
        dest = src.parent / new_name
    else:
        dest_dir_or_file = safe_path(destination, must_exist=False)
        dest = dest_dir_or_file / src.name if dest_dir_or_file.is_dir() else dest_dir_or_file
    dest = safe_path(str(dest), must_exist=False)
    if not dest.parent.is_dir():
        raise MacActionError(f"The folder {dest.parent} doesn't exist.")
    if dest.exists():
        raise MacActionError(f"Something called {dest.name} is already in {dest.parent}; nothing was overwritten.")
    if mode == "copy":
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    else:
        shutil.move(str(src), str(dest))
    return {"done": mode, "from": str(src), "to": str(dest)}


def move_to_bin(path: str) -> dict[str, Any]:
    """Finder's own "Move to Bin": it can be put back from the Bin. Never a permanent delete."""
    p = safe_path(path)
    if p in _roots():
        raise MacActionError("That's a whole drive or your home folder; Frank won't bin it.")
    script = 'tell application "Finder" to delete (POSIX file "' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '" as alias)'
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=30)
    return {"binned": str(p)}


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "file"


def stage_for_phone(path: str) -> dict[str, Any]:
    """Picks the route for "send me this": small files are read for the cloud inbox; big ones are copied into iCloud Drive."""
    p = safe_path(path)
    if p.is_dir():
        raise MacActionError("That's a folder. Ask for a file, or have Frank find the file you want first.")
    size = p.stat().st_size
    if size <= INBOX_MAX_BYTES:
        return {"via": "cloud", "path": str(p), "name": p.name, "size": size, "content": p.read_bytes()}
    if not ICLOUD.is_dir():
        raise MacActionError(f"{p.name} is {size / 1e6:.0f} MB, too big for the phone inbox (45 MB), and iCloud Drive isn't on this Mac.")
    ICLOUD_INBOX.mkdir(exist_ok=True)
    dest = ICLOUD_INBOX / p.name
    if dest.exists():
        dest = ICLOUD_INBOX / f"{p.stem} {datetime.now().strftime('%H%M%S')}{p.suffix}"
    shutil.copy2(p, dest)
    return {"via": "icloud", "path": str(p), "name": dest.name, "size": size, "icloud_path": str(dest)}


# ----------------------------------------------------------------------------------------------------------------- cloud inbox storage
INBOX_PREFIX = "macinbox-"


async def upload_to_inbox(name: str, content: bytes) -> str:
    """Puts the file in the shared cloud storage under a name the chat's document route serves; returns that name."""
    import httpx
    from app.supabase_storage import _headers, _object_url
    key = f"{INBOX_PREFIX}{uuid.uuid4().hex[:10]}-{_safe_name(name)}"
    headers = _headers(mimetypes.guess_type(name)[0] or "application/octet-stream")
    headers["x-upsert"] = "true"
    async with httpx.AsyncClient() as client:
        resp = await client.post(_object_url(key), headers=headers, content=content, timeout=300.0)
        resp.raise_for_status()
    return key


async def delete_from_inbox(key: str) -> None:
    import httpx
    from app.supabase_storage import _headers, _object_url
    async with httpx.AsyncClient() as client:
        await client.delete(_object_url(key), headers=_headers(), timeout=30.0)


# ----------------------------------------------------------------------------------------------------------------- the phone relay
_COLUMNS = ("id", "created_at", "action", "args_json", "status", "result_json", "updated_at")
MAC_ONLINE_SECONDS = 20
QUEUE_EXPIRES_SECONDS = 120


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _table(conn: Any, name: str) -> str:
    return f"mac.{name}" if conn is not None else f"mac_{name}"


DB_PATH = Path(__file__).parent.parent / "data" / "mac_actions.db"   # local-only stand-in when there is no shared database (tests point it at a temp file)


async def _run(conn: Any, sql: str, params: tuple = ()) -> list[tuple]:
    """One statement, the same SQL on both databases, committed."""
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute(sql.replace("?", "%s"), params)
            rows = await cur.fetchall() if cur.description else []
        await conn.commit()
        return rows
    import aiosqlite
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        await db.commit()
        return [tuple(r) for r in rows]


async def ensure_tables(conn: Any = None) -> None:
    identity = "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if conn is not None else "INTEGER PRIMARY KEY AUTOINCREMENT"
    if conn is not None:
        await _run(conn, "CREATE SCHEMA IF NOT EXISTS mac")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "actions")} (id {identity}, created_at TEXT NOT NULL, action TEXT NOT NULL,
        args_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, updated_at TEXT NOT NULL)""")
    await _run(conn, f"CREATE TABLE IF NOT EXISTS {_table(conn, 'worker')} (id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL)")
    await _run(conn, f"CREATE TABLE IF NOT EXISTS {_table(conn, 'inbox')} (storage_key TEXT PRIMARY KEY, name TEXT NOT NULL, size BIGINT NOT NULL, created_at TEXT NOT NULL)")


async def tables_exist(conn: Any = None) -> bool:
    try:
        await _run(conn, f"SELECT 1 FROM {_table(conn, 'worker')} LIMIT 1")
        return True
    except Exception:
        if conn is not None:
            await conn.rollback()
        return False


async def mac_online(conn: Any = None) -> bool:
    if not await tables_exist(conn):
        return False
    rows = await _run(conn, f"SELECT seen_at FROM {_table(conn, 'worker')} WHERE id = 1")
    return bool(rows and rows[0][0] >= _ago(MAC_ONLINE_SECONDS))


async def queue(action: str, args: dict[str, Any], conn: Any = None) -> int:
    await ensure_tables(conn)
    now = now_iso()
    rows = await _run(conn, f"""INSERT INTO {_table(conn, 'actions')} (created_at, action, args_json, status, updated_at) VALUES (?, ?, ?, 'new', ?) RETURNING id""",
                      (now, action, json.dumps(args), now))
    return int(rows[0][0])


async def wait_for(action_id: int, timeout: float, conn: Any = None) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = await _run(conn, f"SELECT status, result_json FROM {_table(conn, 'actions')} WHERE id = ?", (action_id,))
        if rows and rows[0][0] in ("done", "failed", "expired"):
            return {"status": rows[0][0], "result": json.loads(rows[0][1]) if rows[0][1] else None}
        await asyncio.sleep(1.0)
    return None


async def heartbeat(conn: Any = None) -> None:
    await _run(conn, f"""INSERT INTO {_table(conn, 'worker')} (id, seen_at) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET seen_at = excluded.seen_at""", (now_iso(),))


async def claim(conn: Any = None) -> dict[str, Any] | None:
    await _run(conn, f"UPDATE {_table(conn, 'actions')} SET status = 'expired', updated_at = ? WHERE status = 'new' AND created_at < ?", (now_iso(), _ago(QUEUE_EXPIRES_SECONDS)))
    rows = await _run(conn, f"""UPDATE {_table(conn, 'actions')} SET status = 'running', updated_at = ?
        WHERE id = (SELECT id FROM {_table(conn, 'actions')} WHERE status = 'new' ORDER BY id LIMIT 1) RETURNING id, action, args_json""", (now_iso(),))
    return {"id": int(rows[0][0]), "action": rows[0][1], "args": json.loads(rows[0][2])} if rows else None


async def finish(action_id: int, status: str, result: dict[str, Any], conn: Any = None) -> None:
    await _run(conn, f"UPDATE {_table(conn, 'actions')} SET status = ?, result_json = ?, updated_at = ? WHERE id = ?", (status, json.dumps(result, default=str), now_iso(), action_id))


async def record_inbox(key: str, name: str, size: int, conn: Any = None) -> None:
    await ensure_tables(conn)
    await _run(conn, f"INSERT INTO {_table(conn, 'inbox')} (storage_key, name, size, created_at) VALUES (?, ?, ?, ?)", (key, name, size, now_iso()))


async def expired_inbox(conn: Any = None) -> list[str]:
    rows = await _run(conn, f"SELECT storage_key FROM {_table(conn, 'inbox')} WHERE created_at < ?", (_ago(INBOX_HOURS * 3600),))
    return [r[0] for r in rows]


async def forget_inbox(key: str, conn: Any = None) -> None:
    await _run(conn, f"DELETE FROM {_table(conn, 'inbox')} WHERE storage_key = ?", (key,))


# ----------------------------------------------------------------------------------------------------------------- running one action (on the Mac)
SYNC_ACTIONS = {"find_files": find_files, "open_path": open_path, "open_app": open_app, "open_url": open_url, "copy_move": copy_move, "move_to_bin": move_to_bin}


async def execute(action: str, args: dict[str, Any], conn: Any = None) -> dict[str, Any]:
    """Runs one action on THIS machine (the Mac). Blocking work runs off the event loop with a time limit."""
    if action in SYNC_ACTIONS:
        try:
            return await asyncio.wait_for(asyncio.to_thread(SYNC_ACTIONS[action], **args), timeout=120)
        except asyncio.TimeoutError:
            raise MacActionError("That took too long (a drive may not be responding).")
        except subprocess.CalledProcessError as exc:
            raise MacActionError(f"The Mac refused: {(exc.stderr or b'').decode(errors='replace')[:200] if isinstance(exc.stderr, bytes) else exc}")
        except TypeError as exc:
            raise MacActionError(f"Missing or wrong details for {action}: {exc}")
    if action == "send_to_phone":
        staged = await asyncio.wait_for(asyncio.to_thread(stage_for_phone, args.get("path", "")), timeout=300)
        if staged["via"] == "icloud":
            return {k: v for k, v in staged.items() if k != "content"}
        key = await upload_to_inbox(staged["name"], staged.pop("content"))
        await record_inbox(key, staged["name"], staged["size"], conn)
        return {**staged, "document": key}
    raise MacActionError(f"Unknown action {action}.")
