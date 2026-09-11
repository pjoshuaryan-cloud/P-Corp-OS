"""
Shared Google OAuth2 module (2026-08-27) backing both Gmail read access
(gmail_client.py/email_db.py) and Google Calendar sync (google_calendar_client.py/
calendar_db.py) -- one grant, one token, since both scopes are requested
together and both consumers need the exact same "is there a valid access
token right now" question answered the same way.

Plain httpx against Google's OAuth endpoints directly, no google-auth/
google-auth-oauthlib/google-api-python-client -- confirmed neither is a
current or transitive dependency (pyproject.toml/uv.lock), and this
matches the codebase's own established "plain REST, no heavy SDK"
convention (supabase_client.py does the same against PostgREST).

Read-only scopes only this pass (gmail.readonly, calendar.readonly) --
see the Gmail/Calendar integration plan's own "Calendar is read-only this
pass" scope note. No write scope is requested, so there is no path by
which this module could be used to send email or create/modify/delete a
Google Calendar event even if some future code tried.

Token storage follows auth.py's own "lazy file under backend/data/"
convention, extended with real read-modify-write logic since this token
(unlike the write-once local auth_token) genuinely needs refreshing. A
dedicated JSON file, not a row in any queryable SQLite domain DB --
satisfies the "never in a plaintext table" boundary from the original
brief without inventing encryption-at-rest infrastructure this codebase
has never had anywhere else (every existing secret, including this one's
own CLIENT_SECRET in .env, is already plaintext on disk). The access/
refresh tokens themselves are never imported by any *_tools.py file, so
no Frank tool can ever return one as a result.

**Dual-backend as of 2026-09-11**: real gap found live during the
iPhone cloud cutover -- this whole module predates the dual-backend
dispatcher pattern applied to every other domain this session, and the
local-file storage above genuinely is local to whichever machine
generated it. A phone (or Render) reading `is_connected()`/
`get_valid_access_token()` had no way to see a grant made through the
Mac's own file, so Gmail/Calendar always read as disconnected from the
cloud. The three functions below now accept `postgres_conn: Any = None`
and, when set, read/write the shared `pcorp.app_state` row via
`db.py`'s `get_google_oauth_tokens_postgres`/`set_google_oauth_tokens_postgres`
instead of the local file -- same shape as every other domain's
dispatcher, except the SQLite-mode "other side" is the pre-existing file
rather than a table (see those two functions' own docstring). Neither
storage is authoritative over the other; whichever backend answers a
given request is the one whose grant it sees, same as the file always
was for the Mac alone.
"""

import os
import time
from pathlib import Path
from typing import Any

import httpx

from app import db

TOKEN_PATH = Path(__file__).parent.parent / "data" / "google_oauth_token.json"
REDIRECT_URI = "http://127.0.0.1:8731/auth/google/callback"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly"
# Access tokens are refreshed a little before their real expiry rather than
# exactly at it, so a slow downstream call never straddles the boundary.
_EXPIRY_SAFETY_MARGIN_SECONDS = 60


def _client_id() -> str | None:
    return os.getenv("GOOGLE_OAUTH_CLIENT_ID")


def _client_secret() -> str | None:
    return os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")


def _read_token_file() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    import json

    try:
        return json.loads(TOKEN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_token_file(data: dict) -> None:
    import json

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data))


