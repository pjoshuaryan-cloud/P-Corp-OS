"""
Alpha Mode Media's business data — clients, projects, invoices,
deliverables. Confirmed decision (2026-07-31): this genuinely exists on
its own, not merged into P Corp OS's core data — a separate SQLite file
(alpha_mode.db, not pcorp.db), so it stays its own thing even though it
currently runs inside the same backend process for simplicity. No
dedicated management UI yet (that's a separate, later, much bigger build
if it ever happens) — for now, Frank is the only way data gets in, via
the tools in alpha_mode_tools.py, the same way save_memory works.

Kept deliberately small: one status field per entity (no enums enforced
at the DB level — Frank writes free-text statuses like "active,"
"unpaid," "done"), no invoice line items, no auth/multi-user concerns.
This is a brand-new, near-zero-record system — added complexity should
wait until real usage actually calls for it.
"""

from pathlib import Path

import aiosqlite

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
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
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
        await db.commit()


async def _find_or_create_client(db: aiosqlite.Connection, name: str) -> int:
    cursor = await db.execute("SELECT id FROM clients WHERE name = ? COLLATE NOCASE", (name,))
    row = await cursor.fetchone()
    if row:
        return row[0]
    cursor = await db.execute("INSERT INTO clients (name) VALUES (?)", (name,))
    return cursor.lastrowid


async def _find_project(db: aiosqlite.Connection, name: str) -> tuple[int, int] | None:
    """Returns (project_id, client_id), most recently created match."""
    cursor = await db.execute(
        "SELECT id, client_id FROM projects WHERE name = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
        (name,),
    )
    row = await cursor.fetchone()
    return (row[0], row[1]) if row else None


async def add_client(name: str, notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_or_create_client(db, name)
        if notes:
            await db.execute("UPDATE clients SET notes = ? WHERE id = ?", (notes, client_id))
        await db.commit()
        return name


async def add_project(client_name: str, project_name: str, status: str = "in progress", notes: str | None = None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_or_create_client(db, client_name)
        await db.execute(
            "INSERT INTO projects (client_id, name, status, notes) VALUES (?, ?, ?, ?)",
            (client_id, project_name, status, notes),
        )
        await db.commit()
        return project_name


async def add_invoice(
    client_name: str, amount: float, due_date: str | None = None, project_name: str | None = None, status: str = "unpaid"
) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        client_id = await _find_or_create_client(db, client_name)
        project_id = None
        if project_name:
            match = await _find_project(db, project_name)
            project_id = match[0] if match else None
        await db.execute(
            "INSERT INTO invoices (client_id, project_id, amount, due_date, status) VALUES (?, ?, ?, ?, ?)",
            (client_id, project_id, amount, due_date, status),
        )
        await db.commit()
        return f"${amount:,.2f} for {client_name}"


async def add_deliverable(project_name: str, description: str, due_date: str | None = None, status: str = "pending") -> str | None:
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


async def update_status(entity_type: str, identifier: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if entity_type == "client":
            cursor = await db.execute(
                "UPDATE clients SET status = ? WHERE name = ? COLLATE NOCASE", (new_status, identifier)
            )
        elif entity_type == "project":
            cursor = await db.execute(
                "UPDATE projects SET status = ? WHERE id = (SELECT id FROM projects WHERE name = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1)",
                (new_status, identifier),
            )
        elif entity_type == "deliverable":
            cursor = await db.execute(
                "UPDATE deliverables SET status = ? WHERE id = (SELECT id FROM deliverables WHERE description LIKE ? ORDER BY id DESC LIMIT 1)",
                (new_status, f"%{identifier}%"),
            )
        elif entity_type == "invoice":
            # Invoices have no natural name -- identifier is the client name,
            # matching their most recent non-paid invoice (the common real
            # case: "mark Acme's invoice as paid").
            cursor = await db.execute(
                """
                UPDATE invoices SET status = ? WHERE id = (
                    SELECT invoices.id FROM invoices
                    JOIN clients ON invoices.client_id = clients.id
                    WHERE clients.name = ? COLLATE NOCASE AND invoices.status != 'paid'
                    ORDER BY invoices.id DESC LIMIT 1
                )
                """,
                (new_status, identifier),
            )
        else:
            return False
        await db.commit()
        return cursor.rowcount > 0


async def summarize() -> str:
    """Current business snapshot for Frank's system prompt -- fine to load
    in full every turn at this scale (a brand-new system, near-zero
    records); revisit with real filtering/ranking if this ever grows large,
    same reasoning already applied to memory_records."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lines: list[str] = []

        cursor = await db.execute("SELECT name, status, notes FROM clients ORDER BY id")
        clients = await cursor.fetchall()
        if not clients:
            return ""
        lines.append("Clients:")
        for c in clients:
            suffix = f" — {c['notes']}" if c["notes"] else ""
            lines.append(f"  - {c['name']} ({c['status']}){suffix}")

        cursor = await db.execute(
            """
            SELECT projects.name, projects.status, projects.notes, clients.name AS client_name
            FROM projects JOIN clients ON projects.client_id = clients.id
            ORDER BY projects.id
            """
        )
        projects = await cursor.fetchall()
        if projects:
            lines.append("Projects:")
            for p in projects:
                suffix = f" — {p['notes']}" if p["notes"] else ""
                lines.append(f"  - {p['name']} for {p['client_name']} ({p['status']}){suffix}")

        cursor = await db.execute(
            """
            SELECT invoices.amount, invoices.status, invoices.due_date, clients.name AS client_name
            FROM invoices JOIN clients ON invoices.client_id = clients.id
            ORDER BY invoices.id
            """
        )
        invoices = await cursor.fetchall()
        if invoices:
            lines.append("Invoices:")
            for i in invoices:
                due = f", due {i['due_date']}" if i["due_date"] else ""
                lines.append(f"  - ${i['amount']:,.2f} for {i['client_name']} ({i['status']}{due})")

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

        return "\n".join(lines)
