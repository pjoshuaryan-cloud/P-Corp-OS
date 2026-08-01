"""
Real, deterministic proactive insights for the right rail's "Frank's
Insights" card. Confirmed decision (2026-08-01): direct feedback that
P Corp OS still felt more "ChatGPT" than "Jarvis" -- this card was still
literal placeholder text ("Placeholder Insight"), never wired to
anything real, the clearest possible example of the app not actually
volunteering anything.

Deliberately NOT LLM-generated: a dedicated call here would mean real
hallucination risk and ongoing cost for something that's actually just
date comparisons against data that already exists (Alpha Mode Media
invoices, Operations tasks). Frank's own in-conversation proactive
behavior (PERSONALITY_SPEC.md's "name patterns unprompted" mandate) is a
separate, already-built mechanism; this only surfaces existing due-date
data without requiring Joshua to ask.

Only overdue items, or ones due within the next 7 days, are surfaced --
a task due next month isn't an "insight," it's just backlog.
"""

from datetime import date, timedelta

import aiosqlite

from app.alpha_mode_db import DB_PATH as ALPHA_MODE_DB_PATH
from app.operations_db import DB_PATH as OPERATIONS_DB_PATH

HORIZON_DAYS = 7


async def _overdue_and_upcoming_tasks(today: str, horizon: str) -> list[dict]:
    async with aiosqlite.connect(OPERATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title, area, due_date FROM tasks WHERE status != 'done' AND due_date IS NOT NULL ORDER BY due_date"
        )
        rows = await cursor.fetchall()

    insights = []
    for row in rows:
        if row["due_date"] > horizon:
            continue
        is_overdue = row["due_date"] < today
        area = f" ({row['area']})" if row["area"] else ""
        insights.append(
            {
                "title": "Task overdue" if is_overdue else "Task due soon",
                "detail": f"{row['title']}{area} — due {row['due_date']}",
                "target_nav_title": "Agents",
                "icon": "exclamationmark.circle" if is_overdue else "checklist",
                "priority": 0 if is_overdue else 1,
            }
        )
    return insights


async def _overdue_and_upcoming_invoices(today: str, horizon: str) -> list[dict]:
    async with aiosqlite.connect(ALPHA_MODE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT invoices.amount, invoices.due_date, clients.name AS client_name
            FROM invoices JOIN clients ON invoices.client_id = clients.id
            WHERE invoices.status != 'paid' AND invoices.due_date IS NOT NULL
            ORDER BY invoices.due_date
            """
        )
        rows = await cursor.fetchall()

    insights = []
    for row in rows:
        if row["due_date"] > horizon:
            continue
        is_overdue = row["due_date"] < today
        insights.append(
            {
                "title": "Invoice overdue" if is_overdue else "Invoice due soon",
                "detail": f"${row['amount']:,.2f} from {row['client_name']} — due {row['due_date']}",
                "target_nav_title": "War Room",
                "icon": "exclamationmark.circle" if is_overdue else "dollarsign.circle",
                "priority": 0 if is_overdue else 1,
            }
        )
    return insights


async def compute_insights(limit: int = 5) -> list[dict]:
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=HORIZON_DAYS)).isoformat()

    tasks = await _overdue_and_upcoming_tasks(today, horizon)
    invoices = await _overdue_and_upcoming_invoices(today, horizon)

    combined = tasks + invoices
    combined.sort(key=lambda item: (item["priority"], item["detail"]))
    return combined[:limit]
