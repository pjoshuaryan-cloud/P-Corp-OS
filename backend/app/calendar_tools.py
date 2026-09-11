"""
Frank's tools for Josh's calendar(s), 2026-08-24. Same shape as
personal_tools.py/joshx_tools.py: narrow, hardcoded actions via the plain
SDK's tool-use.

Auto-scheduling, 2026-08-30 (item 5 of the six-part brief): the three
write tools -- propose_create_calendar_event/propose_update_calendar_event/
propose_delete_calendar_event -- no longer write immediately. Renamed from
their old create_calendar_event/update_calendar_event/delete_calendar_event
names specifically so the tool name itself tells Frank what it does (a
tool called "create_calendar_event" reads as "does it now"; a name
matching propose_file_edit's own convention doesn't). Each sends a real
approval card over the websocket and blocks until Josh approves or
rejects, exactly mirroring agent_codebase_tools.py's `_propose_file_edit`
-- copied directly rather than factored into a shared helper, since this
is only the second approval flow ever built in this codebase (the first
being propose_file_edit itself); a shared abstraction waits for a third
occurrence, same "rule of three" already applied when
agent_codebase_tools.py itself was extracted from engineering_agent.py.

No before/after diff like file edits get -- there's no existing "look up
this event's current fields" helper, and update/delete already resolve
their target via AppleScript's own fuzzy title match at execution time
(unchanged, same as before this feature). The card shows the proposed
change's own fields, not a computed diff against current state -- a
real, disclosed simplification, not an oversight.

list_calendar_events stays read-only, unchanged, reading from
app/calendar_db.py's cache (merges the AppleScript calendar with the
read-only Google Calendar sync, google_calendar_client.py -- Google
Calendar itself stays read-only; any approved write here still only ever
goes through system_calendar.py's AppleScript path, same as before).

No consult_calendar_agent -- there's nothing here to delegate; these are
plain actions on Josh's own calendar(s), not a domain complex enough to
need a specialist's commentary.
"""

import json
import uuid
from datetime import datetime

from fastapi import WebSocket

from app.calendar_db import get_cached_events
from app.system_calendar import check_calendar_available, create_event, delete_event, update_event

_CALENDAR_UNAVAILABLE_MESSAGE = (
    "Mac Calendar isn't reachable right now (Local Node capability unavailable) -- nothing was proposed."
)

PROPOSE_CREATE_CALENDAR_EVENT_TOOL = {
    "name": "propose_create_calendar_event",
    "description": (
        "Proposes creating a new event on Josh's real macOS Calendar. Does NOT create it immediately -- sends "
        "Josh a real approval card and blocks until he approves or rejects. Personal events only -- never adds "
        "attendees or sends invites."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "e.g. \"2026-08-26 14:00\"."},
            "end": {"type": "string", "description": "e.g. \"2026-08-26 14:30\"."},
            "calendar_name": {
                "type": "string",
                "description": "Which calendar, e.g. \"Home\", \"Work\". Omit to use Josh's first calendar.",
            },
            "location": {"type": "string"},
        },
        "required": ["title", "start", "end"],
    },
}

PROPOSE_UPDATE_CALENDAR_EVENT_TOOL = {
    "name": "propose_update_calendar_event",
    "description": (
        "Proposes rescheduling or renaming an existing upcoming event, matched by a title fragment. Does NOT "
        "change it immediately -- sends Josh a real approval card and blocks until he approves or rejects. Only "
        "give the fields that should change -- everything else on the event stays as is."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The event's current title, or a close match."},
            "new_title": {"type": "string"},
            "new_start": {"type": "string", "description": "e.g. \"2026-08-26 14:00\"."},
            "new_end": {"type": "string", "description": "e.g. \"2026-08-26 14:30\"."},
        },
        "required": ["identifier"],
    },
}

PROPOSE_DELETE_CALENDAR_EVENT_TOOL = {
    "name": "propose_delete_calendar_event",
    "description": (
        "Proposes cancelling/removing an upcoming event, matched by a title fragment. Does NOT remove it "
        "immediately -- sends Josh a real approval card and blocks until he approves or rejects."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The event's title, or a close match."},
        },
        "required": ["identifier"],
    },
}

LIST_CALENDAR_EVENTS_TOOL = {
    "name": "list_calendar_events",
    "description": "Check what's actually on Josh's calendar in the coming days -- covers both the macOS Calendar and, if connected, Google Calendar. Use before booking or moving anything, to avoid double-booking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "How many days ahead to check. Defaults to 7."},
        },
        "required": [],
    },
}

CALENDAR_TOOLS = [
    PROPOSE_CREATE_CALENDAR_EVENT_TOOL,
    PROPOSE_UPDATE_CALENDAR_EVENT_TOOL,
    PROPOSE_DELETE_CALENDAR_EVENT_TOOL,
    LIST_CALENDAR_EVENTS_TOOL,
]
CALENDAR_TOOL_NAMES = {tool["name"] for tool in CALENDAR_TOOLS}


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


