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
        # Migration path: projects existed before payment_status did
        # (added 2026-08-31 so "has the client paid" can be tracked
        # separately from `status` -- status also encodes production
        # stage, so a project sitting at "delivery" or "archived" had no
        # way to record payment, and a project paid early had no way to
        # reflect that without wrongly overwriting its real pipeline
        # stage). Same guarded-ALTER idiom as operations_db.py's
        # `deleted_at` migration -- CREATE TABLE alone wouldn't touch
        # Josh's real existing rows in this already-populated file.
        cursor = await db.execute("PRAGMA table_info(projects)")
        columns = {row[1] async for row in cursor}
        if "payment_status" not in columns:
            await db.execute("ALTER TABLE projects ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'unpaid'")
        # Migration path: added 2026-08-31 alongside convert_lead_to_project
        # -- gives a project a real, explicit link back to the lead it came
        # from, replacing add_project's own ambiguous "exactly one open
        # lead for this client" heuristic for the conversion path. Nullable
        # and unenforced at the app layer (SQLite doesn't enforce FKs here
        # by default, consistent with this file's own "no rigid
        # constraints" convention) -- a project with source_lead_id NULL is
        # still fully valid (direct-start project, no prior lead, or any
        # pre-existing row from before this column existed -- there's no
        # reliable way to reconstruct which lead an old project came from,
        # and guessing would be worse than an honest NULL).
        if "source_lead_id" not in columns:
            await db.execute("ALTER TABLE projects ADD COLUMN source_lead_id INTEGER REFERENCES leads(id)")

        # Invoices (2026-08-31) -- brand-new table, no existing rows to
        # migrate. NOT reusing alpha_mode_db.py's own `invoices` table as
        # a pattern beyond its original pre-migration shape (client_id/
        # project_id/amount/due_date/status): that table is explicitly
        # dead code today (see that file's own docstring, "Projects and
        # invoices moved OUT of here 2026-08-02... nothing writes to
        # them anymore") -- real Alpha Mode invoices live in the actual
        # production Supabase app (alpha_mode_supabase.py). Joshx has no
        # equivalent external app to sync to, so this is Joshx's own
        # real, first-class invoices table, extended with amount_paid/
        # issued_date/notes/a richer status vocabulary. project_id is a
        # genuine FK to an already-existing project row -- unlike
        # client_name/project_name elsewhere in this file, an invoice
        # can't exist ahead of the project it belongs to the way a
        # project can exist with no matching client record.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                amount REAL NOT NULL,
                amount_paid REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                issued_date TEXT,
                due_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )

        # Expenses (2026-09-03, P Corp OS systems audit) -- brand-new
        # table, same "real table, not a lossy single field" reasoning as
        # invoices: a project accrues multiple real line items (props,
        # fuel, crew meals) over its life, so a single running-total
        # column on `projects` couldn't be itemized or corrected without
        # hand-recomputing a total. `description` is free text, not a
        # category enum, matching this file's own "no enums enforced at
        # the DB level" convention. Revenue is deliberately NOT a new
        # column anywhere in this file -- it's computed as invoice totals
        # (once real invoices exist) falling back to `budget` otherwise,
        # same precedence rule _sync_project_payment_status_from_invoices
        # already established; profit/margin are likewise always computed
        # from these rows, never stored, so neither can ever drift from
        # the real data behind it.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                amount REAL NOT NULL,
                description TEXT,
                incurred_date TEXT,
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


async def delete_client(identifier: str) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing) -- "everything must be
    deletable if needed" (2026-08-31), same reasoning/shape as
    delete_lead. Returns the deleted client's real name, or None if
    nothing matched."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        client_id = await _find_row_id(db, "clients", identifier)
        if client_id is None:
            return None
        cursor = await db.execute("SELECT name FROM clients WHERE id = ?", (client_id,))
        row = await cursor.fetchone()
        await db.execute("UPDATE clients SET deleted_at = datetime('now') WHERE id = ?", (client_id,))
        await db.commit()
        return row["name"] if row else None


