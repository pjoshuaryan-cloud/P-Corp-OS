"""Frank's Mac tools (2026-11-20) -- what Frank can do on Josh's Mac, from the Mac app or the phone. The actions themselves and the folder rules live in
mac_actions.py; this file is the part Frank sees: the tool descriptions, the tap-to-confirm card for anything that changes or sends a file, and the choice
between running here (this IS the Mac) and queueing for the Mac (this is the cloud server, so the phone asked).
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from fastapi import WebSocket

from app import mac_actions
from app.mac_actions import MacActionError

_PATH = {"type": "string", "description": "A full path on the Mac, e.g. /Users/joshuapeters/Desktop/Invoices or /Volumes/Joshx/Shoots. Use find_files_on_mac first if you don't know it."}

MAC_TOOLS = [
    {"name": "find_files_on_mac",
     "description": "Find files or folders on Josh's Mac (home folder and plugged-in drives) whose NAME contains the given words. Newest first, up to 25. "
                    "Read-only. Use it to get the exact path before opening, sending, copying or binning something.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words in the file or folder name, e.g. 'JD invoice' or 'birkenstock'."},
         "folder": {"type": "string", "description": "Optional: only look inside this folder (a full path)."}}, "required": ["query"]}},
    {"name": "open_on_mac",
     "description": "Open a folder in Finder, or a file in its usual app, on Josh's Mac screen. reveal=true shows the file selected in Finder instead of opening it.",
     "input_schema": {"type": "object", "properties": {"path": _PATH, "reveal": {"type": "boolean"}}, "required": ["path"]}},
    {"name": "open_app_on_mac",
     "description": "Open an app on Josh's Mac by name (e.g. 'Premiere Pro 2027', 'MetaTrader 5', 'Finder'). Only apps already installed.",
     "input_schema": {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}},
    {"name": "open_website_on_mac",
     "description": "Open a web address in the Mac's browser.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "send_file_to_phone",
     "description": "Send one file from the Mac to Josh's iPhone (his 'airdrop me this'). Josh confirms with a tap first. Files up to 45 MB arrive in this "
                    "chat as an attachment he can open, save or share (kept 24 hours); bigger files are copied to iCloud Drive > P Corp Inbox, which "
                    "the Files app on his phone shows. Not for folders.",
     "input_schema": {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}},
    {"name": "copy_or_move_on_mac",
     "description": "Copy, move or rename a file or folder on the Mac. Josh confirms with a tap first. Never overwrites: if the name is taken it stops. "
                    "For copy/move, destination is a folder (or a full new path); for rename, destination is just the new name.",
     "input_schema": {"type": "object", "properties": {"source": _PATH, "destination": {"type": "string"},
                                                       "mode": {"type": "string", "enum": ["copy", "move", "rename"]}},
                      "required": ["source", "destination", "mode"]}},
    {"name": "move_to_bin_on_mac",
     "description": "Move a file or folder on the Mac to the Bin (it can be put back from the Bin; nothing is deleted permanently). Josh confirms with a tap first.",
     "input_schema": {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}},
]
MAC_TOOL_NAMES = {t["name"] for t in MAC_TOOLS}

# tool name -> (action in mac_actions, needs Josh's tap)
_ACTIONS = {
    "find_files_on_mac": ("find_files", False),
    "open_on_mac": ("open_path", False),
    "open_app_on_mac": ("open_app", False),
    "open_website_on_mac": ("open_url", False),
    "send_file_to_phone": ("send_to_phone", True),
    "copy_or_move_on_mac": ("copy_move", True),
    "move_to_bin_on_mac": ("move_to_bin", True),
}
RELAY_WAIT_SECONDS = 45
SEND_WAIT_SECONDS = 180


def on_the_mac() -> bool:
    """This backend is the Mac's own (the cloud server always has PORT set)."""
    return not os.environ.get("PORT")


def _args(tool: str, tool_input: dict) -> dict[str, Any]:
    if tool == "find_files_on_mac":
        return {"query": tool_input.get("query", ""), **({"folder": tool_input["folder"]} if tool_input.get("folder") else {})}
    if tool == "open_on_mac":
        return {"path": tool_input.get("path", ""), "reveal": bool(tool_input.get("reveal"))}
    if tool == "open_app_on_mac":
        return {"app": tool_input.get("app", "")}
    if tool == "open_website_on_mac":
        return {"url": tool_input.get("url", "")}
    if tool == "copy_or_move_on_mac":
        return {"source": tool_input.get("source", ""), "destination": tool_input.get("destination", ""), "mode": tool_input.get("mode", "")}
    return {"path": tool_input.get("path", "")}


def _card(tool: str, a: dict[str, Any]) -> tuple[str, str]:
    if tool == "send_file_to_phone":
        return "Send to your iPhone", a["path"]
    if tool == "copy_or_move_on_mac":
        verb = {"copy": "Copy", "move": "Move", "rename": "Rename"}.get(a["mode"], a["mode"])
        return f"{verb} on your Mac", f"{a['source']}\n→ {a['destination']}"
    return "Move to the Bin on your Mac", f"{a['path']}\n(You can put it back from the Bin.)"


