"""
Joshx -- Joshua's independent freelance creative division (video editing,
videography, photography), 2026-08-21. Confirmed directly with Joshua
before building: this is Phase 1 of a 28-section vision (full CRM, quote
builder, invoicing, finance/analytics, rate card, availability, equipment,
crew, portfolio, creative lab, content pipeline, documents, morning
brief/weekly review) -- foundation only. Clients/Leads/Projects, real data,
nothing fabricated; everything else is real future scope, not silently
dropped.

Own SQLite file (joshx.db), same "genuinely separate domain" reasoning as
alpha_mode.db/personal.db/automations.db. This is a deliberate, load-
bearing choice, not just convention-following: Alpha Mode Media's real
financial data lives in a completely separate, actual production Supabase
app Joshua runs day-to-day outside P Corp OS (see alpha_mode_supabase.py's
docstring) -- Joshx has no equivalent external app, so there's no shared
schema to bolt a `division` discriminator column onto even if that were
otherwise the right call. A wholly separate file satisfies the spec's own
"never merge the two businesses' operational data" requirement literally,
not just logically.

Kept deliberately small, same philosophy as alpha_mode_db.py's crew/
equipment tables: one free-text status/stage field per entity, no enums
enforced at the DB level -- Frank writes plain-English values directly.
Like every file under backend/data/, this is gitignored.
"""

from datetime import date, timedelta
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "joshx.db"


async def init_joshx_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                company TEXT,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                instagram TEXT,
                website TEXT,
                industry TEXT,
                client_type TEXT,
                lead_source TEXT,
                status TEXT NOT NULL DEFAULT 'lead',
                last_contact_date TEXT,
                next_follow_up_date TEXT,
                relationship_strength TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                project_description TEXT,
                service TEXT,
                estimated_value REAL,
                budget REAL,
                lead_source TEXT,
                probability INTEGER,
                stage TEXT NOT NULL DEFAULT 'new',
                follow_up_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                project_name TEXT NOT NULL,
                project_type TEXT,
                brief TEXT,
                start_date TEXT,
                due_date TEXT,
                shoot_date TEXT,
                budget REAL,
                priority TEXT,
                status TEXT NOT NULL DEFAULT 'brief',
                deliverables TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.commit()


