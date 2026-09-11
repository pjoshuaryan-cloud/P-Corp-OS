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

Dual-backend dispatchers (2026-09-11, iPhone independence pass): same
pattern as every other domain -- postgres_conn: Any = None, SQLite body
renamed _<name>_sqlite, Postgres sibling added. One real translation
issue found here specifically: SQLite's `service IS ? COLLATE NOCASE`
(a NULL-safe comparison against a bound parameter) has no Postgres
equivalent via plain IS -- Postgres's IS only accepts NULL/TRUE/FALSE/
DISTINCT FROM literals, not an arbitrary bound value. The Postgres
sibling uses `IS NOT DISTINCT FROM %s` instead, which is the real
NULL-safe equality Postgres does support.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
        cursor = await db.execute("PRAGMA table_info(projects)")
        columns = {row[1] async for row in cursor}
        if "payment_status" not in columns:
            await db.execute("ALTER TABLE projects ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'unpaid'")
        if "source_lead_id" not in columns:
            await db.execute("ALTER TABLE projects ADD COLUMN source_lead_id INTEGER REFERENCES leads(id)")

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


async def _find_row_id_postgres(conn: Any, table: str, identifier: str, name_col: str = "name") -> int | None:
    # ILIKE, not LIKE -- same case-sensitivity fix proven necessary
    # throughout this migration. table is always one of a small fixed set
    # of literal strings this file passes itself, never user input, so
    # f-string interpolation here is the same trust boundary as the
    # SQLite version above.
    async with conn.cursor() as cur:
        await cur.execute(
            f"SELECT id FROM joshx.{table} WHERE {name_col} ILIKE %s AND deleted_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (identifier,),
        )
        row = await cur.fetchone()
        if row is None:
            await cur.execute(
                f"SELECT id FROM joshx.{table} WHERE {name_col} ILIKE %s AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                (f"%{identifier}%",),
            )
            row = await cur.fetchone()
        return row[0] if row else None


async def add_client(name: str, postgres_conn: Any = None, **fields) -> str:
    if postgres_conn is not None:
        # status/created_at supplied explicitly -- same missing-DEFAULT
        # gap found repeatedly this migration.
        columns = ["name", *fields.keys(), "status", "created_at"]
        value_placeholders = ", ".join("%s" for _ in fields)
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"INSERT INTO joshx.clients ({', '.join(columns)}) "
                f"VALUES (%s{',' + value_placeholders if fields else ''}, 'lead', (now() AT TIME ZONE 'utc'))",
                (name, *fields.values()),
            )
        await postgres_conn.commit()
        return name
    columns = ["name", *fields.keys()]
    placeholders = ", ".join("?" for _ in columns)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO clients ({', '.join(columns)}) VALUES ({placeholders})",
            (name, *fields.values()),
        )
        await db.commit()
    return name


