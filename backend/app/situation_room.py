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
from app.operations_db import DB_PATH as OPERATIONS_DB_PATH

INVOICE_OVERDUE_DAYS = 30
TASK_OVERDUE_DAYS = 14
OUTREACH_STALE_DAYS = 45


async def _severely_overdue_tasks(today: date) -> list[dict]:
    async with aiosqlite.connect(OPERATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title, area, due_date FROM tasks WHERE status != 'done' AND due_date IS NOT NULL"
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
                "detail": f"${row['amount']:,.2f} from {row['client_name']} — {days_overdue} days overdue",
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


async def compute_situation_room_alerts() -> list[dict]:
    today = date.today()
    tasks = await _severely_overdue_tasks(today)
    invoices = await _severely_overdue_invoices(today)
    outreach = await _severely_stale_outreach()
    return tasks + invoices + outreach