async def is_connected(postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        stored = await db.get_google_oauth_tokens_postgres(postgres_conn)
        return bool(stored and stored.get("refresh_token"))
    stored = _read_token_file()
    return bool(stored and stored.get("refresh_token"))


def get_authorization_url(state: str) -> str:
    params = {
        "client_id": _client_id(),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        # Forces Google to hand back a refresh_token even on a repeat
        # authorization -- without this, only the very first-ever consent
        # for this app+account returns one.
        "prompt": "consent",
        "state": state,
    }
    query = httpx.QueryParams(params)
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


async def exchange_code_for_tokens(code: str, postgres_conn: Any = None) -> bool:
    async with httpx.AsyncClient(timeout=15.0) as http:
        response = await http.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        return False
    payload = response.json()
    refresh_token = payload["refresh_token"]
    access_token = payload["access_token"]
    expires_at = time.time() + payload["expires_in"]
    if postgres_conn is not None:
        await db.set_google_oauth_tokens_postgres(postgres_conn, refresh_token, access_token, expires_at)
        return True
    _write_token_file({"refresh_token": refresh_token, "access_token": access_token, "expires_at": expires_at})
    return True


async def _refresh(refresh_token: str) -> dict | None:
    async with httpx.AsyncClient(timeout=15.0) as http:
        response = await http.post(
            TOKEN_ENDPOINT,
            data={
                "refresh_token": refresh_token,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        # Real gap found live (2026-09-06, systems audit §18 sweep): a
        # revoked/expired refresh token failed here silently, with zero
        # logging anywhere in this chain -- a genuine, recurring
        # revocation would look identical to "nothing new happened" to
        # every caller and never surface anywhere for Josh to notice.
        # Matches search.py's own established `print(f"[...] failed: ...")`
        # convention -- the one place in this backend that already logs a
        # swallowed exception to console.
        print(f"[google_oauth] token refresh failed: {response.status_code} {response.text[:200]}")
        return None
    return response.json()


async def get_valid_access_token(postgres_conn: Any = None) -> str | None:
    """The only function gmail_client.py/google_calendar_client.py call --
    refreshes and persists a new access token if the stored one is
    expired or close to it, returns None if Google was never authorized
    at all (rather than raising, so a not-yet-connected state is just
    "no data" to every caller, same fail-soft posture as the rest of this
    module)."""
    if postgres_conn is not None:
        stored = await db.get_google_oauth_tokens_postgres(postgres_conn)
        if stored is None:
            return None
        if stored["expires_at"] - _EXPIRY_SAFETY_MARGIN_SECONDS > time.time():
            return stored["access_token"]
        refreshed = await _refresh(stored["refresh_token"])
        if refreshed is None:
            return None
        new_access_token = refreshed["access_token"]
        new_expires_at = time.time() + refreshed["expires_in"]
        await db.set_google_oauth_tokens_postgres(postgres_conn, stored["refresh_token"], new_access_token, new_expires_at)
        return new_access_token

    stored = _read_token_file()
    if stored is None:
        return None
    if stored["expires_at"] - _EXPIRY_SAFETY_MARGIN_SECONDS > time.time():
        return stored["access_token"]
    refreshed = await _refresh(stored["refresh_token"])
    if refreshed is None:
        return None
    stored["access_token"] = refreshed["access_token"]
    stored["expires_at"] = time.time() + refreshed["expires_in"]
    _write_token_file(stored)
    return stored["access_token"]


async def google_api_get(http: httpx.AsyncClient, url: str, token: str, params: dict | None = None) -> dict | None:
    """Shared GET pattern for Google's REST APIs (2026-09-06, systems
    audit §13's connector-framework investigation) -- the same ~10-line
    "bearer-auth GET; non-200 or httpx.HTTPError/ValueError means
    failure; else parse JSON" block was independently duplicated three
    times across gmail_client.py's _get_message()/fetch_recent_messages()
    and google_calendar_client.py's fetch_upcoming_events() before this.
    That was the one real, narrow duplication a broader audit of every
    external integration in this backend actually found -- Supabase/
    Luno/CoinGecko/HF Markets each have genuinely different auth models
    and failure modes, so nothing broader than this was extracted.

    Returns the parsed JSON body on success, None on any failure --
    callers translate None into whatever "nothing" means for them (an
    empty list, skipping one item), since that part is genuinely
    caller-specific, not duplicated."""
    try:
        response = await http.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if response.status_code != 200:
            return None
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None
