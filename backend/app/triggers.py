"""
Proactive Triggers Layer (2026-08-21) — the rule-checking + digest-
composition half. See triggers_db.py's docstring for the persistence
design (rule rows + per-item dedup/decay state) and email_digest.py for
delivery. This file is the part that actually decides what's true right
now, against real data:

- invoice_overdue / project_stage_stall read the REAL Alpha Mode Media
  Admin Supabase (alpha_mode_supabase.py's `select_rows`) — the live
  source of truth since projects/invoices moved there 2026-08-02.
- client_contact_gap / deliverable_overdue read local alpha_mode.db —
  Supabase has no `clients` or `deliverables` table (alpha_mode_supabase.py's
  own docstring), so local SQLite is the only real data for these two,
  not a stale fallback.

This deliberately does NOT reuse insights.py/situation_room.py's queries
against local alpha_mode.db `invoices`/`clients` for the invoice signal —
those tables stopped being written to 2026-08-02 (confirmed via
alpha_mode_db.py's own docstring) and would silently disagree with what's
true in the real app. That staleness is pre-existing in those two files,
not introduced here; this layer reads the live table on purpose.

`stale_task` is not implemented — see triggers_db.py's docstring for why.
"""

from datetime import date, datetime, timedelta

import aiosqlite

from app.alpha_mode_db import DB_PATH as ALPHA_MODE_DB_PATH
from app.alpha_mode_supabase import PROJECT_STAGES
from app.email_digest import send_digest_email
from app.market_movers import check_market_movers
from app.people_db import get_overdue_follow_ups
from app.supabase_client import select_rows
from app.triggers_db import (
    clear_resolved,
    enabled_rule_thresholds,
    get_digest_schedule,
    items_due_for_notification,
    list_rules,
    mark_digest_sent,
    mark_notified,
    peek_due_status,
)

TERMINAL_STAGES = {"delivered", "final_delivered"}


async def _check_invoice_overdue() -> list[dict]:
    today = date.today().isoformat()
    rows = await select_rows(
        "invoices",
        {
            "select": "id,amount,due_date,projects(client,project_name)",
            "status": "neq.paid",
            "due_date": f"lt.{today}",
            "order": "due_date.asc",
        },
    )
    items = []
    for row in rows:
        proj = row.get("projects") or {}
        due = date.fromisoformat(row["due_date"])
        days_overdue = (date.today() - due).days
        items.append(
            {
                "item_key": f"invoice_overdue:{row['id']}",
                "title": f"R{row['amount']:,.2f} — {proj.get('client', '?')}",
                "detail": f"{proj.get('project_name', '?')}, {days_overdue}d overdue (due {row['due_date']})",
            }
        )
    return items


