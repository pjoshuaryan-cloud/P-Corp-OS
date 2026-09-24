"""
VENTURES (2026-09-23, Phase 1) -- a structured business-opportunity-
discovery/pipeline system, genuinely separate domain from Joshx
(Josh's existing freelance-creative client/project/invoice tracking)
and from Alpha Mode Media. Own SQLite file (ventures.db) and own
Postgres schema (ventures), same "genuinely separate domain" reasoning
as every other *_db.py module in this app.

Deliberately uses trade_proposals_db.py's inline-DDL-with-real-CHECK-
constraints pattern, NOT Joshx's own "loose free-text status, no DB
enforcement" convention (confirmed via direct research: joshx_db.py's
own docstring states this choice explicitly). The difference: Joshx's
status fields are Frank's own free-text notes-to-self, while a
venture's pipeline `status` and an opportunity's rating fields are
meant to be real, enforced vocabularies a UI Picker presents -- letting
Frank (or any other caller) write an arbitrary string into a pipeline
stage would silently break the dashboard's own stage grouping. As
established for trade_proposals_db.py: the Stage 3/4 migration tool
(app/migration/replicate.py) never carries CHECK constraints over, so
the Postgres side is created by real inline DDL here too, not that
pipeline.

Like every file under backend/data/, gitignored -- nothing written
here ever reaches GitHub.
"""

from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "ventures.db"

VENTURE_STATUSES = ("idea", "research", "validation", "build", "launch", "growth", "mature", "paused", "closed")
LEVELS = ("low", "medium", "high")
CONFIDENCE_LEVELS = ("high", "medium", "low")
SCORE_LABELS = ("healthy", "watch", "experimental")
OPPORTUNITY_STATUSES = ("new", "dismissed", "promoted")
CHECKLIST_ITEM_STATUSES = ("pending", "done", "skipped")
CHECKLIST_ITEM_SOURCES = ("manual", "builder")
CUSTOMER_STATUSES = ("active", "churned")
REVENUE_EVENT_TYPES = ("charge", "refund")
FULFILLMENT_ITEM_STATUSES = ("pending", "done", "skipped")
MARKETING_CONTENT_TYPES = ("social_post", "launch_announcement", "ad_copy")
AUTOMATION_SUGGESTION_STATUSES = ("new", "dismissed", "implemented")

_VENTURE_COLUMNS = (
    "id", "name", "description", "status", "type", "revenue_model", "owner_time", "automation_level",
    "setup_cost", "monthly_revenue", "risk_level", "confidence", "score_label", "notes", "created_at",
    "concept_summary", "positioning_copy", "operations_sop",
)
_OPPORTUNITY_COLUMNS = (
    "id", "name", "description", "revenue_model", "setup_cost", "automation_potential", "owner_time_required",
    "confidence", "risks", "recommended_next_step", "source", "status", "promoted_venture_id", "created_at",
)
_VALIDATION_REPORT_COLUMNS = (
    "id", "venture_id", "evidence", "assumptions", "unknowns", "risks", "verdict", "confidence", "created_at",
)
_CHECKLIST_ITEM_COLUMNS = (
    "id", "venture_id", "title", "status", "position", "source", "created_at",
)
_CUSTOMER_COLUMNS = (
    "id", "venture_id", "name", "status", "acquisition_source", "acquisition_cost",
    "acquired_at", "churned_at", "created_at",
)
_REVENUE_EVENT_COLUMNS = (
    "id", "customer_id", "amount", "event_type", "occurred_at", "notes", "created_at",
)
_FULFILLMENT_ITEM_COLUMNS = (
    "id", "customer_id", "title", "status", "position", "created_at",
)
_MARKETING_CONTENT_COLUMNS = (
    "id", "venture_id", "content_type", "content", "created_at",
)
_AUTOMATION_SUGGESTION_COLUMNS = (
    "id", "venture_id", "title", "description", "suggested_approach", "status", "created_at",
)


