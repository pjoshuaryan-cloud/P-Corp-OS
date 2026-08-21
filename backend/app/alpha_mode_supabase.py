"""
Project/invoice writes against the real Alpha Mode Media Admin app's
Supabase database (~/Desktop/alpha-mode-media-app), not the local
alpha_mode.db copy. Confirmed 2026-08-02: Joshua wants "add a new
project" / "X client has paid" to show up live in the real app he
actually runs, not a separate local record that quietly drifts out of
sync -- so project and invoice writes go straight into Supabase's
`projects`/`invoices` tables via the service_role key (server-side only,
bypasses RLS -- see supabase_client.py for why that key belongs here).

Scope, deliberately narrow: only projects and invoices move to Supabase.
Clients and deliverables stay in local SQLite (alpha_mode_db.py) --
Supabase's real schema has no separate `clients` table (client is just a
text field on projects) and no separate deliverables table (a free-text
`deliverables` field + a `tasks` JSON checklist, not individual dated
items), so neither has a clean 1:1 target yet without a bigger schema
decision Joshua hasn't made. Crew/equipment stay out of the real app
entirely per his explicit instruction.

Known consequence: add_deliverable (alpha_mode_tools.py) still looks up
projects in the *local* table, so it won't find projects created after
this change (those now only exist in Supabase). Not fixed here --
flagged as a follow-up, not guessed at.
"""

from datetime import date, timedelta

from app.supabase_client import insert_row, select_rows, update_rows

PROJECT_STAGES = {"briefed", "shooting", "editing", "review", "delivered", "client_revert", "final_delivered"}
INVOICE_STATUSES = {"not_invoiced", "invoiced", "paid"}

# Frank will hear plain-English statuses ("done", "unpaid") far more often
# than the app's exact enum values -- map the common ones rather than
# forcing Joshua to speak in schema terms.
_STAGE_SYNONYMS = {
    "completed": "final_delivered",
    "done": "final_delivered",
    "finished": "final_delivered",
    "in progress": "editing",
    "in review": "review",
}
_INVOICE_SYNONYMS = {
    "unpaid": "not_invoiced",
    "not paid": "not_invoiced",
    "sent": "invoiced",
}


async def create_project(fields: dict) -> dict:
    """fields must include client, project_name; any other real `projects`
    column (contact/type/discipline/stage/due_date/shoot_date/crew/brief/
    notes) is optional and passed through as-is."""
    return await insert_row("projects", fields)


async def find_latest_project(client_name: str, project_name: str | None = None) -> dict | None:
    params = {"client": f"ilike.{client_name}", "order": "created_at.desc", "limit": "1", "select": "*"}
    if project_name:
        params["project_name"] = f"ilike.{project_name}"
    rows = await select_rows("projects", params)
    return rows[0] if rows else None


async def _update_project_field(client_name: str, project_name: str | None, field: str, value) -> dict | None:
    project = await find_latest_project(client_name, project_name)
    if not project:
        return None
    rows = await update_rows("projects", {"id": f"eq.{project['id']}"}, {field: value})
    return rows[0] if rows else None


async def set_project_stage(client_name: str, project_name: str | None, new_status: str) -> dict | None:
    key = new_status.strip().lower()
    stage = _STAGE_SYNONYMS.get(key, key.replace(" ", "_"))
    if stage in PROJECT_STAGES:
        return await _update_project_field(client_name, project_name, "stage", stage)
    # Not a real stage -- record it as a free-text tag instead of failing outright.
    return await _update_project_field(client_name, project_name, "status_tag", new_status)


async def create_invoice(
    client_name: str, project_name: str | None, amount: float, due_date: str | None, status: str = "invoiced"
) -> dict | None:
    project = await find_latest_project(client_name, project_name)
    if not project:
        return None
    key = status.strip().lower()
    normalized = _INVOICE_SYNONYMS.get(key, key)
    if normalized not in INVOICE_STATUSES:
        normalized = "invoiced"
    return await insert_row(
        "invoices", {"project_id": project["id"], "amount": amount, "due_date": due_date, "status": normalized}
    )