async def update_client_status(identifier: str, new_status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        client_id = await _find_row_id_postgres(postgres_conn, "clients", identifier)
        if client_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE joshx.clients SET status = %s WHERE id = %s", (new_status, client_id))
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_row_id(db, "clients", identifier)
        if client_id is None:
            return False
        await db.execute("UPDATE clients SET status = ? WHERE id = ?", (new_status, client_id))
        await db.commit()
        return True


async def log_client_contact(identifier: str, contact_date: str | None = None, postgres_conn: Any = None) -> bool:
    date_value = contact_date or date.today().isoformat()
    if postgres_conn is not None:
        client_id = await _find_row_id_postgres(postgres_conn, "clients", identifier)
        if client_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE joshx.clients SET last_contact_date = %s WHERE id = %s", (date_value, client_id))
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_row_id(db, "clients", identifier)
        if client_id is None:
            return False
        await db.execute("UPDATE clients SET last_contact_date = ? WHERE id = ?", (date_value, client_id))
        await db.commit()
        return True


async def delete_client(identifier: str, postgres_conn: Any = None) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing) -- "everything must be
    deletable if needed" (2026-08-31), same reasoning/shape as
    delete_lead. Returns the deleted client's real name, or None if
    nothing matched."""
    if postgres_conn is not None:
        client_id = await _find_row_id_postgres(postgres_conn, "clients", identifier)
        if client_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT name FROM joshx.clients WHERE id = %s", (client_id,))
            (name,) = await cur.fetchone()
            await cur.execute("UPDATE joshx.clients SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (client_id,))
        await postgres_conn.commit()
        return name
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


async def delete_client_by_id(client_id: int, postgres_conn: Any = None) -> bool:
    """Id-based, for the UI's own delete action -- same reasoning as
    delete_lead_by_id."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.clients SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (client_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE clients SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (client_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def add_lead(client_name: str, postgres_conn: Any = None, **fields) -> str:
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
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            # IS NOT DISTINCT FROM, not IS -- Postgres's IS only accepts
            # NULL/TRUE/FALSE/DISTINCT FROM literals, not an arbitrary
            # bound parameter (SQLite's IS ? works fine; Postgres's
            # equivalent NULL-safe comparison against a bound value is
            # IS NOT DISTINCT FROM).
            await cur.execute(
                "SELECT id FROM joshx.leads WHERE client_name ILIKE %s "
                "AND service IS NOT DISTINCT FROM %s AND deleted_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (client_name, fields.get("service")),
            )
            existing = await cur.fetchone()
            if existing is None:
                columns = ["client_name", *fields.keys(), "stage", "created_at"]
                value_placeholders = ", ".join("%s" for _ in fields)
                await cur.execute(
                    f"INSERT INTO joshx.leads ({', '.join(columns)}) "
                    f"VALUES (%s{',' + value_placeholders if fields else ''}, 'new', (now() AT TIME ZONE 'utc'))",
                    (client_name, *fields.values()),
                )
            else:
                lead_id = existing[0]
                non_null_fields = {k: v for k, v in fields.items() if v is not None}
                if non_null_fields:
                    set_clause = ", ".join(f"{col} = %s" for col in non_null_fields)
                    await cur.execute(
                        f"UPDATE joshx.leads SET {set_clause} WHERE id = %s",
                        (*non_null_fields.values(), lead_id),
                    )
        await postgres_conn.commit()
        return client_name
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


