"""
Situation Room (2026-08-10, from the additive feature spec, scope
confirmed with Joshua over two rounds: what the term meant, then the
concrete severity thresholds) -- an escalated alert surface, distinct
from the routine "Frank's Insights" card (app/insights.py). Same
deterministic, no-LLM, data-already-exists shape as Insights, but a
stricter tier: only things severe enough to interrupt, not just list.

Thresholds are judgment calls, confirmed directly with Joshua rather
than guessed -- same "somewhat arbitrary, adjust if wrong" spirit as
insights.py's own OUTREACH_STALE_AFTER_DAYS:
- Invoice overdue 30+ days (real cash-flow risk, vs. any-amount-overdue)
- Task overdue 14+ days (stale/neglected, vs. daily overdue debris)
- Client outreach stale 45+ days (a real relationship risk, vs. the
  routine 14-day nudge)

Rendered client-side as a banner at the top of War Room, not another
right-rail card -- this should read as "interrupt," not "routine list."
"""

from datetime import date

import aiosqlite

from app.alpha_mode_db import DB_PATH as ALPHA_MODE_DB_PATH
from app.alpha_mode_db import clients_needing_outreach
from app.connected_apps import get_cached_connected_apps_status
from app.db import get_credits_exhausted_since
from app.operations_db import DB_PATH as OPERATIONS_DB_PATH

INVOICE_OVERDUE_DAYS = 30
TASK_OVERDUE_DAYS = 14
OUTREACH_STALE_DAYS = 45


async def _severely_overdue_tasks(today: date) -> list[dict]:
    async with aiosqlite.connect(OPERATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title, area, due_date FROM tasks WHERE status != 'done' AND due_date IS NOT NULL AND deleted_at IS NULL"
        )
        rows = await cursor.fetchall()

    alerts = []
    for row in rows:
        days_overdue = (today - date.fromisoformat(row["due_date"])).days
        if days_overdue < TASK_OVERDUE_DAYS:
            continue
        area = f" ({row['area']})" if row["area"] else ""
        alerts.append(
            {
                "title": "Task badly overdue",
                "detail": f"{row['title']}{area} — {days_overdue} days overdue",
                "target_nav_title": "Agents",
            }
        )
    return alerts


async def _severely_overdue_invoices(today: date) -> list[dict]:
    async with aiosqlite.connect(ALPHA_MODE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT invoices.amount, invoices.due_date, clients.name AS client_name
            FROM invoices JOIN clients ON invoices.client_id = clients.id
            WHERE invoices.status != 'paid' AND invoices.due_date IS NOT NULL
            """
        )
        rows = await cursor.fetchall()

    alerts = []
    for row in rows:
        days_overdue = (today - date.fromisoformat(row["due_date"])).days
        if days_overdue < INVOICE_OVERDUE_DAYS:
            continue
        alerts.append(
            {
                "title": "Invoice badly overdue",
                "detail": f"R{row['amount']:,.2f} from {row['client_name']} — {days_overdue} days overdue",
                "target_nav_title": "War Room",
            }
        )
    return alerts


async def _severely_stale_outreach() -> list[dict]:
    stale_clients = await clients_needing_outreach(OUTREACH_STALE_DAYS)
    alerts = []
    for client in stale_clients:
        detail = (
            f"{client['name']} — last contacted {client['last_contacted_date']}"
            if client["last_contacted_date"]
            else f"{client['name']} — no contact ever logged"
        )
        alerts.append(
            {
                "title": "Client relationship at risk",
                "detail": detail,
                "target_nav_title": "War Room",
            }
        )
    return alerts


async def _credit_exhausted_alert() -> list[dict]:
    """Reliability pass (2026-09-07): main.py's websocket_chat sets
    app_state.credits_exhausted_since the moment a real Anthropic billing
    error is caught, and clears it the moment a turn next succeeds -- see
    db.py's get/set/clear_credits_exhausted(). Surfaced here rather than
    only as the one in-chat error message so it stays visible across both
    apps for as long as it's actually true, not just in the one chat
    bubble that happened to trigger it."""
    exhausted_since = await get_credits_exhausted_since()
    if exhausted_since is None:
        return []
    return [
        {
            "title": "Anthropic credits exhausted",
            "detail": f"Since {exhausted_since} UTC — add credits at console.anthropic.com/settings/billing",
            "target_nav_title": "Frank",
        }
    ]


async def _connected_apps_alerts() -> list[dict]:
    """Reliability pass (2026-09-07): reads connected_apps.py's cache
    (refreshed every 15 minutes by main.py's existing scheduler tick),
    never the live compute_connected_apps_status() directly -- that call
    makes a real network round-trip, and this function is itself called on
    Situation Room's 30s poll cadence, so calling it live here would pay
    that cost every 30 seconds instead of every 15 minutes. Empty cache
    (a fresh restart, first tick hasn't fired yet) reads as "nothing to
    report" rather than blocking on a live check just to cover a brief
    startup gap."""
    cached_status = get_cached_connected_apps_status()
    if cached_status is None:
        return []
    return [
        {
            "title": f"{row['name']} disconnected",
            "detail": "Hasn't been reachable on the last check — reconnect via Settings.",
            "target_nav_title": "Settings",
        }
        for row in cached_status
        if not row["connected"]
    ]


async def compute_situation_room_alerts() -> list[dict]:
    today = date.today()
    credits = await _credit_exhausted_alert()
    connected_apps = await _connected_apps_alerts()
    tasks = await _severely_overdue_tasks(today)
    invoices = await _severely_overdue_invoices(today)
    outreach = await _severely_stale_outreach()
    return credits + connected_apps + tasks + invoices + outreach
