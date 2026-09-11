"""
Connected Apps status (2026-09-04) -- the first real UI surface for
connection health on any of this backend's three external integrations.
GET /auth/google/status has existed since 2026-08-27 with zero Swift call
sites on either platform (confirmed via grep); this supersedes it for UI
purposes without removing it, since nothing else calls it either.

Deliberately three independent rows, not one rolled-up "integrations: OK"
boolean -- Gmail and Calendar share one Google token but have genuinely
different sync stories (Calendar has a real periodic cache with a real
synced_at column; Gmail only syncs on demand, see db.py's
last_gmail_sync_at), and Supabase is a static API key, not an OAuth grant
at all. Collapsing these away would hide exactly the distinctions that
make each row's "last synced" mean something different -- same "never
fabricate, never launder away a real distinction" discipline as
finance_db.py/joshx_db.py.
"""

import asyncio
from datetime import datetime, timezone

from app import google_oauth
from app.calendar_db import get_last_google_calendar_sync_at
from app.db import get_last_gmail_sync_at
from app.supabase_client import select_rows


async def _supabase_status() -> dict:
    """Live PostgREST round-trip (one row, one column), not just an "is
    the key configured" check -- a service_role key can be present and
    still wrong/revoked, and that's exactly the failure this exists to
    catch. Cheap enough to pay on every call: this endpoint is only
    fetched when Josh actually opens Settings (ConnectedAppsClient.swift's
    onAppear-driven fetch, not a timed poll like Insights/Situation
    Room), so there's no meaningful request-volume cost. Fails soft
    (connected: false, no fabricated timestamp) on any error, including a
    missing env var -- supabase_client.py reads via os.environ[...],
    which raises KeyError rather than returning None when unset.

    One retry after a real-world transient failure (2026-09-04): caught
    live -- a single network blip made this read connected: false for one
    request, then connected: true again on the very next one seconds
    later, with nothing on the Supabase side actually wrong. A genuine key
    revocation or outage will still fail twice in a row and correctly
    report disconnected; a one-off hiccup shouldn't read as a real outage
    to someone glancing at Settings."""
    for attempt in range(2):
        try:
            await select_rows("projects", {"select": "id", "limit": "1"})
            break
        except Exception as exc:
            if attempt == 1:
                # Logged rather than swallowed (2026-09-11) -- this
                # except previously discarded the real reason entirely,
                # so a genuine key revocation and a config-loading bug
                # looked identical to a glance at Settings. Matches this
                # file's own "never launder away a real distinction"
                # discipline.
                reason = f"{type(exc).__name__}: {exc}"
                print(f"[connected_apps] Supabase check failed: {reason}")
                return {
                    "name": "Supabase (Alpha Mode Media)",
                    "connected": False,
                    "last_synced_at": None,
                    "debug_reason": reason,
                }
            await asyncio.sleep(0.5)
    return {
        "name": "Supabase (Alpha Mode Media)",
        "connected": True,
        # "Last synced" here means "last time we confirmed this key still
        # works" -- Supabase reads are always live (alpha_mode_supabase.py
        # has no cache), so this check itself *is* the sync.
        "last_synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


async def compute_connected_apps_status(postgres_conn=None) -> list[dict]:
    # Real gap found live (2026-09-06, systems audit §18 sweep):
    # is_connected() only checks that a refresh-token file exists on
    # disk -- a real revocation (Josh removes access in his Google
    # Account, or Google itself revokes it) leaves that file untouched,
    # so this would report "connected" forever. get_valid_access_token()
    # already attempts a real refresh (and now logs a failure, see
    # google_oauth.py's own _refresh()) -- reusing it here turns this
    # into a genuine liveness check, matching the discipline
    # _supabase_status() above already applies to its own integration.
    google_connected = await google_oauth.get_valid_access_token(postgres_conn) is not None
    return [
        {
            "name": "Gmail",
            "connected": google_connected,
            "last_synced_at": await get_last_gmail_sync_at(postgres_conn),
        },
        {
            "name": "Google Calendar",
            "connected": google_connected,
            "last_synced_at": await get_last_google_calendar_sync_at(postgres_conn),
        },
        await _supabase_status(),
    ]


_cached_status: list[dict] | None = None


async def refresh_connected_apps_cache(postgres_conn=None) -> None:
    """Feeds the Situation Room's disconnection alert (reliability pass,
    2026-09-07) without adding compute_connected_apps_status()'s real
    network cost to Situation Room's own 30s poll cadence -- see
    situation_room.py's _connected_apps_alerts(), which reads this cache
    and never calls compute_connected_apps_status() directly. Rides
    main.py's existing 15-minute _trigger_scheduler_loop() tick, same
    reasoning as Luno/HF Markets/market-movers riding it already.

    Deliberately not named maybe_*() like this backend's other
    scheduler-tick jobs -- every existing maybe_* function means "gated to
    once per day"; this one re-checks unconditionally on every tick, no
    gating, so it doesn't earn that prefix.

    GET /connected-apps (Settings' own on-demand endpoint) is untouched by
    this cache -- it still always calls compute_connected_apps_status()
    directly, since that's a deliberate user action that should always see
    fresh truth, not the last cached tick."""
    global _cached_status
    _cached_status = await compute_connected_apps_status(postgres_conn)


def get_cached_connected_apps_status() -> list[dict] | None:
    return _cached_status


async def summarize(postgres_conn=None) -> str:
    """Plain-text snapshot, same style as trading_division.py's own
    summarize() -- for a Frank-facing tool, not the /connected-apps REST
    endpoint (which returns the structured list directly to Settings).
    Deliberately NOT folded into main.py's always-on per-turn system
    prompt concatenation the way every other domain's summarize() is:
    compute_connected_apps_status() above makes a real, live Supabase
    network round-trip (_supabase_status()) on every call, by design, since
    this was only ever meant to be paid when Settings' own onAppear fetches
    it -- folding it into every single chat turn would add that network
    call's latency to every message Frank sends, not just the rare
    "how's everything connected" or executive-summary ask that actually
    needs it. Exposed as an on-demand tool instead (see below)."""
    rows = await compute_connected_apps_status(postgres_conn)
    lines = []
    for row in rows:
        synced = row["last_synced_at"] or "never"
        status = "connected" if row["connected"] else "not connected"
        lines.append(f"  - {row['name']}: {status} (last synced: {synced})")
    return "\n".join(lines)


CHECK_CONNECTED_APPS_TOOL = {
    "name": "check_connected_apps_status",
    "description": (
        "Check the real, current connection health of Gmail, Google Calendar, and Supabase (the live Alpha "
        "Mode Media integration) -- each with its own connected/not-connected state and last-synced time. "
        "Use this when Josh asks about integration/connection status directly, or as one input when compiling "
        "a broader executive summary / \"how's everything looking\" business report -- this data has no other "
        "path into your context, unlike Joshx/Finance/Trading Division, which you already see every turn."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

CONNECTED_APPS_TOOLS = [CHECK_CONNECTED_APPS_TOOL]
CONNECTED_APPS_TOOL_NAMES = {tool["name"] for tool in CONNECTED_APPS_TOOLS}


async def execute_connected_apps_tool_call(name: str, tool_input: dict, postgres_conn=None) -> str:
    if name != "check_connected_apps_status":
        return f"Unknown tool: {name}"
    return await summarize(postgres_conn)