async def _find_row_id(db: aiosqlite.Connection, table: str, identifier: str, name_col: str = "name") -> int | None:
    cursor = await db.execute(
        f"SELECT id FROM {table} WHERE {name_col} = ? COLLATE NOCASE AND deleted_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (identifier,),
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await db.execute(
            f"SELECT id FROM {table} WHERE {name_col} LIKE ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (f"%{identifier}%",),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def add_client(name: str, **fields) -> str:
    columns = ["name", *fields.keys()]
    placeholders = ", ".join("?" for _ in columns)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO clients ({', '.join(columns)}) VALUES ({placeholders})",
            (name, *fields.values()),
        )
        await db.commit()
    return name


async def update_client_status(identifier: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_row_id(db, "clients", identifier)
        if client_id is None:
            return False
        await db.execute("UPDATE clients SET status = ? WHERE id = ?", (new_status, client_id))
        await db.commit()
        return True


async def log_client_contact(identifier: str, contact_date: str | None = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_row_id(db, "clients", identifier)
        if client_id is None:
            return False
        await db.execute(
            "UPDATE clients SET last_contact_date = ? WHERE id = ?",
            (contact_date or date.today().isoformat(), client_id),
        )
        await db.commit()
        return True


async def add_lead(client_name: str, **fields) -> str:
    columns = ["client_name", *fields.keys()]
    placeholders = ", ".join("?" for _ in columns)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO leads ({', '.join(columns)}) VALUES ({placeholders})",
            (client_name, *fields.values()),
        )
        await db.commit()
    return client_name


async def update_lead_stage(identifier: str, new_stage: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        lead_id = await _find_row_id(db, "leads", identifier, name_col="client_name")
        if lead_id is None:
            return False
        await db.execute("UPDATE leads SET stage = ? WHERE id = ?", (new_stage, lead_id))
        await db.commit()
        return True


async def add_project(client_name: str, project_name: str, **fields) -> str:
    columns = ["client_name", "project_name", *fields.keys()]
    placeholders = ", ".join("?" for _ in columns)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO projects ({', '.join(columns)}) VALUES ({placeholders})",
            (client_name, project_name, *fields.values()),
        )
        await db.commit()
    return project_name


async def update_project_status(identifier: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        await db.execute("UPDATE projects SET status = ? WHERE id = ?", (new_status, project_id))
        await db.commit()
        return True


# Statuses that count as "wrapped up" for the dashboard's Active Projects
# count and Leads pipeline's Open Leads count -- kept in one place so the
# dashboard and any future Triggers-style rule agree on what "done" means.
_CLOSED_PROJECT_STATUSES = {"paid", "archived"}
_CLOSED_LEAD_STAGES = {"booked", "lost"}
_UPCOMING_SHOOT_WINDOW_DAYS = 14


async def dashboard_snapshot() -> dict:
    """Backs GET /joshx/dashboard. Deliberately does NOT include revenue/
    outstanding/available-days -- Phase 1 has no invoices or availability
    tables, and this codebase's own rule (Mission Status's fake progress
    bar, removed 2026-08-20; no fabricated 'Active Missions' stat on the
    War Room command map) is that a stat only appears once there's real
    data behind it. Those arrive when Money/Availability are built."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, company, status, last_contact_date, next_follow_up_date, created_at "
            "FROM clients WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        clients = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, client_name, project_description, service, estimated_value, stage, "
            "probability, follow_up_date, created_at FROM leads WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        leads = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, client_name, project_name, project_type, due_date, shoot_date, budget, "
            "priority, status, created_at FROM projects WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        projects = [dict(r) for r in await cursor.fetchall()]

    active_projects = sum(1 for p in projects if p["status"] not in _CLOSED_PROJECT_STATUSES)
    open_leads = sum(1 for lead in leads if lead["stage"] not in _CLOSED_LEAD_STAGES)
    shoot_horizon = (date.today() + timedelta(days=_UPCOMING_SHOOT_WINDOW_DAYS)).isoformat()
    today = date.today().isoformat()
    upcoming_shoots = sum(
        1
        for p in projects
        if p["shoot_date"] and today <= p["shoot_date"] <= shoot_horizon and p["status"] not in _CLOSED_PROJECT_STATUSES
    )

    return {
        "active_projects": active_projects,
        "open_leads": open_leads,
        "upcoming_shoots": upcoming_shoots,
        "clients": clients,
        "leads": leads,
        "projects": projects,
    }


async def summarize() -> str:
    """Folded into Frank's own system prompt (joshx_tools.build_joshx_block())
    -- same mechanism as build_alpha_mode_block()/build_operations_block(),
    so Frank has real context on Josh's freelance business without a
    delegated specialist relaying it (no consult_joshx_agent -- same "keep
    it Frank's own voice" call already made for Personal)."""
    snapshot = await dashboard_snapshot()
    if not snapshot["clients"] and not snapshot["leads"] and not snapshot["projects"]:
        return ""
    lines: list[str] = []
    if snapshot["clients"]:
        lines.append(f"Joshx clients ({len(snapshot['clients'])}):")
        for c in snapshot["clients"]:
            lines.append(f"  - {c['name']} ({c['status']})" + (f", {c['company']}" if c["company"] else ""))
    if snapshot["leads"]:
        lines.append(f"Joshx leads ({snapshot['open_leads']} open of {len(snapshot['leads'])} total):")
        for lead in snapshot["leads"]:
            value = f", est. R{lead['estimated_value']:,.2f}" if lead["estimated_value"] else ""
            lines.append(f"  - {lead['client_name']} — {lead['stage']}{value}")
    if snapshot["projects"]:
        lines.append(f"Joshx projects ({snapshot['active_projects']} active of {len(snapshot['projects'])} total):")
        for p in snapshot["projects"]:
            due = f", due {p['due_date']}" if p["due_date"] else ""
            lines.append(f"  - {p['project_name']} for {p['client_name']} — {p['status']}{due}")
    return "\n".join(lines)
