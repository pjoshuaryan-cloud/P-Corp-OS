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

Opportunity Radar (2026-08-10, from the additive feature spec) folded in
here rather than becoming its own card: Joshua confirmed "extend the
existing Insights mechanism" over a new UI surface, and its signals
(warm/hot leads in the real Alpha Mode `leads` table with no follow-up
sent; quotes sent but sitting unanswered) are the same deterministic,
data-already-exists shape as everything else in this file.
"""

from datetime import date, timedelta

import aiosqlite

from app.alpha_mode_db import DB_PATH as ALPHA_MODE_DB_PATH
from app.alpha_mode_db import clients_needing_outreach
from app.alpha_mode_supabase import leads_needing_followup, quotes_needing_followup
from app.operations_db import DB_PATH as OPERATIONS_DB_PATH
from app.people_db import get_overdue_follow_ups

HORIZON_DAYS = 7
# Added 2026-08-01 for outreach-reminder insights (Alpha Mode Agent's
# first concrete capability) -- a client not contacted in two weeks is a
# reasonable, if somewhat arbitrary, default cadence to flag; adjust if
# it turns out too noisy or too quiet once actually used.
OUTREACH_STALE_AFTER_DAYS = 14


async def _overdue_and_upcoming_tasks(today: str, horizon: str, postgres_conn=None) -> list[dict]:
    # Real bypass fix (2026-09-11, iPhone independence pass): this used to
    # open its own raw aiosqlite connection straight against
    # operations.db's local file, completely bypassing DATA_BACKEND.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT title, area, due_date FROM operations.tasks "
                "WHERE status != 'done' AND due_date IS NOT NULL AND deleted_at IS NULL ORDER BY due_date"
            )
            rows = [{"title": r[0], "area": r[1], "due_date": r[2]} for r in await cur.fetchall()]
    else:
        async with aiosqlite.connect(OPERATIONS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT title, area, due_date FROM tasks WHERE status != 'done' AND due_date IS NOT NULL AND deleted_at IS NULL ORDER BY due_date"
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
                "category": "risk" if is_overdue else "follow_up",
            }
        )
    return insights


async def _overdue_and_upcoming_invoices(today: str, horizon: str, postgres_conn=None) -> list[dict]:
    # Real bypass fix (2026-09-11) -- same as _overdue_and_upcoming_tasks
    # above, against alpha_mode.db instead of operations.db. Note: these
    # local invoices/clients tables are pre-existing, known-dead data
    # (alpha_mode_db.py's own docstring: nothing has written to them since
    # 2026-08-02, real invoices moved to Supabase) -- that staleness is
    # unrelated to and unfixed by this change, which only stops the read
    # from silently ignoring DATA_BACKEND.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                """
                SELECT invoices.amount, invoices.due_date, clients.name
                FROM alpha_mode.invoices JOIN alpha_mode.clients ON invoices.client_id = clients.id
                WHERE invoices.status != 'paid' AND invoices.due_date IS NOT NULL
                ORDER BY invoices.due_date
                """
            )
            rows = [{"amount": r[0], "due_date": r[1], "client_name": r[2]} for r in await cur.fetchall()]
    else:
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
                "detail": f"R{row['amount']:,.2f} from {row['client_name']} — due {row['due_date']}",
                "target_nav_title": "War Room",
                "icon": "exclamationmark.circle" if is_overdue else "dollarsign.circle",
                "priority": 0 if is_overdue else 1,
                "category": "risk" if is_overdue else "follow_up",
            }
        )
    return insights


async def _clients_needing_outreach(postgres_conn=None) -> list[dict]:
    stale_clients = await clients_needing_outreach(OUTREACH_STALE_AFTER_DAYS, postgres_conn)
    insights = []
    for client in stale_clients:
        if client["last_contacted_date"]:
            detail = f"{client['name']} — last contacted {client['last_contacted_date']}"
        else:
            detail = f"{client['name']} — no contact ever logged"
        insights.append(
            {
                "title": "Client outreach due",
                "detail": detail,
                "target_nav_title": "War Room",
                "icon": "person.crop.circle.badge.exclamationmark",
                "priority": 1,
                "category": "follow_up",
            }
        )
    return insights


async def _leads_needing_followup() -> list[dict]:
    # Opportunity Radar (2026-08-10): the one signal Joshua confirmed --
    # warm/hot leads with no follow-up sent -- folded into this existing
    # card rather than a new one, per the additive spec's own "extend,
    # don't duplicate" rule.
    leads = await leads_needing_followup()
    insights = []
    for lead in leads:
        score = lead.get("qualification_score")
        detail = f"{lead['client']} — qualification score {score}" if score is not None else lead["client"]
        insights.append(
            {
                "title": f"{lead['temperature'].capitalize()} lead needs follow-up",
                "detail": detail,
                "target_nav_title": "War Room",
                "icon": "flame",
                "priority": 1,
                "category": "opportunity",
            }
        )
    return insights


async def _quotes_needing_followup() -> list[dict]:
    # Opportunity Radar's second signal (2026-08-10): quotes sent but
    # sitting unanswered for 14+ days -- same extend-not-duplicate
    # reasoning as the leads signal above.
    quotes = await quotes_needing_followup()
    insights = []
    for quote in quotes:
        amount = quote.get("quote_amount")
        detail = (
            f"{quote['client']} — R{amount:,.2f} quote, sent {quote['quote_sent_date']}"
            if amount
            else f"{quote['client']} — quote sent {quote['quote_sent_date']}"
        )
        insights.append(
            {
                "title": "Quote awaiting response",
                "detail": detail,
                "target_nav_title": "War Room",
                "icon": "hourglass",
                "priority": 1,
                "category": "opportunity",
            }
        )
    return insights


async def _relationship_follow_up_needed(postgres_conn=None) -> list[dict]:
    # People/Relationships layer (2026-08-27, people_db.py) -- same
    # "relationship going stale" semantic as _clients_needing_outreach
    # above, same category, but over Josh's real personal/professional
    # network rather than Alpha Mode Media clients.
    overdue = await get_overdue_follow_ups(postgres_conn=postgres_conn)
    insights = []
    for person in overdue:
        last = person["last_contact_date"] or "never"
        insights.append(
            {
                "title": "Follow-up due",
                "detail": f"{person['name']} — last contact {last}",
                "target_nav_title": "Personal",
                "icon": "person.crop.circle.badge.clock",
                "priority": 1,
                "category": "follow_up",
            }
        )
    return insights


async def compute_insights(limit: int = 5, postgres_conn=None) -> list[dict]:
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=HORIZON_DAYS)).isoformat()

    tasks = await _overdue_and_upcoming_tasks(today, horizon, postgres_conn)
    invoices = await _overdue_and_upcoming_invoices(today, horizon, postgres_conn)
    outreach = await _clients_needing_outreach(postgres_conn)
    leads = await _leads_needing_followup()
    quotes = await _quotes_needing_followup()
    relationships = await _relationship_follow_up_needed(postgres_conn)

    combined = tasks + invoices + outreach + leads + quotes + relationships
    combined.sort(key=lambda item: (item["priority"], item["detail"]))
    return combined[:limit]