async def delete_client_by_id(client_id: int) -> bool:
    """Id-based, for the UI's own delete action -- same reasoning as
    delete_lead_by_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE clients SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (client_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def add_lead(client_name: str, **fields) -> str:
    """Upsert, not a bare INSERT (fixed 2026-08-27) -- same real bug class
    just found and fixed on add_project (confirmed live: two identical
    "Malondie SS26" project rows from Frank being asked to add/update the
    same project twice). `leads` has no unique constraint at all (unlike
    `clients.name`, which is UNIQUE and would at least raise rather than
    silently duplicate), so this was exposed here too.

    Keyed on (client_name, service), case-insensitive (COLLATE NOCASE) --
    `service` is the closest analog to add_project's own `project_name`
    half of its key: the thing that distinguishes two genuinely different
    engagements for the same client, rather than client_name alone (which
    would incorrectly merge two real simultaneous inquiries from one
    client into one row). Soft-deleted rows excluded from the match, same
    reasoning as add_project. On a match, only non-None fields from this
    call are merged in; on no match, a plain INSERT as before.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM leads WHERE client_name = ? COLLATE NOCASE "
            "AND service IS ? COLLATE NOCASE AND deleted_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (client_name, fields.get("service")),
        )
        existing = await cursor.fetchone()
        if existing is None:
            columns = ["client_name", *fields.keys()]
            placeholders = ", ".join("?" for _ in columns)
            await db.execute(
                f"INSERT INTO leads ({', '.join(columns)}) VALUES ({placeholders})",
                (client_name, *fields.values()),
            )
        else:
            lead_id = existing[0]
            non_null_fields = {k: v for k, v in fields.items() if v is not None}
            if non_null_fields:
                set_clause = ", ".join(f"{col} = ?" for col in non_null_fields)
                await db.execute(
                    f"UPDATE leads SET {set_clause} WHERE id = ?",
                    (*non_null_fields.values(), lead_id),
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


async def delete_lead(identifier: str) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing) -- for a dormant lead Josh
    wants gone from the list, same reasoning as operations_db.py's
    delete_task: distinct from update_lead_stage's "booked"/"lost"/etc.,
    which is for a lead that reached a real outcome. `leads` has no UI
    concept of "closed stages hide themselves" -- a booked/lost lead
    stays visible in the LEADS section indefinitely (confirmed live,
    2026-08-31: "Malondie" stayed listed as a lead well after "Malondie
    SS26" became a real, in-progress project) since a lead becoming a
    real project isn't tracked as a link anywhere, so nothing here
    auto-closes it. Returns the deleted lead's real client_name (so
    Frank can confirm what happened), or None if nothing matched."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lead_id = await _find_row_id(db, "leads", identifier, name_col="client_name")
        if lead_id is None:
            return None
        cursor = await db.execute("SELECT client_name FROM leads WHERE id = ?", (lead_id,))
        row = await cursor.fetchone()
        await db.execute("UPDATE leads SET deleted_at = datetime('now') WHERE id = ?", (lead_id,))
        await db.commit()
        return row["client_name"] if row else None


