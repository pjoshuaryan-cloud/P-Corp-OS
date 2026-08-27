"""
People/Relationships -- a real personal-relationship tracker, deliberately
separate from Joshx clients (joshx_db.py) and Alpha Mode Media clients
(alpha_mode_supabase.py), 2026-08-27. A business record stays the source
of truth for business data (project status, invoices, deals); this table
is the source of truth for the actual human relationship underneath it --
`linked_client_name` is a plain-text cross-reference, never a real
foreign key across databases, so the two domains' data never merges.

Own SQLite file (people.db), same "genuinely separate domain" reasoning
already established for joshx.db/alpha_mode.db/personal.db. Like every
file under backend/data/, this is gitignored.

No `deleted_at`/delete tool -- not asked for when this was scoped, and
adding an unrequested delete capability here would be scope creep beyond
what was actually specced. The column can be added later without a
migration if a real need for it shows up (same "don't build ahead of
real usage" discipline already applied elsewhere in this codebase).
"""

from datetime import date
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "people.db"


async def init_people_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                relationship_type TEXT,
                company TEXT,
                email TEXT,
                phone TEXT,
                linked_client_name TEXT,
                last_contact_date TEXT,
                next_follow_up_date TEXT,
                follow_up_cadence_days INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL REFERENCES people(id),
                date TEXT NOT NULL,
                channel TEXT,
                summary TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def _find_person_id(db: aiosqlite.Connection, identifier: str) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (identifier,)
    )
    row = await cursor.fetchone()
    if row:
        return row[0]
    cursor = await db.execute(
        "SELECT id FROM people WHERE name LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
        (f"%{identifier}%",),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def add_person(name: str, **fields) -> str:
    """Upsert, not a bare INSERT -- keyed on name (case-insensitive),
    built this way from the start. `joshx_db.py`'s add_project/add_lead
    were both found live-duplicating rows today from being plain INSERTs
    called twice for the same entity; no reason to reintroduce that exact
    bug in a brand-new domain when the fix is already known."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (name,)
        )
        existing = await cursor.fetchone()
        if existing is None:
            columns = ["name", *fields.keys()]
            placeholders = ", ".join("?" for _ in columns)
            await db.execute(
                f"INSERT INTO people ({', '.join(columns)}) VALUES ({placeholders})",
                (name, *fields.values()),
            )
        else:
            person_id = existing[0]
            non_null_fields = {k: v for k, v in fields.items() if v is not None}
            if non_null_fields:
                set_clause = ", ".join(f"{col} = ?" for col in non_null_fields)
                await db.execute(
                    f"UPDATE people SET {set_clause} WHERE id = ?",
                    (*non_null_fields.values(), person_id),
                )
        await db.commit()
    return name


async def log_interaction(
    person_identifier: str, interaction_date: str, channel: str | None = None, summary: str | None = None
) -> bool:
    """Logs one real contact event, and bumps people.last_contact_date to
    match if this interaction is more recent than what's currently
    stored -- doing both here means logging a real contact event never
    needs two separate tool calls to be reflected correctly."""
    async with aiosqlite.connect(DB_PATH) as db:
        person_id = await _find_person_id(db, person_identifier)
        if person_id is None:
            return False
        await db.execute(
            "INSERT INTO interactions (person_id, date, channel, summary) VALUES (?, ?, ?, ?)",
            (person_id, interaction_date, channel, summary),
        )
        await db.execute(
            "UPDATE people SET last_contact_date = ? "
            "WHERE id = ? AND (last_contact_date IS NULL OR last_contact_date < ?)",
            (interaction_date, person_id, interaction_date),
        )
        await db.commit()
        return True


async def update_follow_up_cadence(person_identifier: str, cadence_days: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        person_id = await _find_person_id(db, person_identifier)
        if person_id is None:
            return False
        await db.execute(
            "UPDATE people SET follow_up_cadence_days = ? WHERE id = ?", (cadence_days, person_id)
        )
        await db.commit()
        return True


async def get_overdue_follow_ups(as_of: str | None = None) -> list[dict]:
    """A person is overdue if: an explicit next_follow_up_date is set and
    has passed, OR (no explicit date, but a follow_up_cadence_days is set
    and last_contact_date + cadence_days has passed -- including someone
    with a cadence set who's never been contacted at all, treated as
    immediately overdue). Someone with neither field set is never
    flagged -- no cadence means no follow-up expectation was ever set.

    Backs both the get_overdue_follow_ups Frank tool and the Triggers
    Layer's relationship_follow_up_overdue checker (triggers.py) -- one
    real query, not two parallel ones that could drift apart."""
    today = as_of or date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, name, relationship_type, last_contact_date, next_follow_up_date, follow_up_cadence_days
            FROM people
            WHERE
                (next_follow_up_date IS NOT NULL AND next_follow_up_date < ?)
                OR (
                    next_follow_up_date IS NULL
                    AND follow_up_cadence_days IS NOT NULL
                    AND (
                        last_contact_date IS NULL
                        OR date(last_contact_date, '+' || follow_up_cadence_days || ' days') < ?
                    )
                )
            ORDER BY id
            """,
            (today, today),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def dashboard_snapshot() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, relationship_type, company, email, phone, linked_client_name, "
            "last_contact_date, next_follow_up_date, follow_up_cadence_days, notes, created_at "
            "FROM people ORDER BY id DESC"
        )
        people = [dict(r) for r in await cursor.fetchall()]
    return {"people": people}


async def summarize() -> str:
    """Folded into Frank's own system prompt (people_tools.build_people_block())
    -- same mechanism as build_joshx_block()/build_personal_block(), no
    consult_people_agent -- same "keep it Frank's own voice, no persona
    drifting into unsolicited relationship advice" call already made for
    Personal and Joshx."""
    snapshot = await dashboard_snapshot()
    if not snapshot["people"]:
        return ""
    lines = [f"People/Relationships tracked ({len(snapshot['people'])}):"]
    for p in snapshot["people"]:
        detail = p["relationship_type"] or "contact"
        if p["company"]:
            detail += f", {p['company']}"
        lines.append(f"  - {p['name']} ({detail}) — last contact {p['last_contact_date'] or 'never'}")
    return "\n".join(lines)
