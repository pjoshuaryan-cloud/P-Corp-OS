"""
Raw Google Calendar REST calls (2026-08-27), read-only -- lists events on
the primary calendar only. Backs calendar_db.py's sync; never imported by
calendar_tools.py directly. No create/update/delete against Google
Calendar in this module or anywhere else -- see the Gmail/Calendar
integration plan's "Calendar is read-only this pass" scope note; real
calendar writes are item 5's (auto-scheduling) approval-gated mechanism,
not this one.

Fail-soft (try/except: return []), same convention as gmail_client.py/
alpha_mode_supabase.py.
"""

from datetime import datetime, timedelta, timezone

import httpx

from app.google_oauth import get_valid_access_token, google_api_get

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


async def fetch_upcoming_events(days: int = 7, postgres_conn=None) -> list[dict]:
    token = await get_valid_access_token(postgres_conn)
    if token is None:
        return []
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()
    async with httpx.AsyncClient(timeout=15.0) as http:
        result = await google_api_get(
            http,
            EVENTS_URL,
            token,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            },
        )
    if result is None:
        return []
    items = result.get("items", [])

    events = []
    for item in items:
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
        if not start or not end:
            continue
        attendees = [a.get("email") for a in item.get("attendees", []) if a.get("email")]
        events.append(
            {
                "id": item["id"],
                "title": item.get("summary", "(no title)"),
                "start": start,
                "end": end,
                "location": item.get("location"),
                "attendees": ", ".join(attendees) if attendees else None,
            }
        )
    return events
