"""
Alpha Mode Media's business data — clients, deliverables, crew,
equipment. Confirmed decision (2026-07-31): this genuinely exists on its
own, not merged into P Corp OS's core data — a separate SQLite file
(alpha_mode.db, not pcorp.db), so it stays its own thing even though it
currently runs inside the same backend process for simplicity. No
dedicated management UI yet (that's a separate, later, much bigger build
if it ever happens) — for now, Frank is the only way data gets in, via
the tools in alpha_mode_tools.py, the same way save_memory works.

Projects and invoices moved OUT of here 2026-08-02 -- they now live in
the real Alpha Mode Media Admin app's Supabase database (see
alpha_mode_supabase.py) so "add a project" / "client X has paid" show up
live in the app Joshua actually runs, instead of a local copy that
silently drifts out of sync. The `projects`/`invoices` tables below still
exist (old rows, if any, aren't migrated) but nothing writes to them
anymore.

Kept deliberately small: one status field per entity (no enums enforced
at the DB level — Frank writes free-text statuses like "active,"
"done"), no auth/multi-user concerns. This is a brand-new, near-zero-
record system — added complexity should wait until real usage actually
calls for it.

Dual-backend dispatchers (2026-09-11, iPhone independence pass): same
pattern as every other domain -- postgres_conn: Any = None, SQLite body
renamed _<name>_sqlite, Postgres sibling added.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from app.alpha_mode_supabase import summarize_block as supabase_summarize_block

DB_PATH = Path(__file__).parent.parent / "data" / "alpha_mode.db"


async def init_alpha_mode_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_contacted_date TEXT
            )
            """
        )
        # Migration path: clients existed before last_contacted_date did
        # (added 2026-08-01 for outreach-reminder insights).
        cursor = await db.execute("PRAGMA table_info(clients)")
        columns = {row[1] async for row in cursor}
        if "last_contacted_date" not in columns:
            await db.execute("ALTER TABLE clients ADD COLUMN last_contacted_date TEXT")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in progress',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                project_id INTEGER REFERENCES projects(id),
                amount REAL NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'unpaid',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS deliverables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                description TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Added 2026-08-02 -- crew and equipment were in the Alpha Mode
        # Agent's stated responsibilities from the start but had no real
        # tracking, only conversational awareness. Same minimal shape as
        # every other table here: one free-text status field, no rigid
        # enums. Deliberately NOT a booking/reservation system (which
        # shoot has which gear checked out, on which dates) -- that's
        # real added complexity with no evidence yet it's actually
        # needed; this is a registry (who/what exists, what state
        # they're in), not a scheduler.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS crew (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                role TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                contact TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT,
                status TEXT NOT NULL DEFAULT 'available',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def _find_or_create_client(db: aiosqlite.Connection, name: str) -> int:
    cursor = await db.execute("SELECT id FROM clients WHERE name = ? COLLATE NOCASE", (name,))
    row = await cursor.fetchone()
    if row:
        return row[0]
    cursor = await db.execute("INSERT INTO clients (name) VALUES (?)", (name,))
    return cursor.lastrowid


async def _find_or_create_client_postgres(conn: Any, name: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM alpha_mode.clients WHERE name ILIKE %s", (name,))
        row = await cur.fetchone()
        if row:
            return row[0]
        # status/created_at supplied explicitly -- same missing-DEFAULT gap
        # found repeatedly this migration.
        await cur.execute(
            "INSERT INTO alpha_mode.clients (name, status, created_at) "
            "VALUES (%s, 'active', (now() AT TIME ZONE 'utc')) RETURNING id",
            (name,),
        )
        (new_id,) = await cur.fetchone()
        return new_id


async def _find_project(db: aiosqlite.Connection, name: str) -> tuple[int, int] | None:
    """Returns (project_id, client_id), most recently created match."""
    cursor = await db.execute(
        "SELECT id, client_id FROM projects WHERE name = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
        (name,),
    )
    row = await cursor.fetchone()
    return (row[0], row[1]) if row else None


async def _find_project_postgres(conn: Any, name: str) -> tuple[int, int] | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, client_id FROM alpha_mode.projects WHERE name ILIKE %s ORDER BY id DESC LIMIT 1",
            (name,),
        )
        row = await cur.fetchone()
        return (row[0], row[1]) if row else None