async def update_lead_stage(identifier: str, new_stage: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        lead_id = await _find_row_id_postgres(postgres_conn, "leads", identifier, name_col="client_name")
        if lead_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE joshx.leads SET stage = %s WHERE id = %s", (new_stage, lead_id))
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        lead_id = await _find_row_id(db, "leads", identifier, name_col="client_name")
        if lead_id is None:
            return False
        await db.execute("UPDATE leads SET stage = ? WHERE id = ?", (new_stage, lead_id))
        await db.commit()
        return True


async def delete_lead(identifier: str, postgres_conn: Any = None) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing) -- for a dormant lead Josh
    wants gone from the list. Returns the deleted lead's real client_name
    (so Frank can confirm what happened), or None if nothing matched."""
    if postgres_conn is not None:
        lead_id = await _find_row_id_postgres(postgres_conn, "leads", identifier, name_col="client_name")
        if lead_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT client_name FROM joshx.leads WHERE id = %s", (lead_id,))
            (client_name,) = await cur.fetchone()
            await cur.execute("UPDATE joshx.leads SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (lead_id,))
        await postgres_conn.commit()
        return client_name
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


async def delete_lead_by_id(lead_id: int, postgres_conn: Any = None) -> bool:
    """Id-based, for the UI's own delete action."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.leads SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s AND deleted_at IS NULL",
                (lead_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
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
    postgres_conn: Any = None,
) -> dict | None:
    """Explicit lead->project conversion (2026-08-31) -- real link
    (source_lead_id) and real field carry-forward from the lead itself.
    One transaction, one commit. Does NOT soft-delete the lead -- marks
    it 'booked' instead."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM joshx.leads WHERE client_name ILIKE %s AND deleted_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (lead_identifier,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT id FROM joshx.leads WHERE client_name ILIKE %s AND deleted_at IS NULL "
                    "ORDER BY id DESC LIMIT 1",
                    (f"%{lead_identifier}%",),
                )
                row = await cur.fetchone()
            if row is None:
                return None
            lead_id = row[0]

            await cur.execute(
                "SELECT client_name, service, budget, estimated_value, notes, project_description "
                "FROM joshx.leads WHERE id = %s",
                (lead_id,),
            )
            client_name, service, budget, estimated_value, notes, project_description = await cur.fetchone()

            project_fields = {
                "project_type": service,
                "budget": budget if budget is not None else estimated_value,
                "brief": project_description,
                "notes": notes,
                "source_lead_id": lead_id,
                "start_date": start_date,
                "due_date": due_date,
                "shoot_date": shoot_date,
                "priority": priority,
                "deliverables": deliverables,
            }
            project_fields = {k: v for k, v in project_fields.items() if v is not None}
            # status/payment_status/created_at supplied explicitly --
            # payment_status is a NOT NULL column added via SQLite ALTER
            # TABLE with a DEFAULT that (like every other DEFAULT in this
            # migration) never made it into the Postgres DDL.
            columns = ["client_name", "project_name", *project_fields.keys(), "status", "payment_status", "created_at"]
            value_placeholders = ", ".join("%s" for _ in project_fields)
            await cur.execute(
                f"INSERT INTO joshx.projects ({', '.join(columns)}) "
                f"VALUES (%s, %s{',' + value_placeholders if project_fields else ''}, 'brief', 'unpaid', (now() AT TIME ZONE 'utc')) "
                f"RETURNING id",
                (client_name, project_name, *project_fields.values()),
            )
            (project_id,) = await cur.fetchone()

            await cur.execute("UPDATE joshx.leads SET stage = 'booked' WHERE id = %s", (lead_id,))
            await cur.execute(
                "UPDATE joshx.clients SET status = 'active' WHERE name ILIKE %s AND deleted_at IS NULL",
                (client_name,),
            )
        await postgres_conn.commit()

        return {
            "project_name": project_name,
            "client_name": client_name,
            "lead_id": lead_id,
            "project_id": project_id,
        }

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


async def add_project(client_name: str, project_name: str, postgres_conn: Any = None, **fields) -> str:
    """Upsert, not a bare INSERT (fixed 2026-08-27). Keyed on
    (client_name, project_name), case-insensitive. Two side effects
    (2026-08-31): matching client's status flips to 'active'; exactly
    one matching open lead gets auto-closed, only when unambiguous."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM joshx.projects WHERE client_name ILIKE %s "
                "AND project_name ILIKE %s AND deleted_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (client_name, project_name),
            )
            existing = await cur.fetchone()
            if existing is None:
                # status/payment_status/created_at supplied explicitly --
                # same missing-DEFAULT gap as convert_lead_to_project above.
                columns = ["client_name", "project_name", *fields.keys(), "status", "payment_status", "created_at"]
                value_placeholders = ", ".join("%s" for _ in fields)
                await cur.execute(
                    f"INSERT INTO joshx.projects ({', '.join(columns)}) "
                    f"VALUES (%s, %s{',' + value_placeholders if fields else ''}, 'brief', 'unpaid', (now() AT TIME ZONE 'utc'))",
                    (client_name, project_name, *fields.values()),
                )
            else:
                project_id = existing[0]
                non_null_fields = {k: v for k, v in fields.items() if v is not None}
                if non_null_fields:
                    set_clause = ", ".join(f"{col} = %s" for col in non_null_fields)
                    await cur.execute(
                        f"UPDATE joshx.projects SET {set_clause} WHERE id = %s",
                        (*non_null_fields.values(), project_id),
                    )

            await cur.execute(
                "UPDATE joshx.clients SET status = 'active' WHERE name ILIKE %s AND deleted_at IS NULL",
                (client_name,),
            )

            await cur.execute(
                "SELECT id FROM joshx.leads WHERE client_name ILIKE %s AND deleted_at IS NULL", (client_name,)
            )
            open_leads = await cur.fetchall()
            if len(open_leads) == 1:
                await cur.execute(
                    "UPDATE joshx.leads SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s",
                    (open_leads[0][0],),
                )
        await postgres_conn.commit()
        return project_name

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


