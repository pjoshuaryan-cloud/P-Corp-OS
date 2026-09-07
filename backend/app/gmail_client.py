"""
Raw Gmail REST calls (2026-08-27), read-only. Backs email_db.py's sync --
never imported by email_tools.py directly, so Frank's tools only ever see
already-synced rows out of email_db.py, never a live Gmail response.

Fail-soft throughout (try/except: return []/None), matching
alpha_mode_supabase.py's own convention -- a missing/expired token or a
Gmail API hiccup should never crash Frank's turn or the periodic sync
tick, just come back empty.
"""

from email.utils import parseaddr

import httpx

from app.google_oauth import get_valid_access_token, google_api_get

MESSAGES_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
MESSAGES_GET_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"


def _header(headers: list[dict], name: str) -> str | None:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


async def _get_message(http: httpx.AsyncClient, token: str, message_id: str) -> dict | None:
    payload = await google_api_get(
        http,
        MESSAGES_GET_URL.format(id=message_id),
        token,
        params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
    )
    if payload is None:
        return None

    headers = payload.get("payload", {}).get("headers", [])
    from_header = _header(headers, "From") or ""
    sender_name, sender_email = parseaddr(from_header)
    return {
        "id": payload["id"],
        "thread_id": payload.get("threadId", payload["id"]),
        "sender_email": sender_email or None,
        "sender_name": sender_name or None,
        "subject": _header(headers, "Subject"),
        "snippet": payload.get("snippet"),
        "received_at": _header(headers, "Date"),
    }


async def fetch_recent_messages(max_results: int = 20, query: str | None = None) -> list[dict]:
    """Lists recent message ids, then fetches metadata for each -- Gmail's
    list endpoint doesn't return headers/snippet inline for anything
    beyond the raw id/threadId, so a second call per message is required.
    Returns [] on any failure (no token yet, expired grant, network
    error) rather than raising."""
    token = await get_valid_access_token()
    if token is None:
        return []
    async with httpx.AsyncClient(timeout=15.0) as http:
        params: dict = {"maxResults": max_results}
        if query:
            params["q"] = query
        result = await google_api_get(http, MESSAGES_LIST_URL, token, params=params)
        if result is None:
            return []
        ids = [m["id"] for m in result.get("messages", [])]

        messages = []
        for message_id in ids:
            message = await _get_message(http, token, message_id)
            if message is not None:
                messages.append(message)
        return messages