async def add_client(name: str, notes: str | None = None, postgres_conn: Any = None) -> str:
    if postgres_conn is not None:
        client_id = await _find_or_create_client_postgres(postgres_conn, name)
        if notes:
            async with postgres_conn.cursor() as cur:
                await cur.execute("UPDATE alpha_mode.clients SET notes = %s WHERE id = %s", (notes, client_id))
        await postgres_conn.commit()
        return name
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_or_create_client(db, name)
        if notes:
            await db.execute("UPDATE clients SET notes = ? WHERE id = ?", (notes, client_id))
        await db.commit()
        return name


async def log_client_contact(client_name: str, contact_date: str | None = None, postgres_conn: Any = None) -> str:
    """Records when a client was last actually reached out to -- the data
    behind outreach-reminder insights (app/insights.py). Creates the
    client if they don't exist yet, same as add_project/add_invoice do,
    since Joshua might mention contacting someone before formally adding
    them as a client."""
    date_value = contact_date or date.today().isoformat()
    if postgres_conn is not None:
        client_id = await _find_or_create_client_postgres(postgres_conn, client_name)
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE alpha_mode.clients SET last_contacted_date = %s WHERE id = %s", (date_value, client_id)
            )
        await postgres_conn.commit()
        return client_name
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_or_create_client(db, client_name)
        await db.execute("UPDATE clients SET last_contacted_date = ? WHERE id = ?", (date_value, client_id))
        await db.commit()
        return client_name


async def add_deliverable(
    project_name: str, description: str, due_date: str | None = None, status: str = "pending",
    postgres_conn: Any = None,
) -> str | None:
    if postgres_conn is not None:
        match = await _find_project_postgres(postgres_conn, project_name)
        if not match:
            return None
        project_id, _ = match
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO alpha_mode.deliverables (project_id, description, due_date, status, created_at) "
                "VALUES (%s, %s, %s, %s, (now() AT TIME ZONE 'utc'))",
                (project_id, description, due_date, status),
            )
        await postgres_conn.commit()
        return description
    async with aiosqlite.connect(DB_PATH) as db:
        match = await _find_project(db, project_name)
        if not match:
            return None
        project_id, _ = match
        await db.execute(
            "INSERT INTO deliverables (project_id, description, due_date, status) VALUES (?, ?, ?, ?)",
            (project_id, description, due_date, status),
        )
        await db.commit()
        return description


async def add_crew_member(
    name: str, role: str | None = None, contact: str | None = None, notes: str | None = None,
    postgres_conn: Any = None,
) -> str:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT id FROM alpha_mode.crew WHERE name ILIKE %s", (name,))
            row = await cur.fetchone()
            if row:
                await cur.execute(
                    "UPDATE alpha_mode.crew SET role = COALESCE(%s, role), contact = COALESCE(%s, contact), "
                    "notes = COALESCE(%s, notes) WHERE id = %s",
                    (role, contact, notes, row[0]),
                )
            else:
                await cur.execute(
                    "INSERT INTO alpha_mode.crew (name, role, status, contact, notes, created_at) "
                    "VALUES (%s, %s, 'active', %s, %s, (now() AT TIME ZONE 'utc'))",
                    (name, role, contact, notes),
                )
        await postgres_conn.commit()
        return name
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM crew WHERE name = ? COLLATE NOCASE", (name,))
        row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE crew SET role = COALESCE(?, role), contact = COALESCE(?, contact), notes = COALESCE(?, notes) WHERE id = ?",
                (role, contact, notes, row[0]),
            )
        else:
            await db.execute(
                "INSERT INTO crew (name, role, contact, notes) VALUES (?, ?, ?, ?)", (name, role, contact, notes)
            )
        await db.commit()
        return name