async def update_project_status(identifier: str, new_status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE joshx.projects SET status = %s WHERE id = %s", (new_status, project_id))
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        await db.execute("UPDATE projects SET status = ? WHERE id = ?", (new_status, project_id))
        await db.commit()
        return True


async def update_project_payment_status(identifier: str, new_payment_status: str, postgres_conn: Any = None) -> bool:
    """Frank-facing, fuzzy-match by name -- mirrors update_project_status
    exactly."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.projects SET payment_status = %s WHERE id = %s", (new_payment_status, project_id)
            )
        await postgres_conn.commit()
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        project_id = await _find_row_id(db, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        await db.execute("UPDATE projects SET payment_status = ? WHERE id = ?", (new_payment_status, project_id))
        await db.commit()
        return True


async def delete_project(identifier: str, postgres_conn: Any = None) -> str | None:
    """Soft delete (fuzzy-match, Frank-facing). Returns the deleted
    project's real name, or None if nothing matched."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT project_name FROM joshx.projects WHERE id = %s", (project_id,))
            (project_name,) = await cur.fetchone()
            await cur.execute(
                "UPDATE joshx.projects SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (project_id,)
            )
        await postgres_conn.commit()
        return project_name
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


async def delete_project_by_id(project_id: int, postgres_conn: Any = None) -> bool:
    """Id-based, for the UI's own delete action."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.projects SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (project_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (project_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_project_status_by_id(project_id: int, new_status: str, postgres_conn: Any = None) -> bool:
    """Id-based, for the UI's own PATCH endpoints."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.projects SET status = %s WHERE id = %s AND deleted_at IS NULL",
                (new_status, project_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET status = ? WHERE id = ? AND deleted_at IS NULL", (new_status, project_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_project_payment_status_by_id(project_id: int, new_payment_status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE joshx.projects SET payment_status = %s WHERE id = %s AND deleted_at IS NULL",
                (new_payment_status, project_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE projects SET payment_status = ? WHERE id = ? AND deleted_at IS NULL",
            (new_payment_status, project_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def _sync_project_payment_status_from_invoices(db: aiosqlite.Connection, project_id: int) -> None:
    """Called at the end of every invoice-mutating function, same
    connection/transaction as the write that triggered it."""
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


async def _sync_project_payment_status_from_invoices_postgres(conn: Any, cur: Any, project_id: int) -> None:
    await cur.execute(
        "SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(amount_paid), 0) "
        "FROM joshx.invoices WHERE project_id = %s AND deleted_at IS NULL",
        (project_id,),
    )
    total, paid = await cur.fetchone()
    if total == 0 and paid == 0:
        await cur.execute(
            "SELECT COUNT(*) FROM joshx.invoices WHERE project_id = %s AND deleted_at IS NULL", (project_id,)
        )
        (count,) = await cur.fetchone()
        if count == 0:
            return
    if paid <= 0:
        new_status = "unpaid"
    elif paid >= total:
        new_status = "paid"
    else:
        new_status = "partially_paid"
    await cur.execute("UPDATE joshx.projects SET payment_status = %s WHERE id = %s", (new_status, project_id))


async def _find_latest_invoice_id(db: aiosqlite.Connection, project_id: int) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM invoices WHERE project_id = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (project_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def _find_latest_invoice_id_postgres(cur: Any, project_id: int) -> int | None:
    await cur.execute(
        "SELECT id FROM joshx.invoices WHERE project_id = %s AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (project_id,),
    )
    row = await cur.fetchone()
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
    postgres_conn: Any = None,
) -> dict | None:
    """Plain INSERT, not an upsert -- a project can legitimately have
    multiple real invoices over its life."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            project_id = await _find_row_id_postgres(postgres_conn, "projects", project_identifier, name_col="project_name")
            if project_id is None:
                return None
            await cur.execute(
                "INSERT INTO joshx.invoices "
                "(project_id, amount, amount_paid, status, issued_date, due_date, notes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (project_id, amount, amount_paid or 0, status or "draft", issued_date, due_date, notes),
            )
            (invoice_id,) = await cur.fetchone()
            await cur.execute("SELECT project_name, client_name FROM joshx.projects WHERE id = %s", (project_id,))
            project_name, client_name = await cur.fetchone()
            await _sync_project_payment_status_from_invoices_postgres(postgres_conn, cur, project_id)
        await postgres_conn.commit()
        return {
            "invoice_id": invoice_id,
            "project_id": project_id,
            "project_name": project_name,
            "client_name": client_name,
            "amount": amount,
        }
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


async def update_joshx_invoice_status(identifier: str, new_status: str, postgres_conn: Any = None) -> bool:
    """identifier is the project's name (fuzzy match) -- resolves to that
    project's most recent non-deleted invoice."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            invoice_id = await _find_latest_invoice_id_postgres(cur, project_id)
            if invoice_id is None:
                return False
            await cur.execute("UPDATE joshx.invoices SET status = %s WHERE id = %s", (new_status, invoice_id))
            await _sync_project_payment_status_from_invoices_postgres(postgres_conn, cur, project_id)
        await postgres_conn.commit()
        return True
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


async def record_joshx_invoice_payment(identifier: str, amount_paid: float, postgres_conn: Any = None) -> bool:
    """Sets amount_paid explicitly (the total paid to date, not an
    increment)."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return False
        async with postgres_conn.cursor() as cur:
            invoice_id = await _find_latest_invoice_id_postgres(cur, project_id)
            if invoice_id is None:
                return False
            await cur.execute("UPDATE joshx.invoices SET amount_paid = %s WHERE id = %s", (amount_paid, invoice_id))
            await _sync_project_payment_status_from_invoices_postgres(postgres_conn, cur, project_id)
        await postgres_conn.commit()
        return True
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


async def delete_joshx_invoice(identifier: str, postgres_conn: Any = None) -> dict | None:
    """Soft delete of a project's most recent invoice. Re-syncs
    payment_status afterward."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            invoice_id = await _find_latest_invoice_id_postgres(cur, project_id)
            if invoice_id is None:
                return None
            await cur.execute("SELECT project_name FROM joshx.projects WHERE id = %s", (project_id,))
            (project_name,) = await cur.fetchone()
            await cur.execute(
                "UPDATE joshx.invoices SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (invoice_id,)
            )
            await _sync_project_payment_status_from_invoices_postgres(postgres_conn, cur, project_id)
        await postgres_conn.commit()
        return {"invoice_id": invoice_id, "project_id": project_id, "project_name": project_name}
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


async def _find_latest_expense_id_postgres(cur: Any, project_id: int) -> int | None:
    await cur.execute(
        "SELECT id FROM joshx.expenses WHERE project_id = %s AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (project_id,),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def log_joshx_project_expense(
    project_identifier: str,
    amount: float,
    *,
    description: str | None = None,
    incurred_date: str | None = None,
    notes: str | None = None,
    postgres_conn: Any = None,
) -> dict | None:
    """Plain INSERT, not an upsert -- a project accrues many real expense
    line items over its life."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", project_identifier, name_col="project_name")
        if project_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO joshx.expenses (project_id, amount, description, incurred_date, notes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (project_id, amount, description, incurred_date, notes),
            )
            (expense_id,) = await cur.fetchone()
            await cur.execute("SELECT project_name, client_name FROM joshx.projects WHERE id = %s", (project_id,))
            project_name, client_name = await cur.fetchone()
        await postgres_conn.commit()
        return {
            "expense_id": expense_id,
            "project_id": project_id,
            "project_name": project_name,
            "client_name": client_name,
            "amount": amount,
        }
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


async def delete_joshx_project_expense(identifier: str, postgres_conn: Any = None) -> dict | None:
    """Soft delete of a project's most recent expense."""
    if postgres_conn is not None:
        project_id = await _find_row_id_postgres(postgres_conn, "projects", identifier, name_col="project_name")
        if project_id is None:
            return None
        async with postgres_conn.cursor() as cur:
            expense_id = await _find_latest_expense_id_postgres(cur, project_id)
            if expense_id is None:
                return None
            await cur.execute("SELECT project_name FROM joshx.projects WHERE id = %s", (project_id,))
            (project_name,) = await cur.fetchone()
            await cur.execute(
                "UPDATE joshx.expenses SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s", (expense_id,)
            )
        await postgres_conn.commit()
        return {"expense_id": expense_id, "project_id": project_id, "project_name": project_name}
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

PROJECT_STATUS_VALUES = {
    "brief", "pre_production", "production", "post_production",
    "client_review", "revision", "delivery", "paid", "archived",
}
PROJECT_PAYMENT_STATUS_VALUES = {"unpaid", "partially_paid", "paid"}
JOSHX_INVOICE_STATUS_VALUES = {"draft", "sent", "partially_paid", "paid", "overdue"}


async def dashboard_snapshot(postgres_conn: Any = None) -> dict:
    """Backs GET /joshx/dashboard."""
    if postgres_conn is not None:
        return await _dashboard_snapshot_postgres(postgres_conn)
    return await _dashboard_snapshot_sqlite()


async def _dashboard_snapshot_sqlite() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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

    return _compute_dashboard_stats(clients, leads, projects, invoices, expenses)


async def _dashboard_snapshot_postgres(conn: Any) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, name, company, contact_name, email, phone, instagram, website, industry, "
            "client_type, lead_source, status, last_contact_date, next_follow_up_date, "
            "relationship_strength, notes, created_at "
            "FROM joshx.clients WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        client_cols = ["id", "name", "company", "contact_name", "email", "phone", "instagram", "website",
                       "industry", "client_type", "lead_source", "status", "last_contact_date",
                       "next_follow_up_date", "relationship_strength", "notes", "created_at"]
        clients = [_row_to_dict(client_cols, r) for r in await cur.fetchall()]

        await cur.execute(
            "SELECT id, client_name, project_description, service, estimated_value, budget, "
            "lead_source, stage, probability, follow_up_date, notes, created_at "
            "FROM joshx.leads WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        lead_cols = ["id", "client_name", "project_description", "service", "estimated_value", "budget",
                     "lead_source", "stage", "probability", "follow_up_date", "notes", "created_at"]
        leads = [_row_to_dict(lead_cols, r) for r in await cur.fetchall()]

        await cur.execute(
            "SELECT id, client_name, project_name, project_type, brief, start_date, due_date, "
            "shoot_date, budget, priority, status, payment_status, source_lead_id, deliverables, notes, "
            "created_at FROM joshx.projects WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        project_cols = ["id", "client_name", "project_name", "project_type", "brief", "start_date", "due_date",
                        "shoot_date", "budget", "priority", "status", "payment_status", "source_lead_id",
                        "deliverables", "notes", "created_at"]
        projects = [_row_to_dict(project_cols, r) for r in await cur.fetchall()]

        await cur.execute(
            "SELECT id, project_id, amount, amount_paid, status, issued_date, due_date, notes, created_at "
            "FROM joshx.invoices WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        invoice_cols = ["id", "project_id", "amount", "amount_paid", "status", "issued_date", "due_date",
                        "notes", "created_at"]
        invoices = [_row_to_dict(invoice_cols, r) for r in await cur.fetchall()]

        await cur.execute(
            "SELECT id, project_id, amount, description, incurred_date, notes, created_at "
            "FROM joshx.expenses WHERE deleted_at IS NULL ORDER BY id DESC"
        )
        expense_cols = ["id", "project_id", "amount", "description", "incurred_date", "notes", "created_at"]
        expenses = [_row_to_dict(expense_cols, r) for r in await cur.fetchall()]

    return _compute_dashboard_stats(clients, leads, projects, invoices, expenses)


def _row_to_dict(cols: list[str], row: tuple) -> dict:
    d = dict(zip(cols, row))
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = str(d["created_at"])
    return d


def _compute_dashboard_stats(clients: list[dict], leads: list[dict], projects: list[dict],
                              invoices: list[dict], expenses: list[dict]) -> dict:
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


async def compute_performance_metrics(postgres_conn: Any = None) -> dict:
    """Backs GET /joshx/analytics."""
    snapshot = await dashboard_snapshot(postgres_conn)
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


async def summarize(postgres_conn: Any = None) -> str:
    """Folded into Frank's own system prompt (joshx_tools.build_joshx_block())."""
    snapshot = await dashboard_snapshot(postgres_conn)
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

    metrics = await compute_performance_metrics(postgres_conn)
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