async def _check_client_contact_gap(threshold_days: int) -> list[dict]:
    cutoff = (date.today() - timedelta(days=threshold_days)).isoformat()
    async with aiosqlite.connect(ALPHA_MODE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, name, last_contacted_date FROM clients
            WHERE status = 'active' AND (last_contacted_date IS NULL OR last_contacted_date < ?)
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
    items = []
    for row in rows:
        last = row["last_contacted_date"] or "never"
        items.append(
            {
                "item_key": f"client_contact_gap:{row['id']}",
                "title": row["name"],
                "detail": f"last contact {last}",
            }
        )
    return items


async def _check_project_stage_stall() -> list[dict]:
    today = date.today().isoformat()
    rows = await select_rows(
        "projects",
        {"select": "id,client,project_name,stage,due_date", "due_date": f"lt.{today}"},
    )
    items = []
    for row in rows:
        stage = row.get("stage")
        if stage in TERMINAL_STAGES or stage not in PROJECT_STAGES:
            continue
        due = date.fromisoformat(row["due_date"])
        days_overdue = (date.today() - due).days
        items.append(
            {
                "item_key": f"project_stage_stall:{row['id']}",
                "title": f"{row.get('project_name') or '(untitled)'} — {row['client']}",
                "detail": f"still {stage}, {days_overdue}d past due (due {row['due_date']})",
            }
        )
    return items


async def _check_deliverable_overdue() -> list[dict]:
    today = date.today().isoformat()
    async with aiosqlite.connect(ALPHA_MODE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT deliverables.id, deliverables.description, deliverables.due_date,
                   projects.name AS project_name, clients.name AS client_name
            FROM deliverables
            JOIN projects ON deliverables.project_id = projects.id
            JOIN clients ON projects.client_id = clients.id
            WHERE deliverables.status = 'pending' AND deliverables.due_date IS NOT NULL
              AND deliverables.due_date < ?
            """,
            (today,),
        )
        rows = await cursor.fetchall()
    items = []
    for row in rows:
        due = date.fromisoformat(row["due_date"])
        days_overdue = (date.today() - due).days
        items.append(
            {
                "item_key": f"deliverable_overdue:{row['id']}",
                "title": f"{row['description']} — {row['client_name']}",
                "detail": f"{row['project_name']}, {days_overdue}d overdue (due {row['due_date']})",
            }
        )
    return items


async def _check_relationship_follow_up_overdue(threshold: int | None) -> list[dict]:
    """Reads people.db, not alpha_mode.db -- the People/Relationships
    layer (people_db.py) is a deliberately separate domain from Alpha
    Mode Media/Joshx clients. Threshold is ignored here: overdue-ness is
    per-person (an explicit next_follow_up_date, or that person's own
    follow_up_cadence_days), not one global cutoff like client_contact_gap's
    21 days -- get_overdue_follow_ups() already encodes that logic, this
    just maps its real rows into the shape this layer expects."""
    rows = await get_overdue_follow_ups()
    return [
        {
            "item_key": f"relationship_follow_up_overdue:{row['id']}",
            "title": row["name"],
            "detail": f"last contact {row['last_contact_date'] or 'never'}",
        }
        for row in rows
    ]


RULE_CHECKERS = {
    "invoice_overdue": lambda threshold: _check_invoice_overdue(),
    "client_contact_gap": lambda threshold: _check_client_contact_gap(threshold or 21),
    "project_stage_stall": lambda threshold: _check_project_stage_stall(),
    "deliverable_overdue": lambda threshold: _check_deliverable_overdue(),
    "relationship_follow_up_overdue": _check_relationship_follow_up_overdue,
    "market_mover": check_market_movers,
}

SECTION_TITLES = {
    "invoice_overdue": "INVOICES OVERDUE",
    "client_contact_gap": "CLIENTS NEEDING CONTACT",
    "project_stage_stall": "PROJECTS STALLED",
    "deliverable_overdue": "DELIVERABLES OVERDUE",
    "relationship_follow_up_overdue": "RELATIONSHIPS NEEDING FOLLOW-UP",
    # Deliberately "MARKET MOVERS," not "OPPORTUNITIES" -- see
    # market_movers.py's own docstring for why the framing stays
    # strictly factual (price moved X%), never a recommendation.
    "market_mover": "MARKET MOVERS",
}


async def compute_due_digest_sections() -> dict[str, list[dict]]:
    """Runs every enabled rule against live data, retires state for items
    that resolved since last run, and returns only the items actually due
    to be surfaced today per the decaying cadence — keyed by rule_type.
    Does not send or mark anything notified; see run_daily_digest()."""
    thresholds = await enabled_rule_thresholds()
    sections: dict[str, list[dict]] = {}
    for rule_type, threshold in thresholds.items():
        checker = RULE_CHECKERS.get(rule_type)
        if checker is None:
            continue
        items = await checker(threshold)
        all_keys = [item["item_key"] for item in items]
        await clear_resolved(rule_type, all_keys)
        due_keys = set(await items_due_for_notification(rule_type, all_keys))
        due_items = [item for item in items if item["item_key"] in due_keys]
        if due_items:
            sections[rule_type] = due_items
    return sections


def _format_digest_body(sections: dict[str, list[dict]]) -> str:
    lines = [f"Frank's Daily Brief — {date.today().strftime('%A, %B %-d, %Y')}", ""]
    for rule_type, items in sections.items():
        lines.append(SECTION_TITLES[rule_type])
        for item in items:
            lines.append(f"  - {item['title']} ({item['detail']})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


async def run_daily_digest() -> dict:
    """Computes, sends (if there's anything due), and records state. Lets
    a send failure propagate — the caller (maybe_run_daily_digest) must
    NOT call mark_digest_sent if this raises, so a failed send is retried
    on the next scheduler tick instead of silently recorded as done."""
    sections = await compute_due_digest_sections()
    if not sections:
        return {"sent": False, "item_count": 0}

    item_count = sum(len(items) for items in sections.values())
    body = _format_digest_body(sections)
    send_digest_email(f"Frank's Daily Brief — {item_count} item(s)", body)

    for rule_type, items in sections.items():
        await mark_notified([item["item_key"] for item in items])

    return {"sent": True, "item_count": item_count}


async def compute_status() -> dict:
    """Read-only live view for the Triggers UI (2026-08-21): every rule
    (enabled or not), and for enabled rules, every currently-matching item
    with a `due` flag showing whether it'd be in *today's* digest per the
    decaying cadence -- via peek_due_status(), which never mutates state.
    Disabled rules report an empty item list rather than skipping the
    live check, so the UI can show "this would still be flagging N
    things" even while a rule's turned off."""
    rules = await list_rules()
    schedule = await get_digest_schedule()
    sections = []
    for rule in rules:
        rule_type = rule["rule_type"]
        items: list[dict] = []
        if rule["enabled"]:
            checker = RULE_CHECKERS.get(rule_type)
            if checker:
                items = await checker(rule["threshold_days"])
                due_map = await peek_due_status(rule_type, [i["item_key"] for i in items])
                for item in items:
                    item["due"] = due_map.get(item["item_key"], True)
        sections.append(
            {
                "rule_type": rule_type,
                "label": SECTION_TITLES.get(rule_type, rule_type),
                "enabled": rule["enabled"],
                "threshold_days": rule["threshold_days"],
                "items": items,
            }
        )
    return {"rules": sections, "last_sent_date": schedule["last_sent_date"], "send_hour": schedule["send_hour"]}


async def maybe_run_daily_digest() -> dict | None:
    """Called on every scheduler tick. Runs at most once per calendar day,
    no earlier than the configured send_hour (local time). Returns the
    run_daily_digest() result if it ran, else None."""
    schedule = await get_digest_schedule()
    today = date.today()
    if schedule["last_sent_date"] == today.isoformat():
        return None
    if datetime.now().hour < schedule["send_hour"]:
        return None

    result = await run_daily_digest()
    await mark_digest_sent(today)
    return result