async def set_invoice_status(client_name: str, project_name: str | None, new_status: str) -> dict | None:
    project = await find_latest_project(client_name, project_name)
    if not project:
        return None
    invoices = await select_rows(
        "invoices", {"project_id": f"eq.{project['id']}", "order": "created_at.desc", "limit": "1", "select": "*"}
    )
    if not invoices:
        return None
    key = new_status.strip().lower()
    normalized = _INVOICE_SYNONYMS.get(key, key)
    if normalized not in INVOICE_STATUSES:
        return None
    rows = await update_rows("invoices", {"id": f"eq.{invoices[0]['id']}"}, {"status": normalized})
    return rows[0] if rows else None


async def leads_needing_followup() -> list[dict]:
    """Opportunity Radar's one signal (2026-08-10): warm/hot leads in the
    real `leads` table that haven't had a follow-up sent yet. Read-only,
    fails soft (empty list) same reasoning as summarize_block() -- a bad
    Supabase request here shouldn't take down the whole Insights card."""
    try:
        return await select_rows(
            "leads",
            {
                "select": "client,temperature,qualification_score,created_at",
                "temperature": "in.(warm,hot)",
                "follow_up_sent": "eq.false",
                "order": "created_at.asc",
            },
        )
    except Exception:
        return []


QUOTE_STALE_AFTER_DAYS = 14


async def quotes_needing_followup(stale_after_days: int = QUOTE_STALE_AFTER_DAYS) -> list[dict]:
    """Opportunity Radar's second signal (2026-08-10): quotes sent but
    still sitting unanswered (`quote_status` still 'sent', never moved to
    'accepted'/'declined') for stale_after_days+. Same 14-day default as
    insights.py's own OUTREACH_STALE_AFTER_DAYS -- a reasonable, if
    somewhat arbitrary, cadence; adjust if it proves too noisy or too
    quiet once actually used. Read-only, fails soft (empty list) same
    reasoning as leads_needing_followup()."""
    cutoff = (date.today() - timedelta(days=stale_after_days)).isoformat()
    try:
        return await select_rows(
            "leads",
            {
                "select": "client,quote_amount,quote_sent_date",
                "quote_status": "eq.sent",
                "quote_sent_date": f"lte.{cutoff}",
                "order": "quote_sent_date.asc",
            },
        )
    except Exception:
        return []


async def get_open_projects(limit: int = 50) -> list[dict]:
    return await select_rows(
        "projects", {"select": "client,project_name,stage,due_date", "order": "created_at.desc", "limit": str(limit)}
    )


async def get_pending_invoices(limit: int = 50) -> list[dict]:
    return await select_rows(
        "invoices",
        {
            "select": "amount,status,due_date,projects(client,project_name)",
            "status": "neq.paid",
            "order": "due_date.asc",
            "limit": str(limit),
        },
    )


async def dashboard_snapshot() -> dict:
    """Backs the sidebar's real Alpha Mode Media section (2026-08-10) --
    was a generic unbuilt placeholder before. Each section fails soft
    independently (empty list, not an exception) so one bad Supabase
    request doesn't blank the whole dashboard -- same reasoning as
    leads_needing_followup's own fail-soft handling."""

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return []

    projects = await _safe(get_open_projects())
    invoices = await _safe(get_pending_invoices())
    leads = await _safe(leads_needing_followup())
    return {"projects": projects, "invoices": invoices, "leads": leads}


async def summarize_block() -> str:
    """Live snapshot of real Supabase projects/pending invoices for
    Frank's context -- same style as alpha_mode_db.summarize(). Fails soft
    (empty string) on any Supabase/network error so one bad request never
    takes down Frank's whole turn -- crew/equipment/local clients still
    need to render regardless (same reasoning as the summarize() early-
    return bug fixed 2026-08-02)."""
    try:
        projects = await get_open_projects()
        invoices = await get_pending_invoices()
    except Exception:
        return ""

    lines: list[str] = []
    if projects:
        lines.append("Alpha Mode Media Admin — Projects (live):")
        for p in projects:
            due = f", due {p['due_date']}" if p.get("due_date") else ""
            lines.append(f"  - {p.get('project_name') or '(untitled)'} for {p['client']} ({p['stage']}){due}")

    if invoices:
        lines.append("Alpha Mode Media Admin — Unpaid/pending invoices (live):")
        for i in invoices:
            proj = i.get("projects") or {}
            due = f", due {i['due_date']}" if i.get("due_date") else ""
            lines.append(
                f"  - R{i['amount']:,.2f} for {proj.get('client', '?')} — {proj.get('project_name', '?')} "
                f"({i['status']}{due})"
            )

    return "\n".join(lines)