async def add_equipment(
    name: str, category: str | None = None, notes: str | None = None, postgres_conn: Any = None
) -> str:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT id FROM alpha_mode.equipment WHERE name ILIKE %s", (name,))
            row = await cur.fetchone()
            if row:
                await cur.execute(
                    "UPDATE alpha_mode.equipment SET category = COALESCE(%s, category), notes = COALESCE(%s, notes) "
                    "WHERE id = %s",
                    (category, notes, row[0]),
                )
            else:
                await cur.execute(
                    "INSERT INTO alpha_mode.equipment (name, category, status, notes, created_at) "
                    "VALUES (%s, %s, 'available', %s, (now() AT TIME ZONE 'utc'))",
                    (name, category, notes),
                )
        await postgres_conn.commit()
        return name
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM equipment WHERE name = ? COLLATE NOCASE", (name,))
        row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE equipment SET category = COALESCE(?, category), notes = COALESCE(?, notes) WHERE id = ?",
                (category, notes, row[0]),
            )
        else:
            await db.execute("INSERT INTO equipment (name, category, notes) VALUES (?, ?, ?)", (name, category, notes))
        await db.commit()
        return name


async def update_status(entity_type: str, identifier: str, new_status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            if entity_type == "client":
                await cur.execute(
                    "UPDATE alpha_mode.clients SET status = %s WHERE name ILIKE %s", (new_status, identifier)
                )
            elif entity_type == "deliverable":
                # ILIKE, not LIKE -- same case-sensitivity fix proven
                # necessary throughout this migration.
                await cur.execute(
                    "UPDATE alpha_mode.deliverables SET status = %s WHERE id = "
                    "(SELECT id FROM alpha_mode.deliverables WHERE description ILIKE %s ORDER BY id DESC LIMIT 1)",
                    (new_status, f"%{identifier}%"),
                )
            elif entity_type == "crew":
                await cur.execute(
                    "UPDATE alpha_mode.crew SET status = %s WHERE name ILIKE %s", (new_status, identifier)
                )
            elif entity_type == "equipment":
                await cur.execute(
                    "UPDATE alpha_mode.equipment SET status = %s WHERE name ILIKE %s", (new_status, identifier)
                )
            else:
                return False
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        if entity_type == "client":
            cursor = await db.execute(
                "UPDATE clients SET status = ? WHERE name = ? COLLATE NOCASE", (new_status, identifier)
            )
        elif entity_type == "deliverable":
            cursor = await db.execute(
                "UPDATE deliverables SET status = ? WHERE id = (SELECT id FROM deliverables WHERE description LIKE ? ORDER BY id DESC LIMIT 1)",
                (new_status, f"%{identifier}%"),
            )
        elif entity_type == "crew":
            cursor = await db.execute(
                "UPDATE crew SET status = ? WHERE name = ? COLLATE NOCASE", (new_status, identifier)
            )
        elif entity_type == "equipment":
            cursor = await db.execute(
                "UPDATE equipment SET status = ? WHERE name = ? COLLATE NOCASE", (new_status, identifier)
            )
        else:
            return False
        await db.commit()
        return cursor.rowcount > 0


async def clients_needing_outreach(stale_after_days: int, postgres_conn: Any = None) -> list[dict]:
    """Active clients never contacted, or not contacted within
    `stale_after_days` -- the data behind outreach-reminder insights.
    NULL last_contacted_date counts as needing outreach: a client with no
    logged contact at all is exactly the case worth flagging, not
    silently skipping."""
    cutoff = (date.today() - timedelta(days=stale_after_days)).isoformat()
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                """
                SELECT name, last_contacted_date FROM alpha_mode.clients
                WHERE status = 'active' AND (last_contacted_date IS NULL OR last_contacted_date < %s)
                ORDER BY last_contacted_date IS NOT NULL, last_contacted_date
                """,
                (cutoff,),
            )
            rows = await cur.fetchall()
            return [{"name": r[0], "last_contacted_date": r[1]} for r in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT name, last_contacted_date FROM clients
            WHERE status = 'active' AND (last_contacted_date IS NULL OR last_contacted_date < ?)
            ORDER BY last_contacted_date IS NOT NULL, last_contacted_date
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [{"name": row["name"], "last_contacted_date": row["last_contacted_date"]} for row in rows]


async def summarize(postgres_conn: Any = None) -> str:
    """Current business snapshot for Frank's system prompt -- fine to load
    in full every turn at this scale (a brand-new system, near-zero
    records); revisit with real filtering/ranking if this ever grows large,
    same reasoning already applied to memory_records."""
    if postgres_conn is not None:
        return await _summarize_postgres(postgres_conn)
    return await _summarize_sqlite()


async def _summarize_sqlite() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lines: list[str] = []

        cursor = await db.execute("SELECT name, status, notes FROM clients ORDER BY id")
        clients = await cursor.fetchall()
        if clients:
            lines.append("Clients:")
            for c in clients:
                suffix = f" — {c['notes']}" if c["notes"] else ""
                lines.append(f"  - {c['name']} ({c['status']}){suffix}")

        supabase_snapshot = await supabase_summarize_block()
        if supabase_snapshot:
            lines.append(supabase_snapshot)

        cursor = await db.execute(
            """
            SELECT deliverables.description, deliverables.status, deliverables.due_date, projects.name AS project_name
            FROM deliverables JOIN projects ON deliverables.project_id = projects.id
            ORDER BY deliverables.id
            """
        )
        deliverables = await cursor.fetchall()
        if deliverables:
            lines.append("Deliverables:")
            for d in deliverables:
                due = f", due {d['due_date']}" if d["due_date"] else ""
                lines.append(f"  - {d['description']} for {d['project_name']} ({d['status']}{due})")

        cursor = await db.execute("SELECT name, role, status, contact, notes FROM crew ORDER BY id")
        crew = await cursor.fetchall()
        if crew:
            lines.append("Crew:")
            for c in crew:
                role = f" — {c['role']}" if c["role"] else ""
                contact = f", {c['contact']}" if c["contact"] else ""
                notes = f" — {c['notes']}" if c["notes"] else ""
                lines.append(f"  - {c['name']}{role} ({c['status']}{contact}){notes}")

        cursor = await db.execute("SELECT name, category, status, notes FROM equipment ORDER BY id")
        equipment = await cursor.fetchall()
        if equipment:
            lines.append("Equipment:")
            for e in equipment:
                category = f" — {e['category']}" if e["category"] else ""
                notes = f" — {e['notes']}" if e["notes"] else ""
                lines.append(f"  - {e['name']}{category} ({e['status']}){notes}")

        return "\n".join(lines)


async def _summarize_postgres(conn: Any) -> str:
    lines: list[str] = []
    async with conn.cursor() as cur:
        await cur.execute("SELECT name, status, notes FROM alpha_mode.clients ORDER BY id")
        clients = await cur.fetchall()
        if clients:
            lines.append("Clients:")
            for name, status, notes in clients:
                suffix = f" — {notes}" if notes else ""
                lines.append(f"  - {name} ({status}){suffix}")

        supabase_snapshot = await supabase_summarize_block()
        if supabase_snapshot:
            lines.append(supabase_snapshot)

        await cur.execute(
            """
            SELECT deliverables.description, deliverables.status, deliverables.due_date, projects.name
            FROM alpha_mode.deliverables
            JOIN alpha_mode.projects ON deliverables.project_id = projects.id
            ORDER BY deliverables.id
            """
        )
        deliverables = await cur.fetchall()
        if deliverables:
            lines.append("Deliverables:")
            for description, status, due_date, project_name in deliverables:
                due = f", due {due_date}" if due_date else ""
                lines.append(f"  - {description} for {project_name} ({status}{due})")

        await cur.execute("SELECT name, role, status, contact, notes FROM alpha_mode.crew ORDER BY id")
        crew = await cur.fetchall()
        if crew:
            lines.append("Crew:")
            for name, role, status, contact, notes in crew:
                role_s = f" — {role}" if role else ""
                contact_s = f", {contact}" if contact else ""
                notes_s = f" — {notes}" if notes else ""
                lines.append(f"  - {name}{role_s} ({status}{contact_s}){notes_s}")

        await cur.execute("SELECT name, category, status, notes FROM alpha_mode.equipment ORDER BY id")
        equipment = await cur.fetchall()
        if equipment:
            lines.append("Equipment:")
            for name, category, status, notes in equipment:
                category_s = f" — {category}" if category else ""
                notes_s = f" — {notes}" if notes else ""
                lines.append(f"  - {name}{category_s} ({status}){notes_s}")

    return "\n".join(lines)
