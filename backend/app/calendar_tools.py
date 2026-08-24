"""
Frank's tools for the real macOS Calendar (app/system_calendar.py),
2026-08-24. Same shape as personal_tools.py/joshx_tools.py: narrow,
hardcoded actions via the plain SDK's tool-use. "Regular" permission
tier under SECURITY.md's model -- local, reversible (an event can always
be rescheduled or recreated), no external effect on anyone else, since
these tools never touch attendees/invites (see system_calendar.py's own
docstring for why that's a deliberate, separate boundary).

No consult_calendar_agent -- there's nothing here to delegate; these are
four plain actions on Josh's own calendar, not a domain complex enough
to need a specialist's commentary.
"""

from datetime import datetime

from app.system_calendar import create_event, delete_event, list_events, update_event

CREATE_CALENDAR_EVENT_TOOL = {
    "name": "create_calendar_event",
    "description": (
        "Create a new event on Josh's real macOS Calendar. Personal events only -- "
        "never adds attendees or sends invites."
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

UPDATE_CALENDAR_EVENT_TOOL = {
    "name": "update_calendar_event",
    "description": (
        "Reschedule or rename an existing upcoming event, matched by a title fragment. "
        "Only give the fields that should change -- everything else on the event stays as is."
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

DELETE_CALENDAR_EVENT_TOOL = {
    "name": "delete_calendar_event",
    "description": "Cancel/remove an upcoming event, matched by a title fragment.",
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
    "description": "Check what's actually on Josh's calendar in the coming days -- use before booking or moving anything, to avoid double-booking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "How many days ahead to check. Defaults to 7."},
        },
        "required": [],
    },
}

CALENDAR_TOOLS = [
    CREATE_CALENDAR_EVENT_TOOL,
    UPDATE_CALENDAR_EVENT_TOOL,
    DELETE_CALENDAR_EVENT_TOOL,
    LIST_CALENDAR_EVENTS_TOOL,
]
CALENDAR_TOOL_NAMES = {tool["name"] for tool in CALENDAR_TOOLS}


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


async def execute_calendar_tool_call(name: str, tool_input: dict) -> str:
    if name == "create_calendar_event":
        try:
            start = _parse_dt(tool_input["start"])
            end = _parse_dt(tool_input["end"])
        except ValueError:
            return "Couldn't parse those dates -- use a format like \"2026-08-26 14:00\"."
        ok = await create_event(
            tool_input["title"], start, end, tool_input.get("calendar_name"), tool_input.get("location")
        )
        return f"Created \"{tool_input['title']}\" on the calendar." if ok else "Couldn't create that event."

    if name == "update_calendar_event":
        try:
            new_start = _parse_dt(tool_input["new_start"]) if "new_start" in tool_input else None
            new_end = _parse_dt(tool_input["new_end"]) if "new_end" in tool_input else None
        except ValueError:
            return "Couldn't parse those dates -- use a format like \"2026-08-26 14:00\"."
        ok = await update_event(tool_input["identifier"], tool_input.get("new_title"), new_start, new_end)
        if ok:
            return "Updated the event."
        return f"No matching upcoming event found for \"{tool_input['identifier']}\", or the update was invalid."

    if name == "delete_calendar_event":
        ok = await delete_event(tool_input["identifier"])
        return "Removed the event." if ok else f"No matching upcoming event found for \"{tool_input['identifier']}\"."

    if name == "list_calendar_events":
        events = await list_events(tool_input.get("days", 7))
        if not events:
            return "Nothing on the calendar in that window."
        lines = [f"- {e['title']} ({e['calendar']}): {e['start']} to {e['end']}" for e in events]
        return "\n".join(lines)

    return f"Unknown tool: {name}"