async def _request_approval(websocket: WebSocket, tool: str, title: str, details: str) -> bool:
    """Same mechanics as email_tools._request_approval; fails closed on anything but a matching yes."""
    request_id = str(uuid.uuid4())
    await websocket.send_text("\n[mac_approval_request]" + json.dumps({"id": request_id, "tool": tool, "title": title, "details": details}))
    raw = await websocket.receive_text()
    try:
        response = json.loads(raw)["approval_response"]
        return bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


async def _run(action: str, a: dict[str, Any], postgres_conn) -> dict[str, Any]:
    """Here if this is the Mac; otherwise through the shared database to the Mac's loop. Raises MacActionError with words Frank can repeat."""
    if on_the_mac():
        return await mac_actions.execute(action, a, postgres_conn)
    if postgres_conn is None:
        raise MacActionError("The cloud server can't reach the shared database right now, so it can't pass this to your Mac.")
    if not await mac_actions.mac_online(postgres_conn):
        raise MacActionError("Your Mac isn't answering (it's asleep, off, or P Corp isn't running on it), so this can't be done from the phone right now.")
    action_id = await mac_actions.queue(action, a, postgres_conn)
    out = await mac_actions.wait_for(action_id, SEND_WAIT_SECONDS if action == "send_to_phone" else RELAY_WAIT_SECONDS, postgres_conn)
    if out is None:
        raise MacActionError("Your Mac took too long to answer. It may still finish it; check before asking again.")
    if out["status"] == "expired":
        raise MacActionError("Your Mac didn't pick this up in time (it may have just gone to sleep).")
    if out["status"] == "failed":
        raise MacActionError((out.get("result") or {}).get("error") or "Your Mac couldn't do it.")
    return out.get("result") or {}


def _say(tool: str, result: dict[str, Any]) -> str:
    if tool == "find_files_on_mac":
        rows = result.get("results") or []
        if not rows:
            return f"Nothing on the Mac with \"{result.get('query')}\" in its name."
        lines = [f"- {r['path']}" + (" (folder)" if r.get("folder") else f" ({(r.get('size') or 0) / 1e6:.1f} MB)") + (f", changed {r['modified']}" if r.get("modified") else "")
                 for r in rows]
        more = f"\n…and {result['more']} more; ask with more words to narrow it." if result.get("more") else ""
        return "Found on the Mac:\n" + "\n".join(lines) + more
    if tool == "send_file_to_phone":
        if result.get("via") == "icloud":
            return (f"{result['name']} ({result['size'] / 1e6:.0f} MB) is too big for the chat, so it was copied to iCloud Drive > P Corp Inbox. "
                    "Open the Files app on the iPhone > iCloud Drive > P Corp Inbox (it can take a minute or two to sync).")
        return f"Sent {result['name']} ({result['size'] / 1e6:.1f} MB). It's attached in this chat; tap it to open, save or share. It's kept for 24 hours."
    return "Done on the Mac: " + json.dumps(result)


async def execute_mac_tool_call(name: str, tool_input: dict, websocket: WebSocket, postgres_conn=None) -> tuple[str, dict | None]:
    """Returns (text for Frank, the sent file's {filename, title} for the chat attachment, or None)."""
    action, needs_tap = _ACTIONS[name]
    a = _args(name, tool_input)
    if needs_tap:
        title, details = _card(name, a)
        if not await _request_approval(websocket, name, title, details):
            return "Josh said no (or the card was dismissed), so nothing was done.", None
    try:
        result = await _run(action, a, postgres_conn)
    except MacActionError as exc:
        return f"Couldn't do it: {exc}", None
    except Exception as exc:   # a real failure (network, storage) -- said plainly, never crashes the chat
        return f"Couldn't do it: {type(exc).__name__}: {str(exc)[:200]}", None
    document = {"filename": result["document"], "title": result["name"]} if result.get("document") else None
    return _say(name, result), document


# ----------------------------------------------------------------------------------------------------------------- the Mac's loop (main.py)
async def relay_pass(conn) -> bool:
    """One pass of the Mac's side: beat, clear old phone files, run one queued action. True if it ran one."""
    await mac_actions.heartbeat(conn)
    for key in await mac_actions.expired_inbox(conn):
        try:
            await mac_actions.delete_from_inbox(key)
        except Exception as exc:
            print(f"[mac relay] couldn't remove {key} from storage: {type(exc).__name__}")
            continue
        await mac_actions.forget_inbox(key, conn)
    job = await mac_actions.claim(conn)
    if job is None:
        return False
    print(f"[mac relay] running {job['action']} (#{job['id']}) for the phone")
    try:
        result = await mac_actions.execute(job["action"], job["args"], conn)
        await mac_actions.finish(job["id"], "done", result, conn)
    except MacActionError as exc:
        await mac_actions.finish(job["id"], "failed", {"error": str(exc)}, conn)
    except Exception as exc:
        await mac_actions.finish(job["id"], "failed", {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, conn)
    return True
