"""
Frank's tools for the Gmail read-log (app/email_db.py), 2026-08-27. Same
shape as people_tools.py: narrow, hardcoded actions via the plain SDK's
tool-use. Read-only -- there is no send/reply/forward tool here, and
never will be, per the original brief's constraint (Communications Agent
stays draft-only; this module doesn't touch Communications Agent at all).

Deliberately no build_email_block() -- unlike Joshx/Personal/People's
small, stable lists, email volume would bloat Frank's system prompt on
every single turn. Surfaced only when Frank actually calls one of these
tools, matching Shadow Mode's own "never proactively volunteer unasked"
discipline.

No consult_email_agent, same call already made for Personal/Joshx/
People/Calendar -- these are plain read actions, not a domain complex
enough to need a specialist's commentary.
"""

from app.email_db import get_recent_emails, search_emails, sync_recent_emails

GET_RECENT_EMAILS_TOOL = {
    "name": "get_recent_emails",
    "description": (
        "Check Josh's most recent Gmail messages. Syncs the latest messages first, then returns them -- "
        "read-only, this never sends, replies, or forwards anything."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "How many recent messages to return. Defaults to 10."},
        },
        "required": [],
    },
}

SEARCH_EMAILS_TOOL = {
    "name": "search_emails",
    "description": (
        "Search Josh's already-synced Gmail messages by subject, sender, or snippet text. Searches what's "
        "already been synced locally, not a live Gmail search -- call get_recent_emails first if the answer "
        "might be in something not yet synced."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "Defaults to 10."},
        },
        "required": ["query"],
    },
}

EMAIL_TOOLS = [GET_RECENT_EMAILS_TOOL, SEARCH_EMAILS_TOOL]
EMAIL_TOOL_NAMES = {tool["name"] for tool in EMAIL_TOOLS}


def _format(emails: list[dict]) -> str:
    lines = []
    for e in emails:
        who = e["sender_name"] or e["sender_email"] or "unknown sender"
        link = ""
        if e.get("linked_person_id"):
            link = " [linked person]"
        elif e.get("linked_client_name"):
            link = f" [linked client: {e['linked_client_name']}]"
        lines.append(f"- From {who} — \"{e['subject'] or '(no subject)'}\" ({e['received_at']}){link}\n  {e['snippet'] or ''}")
    return "\n".join(lines)


async def execute_email_tool_call(name: str, tool_input: dict) -> str:
    if name == "get_recent_emails":
        await sync_recent_emails(max_results=tool_input.get("limit", 10))
        emails = await get_recent_emails(tool_input.get("limit", 10))
        if not emails:
            return "No emails found -- either nothing recent, or Gmail isn't connected yet (see /auth/google/start)."
        return _format(emails)

    if name == "search_emails":
        emails = await search_emails(tool_input["query"], tool_input.get("limit", 10))
        if not emails:
            return f"No synced emails matching \"{tool_input['query']}\"."
        return _format(emails)

    return f"Unknown tool: {name}"
