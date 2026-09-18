"""
Frank's tools for the Gmail read-log (app/email_db.py), 2026-08-27. Same
shape as people_tools.py: narrow, hardcoded actions via the plain SDK's
tool-use.

Deliberately no build_email_block() -- unlike Joshx/Personal/People's
small, stable lists, email volume would bloat Frank's system prompt on
every single turn. Surfaced only when Frank actually calls one of these
tools, matching Shadow Mode's own "never proactively volunteer unasked"
discipline.

No consult_email_agent, same call already made for Personal/Joshx/
People/Calendar -- these are plain read actions, not a domain complex
enough to need a specialist's commentary.

Update (2026-09-18): propose_send_email added -- a deliberate, explicit
reversal of this module's own former "read-only, no send tool, ever"
framing (AGENTS_VISION.md's Communications Agent section had recorded
"no send tool at all" as a standing decision). Asked Josh directly
rather than just building it: he chose approval-gated send specifically
-- Frank drafts, Josh sees the exact to/subject/body on a real approval
card, and it only actually sends after explicit approval, mirroring
calendar_tools.py's/alpha_mode_tools.py's own propose_*/_request_approval
shape exactly (own request_id, blocks on websocket.receive_text(), fails
closed on rejection/malformed reply) -- a fifth occurrence of a pattern
this codebase has now built four times independently. Needs the new
gmail.send scope (google_oauth.py); Josh must re-consent once through
/auth/google/start before this actually works.
"""

import json
import uuid

from fastapi import WebSocket

from app.email_db import get_email_by_id, get_recent_emails, search_emails, sync_recent_emails
from app.gmail_client import send_message

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

READ_EMAIL_TOOL = {
    "name": "read_email",
    "description": (
        "Read one specific already-synced email in full, by its id (from get_recent_emails/search_emails' "
        "own results) -- those two only ever return a short snippet preview to avoid bloating every turn "
        "with full email text, so call this once you know which message Josh actually wants read in full."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "The email's id, as returned by get_recent_emails/search_emails."},
        },
        "required": ["id"],
    },
}

PROPOSE_SEND_EMAIL_TOOL = {
    "name": "propose_send_email",
    "description": (
        "Proposes sending a new email through Josh's real Gmail account. Does NOT send it immediately -- sends "
        "Josh a real approval card showing the exact recipient/subject/body and blocks until he approves or "
        "rejects. A fresh standalone message only -- no reply-threading yet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Plain-text email body."},
        },
        "required": ["to", "subject", "body"],
    },
}

EMAIL_TOOLS = [GET_RECENT_EMAILS_TOOL, SEARCH_EMAILS_TOOL, READ_EMAIL_TOOL, PROPOSE_SEND_EMAIL_TOOL]
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


async def _request_approval(websocket: WebSocket, tool: str, title: str, details: str) -> bool:
    """Mirrors calendar_tools.py's/alpha_mode_tools.py's _request_approval
    mechanics exactly. Returns True only on an explicit, correctly-matched
    approval -- fails closed (False) on rejection, a stale/mismatched id,
    or any malformed reply."""
    request_id = str(uuid.uuid4())
    payload = json.dumps({"id": request_id, "tool": tool, "title": title, "details": details})
    await websocket.send_text(f"\n[email_approval_request]{payload}")

    raw = await websocket.receive_text()
    try:
        response = json.loads(raw)["approval_response"]
        return bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


async def execute_email_tool_call(name: str, tool_input: dict, websocket: WebSocket, postgres_conn=None) -> str:
    if name == "get_recent_emails":
        await sync_recent_emails(max_results=tool_input.get("limit", 10), postgres_conn=postgres_conn)
        emails = await get_recent_emails(tool_input.get("limit", 10), postgres_conn)
        if not emails:
            return "No emails found -- either nothing recent, or Gmail isn't connected yet (see /auth/google/start)."
        return _format(emails)

    if name == "search_emails":
        emails = await search_emails(tool_input["query"], tool_input.get("limit", 10), postgres_conn)
        if not emails:
            return f"No synced emails matching \"{tool_input['query']}\"."
        return _format(emails)

    if name == "read_email":
        email = await get_email_by_id(tool_input["id"], postgres_conn)
        if email is None:
            return f"No synced email found with id {tool_input['id']!r}."
        who = email["sender_name"] or email["sender_email"] or "unknown sender"
        body = email["body"] or email["snippet"] or "(no readable body -- was synced before full-body support, or Gmail returned no text content)"
        return f"From {who} — \"{email['subject'] or '(no subject)'}\" ({email['received_at']})\n\n{body}"

    if name == "propose_send_email":
        to = tool_input["to"]
        subject = tool_input["subject"]
        body = tool_input["body"]
        if "@" not in to:
            return f"\"{to}\" doesn't look like a valid email address -- nothing was proposed."
        approved = await _request_approval(websocket, name, f"To: {to} — {subject}", body)
        if not approved:
            return f"Rejected by Josh: email to {to} was not sent."
        ok = await send_message(to, subject, body, postgres_conn)
        if ok:
            return f"Approved and sent to {to}."
        return "Approved, but sending failed -- Gmail isn't connected with send permission yet (Josh needs to re-consent via /auth/google/start), or a real Gmail API error occurred."

    return f"Unknown tool: {name}"