async def init_ventures_db(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        await _init_postgres(postgres_conn)
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN {VENTURE_STATUSES}),
                type TEXT,
                revenue_model TEXT,
                owner_time TEXT CHECK (owner_time IN {LEVELS}),
                automation_level TEXT CHECK (automation_level IN {LEVELS}),
                setup_cost REAL,
                monthly_revenue REAL NOT NULL DEFAULT 0,
                risk_level TEXT CHECK (risk_level IN {LEVELS}),
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                score_label TEXT CHECK (score_label IN {SCORE_LABELS}),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT,
                concept_summary TEXT,
                positioning_copy TEXT,
                operations_sop TEXT
            )
            """
        )
        cursor = await db.execute("PRAGMA table_info(ventures)")
        venture_columns = {row[1] async for row in cursor}
        if "concept_summary" not in venture_columns:
            await db.execute("ALTER TABLE ventures ADD COLUMN concept_summary TEXT")
        if "positioning_copy" not in venture_columns:
            await db.execute("ALTER TABLE ventures ADD COLUMN positioning_copy TEXT")
        if "operations_sop" not in venture_columns:
            await db.execute("ALTER TABLE ventures ADD COLUMN operations_sop TEXT")
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                revenue_model TEXT,
                setup_cost REAL,
                automation_potential TEXT CHECK (automation_potential IN {LEVELS}),
                owner_time_required TEXT CHECK (owner_time_required IN {LEVELS}),
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                risks TEXT,
                recommended_next_step TEXT,
                source TEXT NOT NULL DEFAULT 'radar',
                status TEXT NOT NULL DEFAULT 'new' CHECK (status IN {OPPORTUNITY_STATUSES}),
                promoted_venture_id INTEGER REFERENCES ventures(id),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_validation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venture_id INTEGER NOT NULL REFERENCES ventures(id),
                evidence TEXT,
                assumptions TEXT,
                unknowns TEXT,
                risks TEXT,
                verdict TEXT,
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venture_id INTEGER NOT NULL REFERENCES ventures(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {CHECKLIST_ITEM_STATUSES}),
                position INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN {CHECKLIST_ITEM_SOURCES}),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venture_id INTEGER NOT NULL REFERENCES ventures(id),
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN {CUSTOMER_STATUSES}),
                acquisition_source TEXT,
                acquisition_cost REAL,
                acquired_at TEXT NOT NULL DEFAULT (datetime('now')),
                churned_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_revenue_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES venture_customers(id),
                amount REAL NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN {REVENUE_EVENT_TYPES}),
                occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS customer_fulfillment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES venture_customers(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {FULFILLMENT_ITEM_STATUSES}),
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_marketing_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venture_id INTEGER NOT NULL REFERENCES ventures(id),
                content_type TEXT NOT NULL CHECK (content_type IN {MARKETING_CONTENT_TYPES}),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS venture_automation_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venture_id INTEGER NOT NULL REFERENCES ventures(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                suggested_approach TEXT,
                status TEXT NOT NULL DEFAULT 'new' CHECK (status IN {AUTOMATION_SUGGESTION_STATUSES}),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.commit()


async def _init_postgres(conn: Any) -> None:
    async with conn.cursor() as cur:
        await cur.execute("CREATE SCHEMA IF NOT EXISTS ventures")
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.ventures (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN {VENTURE_STATUSES}),
                type TEXT,
                revenue_model TEXT,
                owner_time TEXT CHECK (owner_time IN {LEVELS}),
                automation_level TEXT CHECK (automation_level IN {LEVELS}),
                setup_cost DOUBLE PRECISION,
                monthly_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
                risk_level TEXT CHECK (risk_level IN {LEVELS}),
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                score_label TEXT CHECK (score_label IN {SCORE_LABELS}),
                notes TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                concept_summary TEXT,
                positioning_copy TEXT,
                operations_sop TEXT
            )
            """
        )
        await cur.execute("ALTER TABLE ventures.ventures ADD COLUMN IF NOT EXISTS concept_summary TEXT")
        await cur.execute("ALTER TABLE ventures.ventures ADD COLUMN IF NOT EXISTS positioning_copy TEXT")
        await cur.execute("ALTER TABLE ventures.ventures ADD COLUMN IF NOT EXISTS operations_sop TEXT")
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.opportunities (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                revenue_model TEXT,
                setup_cost DOUBLE PRECISION,
                automation_potential TEXT CHECK (automation_potential IN {LEVELS}),
                owner_time_required TEXT CHECK (owner_time_required IN {LEVELS}),
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                risks TEXT,
                recommended_next_step TEXT,
                source TEXT NOT NULL DEFAULT 'radar',
                status TEXT NOT NULL DEFAULT 'new' CHECK (status IN {OPPORTUNITY_STATUSES}),
                promoted_venture_id BIGINT REFERENCES ventures.ventures(id),
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.validation_reports (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                venture_id BIGINT NOT NULL REFERENCES ventures.ventures(id),
                evidence TEXT,
                assumptions TEXT,
                unknowns TEXT,
                risks TEXT,
                verdict TEXT,
                confidence TEXT CHECK (confidence IN {CONFIDENCE_LEVELS}),
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.checklist_items (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                venture_id BIGINT NOT NULL REFERENCES ventures.ventures(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {CHECKLIST_ITEM_STATUSES}),
                position INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN {CHECKLIST_ITEM_SOURCES}),
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.customers (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                venture_id BIGINT NOT NULL REFERENCES ventures.ventures(id),
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN {CUSTOMER_STATUSES}),
                acquisition_source TEXT,
                acquisition_cost DOUBLE PRECISION,
                acquired_at TEXT NOT NULL,
                churned_at TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.revenue_events (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                customer_id BIGINT NOT NULL REFERENCES ventures.customers(id),
                amount DOUBLE PRECISION NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN {REVENUE_EVENT_TYPES}),
                occurred_at TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.fulfillment_items (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                customer_id BIGINT NOT NULL REFERENCES ventures.customers(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {FULFILLMENT_ITEM_STATUSES}),
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.marketing_content (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                venture_id BIGINT NOT NULL REFERENCES ventures.ventures(id),
                content_type TEXT NOT NULL CHECK (content_type IN {MARKETING_CONTENT_TYPES}),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ventures.automation_suggestions (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                venture_id BIGINT NOT NULL REFERENCES ventures.ventures(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                suggested_approach TEXT,
                status TEXT NOT NULL DEFAULT 'new' CHECK (status IN {AUTOMATION_SUGGESTION_STATUSES}),
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
    await conn.commit()


# ---------------------------------------------------------------- ventures

async def create_venture(
    name: str,
    description: str | None = None,
    status: str = "idea",
    type_: str | None = None,
    revenue_model: str | None = None,
    owner_time: str | None = None,
    automation_level: str | None = None,
    setup_cost: float | None = None,
    monthly_revenue: float = 0,
    risk_level: str | None = None,
    confidence: str | None = None,
    score_label: str | None = None,
    notes: str | None = None,
    postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.ventures "
                "(name, description, status, type, revenue_model, owner_time, automation_level, setup_cost, "
                "monthly_revenue, risk_level, confidence, score_label, notes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc')) "
                "RETURNING id",
                (name, description, status, type_, revenue_model, owner_time, automation_level, setup_cost,
                 monthly_revenue, risk_level, confidence, score_label, notes),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO ventures "
            "(name, description, status, type, revenue_model, owner_time, automation_level, setup_cost, "
            "monthly_revenue, risk_level, confidence, score_label, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, status, type_, revenue_model, owner_time, automation_level, setup_cost,
             monthly_revenue, risk_level, confidence, score_label, notes),
        )
        await db.commit()
        return cursor.lastrowid


async def list_ventures(postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_VENTURE_COLUMNS)} FROM ventures.ventures "
                "WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
            return [dict(zip(_VENTURE_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_VENTURE_COLUMNS)} FROM ventures WHERE deleted_at IS NULL ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_venture(venture_id: int, postgres_conn: Any = None) -> dict | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_VENTURE_COLUMNS)} FROM ventures.ventures WHERE id = %s AND deleted_at IS NULL",
                (venture_id,),
            )
            row = await cur.fetchone()
            return dict(zip(_VENTURE_COLUMNS, row)) if row else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_VENTURE_COLUMNS)} FROM ventures WHERE id = ? AND deleted_at IS NULL", (venture_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_venture_concept(
    venture_id: int, concept_summary: str, positioning_copy: str, postgres_conn: Any = None
) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.ventures SET concept_summary = %s, positioning_copy = %s "
                "WHERE id = %s AND deleted_at IS NULL",
                (concept_summary, positioning_copy, venture_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE ventures SET concept_summary = ?, positioning_copy = ? WHERE id = ? AND deleted_at IS NULL",
            (concept_summary, positioning_copy, venture_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_venture_status(venture_id: int, status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.ventures SET status = %s WHERE id = %s AND deleted_at IS NULL",
                (status, venture_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE ventures SET status = ? WHERE id = ? AND deleted_at IS NULL", (status, venture_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_venture(venture_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.ventures SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (venture_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE ventures SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (venture_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# ------------------------------------------------------------ opportunities

async def create_opportunity(
    name: str,
    description: str,
    revenue_model: str | None = None,
    setup_cost: float | None = None,
    automation_potential: str | None = None,
    owner_time_required: str | None = None,
    confidence: str | None = None,
    risks: str | None = None,
    recommended_next_step: str | None = None,
    source: str = "radar",
    postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.opportunities "
                "(name, description, revenue_model, setup_cost, automation_potential, owner_time_required, "
                "confidence, risks, recommended_next_step, source, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new', (now() AT TIME ZONE 'utc')) "
                "RETURNING id",
                (name, description, revenue_model, setup_cost, automation_potential, owner_time_required,
                 confidence, risks, recommended_next_step, source),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO opportunities "
            "(name, description, revenue_model, setup_cost, automation_potential, owner_time_required, "
            "confidence, risks, recommended_next_step, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, revenue_model, setup_cost, automation_potential, owner_time_required,
             confidence, risks, recommended_next_step, source),
        )
        await db.commit()
        return cursor.lastrowid


async def list_opportunities(status: str | None = None, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            if status is not None:
                await cur.execute(
                    f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM ventures.opportunities "
                    "WHERE deleted_at IS NULL AND status = %s ORDER BY created_at DESC",
                    (status,),
                )
            else:
                await cur.execute(
                    f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM ventures.opportunities "
                    "WHERE deleted_at IS NULL ORDER BY created_at DESC"
                )
            rows = await cur.fetchall()
            return [dict(zip(_OPPORTUNITY_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status is not None:
            cursor = await db.execute(
                f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM opportunities "
                "WHERE deleted_at IS NULL AND status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM opportunities "
                "WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        return [dict(r) for r in await cursor.fetchall()]


async def get_opportunity(opportunity_id: int, postgres_conn: Any = None) -> dict | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM ventures.opportunities "
                "WHERE id = %s AND deleted_at IS NULL",
                (opportunity_id,),
            )
            row = await cur.fetchone()
            return dict(zip(_OPPORTUNITY_COLUMNS, row)) if row else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_OPPORTUNITY_COLUMNS)} FROM opportunities WHERE id = ? AND deleted_at IS NULL",
            (opportunity_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def dismiss_opportunity(opportunity_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.opportunities SET status = 'dismissed' WHERE id = %s AND status = 'new'",
                (opportunity_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE opportunities SET status = 'dismissed' WHERE id = ? AND status = 'new'", (opportunity_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def promote_opportunity(opportunity_id: int, venture_id: int, postgres_conn: Any = None) -> bool:
    """Only ever fires from status='new', so an already-promoted/dismissed
    opportunity can't be double-promoted by a stale UI state."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.opportunities SET status = 'promoted', promoted_venture_id = %s "
                "WHERE id = %s AND status = 'new'",
                (venture_id, opportunity_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE opportunities SET status = 'promoted', promoted_venture_id = ? WHERE id = ? AND status = 'new'",
            (venture_id, opportunity_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def dashboard_snapshot(postgres_conn: Any = None) -> dict:
    """Deterministic aggregation over already-fetched rows, same
    discipline as trade_intelligence_db.py's compute_breakdown_stats --
    one source of truth in plain Python, not a second SQL GROUP BY
    dialect to keep in sync. monthly_revenue here is Josh's own entered
    figure, not real bookkeeping -- labeled as such in the UI, never
    blended into a single fabricated total across ventures with
    potentially different real-world contexts (same honesty discipline
    finance_db.py already applies to cross-currency balances)."""
    ventures = await list_ventures(postgres_conn)
    by_status: dict[str, int] = {status: 0 for status in VENTURE_STATUSES}
    for v in ventures:
        by_status[v["status"]] = by_status.get(v["status"], 0) + 1
    active_statuses = {"build", "launch", "growth", "mature"}
    # Real revenue, summed across ventures -- safe here (unlike
    # finance_db.py's cross-currency balances) because every venture's
    # revenue is denominated in the same real currency (ZAR).
    total_revenue_last_30d = 0.0
    for v in ventures:
        if v["status"] == "closed":
            continue
        metrics = await compute_customer_metrics(v["id"], postgres_conn)
        total_revenue_last_30d += metrics["revenue_last_30d"]
    return {
        "total_ventures": len(ventures),
        "active_ventures": sum(c for s, c in by_status.items() if s in active_statuses),
        "testing_ventures": by_status.get("validation", 0),
        "paused_ventures": by_status.get("paused", 0),
        "closed_ventures": by_status.get("closed", 0),
        "total_monthly_revenue": sum(v["monthly_revenue"] for v in ventures if v["status"] not in ("closed",)),
        "total_revenue_last_30d": total_revenue_last_30d,
        "by_status": by_status,
    }


# --------------------------------------------------------- validation reports

async def create_validation_report(
    venture_id: int,
    evidence: str,
    assumptions: str,
    unknowns: str,
    risks: str,
    verdict: str,
    confidence: str,
    postgres_conn: Any = None,
) -> int:
    """Every run inserts a new row -- history is kept, never overwritten,
    so Josh can look back at an earlier report without paying for a
    re-run of the (slow, real) Claude call."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.validation_reports "
                "(venture_id, evidence, assumptions, unknowns, risks, verdict, confidence, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (venture_id, evidence, assumptions, unknowns, risks, verdict, confidence),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO venture_validation_reports "
            "(venture_id, evidence, assumptions, unknowns, risks, verdict, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (venture_id, evidence, assumptions, unknowns, risks, verdict, confidence),
        )
        await db.commit()
        return cursor.lastrowid


async def list_validation_reports(venture_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_VALIDATION_REPORT_COLUMNS)} FROM ventures.validation_reports "
                "WHERE venture_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                (venture_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_VALIDATION_REPORT_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_VALIDATION_REPORT_COLUMNS)} FROM venture_validation_reports "
            "WHERE venture_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (venture_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ------------------------------------------------------------ checklist items

async def create_checklist_item(
    venture_id: int, title: str, source: str = "manual", postgres_conn: Any = None
) -> int:
    """New items are appended to the end of the ordered list -- position
    is simply the current item count for this venture, matching the
    simple "append, never renumber" approach; reordering isn't a Phase 2
    requirement."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM ventures.checklist_items WHERE venture_id = %s AND deleted_at IS NULL",
                (venture_id,),
            )
            (position,) = await cur.fetchone()
            await cur.execute(
                "INSERT INTO ventures.checklist_items (venture_id, title, status, position, source, created_at) "
                "VALUES (%s, %s, 'pending', %s, %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (venture_id, title, position, source),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM venture_checklist_items WHERE venture_id = ? AND deleted_at IS NULL",
            (venture_id,),
        )
        (position,) = await cursor.fetchone()
        cursor = await db.execute(
            "INSERT INTO venture_checklist_items (venture_id, title, status, position, source) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (venture_id, title, position, source),
        )
        await db.commit()
        return cursor.lastrowid


async def list_checklist_items(venture_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_CHECKLIST_ITEM_COLUMNS)} FROM ventures.checklist_items "
                "WHERE venture_id = %s AND deleted_at IS NULL ORDER BY position ASC",
                (venture_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_CHECKLIST_ITEM_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_CHECKLIST_ITEM_COLUMNS)} FROM venture_checklist_items "
            "WHERE venture_id = ? AND deleted_at IS NULL ORDER BY position ASC",
            (venture_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def update_checklist_item_status(item_id: int, status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.checklist_items SET status = %s WHERE id = %s AND deleted_at IS NULL",
                (status, item_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE venture_checklist_items SET status = ? WHERE id = ? AND deleted_at IS NULL", (status, item_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_checklist_item(item_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.checklist_items SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (item_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE venture_checklist_items SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------------------------------------------------------- customers

async def create_customer(
    venture_id: int, name: str, acquisition_source: str | None = None,
    acquisition_cost: float | None = None, postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.customers (venture_id, name, status, acquisition_source, acquisition_cost, "
                "acquired_at, created_at) VALUES (%s, %s, 'active', %s, %s, (now() AT TIME ZONE 'utc'), "
                "(now() AT TIME ZONE 'utc')) RETURNING id",
                (venture_id, name, acquisition_source, acquisition_cost),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO venture_customers (venture_id, name, status, acquisition_source, acquisition_cost) "
            "VALUES (?, ?, 'active', ?, ?)",
            (venture_id, name, acquisition_source, acquisition_cost),
        )
        await db.commit()
        return cursor.lastrowid


async def list_customers(venture_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_CUSTOMER_COLUMNS)} FROM ventures.customers "
                "WHERE venture_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                (venture_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_CUSTOMER_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_CUSTOMER_COLUMNS)} FROM venture_customers "
            "WHERE venture_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (venture_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def update_customer_status(customer_id: int, status: str, postgres_conn: Any = None) -> bool:
    """Moving to 'churned' also stamps churned_at; moving back to 'active'
    (a correction) clears it -- churned_at always reflects the most
    recent transition, not the first one."""
    churned_at_sql = "(now() AT TIME ZONE 'utc')" if status == "churned" else "NULL"
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"UPDATE ventures.customers SET status = %s, churned_at = {churned_at_sql} "
                "WHERE id = %s AND deleted_at IS NULL",
                (status, customer_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    churned_at_sql = "datetime('now')" if status == "churned" else "NULL"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"UPDATE venture_customers SET status = ?, churned_at = {churned_at_sql} "
            "WHERE id = ? AND deleted_at IS NULL",
            (status, customer_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_customer(customer_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.customers SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (customer_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE venture_customers SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (customer_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------- revenue events

async def create_revenue_event(
    customer_id: int, amount: float, event_type: str, notes: str | None = None, postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.revenue_events (customer_id, amount, event_type, occurred_at, notes, "
                "created_at) VALUES (%s, %s, %s, (now() AT TIME ZONE 'utc'), %s, (now() AT TIME ZONE 'utc')) "
                "RETURNING id",
                (customer_id, amount, event_type, notes),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO venture_revenue_events (customer_id, amount, event_type, notes) VALUES (?, ?, ?, ?)",
            (customer_id, amount, event_type, notes),
        )
        await db.commit()
        return cursor.lastrowid


async def list_revenue_events(customer_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_REVENUE_EVENT_COLUMNS)} FROM ventures.revenue_events "
                "WHERE customer_id = %s AND deleted_at IS NULL ORDER BY occurred_at DESC",
                (customer_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_REVENUE_EVENT_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_REVENUE_EVENT_COLUMNS)} FROM venture_revenue_events "
            "WHERE customer_id = ? AND deleted_at IS NULL ORDER BY occurred_at DESC",
            (customer_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def compute_customer_metrics(venture_id: int, postgres_conn: Any = None) -> dict:
    """Deterministic Python aggregation over already-fetched rows, same
    discipline as compute_breakdown_stats/dashboard_snapshot -- one
    source of truth, not a second SQL dialect to keep in sync.
    revenue_last_30d is deliberately never called "MRR": many of these
    ventures are one-time-purchase digital products, not subscriptions,
    and labeling a 30-day sum "MRR" would fabricate a recurring-revenue
    claim that isn't real. churn_rate/average_cac/average_ltv are all
    None (not 0) when there's nothing to compute them from -- "no
    customers yet" is not the same claim as "0% churn"."""
    from datetime import datetime, timedelta, timezone

    customers = await list_customers(venture_id, postgres_conn)
    all_events: list[dict] = []
    for customer in customers:
        all_events.extend(await list_revenue_events(customer["id"], postgres_conn))

    def signed(event: dict) -> float:
        return event["amount"] if event["event_type"] == "charge" else -event["amount"]

    total_revenue = sum(signed(e) for e in all_events)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    revenue_last_30d = sum(signed(e) for e in all_events if str(e["occurred_at"]) >= cutoff)

    active = [c for c in customers if c["status"] == "active"]
    churned = [c for c in customers if c["status"] == "churned"]
    churn_rate = len(churned) / len(customers) if customers else None

    costed = [c for c in customers if c["acquisition_cost"] is not None]
    average_cac = sum(c["acquisition_cost"] for c in costed) / len(costed) if costed else None
    average_ltv = total_revenue / len(customers) if customers else None

    return {
        "active_customers": len(active),
        "churned_customers": len(churned),
        "total_customers": len(customers),
        "churn_rate": churn_rate,
        "total_revenue": total_revenue,
        "revenue_last_30d": revenue_last_30d,
        "average_ltv": average_ltv,
        "average_cac": average_cac,
        "customers_with_recorded_cac": len(costed),
    }


# ------------------------------------------------------------ fulfillment

async def create_fulfillment_item(customer_id: int, title: str, postgres_conn: Any = None) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM ventures.fulfillment_items WHERE customer_id = %s AND deleted_at IS NULL",
                (customer_id,),
            )
            (position,) = await cur.fetchone()
            await cur.execute(
                "INSERT INTO ventures.fulfillment_items (customer_id, title, status, position, created_at) "
                "VALUES (%s, %s, 'pending', %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (customer_id, title, position),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM customer_fulfillment_items WHERE customer_id = ? AND deleted_at IS NULL",
            (customer_id,),
        )
        (position,) = await cursor.fetchone()
        cursor = await db.execute(
            "INSERT INTO customer_fulfillment_items (customer_id, title, status, position) "
            "VALUES (?, ?, 'pending', ?)",
            (customer_id, title, position),
        )
        await db.commit()
        return cursor.lastrowid


async def list_fulfillment_items(customer_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_FULFILLMENT_ITEM_COLUMNS)} FROM ventures.fulfillment_items "
                "WHERE customer_id = %s AND deleted_at IS NULL ORDER BY position ASC",
                (customer_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_FULFILLMENT_ITEM_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_FULFILLMENT_ITEM_COLUMNS)} FROM customer_fulfillment_items "
            "WHERE customer_id = ? AND deleted_at IS NULL ORDER BY position ASC",
            (customer_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def update_fulfillment_item_status(item_id: int, status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.fulfillment_items SET status = %s WHERE id = %s AND deleted_at IS NULL",
                (status, item_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE customer_fulfillment_items SET status = ? WHERE id = ? AND deleted_at IS NULL", (status, item_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_fulfillment_item(item_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.fulfillment_items SET deleted_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = %s AND deleted_at IS NULL",
                (item_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE customer_fulfillment_items SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


# ------------------------------------------------------------- venture health

async def update_venture_score_label(venture_id: int, score_label: str | None, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.ventures SET score_label = %s WHERE id = %s AND deleted_at IS NULL",
                (score_label, venture_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE ventures SET score_label = ? WHERE id = ? AND deleted_at IS NULL", (score_label, venture_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def compute_health_label(venture_id: int, postgres_conn: Any = None) -> str | None:
    """A simple, transparent, deterministic ruleset -- not a black-box
    model, not LLM-scored. Same 'compute deterministically, never
    fabricate confidence' discipline as compute_breakdown_stats. A
    first-cut heuristic Josh can tune once he's seen it run on real
    ventures, not a finished scoring system."""
    venture = await get_venture(venture_id, postgres_conn)
    if venture is None or venture["status"] in ("paused", "closed"):
        return None
    metrics = await compute_customer_metrics(venture_id, postgres_conn)
    if metrics["total_customers"] > 0:
        if metrics["churn_rate"] is not None and metrics["churn_rate"] > 0.5:
            return "watch"
        return "healthy" if metrics["revenue_last_30d"] > 0 else "watch"
    reports = await list_validation_reports(venture_id, postgres_conn)
    if reports and reports[0]["confidence"] == "low":
        return "watch"
    checklist = await list_checklist_items(venture_id, postgres_conn)
    if checklist and all(item["status"] in ("done", "skipped") for item in checklist):
        return "healthy"
    return "experimental"


async def recompute_and_store_health(venture_id: int, postgres_conn: Any = None) -> str | None:
    label = await compute_health_label(venture_id, postgres_conn)
    await update_venture_score_label(venture_id, label, postgres_conn)
    return label


# ------------------------------------------------------------- operations SOP

async def update_venture_operations_sop(venture_id: int, sop: str, postgres_conn: Any = None) -> bool:
    """A living document, not a dated history like validation reports --
    regenerating overwrites the previous one, same as update_venture_concept."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.ventures SET operations_sop = %s WHERE id = %s AND deleted_at IS NULL",
                (sop, venture_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE ventures SET operations_sop = ? WHERE id = ? AND deleted_at IS NULL", (sop, venture_id)
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------------------------------------------------- marketing content

async def create_marketing_content(
    venture_id: int, content_type: str, content: str, postgres_conn: Any = None
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.marketing_content (venture_id, content_type, content, created_at) "
                "VALUES (%s, %s, %s, (now() AT TIME ZONE 'utc')) RETURNING id",
                (venture_id, content_type, content),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO venture_marketing_content (venture_id, content_type, content) VALUES (?, ?, ?)",
            (venture_id, content_type, content),
        )
        await db.commit()
        return cursor.lastrowid


async def list_marketing_content(venture_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_MARKETING_CONTENT_COLUMNS)} FROM ventures.marketing_content "
                "WHERE venture_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                (venture_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_MARKETING_CONTENT_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_MARKETING_CONTENT_COLUMNS)} FROM venture_marketing_content "
            "WHERE venture_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (venture_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ---------------------------------------------------- automation suggestions

async def create_automation_suggestion(
    venture_id: int, title: str, description: str, suggested_approach: str | None = None,
    postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO ventures.automation_suggestions "
                "(venture_id, title, description, suggested_approach, status, created_at) "
                "VALUES (%s, %s, %s, %s, 'new', (now() AT TIME ZONE 'utc')) RETURNING id",
                (venture_id, title, description, suggested_approach),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO venture_automation_suggestions "
            "(venture_id, title, description, suggested_approach, status) VALUES (?, ?, ?, ?, 'new')",
            (venture_id, title, description, suggested_approach),
        )
        await db.commit()
        return cursor.lastrowid


async def list_automation_suggestions(
    venture_id: int, status: str | None = None, postgres_conn: Any = None
) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            if status is not None:
                await cur.execute(
                    f"SELECT {', '.join(_AUTOMATION_SUGGESTION_COLUMNS)} FROM ventures.automation_suggestions "
                    "WHERE venture_id = %s AND status = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                    (venture_id, status),
                )
            else:
                await cur.execute(
                    f"SELECT {', '.join(_AUTOMATION_SUGGESTION_COLUMNS)} FROM ventures.automation_suggestions "
                    "WHERE venture_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                    (venture_id,),
                )
            rows = await cur.fetchall()
            return [dict(zip(_AUTOMATION_SUGGESTION_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status is not None:
            cursor = await db.execute(
                f"SELECT {', '.join(_AUTOMATION_SUGGESTION_COLUMNS)} FROM venture_automation_suggestions "
                "WHERE venture_id = ? AND status = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                (venture_id, status),
            )
        else:
            cursor = await db.execute(
                f"SELECT {', '.join(_AUTOMATION_SUGGESTION_COLUMNS)} FROM venture_automation_suggestions "
                "WHERE venture_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                (venture_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]


async def update_automation_suggestion_status(suggestion_id: int, status: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE ventures.automation_suggestions SET status = %s WHERE id = %s AND deleted_at IS NULL",
                (status, suggestion_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE venture_automation_suggestions SET status = ? WHERE id = ? AND deleted_at IS NULL",
            (status, suggestion_id),
        )
        await db.commit()
        return cursor.rowcount > 0