async def _request_approval(websocket: WebSocket, tool: str, title: str, details: str, start: str | None, end: str | None) -> bool:
    """Mirrors agent_codebase_tools.py's `_propose_file_edit` blocking-
    approval mechanics exactly, adapted for calendar fields instead of a
    path/diff. Returns True only on an explicit, correctly-matched
    approval -- fails closed (False) on rejection, a stale/mismatched id,
    or any malformed reply, same as the file-edit flow."""
    request_id = str(uuid.uuid4())
    payload = json.dumps({"id": request_id, "tool": tool, "title": title, "details": details, "start": start, "end": end})
    await websocket.send_text(f"\n[calendar_approval_request]{payload}")

    # Blocks here -- same single-in-flight-receive contract propose_file_edit
    # relies on: nothing else reads this socket while this turn is in-flight.
    raw = await websocket.receive_text()
    try:
        response = json.loads(raw)["approval_response"]
        return bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


async def execute_calendar_tool_call(name: str, tool_input: dict, websocket: WebSocket, postgres_conn=None) -> str:
    if name == "propose_create_calendar_event":
        if not await check_calendar_available():
            return _CALENDAR_UNAVAILABLE_MESSAGE
        try:
            start = _parse_dt(tool_input["start"])
            end = _parse_dt(tool_input["end"])
        except ValueError:
            return "Couldn't parse those dates -- use a format like \"2026-08-26 14:00\"."
        details = f"{start.isoformat(sep=' ', timespec='minutes')} to {end.isoformat(sep=' ', timespec='minutes')}"
        if tool_input.get("calendar_name"):
            details += f", {tool_input['calendar_name']} calendar"
        if tool_input.get("location"):
            details += f", at {tool_input['location']}"
        approved = await _request_approval(
            websocket, name, tool_input["title"], details, start.isoformat(), end.isoformat()
        )
        if not approved:
            return f"Rejected by Josh: \"{tool_input['title']}\" was not created."
        ok = await create_event(
            tool_input["title"], start, end, tool_input.get("calendar_name"), tool_input.get("location")
        )
        return f"Approved and created \"{tool_input['title']}\" on the calendar." if ok else "Approved, but the event couldn't actually be created."

    if name == "propose_update_calendar_event":
        if not await check_calendar_available():
            return _CALENDAR_UNAVAILABLE_MESSAGE
        try:
            new_start = _parse_dt(tool_input["new_start"]) if "new_start" in tool_input else None
            new_end = _parse_dt(tool_input["new_end"]) if "new_end" in tool_input else None
        except ValueError:
            return "Couldn't parse those dates -- use a format like \"2026-08-26 14:00\"."
        changes = []
        if tool_input.get("new_title"):
            changes.append(f"rename to \"{tool_input['new_title']}\"")
        if new_start and new_end:
            changes.append(f"move to {new_start.isoformat(sep=' ', timespec='minutes')}–{new_end.isoformat(sep=' ', timespec='minutes')}")
        elif new_start:
            changes.append(f"move start to {new_start.isoformat(sep=' ', timespec='minutes')}")
        elif new_end:
            changes.append(f"move end to {new_end.isoformat(sep=' ', timespec='minutes')}")
        details = "; ".join(changes) if changes else "no actual changes given"
        approved = await _request_approval(
            websocket,
            name,
            tool_input["identifier"],
            details,
            new_start.isoformat() if new_start else None,
            new_end.isoformat() if new_end else None,
        )
        if not approved:
            return f"Rejected by Josh: \"{tool_input['identifier']}\" was not changed."
        ok = await update_event(tool_input["identifier"], tool_input.get("new_title"), new_start, new_end)
        if ok:
            return "Approved and updated the event."
        return f"Approved, but no matching upcoming event was found for \"{tool_input['identifier']}\", or the update was invalid."

    if name == "propose_delete_calendar_event":
        if not await check_calendar_available():
            return _CALENDAR_UNAVAILABLE_MESSAGE
        approved = await _request_approval(
            websocket, name, tool_input["identifier"], "Cancel this event", None, None
        )
        if not approved:
            return f"Rejected by Josh: \"{tool_input['identifier']}\" was not cancelled."
        ok = await delete_event(tool_input["identifier"])
        return "Approved and removed the event." if ok else f"Approved, but no matching upcoming event was found for \"{tool_input['identifier']}\"."

    if name == "list_calendar_events":
        events = await get_cached_events(tool_input.get("days", 7), postgres_conn)
        if not events:
            return "Nothing on the calendar in that window."
        lines = [f"- {e['title']} ({e['calendar_name']}): {e['start']} to {e['end']}" for e in events]
        return "\n".join(lines)

    return f"Unknown tool: {name}"
