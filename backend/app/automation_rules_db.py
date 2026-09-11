"""
Real, persisted automation rules (2026-09-06) -- what used to be
automations_registry.py's single hardcoded Python-list entry becomes a
real table Frank can add rows to conversationally (see automation_tools.py's
propose_create_automation).

Deliberately a separate file from automations_db.py, not an extension of
it -- that file already backs the real, working GET /automations/runs
history (automation_runs table); splitting keeps that surface completely
untouched by this change. Same SQLite file (automations.db) though, since
both are the one "automations" concern -- rules and their run history are
two tables in one cross-cutting database, same reasoning automations_db.py
already gives for having its own file separate from pcorp.db.
"""

from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "automations.db"


async def init_automation_rules_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                trigger_tool TEXT NOT NULL,
                agent TEXT NOT NULL,
                instruction TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Seeds the one rule that already existed as hardcoded Python (see
        # automations_registry.py, now deleted) -- same literal id, so its
        # existing automation_runs history (keyed by this id already)
        # stays joinable across the migration. INSERT OR IGNORE makes this
        # idempotent across every restart, same idiom triggers_db.py's own
        # RULE_TYPES seed already uses.
        await db.execute(
            "INSERT OR IGNORE INTO automation_rules "
            "(id, name, description, trigger_tool, agent, instruction, enabled) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (
                "new_project_folder_structure",
                "New project -> folder structure",
                "When a new Alpha Mode Media project is added, ask the Design Agent to suggest a real "
                "folder/asset structure for it.",
                "add_project",
                "design",
                "Suggest a real, concrete folder/asset structure for organizing this new Alpha Mode Media "
                "project's files (raw footage, project files, deliverables, etc.) -- specific folder names "
                "for this project, not generic advice.",
            ),
        )
        await db.commit()


async def list_rules(postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, description, trigger_tool, agent, instruction, enabled, created_at "
                "FROM automations.automation_rules ORDER BY created_at ASC"
            )
            rows = await cur.fetchall()
            return [_row_to_dict_postgres(r) for r in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, description, trigger_tool, agent, instruction, enabled, created_at "
            "FROM automation_rules ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(row) for row in rows]


async def list_enabled_rules_for_tool(trigger_tool: str, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, description, trigger_tool, agent, instruction, enabled, created_at "
                "FROM automations.automation_rules WHERE trigger_tool = %s AND enabled = 1",
                (trigger_tool,),
            )
            rows = await cur.fetchall()
            return [_row_to_dict_postgres(r) for r in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, description, trigger_tool, agent, instruction, enabled, created_at "
            "FROM automation_rules WHERE trigger_tool = ? AND enabled = 1",
            (trigger_tool,),
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(row) for row in rows]


async def create_rule(
    id: str, name: str, description: str, trigger_tool: str, agent: str, instruction: str, postgres_conn: Any = None
) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO automations.automation_rules "
                "(id, name, description, trigger_tool, agent, instruction, enabled, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 1, (now() AT TIME ZONE 'utc'))",
                (id, name, description, trigger_tool, agent, instruction),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO automation_rules (id, name, description, trigger_tool, agent, instruction, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (id, name, description, trigger_tool, agent, instruction),
        )
        await db.commit()


async def set_rule_enabled(rule_id: str, enabled: bool, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE automations.automation_rules SET enabled = %s WHERE id = %s", (1 if enabled else 0, rule_id)
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE automation_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id)
        )
        await db.commit()


async def delete_rule(rule_id: str, postgres_conn: Any = None) -> bool:
    # Hard delete, unlike Joshx's soft-deleted leads/clients/projects -- a
    # rule has no downstream foreign-key dependency that needs it to
    # "still exist": automation_runs.rule_id is a bare string snapshot,
    # not a real FK, so deleting the rule row never orphans a join.
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("DELETE FROM automations.automation_rules WHERE id = %s", (rule_id,))
            deleted = cur.rowcount > 0
        await postgres_conn.commit()
        return deleted
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
        await db.commit()
        return cursor.rowcount > 0


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "trigger_tool": row["trigger_tool"],
        "agent": row["agent"],
        "instruction": row["instruction"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
    }


def _row_to_dict_postgres(row: tuple) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "trigger_tool": row[3],
        "agent": row[4],
        "instruction": row[5],
        "enabled": bool(row[6]),
        "created_at": str(row[7]) if row[7] is not None else None,
    }
