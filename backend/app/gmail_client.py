"""
Raw Gmail REST calls (2026-08-27), read-only. Backs email_db.py's sync --
never imported by email_tools.py directly, so Frank's tools only ever see
already-synced rows out of email_db.py, never a live Gmail response.

Fail-soft throughout (try/except: return []/None), matching
alpha_mode_supabase.py's own convention -- a missing/expired token or a
Gmail API hiccup should never crash Frank's turn or the periodic sync
tick, just come back empty.

Update (2026-09-18): fetches `format=full` instead of `format=metadata`
and decodes the actual message body -- the old metadata-only fetch never
requested a body at all, so the only text ever available anywhere
downstream was Gmail's own ~100-character auto-generated `snippet`,
which is why Frank could only ever show "the first line." No new scope
needed -- still the same read-only gmail.readonly grant, just asking for
more of what it already permits.
"""

import base64
import re
from email.utils import parseaddr
from html.parser import HTMLParser

import httpx

from app.google_oauth import get_valid_access_token, google_api_get

MESSAGES_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
MESSAGES_GET_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"


def _header(headers: list[dict], name: str) -> str | None:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


class _HTMLTextExtractor(HTMLParser):
    """Minimal, dependency-free HTML-to-text for a text/html-only body --
    deliberately not pulling in bs4/lxml just for this (lxml is only an
    incidental transitive dependency of other packages today, not
    something this app has ever depended on directly), matching this
    codebase's own established "plain stdlib/httpx, no heavy SDK"
    convention. Good enough for reading an email, not a general-purpose
    renderer."""

    _BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def _decode_part_data(data: str) -> str:
    # Gmail's body data is base64url, sometimes missing its padding.
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body(payload: dict) -> str | None:
    """Walks a (possibly nested multipart) Gmail message payload for the
    best available body text. text/plain is preferred when present;
    text/html is decoded and stripped to plain text otherwise -- either
    way this returns what a human would actually read, not raw MIME."""
    plain: str | None = None
    html: str | None = None

    def walk(part: dict) -> None:
        nonlocal plain, html
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if body_data:
            if mime_type == "text/plain" and plain is None:
                plain = _decode_part_data(body_data)
            elif mime_type == "text/html" and html is None:
                html = _decode_part_data(body_data)
        for sub_part in part.get("parts") or []:
            walk(sub_part)

    walk(payload)
    if plain:
        return plain.strip()
    if html:
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.text()
    return None


async def _get_message(http: httpx.AsyncClient, token: str, message_id: str) -> dict | None:
    payload = await google_api_get(
        http,
        MESSAGES_GET_URL.format(id=message_id),
        token,
        params={"format": "full"},
    )
    if payload is None:
        return None

    message_payload = payload.get("payload", {})
    headers = message_payload.get("headers", [])
    from_header = _header(headers, "From") or ""
    sender_name, sender_email = parseaddr(from_header)
    return {
        "id": payload["id"],
        "thread_id": payload.get("threadId", payload["id"]),
        "sender_email": sender_email or None,
        "sender_name": sender_name or None,
        "subject": _header(headers, "Subject"),
        "snippet": payload.get("snippet"),
        "body": _extract_body(message_payload),
        "received_at": _header(headers, "Date"),
    }


async def fetch_recent_messages(max_results: int = 20, query: str | None = None, postgres_conn=None) -> list[dict]:
    """Lists recent message ids, then fetches metadata for each -- Gmail's
    list endpoint doesn't return headers/snippet inline for anything
    beyond the raw id/threadId, so a second call per message is required.
    Returns [] on any failure (no token yet, expired grant, network
    error) rather than raising."""
    token = await get_valid_access_token(postgres_conn)
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