async def delete_lead_by_id(lead_id: int) -> bool:
    """Id-based, for the UI's own delete action -- same reasoning as
    set_project_status_by_id: the UI already knows the exact row id it's
    displaying, so fuzzy name-matching would be a real footgun here."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE leads SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (lead_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def convert_lead_to_project(
    lead_identifier: str,
    project_name: str,
    *,
    start_date: str | None = None,
    due_date: str | None = None,
    shoot_date: str | None = None,
    priority: str | None = None,
    deliverables: str | None = None,
) -> dict | None:
    """Explicit lead->project conversion (2026-08-31), replacing the
    ambiguous "exactly one open lead for this client" guess add_project
    makes with a real link (source_lead_id) and real field carry-forward
    -- client_name/project_type/budget/brief/notes come from the lead
    itself instead of Frank re-typing them from memory. add_project's
    own heuristic stays as a fallback for a project created directly
    (no formal lead was ever logged) -- this function is for the case
    where a tracked lead is the thing actually converting.

    One transaction, one commit -- deliberately does NOT call
    add_project/update_lead_stage (each opens and commits its own
    connection), since splitting this across multiple transactions
    would reintroduce the exact "two independent writes for one real
    event" race this file's own upsert docstrings already warn about.

    Unlike add_project's heuristic, this does NOT soft-delete the lead
    -- marks it 'booked' instead, which already excludes it from the
    open-leads list (JoshxView.swift's closedLeadStages, this file's own
    _CLOSED_LEAD_STAGES) without destroying its history. Returns a dict
    describing the new project, or None if lead_identifier matches
    nothing."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lead_id = await _find_row_id(db, "leads", lead_identifier, name_col="client_name")
        if lead_id is None:
            return None

        cursor = await db.execute(
            "SELECT client_name, service, budget, estimated_value, notes, project_description "
            "FROM leads WHERE id = ?",
            (lead_id,),
        )
        lead = await cursor.fetchone()

        project_fields = {
            "project_type": lead["service"],
            "budget": lead["budget"] if lead["budget"] is not None else lead["estimated_value"],
            "brief": lead["project_description"],
            "notes": lead["notes"],
            "source_lead_id": lead_id,
            "start_date": start_date,
            "due_date": due_date,
            "shoot_date": shoot_date,
            "priority": priority,
            "deliverables": deliverables,
        }
        project_fields = {k: v for k, v in project_fields.items() if v is not None}
        columns = ["client_name", "project_name", *project_fields.keys()]
        placeholders = ", ".join("?" for _ in columns)
        cursor = await db.execute(
            f"INSERT INTO projects ({', '.join(columns)}) VALUES ({placeholders})",
            (lead["client_name"], project_name, *project_fields.values()),
        )
        project_id = cursor.lastrowid

        await db.execute("UPDATE leads SET stage = 'booked' WHERE id = ?", (lead_id,))
        await db.execute(
            "UPDATE clients SET status = 'active' WHERE name = ? COLLATE NOCASE AND deleted_at IS NULL",
            (lead["client_name"],),
        )
        await db.commit()

        return {
            "project_name": project_name,
            "client_name": lead["client_name"],
            "lead_id": lead_id,
            "project_id": project_id,
        }


async def add_project(client_name: str, project_name: str, **fields) -> str:
    """Upsert, not a bare INSERT (fixed 2026-08-27) -- real bug: Frank
    calling this twice for the same project (e.g. re-confirming a booked
    job, or a slightly different phrasing of the same request in the same
    conversation) silently created a second row instead of updating the
    first, producing exact duplicates in the dashboard/summarize() output
    (confirmed live: two "Malondie SS26" rows for client_name=Malondie).

    Keyed on (client_name, project_name), case-insensitive (COLLATE
    NOCASE) -- matches this file's own existing case-insensitive lookup
    convention in _find_row_id, and "Malondie ss26" vs "Malondie SS26"
    should never be treated as two different projects. Soft-deleted rows
    (deleted_at IS NOT NULL) are excluded from the match, so re-adding a
    project whose old row was deleted creates a fresh one rather than
    reviving the deleted row.

    On a match, only non-None fields from this call are merged into the
    existing row (a plain UPDATE ... SET on the changed columns) --
    fields the caller didn't pass this time are left alone rather than
    being null'd out, since add_project's **fields already only carries
    whatever Frank actually supplied. On no match, behaves exactly as
    before: a plain INSERT.

    Two side effects added 2026-08-31, closing a real gap Joshua found
    live: "Malondie" stayed listed as an open lead well after "Malondie
    SS26" became a real, in-progress project -- leads/projects/clients
    are three unlinked tables (client_name is plain text everywhere, no
    FK) and nothing ever closed a lead out when it converted. Bundled
    here rather than left to the tool-dispatch layer, same reasoning
    people_db.py's log_interaction already uses for bundling two related
    writes into one call -- a caller shouldn't need two separate tool
    calls for one real event, regardless of which path invokes this.
      1. The matching client's status flips to 'active', if a clients
         row for this name exists (best-effort match, same as
         everywhere else in this file -- a project can exist with no
         linked client row, which stays a valid, unchanged state). A
         client with a real project underway is active by definition.
      2. Exactly one matching open lead gets auto-closed (soft-deleted),
         and ONLY when unambiguous: if zero or more than one non-deleted
         lead exists for this client_name, nothing is touched --
         guessing which of several live leads just converted risks
         silently destroying a real, unrelated, still-open opportunity.
         The ambiguous case is what delete_lead/delete_lead_by_id (the
         explicit, Josh-or-Frank-directed delete) is for instead.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM projects WHERE client_name = ? COLLATE NOCASE "
            "AND project_name = ? COLLATE NOCASE AND deleted_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (client_name, project_name),
        )
        existing = await cursor.fetchone()
        if existing is None:
            columns = ["client_name", "project_name", *fields.keys()]
            placeholders = ", ".join("?" for _ in columns)
            await db.execute(
                f"INSERT INTO projects ({', '.join(columns)}) VALUES ({placeholders})",
                (client_name, project_name, *fields.values()),
            )
        else:
            project_id = existing[0]
            non_null_fields = {k: v for k, v in fields.items() if v is not None}
            if non_null_fields:
                set_clause = ", ".join(f"{col} = ?" for col in non_null_fields)
                await db.execute(
                    f"UPDATE projects SET {set_clause} WHERE id = ?",
                    (*non_null_fields.values(), project_id),
                )

        await db.execute(
            "UPDATE clients SET status = 'active' WHERE name = ? COLLATE NOCASE AND deleted_at IS NULL",
            (client_name,),
        )

        cursor = await db.execute(
            "SELECT id FROM leads WHERE client_name = ? COLLATE NOCASE AND deleted_at IS NULL", (client_name,)
        )
        open_leads = await cursor.fetchall()
        if len(open_leads) == 1:
            await db.execute(
                "UPDATE leads SET deleted_at = datetime('now') WHERE id = ?", (open_leads[0][0],)
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


async def update_project_payment_status(identifier: str, new_payment_status: str) -> bool:
    """Frank-facing, fuzzy-match by name -- mirrors update_project_status
    exactly. Separate from `status`: that field also encodes production
    stage, so it can't double as "has the client paid" without either
    losing pipeline position or being unable to reflect an early
    payment."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        await db.execute("UPDATE projects SET payment_status = ? WHERE id = ?", (new_payment_status, project_id))
        await db.commit()
        return True


async def delete_project(identifier: str) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing) -- "everything must be
    deletable if needed" (2026-08-31), same reasoning/shape as
    delete_lead/delete_client. Returns the deleted project's real name,
    or None if nothing matched."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        cursor = await db.execute("SELECT project_name FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        await db.execute("UPDATE projects SET deleted_at = datetime('now') WHERE id = ?", (project_id,))
        await db.commit()
        return row["project_name"] if row else None


async def delete_project_by_id(project_id: int) -> bool:
    """Id-based, for the UI's own delete action -- same reasoning as
    set_project_status_by_id/delete_lead_by_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (project_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_project_status_by_id(project_id: int, new_status: str) -> bool:
    """Id-based, for the UI's own PATCH endpoints (main.py) -- deliberately
    not routed through _find_row_id's fuzzy name-matching, since the UI
    already knows the exact row id from the dashboard payload it's
    already displaying. Reusing the fuzzy-match path for a precise click
    on a specific row would be a real footgun, not a simplification."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET status = ? WHERE id = ? AND deleted_at IS NULL", (new_status, project_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_project_payment_status_by_id(project_id: int, new_payment_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET payment_status = ? WHERE id = ? AND deleted_at IS NULL",
            (new_payment_status, project_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def _sync_project_payment_status_from_invoices(db: aiosqlite.Connection, project_id: int) -> None:
    """Called at the end of add_joshx_invoice/update_joshx_invoice_status/
    record_joshx_invoice_payment/delete_joshx_invoice, same connection/
    transaction as the write that triggered it -- never runs on a bare
    read, so it can't silently clobber a manual override
    (update_joshx_project_payment_status/set_project_payment_status_by_id)
    between invoice events. Confirmed directly with Josh (2026-08-31):
    once real invoices exist for a project, invoice totals become the
    source of truth for payment_status -- a manual override only holds
    until the next invoice event recomputes it. If no non-deleted
    invoices exist for this project at all, payment_status is left
    completely untouched (a project can still be marked paid/unpaid on
    Frank's own say-so with zero invoices behind it, exactly as it
    already works today)."""
    cursor = await db.execute(
        "SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(amount_paid), 0) "
        "FROM invoices WHERE project_id = ? AND deleted_at IS NULL",
        (project_id,),
    )
    total, paid = await cursor.fetchone()
    if total == 0 and paid == 0:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM invoices WHERE project_id = ? AND deleted_at IS NULL", (project_id,)
        )
        (count,) = await cursor.fetchone()
        if count == 0:
            return
    if paid <= 0:
        new_status = "unpaid"
    elif paid >= total:
        new_status = "paid"
    else:
        new_status = "partially_paid"
    await db.execute("UPDATE projects SET payment_status = ? WHERE id = ?", (new_status, project_id))


async def _find_latest_invoice_id(db: aiosqlite.Connection, project_id: int) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM invoices WHERE project_id = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (project_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def add_joshx_invoice(
    project_identifier: str,
    amount: float,
    *,
    amount_paid: float | None = None,
    status: str | None = None,
    issued_date: str | None = None,
    due_date: str | None = None,
    notes: str | None = None,
) -> dict | None:
    """Resolves project_identifier via _find_row_id against `projects`
    (project_name). Plain INSERT, not an upsert-by-name like
    add_project/add_lead -- a project can legitimately have multiple
    real invoices over its life (a deposit, then a final invoice), so a
    repeat call is a genuinely new invoice, not the same event stated
    twice. Returns None if no project matches."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", project_identifier, name_col="project_name")
        if project_id is None:
            return None
        cursor = await db.execute(
            "INSERT INTO invoices (project_id, amount, amount_paid, status, issued_date, due_date, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, amount, amount_paid or 0, status or "draft", issued_date, due_date, notes),
        )
        invoice_id = cursor.lastrowid
        cursor = await db.execute("SELECT project_name, client_name FROM projects WHERE id = ?", (project_id,))
        project_name, client_name = await cursor.fetchone()
        await _sync_project_payment_status_from_invoices(db, project_id)
        await db.commit()
        return {
            "invoice_id": invoice_id,
            "project_id": project_id,
            "project_name": project_name,
            "client_name": client_name,
            "amount": amount,
        }


async def update_joshx_invoice_status(identifier: str, new_status: str) -> bool:
    """identifier is the project's name (fuzzy match, same as every
    other Frank-facing update_* in this file) -- resolves to that
    project's most recent non-deleted invoice, since Frank will say
    "mark Acme's invoice paid," not quote an invoice id."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        invoice_id = await _find_latest_invoice_id(db, project_id)
        if invoice_id is None:
            return False
        await db.execute("UPDATE invoices SET status = ? WHERE id = ?", (new_status, invoice_id))
        await _sync_project_payment_status_from_invoices(db, project_id)
        await db.commit()
        return True


async def record_joshx_invoice_payment(identifier: str, amount_paid: float) -> bool:
    """Sets amount_paid explicitly (the total paid to date, not an
    increment) -- "paid R5000 of it" should mean the running total, not
    add-to, avoiding double-counting if Frank is told the same fact
    twice. Same most-recent-invoice-for-this-project resolution as
    update_joshx_invoice_status."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        invoice_id = await _find_latest_invoice_id(db, project_id)
        if invoice_id is None:
            return False
        await db.execute("UPDATE invoices SET amount_paid = ? WHERE id = ?", (amount_paid, invoice_id))
        await _sync_project_payment_status_from_invoices(db, project_id)
        await db.commit()
        return True


async def delete_joshx_invoice(identifier: str) -> dict | None:
    """Soft delete of a project's most recent invoice, same shape as
    delete_project/delete_lead/delete_client -- "everything must be
    deletable if needed." Re-syncs payment_status afterward, since
    removing an invoice changes the real total behind it."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        invoice_id = await _find_latest_invoice_id(db, project_id)
        if invoice_id is None:
            return None
        cursor = await db.execute("SELECT project_name FROM projects WHERE id = ?", (project_id,))
        (project_name,) = await cursor.fetchone()
        await db.execute("UPDATE invoices SET deleted_at = datetime('now') WHERE id = ?", (invoice_id,))
        await _sync_project_payment_status_from_invoices(db, project_id)
        await db.commit()
        return {"invoice_id": invoice_id, "project_id": project_id, "project_name": project_name}


async def _find_latest_expense_id(db: aiosqlite.Connection, project_id: int) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM expenses WHERE project_id = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (project_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def log_joshx_project_expense(
    project_identifier: str,
    amount: float,
    *,
    description: str | None = None,
    incurred_date: str | None = None,
    notes: str | None = None,
) -> dict | None:
    """Plain INSERT, not an upsert -- a project legitimately accrues many
    real expense line items over its life (props, fuel, crew meals), so a
    repeat call is a genuinely new expense, not the same event stated
    twice (same reasoning as add_joshx_invoice)."""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", project_identifier, name_col="project_name")
        if project_id is None:
            return None
        cursor = await db.execute(
            "INSERT INTO expenses (project_id, amount, description, incurred_date, notes) VALUES (?, ?, ?, ?, ?)",
            (project_id, amount, description, incurred_date, notes),
        )
        expense_id = cursor.lastrowid
        cursor = await db.execute("SELECT project_name, client_name FROM projects WHERE id = ?", (project_id,))
        project_name, client_name = await cursor.fetchone()
        await db.commit()
        return {
            "expense_id": expense_id,
            "project_id": project_id,
            "project_name": project_name,
            "client_name": client_name,
            "amount": amount,
        }


async def delete_joshx_project_expense(identifier: str) -> dict | None:
    """Soft delete of a project's most recent expense -- same shape as
    delete_joshx_invoice, "everything must be deletable if needed.\""""
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        expense_id = await _find_latest_expense_id(db, project_id)
        if expense_id is None:
            return None
        cursor = await db.execute("SELECT project_name FROM projects WHERE id = ?", (project_id,))
        (project_name,) = await cursor.fetchone()
        await db.execute("UPDATE expenses SET deleted_at = datetime('now') WHERE id = ?", (expense_id,))
        await db.commit()
        return {"expense_id": expense_id, "project_id": project_id, "project_name": project_name}


# Statuses that count as "wrapped up" for the dashboard's Active Projects
# count and Leads pipeline's Open Leads count -- kept in one place so the
# dashboard and any future Triggers-style rule agree on what "done" means.
_CLOSED_PROJECT_STATUSES = {"paid", "archived"}
_CLOSED_LEAD_STAGES = {"booked", "lost"}
_UPCOMING_SHOOT_WINDOW_DAYS = 14

# The real, full vocabulary for `projects.status`/`payment_status` -- not
# enforced at the DB level (see this file's own docstring), but Frank's
# tool descriptions already commit to exactly this set, and the new
# UI-facing PATCH endpoints (main.py) validate against it server-side --
# the first Joshx write path not gated by Frank's own judgment, so it
# earns a guardrail the chat-tool path doesn't need.
PROJECT_STATUS_VALUES = {
    "brief", "pre_production", "production", "post_production",
    "client_review", "revision", "delivery", "paid", "archived",
}
PROJECT_PAYMENT_STATUS_VALUES = {"unpaid", "partially_paid", "paid"}
JOSHX_INVOICE_STATUS_VALUES = {"draft", "sent", "partially_paid", "paid", "overdue"}


async def dashboard_snapshot() -> dict:
    """Backs GET /joshx/dashboard. Deliberately does NOT compute a
    revenue/outstanding stat, even though invoices now exist (2026-08-31)
    -- this codebase's own rule (Mission Status's fake progress bar,
    removed 2026-08-20; no fabricated 'Active Missions' stat on the War
    Room command map) is that a stat only appears once there's real data
    AND a real UI asking for it; dashboard stat UI for invoicing is an
    explicit, named follow-on, not built here. The raw `invoices` list
    is still returned below, same as every other domain -- Frank's own
    context (summarize()) and any future UI can read it directly.
    Available-days still has no table at all."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Real bug found live (2026-08-27): these three SELECTs were
        # under-selecting columns that add_joshx_client/add_joshx_lead/
        # add_joshx_project can already write -- a client's email/phone/
        # Instagram, a lead's budget, a project's brief, all genuinely
        # stored, never once shown on either platform's dashboard because
        # the gap was here, not in the Swift views (which just render
        # whatever this function returns). Every column below already
        # existed in the schema at the top of this file; nothing new was
        # added to get this data flowing.
        cursor = await db.execute(
            "SELECT id, name, company, contact_name, email, phone, instagram, website, industry, "
            "client_type, lead_source, status, last_contact_date, next_follow_up_date, "
            "relationship_strength, notes, created_at "
            "FROM clients WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        clients = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, client_name, project_description, service, estimated_value, budget, "
            "lead_source, stage, probability, follow_up_date, notes, created_at "
            "FROM leads WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        leads = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, client_name, project_name, project_type, brief, start_date, due_date, "
            "shoot_date, budget, priority, status, payment_status, source_lead_id, deliverables, notes, "
            "created_at FROM projects WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        projects = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, project_id, amount, amount_paid, status, issued_date, due_date, notes, created_at "
            "FROM invoices WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        invoices = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, project_id, amount, description, incurred_date, notes, created_at "
            "FROM expenses WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        expenses = [dict(r) for r in await cursor.fetchall()]

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
        "invoices": invoices,
        "expenses": expenses,
    }


async def compute_performance_metrics() -> dict:
    """Backs GET /joshx/analytics (2026-09-06, systems audit §3: "zero
    averages, growth rates, repeat-client %, or period-over-period
    comparisons anywhere"). Deliberately a separate function from
    dashboard_snapshot() above, not new keys folded into it -- that
    function's own docstring already drew a real boundary ("deliberately
    does NOT compute a revenue/outstanding stat"), and blurring it here
    would undo that.

    Real finding checked directly against backend/data/joshx.db before
    designing anything, not assumed from the schema: invoices.issued_date,
    expenses.incurred_date, and projects.start_date/due_date are always
    NULL in every real row today -- free-text fields Frank can fill in but
    usually doesn't. shoot_date is sometimes populated but isn't even
    guaranteed to be a real date string (one real row's value is literally
    "This Wednesday, 9:30am-12pm"). The only reliably-populated timestamp
    anywhere in this schema is created_at, a SQL DEFAULT (datetime('now'))
    -- not something Frank has to remember. Every metric below is chosen
    because it survives that reality, not because it's the most ambitious
    thing the audit's own wishlist named.

    Also found: the dedicated `clients` table has zero real rows -- client
    identity in practice lives entirely in the free-text `client_name`
    field on leads/projects, never the clients table its own CRUD tools
    were built for. Repeat-client rate is deliberately keyed off
    projects.client_name (exact string match, no fuzzy dedup) for exactly
    this reason -- that's what the business actually runs on today.

    Every rate/average below ships with its own real sample size (n), not
    just the number -- same "don't let a small sample read as more
    confident than it is" discipline the executive summary's own Trading
    Division section already established ("3 trades carries no
    statistical weight yet")."""
    snapshot = await dashboard_snapshot()
    projects = snapshot["projects"]
    leads = snapshot["leads"]

    client_project_counts: dict[str, int] = {}
    for p in projects:
        client_project_counts[p["client_name"]] = client_project_counts.get(p["client_name"], 0) + 1
    distinct_clients = len(client_project_counts)
    repeat_clients = sum(1 for count in client_project_counts.values() if count >= 2)
    repeat_client_rate = (repeat_clients / distinct_clients) if distinct_clients else None

    project_budgets = [p["budget"] for p in projects if p["budget"]]
    avg_project_value = (sum(project_budgets) / len(project_budgets)) if project_budgets else None

    total_leads = len(leads)
    converted_leads = sum(1 for lead in leads if lead["stage"] == "booked")
    lead_conversion_rate = (converted_leads / total_leads) if total_leads else None

    today = date.today()
    this_month_key = (today.year, today.month)
    last_month_date = (today.replace(day=1) - timedelta(days=1))
    last_month_key = (last_month_date.year, last_month_date.month)
    projects_this_month = 0
    projects_last_month = 0
    for p in projects:
        created = p["created_at"]
        if not created:
            continue
        try:
            created_date = date.fromisoformat(created[:10])
        except ValueError:
            continue
        key = (created_date.year, created_date.month)
        if key == this_month_key:
            projects_this_month += 1
        elif key == last_month_key:
            projects_last_month += 1

    return {
        "repeat_client_rate": repeat_client_rate,
        "distinct_clients": distinct_clients,
        "repeat_clients": repeat_clients,
        "avg_project_value": avg_project_value,
        "priced_projects": len(project_budgets),
        "lead_conversion_rate": lead_conversion_rate,
        "converted_leads": converted_leads,
        "total_leads": total_leads,
        "projects_created_this_month": projects_this_month,
        "projects_created_last_month": projects_last_month,
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
    if snapshot["invoices"]:
        projects_by_id = {p["id"]: p for p in snapshot["projects"]}
        lines.append(f"Joshx invoices ({len(snapshot['invoices'])}):")
        for inv in snapshot["invoices"]:
            project = projects_by_id.get(inv["project_id"])
            label = project["project_name"] if project else f"project #{inv['project_id']}"
            due = f", due {inv['due_date']}" if inv["due_date"] else ""
            lines.append(f"  - {label} — R{inv['amount']:,.2f} ({inv['status']}, R{inv['amount_paid']:,.2f} paid){due}")
    if snapshot["expenses"]:
        projects_by_id = {p["id"]: p for p in snapshot["projects"]}
        lines.append(f"Joshx expenses ({len(snapshot['expenses'])}):")
        for exp in snapshot["expenses"]:
            project = projects_by_id.get(exp["project_id"])
            label = project["project_name"] if project else f"project #{exp['project_id']}"
            desc = f" — {exp['description']}" if exp["description"] else ""
            lines.append(f"  - {label}: R{exp['amount']:,.2f}{desc}")
    # Per-project profit, computed here rather than stored anywhere (same
    # "never persist a derived value" discipline this file already
    # applies to payment_status/revenue) -- deliberately skips any
    # project with zero real invoice/expense activity, so a project
    # sitting on just a budget quote never gets a fabricated "100%
    # margin" nobody has actually verified. This is a smaller, different
    # thing than the business-wide revenue rollup already declined twice
    # in this file's own docstrings: "how profitable was this specific
    # job" is exactly the conversational use case real invoices/expenses
    # exist for.
    if snapshot["invoices"] or snapshot["expenses"]:
        invoices_by_project: dict[int, list[dict]] = {}
        for inv in snapshot["invoices"]:
            invoices_by_project.setdefault(inv["project_id"], []).append(inv)
        expenses_by_project: dict[int, list[dict]] = {}
        for exp in snapshot["expenses"]:
            expenses_by_project.setdefault(exp["project_id"], []).append(exp)
        profit_lines = []
        for p in snapshot["projects"]:
            project_invoices = invoices_by_project.get(p["id"], [])
            project_expenses = expenses_by_project.get(p["id"], [])
            if not project_invoices and not project_expenses:
                continue
            revenue = sum(inv["amount"] for inv in project_invoices) if project_invoices else (p["budget"] or 0)
            expenses_total = sum(exp["amount"] for exp in project_expenses)
            profit = revenue - expenses_total
            margin = f", {profit / revenue * 100:.0f}% margin" if revenue else ""
            profit_lines.append(
                f"  - {p['project_name']} — R{revenue:,.2f} revenue, R{expenses_total:,.2f} expenses, "
                f"R{profit:,.2f} profit{margin}"
            )
        if profit_lines:
            lines.append("Joshx project profitability (revenue = invoiced total, or budget if no invoices yet):")
            lines.extend(profit_lines)

    metrics = await compute_performance_metrics()
    metric_lines = []
    if metrics["repeat_client_rate"] is not None:
        metric_lines.append(
            f"  - Repeat-client rate: {metrics['repeat_client_rate']:.0%} "
            f"({metrics['repeat_clients']} of {metrics['distinct_clients']} clients have booked more than one project)"
        )
    if metrics["avg_project_value"] is not None:
        metric_lines.append(
            f"  - Average project value: R{metrics['avg_project_value']:,.2f} "
            f"(across {metrics['priced_projects']} priced project(s))"
        )
    if metrics["lead_conversion_rate"] is not None:
        metric_lines.append(
            f"  - Lead-to-project conversion: {metrics['lead_conversion_rate']:.0%} "
            f"({metrics['converted_leads']} of {metrics['total_leads']} leads booked)"
        )
    metric_lines.append(
        f"  - Projects created this calendar month: {metrics['projects_created_this_month']} "
        f"(last month: {metrics['projects_created_last_month']})"
    )
    if metric_lines:
        lines.append(
            "Joshx performance metrics (small real sample sizes -- treat rates/averages accordingly, "
            "not as statistically confident trends yet):"
        )
        lines.extend(metric_lines)
    return "\n".join(lines)
