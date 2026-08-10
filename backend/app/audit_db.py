"""
Real audit log for every tool call any agent makes -- who/what/when/input/
result, closing the gap SECURITY.md flagged after the 2026-08-10 audit
against the additive feature spec ("Every consequential action should be
auditable... WHO/WHAT initiated it, WHAT happened, WHEN, WHAT data was
used, WHAT tool was called, WHAT result occurred").

No "who" column -- P Corp OS has exactly one user, and every tool call is
always Frank acting on Joshua's behalf; a column that's constant for
every row forever would be noise, not signal. If that ever changes
(a second person's own access -- see ALPHA_MODE.md's open question on
Nick/Raoof), this is the first place that would need a real column.

Its own SQLite file (audit.db), not merged into pcorp.db -- this has a
different retention/access pattern than conversations or memory
(append-only, never soft-deleted, potentially inspected under very
different circumstances than normal use), same "distinct concern gets
its own file" reasoning already applied to operations.db/automations.db,
just for a different reason (audit isolation, not business-domain
separation).

Deliberately backend-only this pass -- no GET /audit endpoint or UI view
yet. The real safety value (an actual, inspectable trail existing at
all) doesn't require a UI to be real; a view is a natural, separate
follow-on once there's actual data in here to look at, not bundled into
"can this be trusted to log correctly" as one piece of work.
"""

import json
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"

# Result text truncated at this length before storage -- an agent's reply
# can be thousands of characters (a full SOP, a shot list); the audit
# trail needs "what happened," not a second copy of every full response
# already sitting in messages/memory_records. Long enough to be useful
# for a quick review, short enough that this table doesn't balloon.
RESULT_TRUNCATE_LENGTH = 500


async def init_audit_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def record_tool_call(tool_name: str, tool_input: dict, result: str) -> None:
    truncated = result if len(result) <= RESULT_TRUNCATE_LENGTH else result[:RESULT_TRUNCATE_LENGTH] + "…"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tool_calls (tool_name, input_json, result) VALUES (?, ?, ?)",
            (tool_name, json.dumps(tool_input), truncated),
        )
        await db.commit()


async def list_recent_calls(limit: int = 100) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, tool_name, input_json, result, created_at FROM tool_calls ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "tool_name": row["tool_name"],
                "input": json.loads(row["input_json"]),
                "result": row["result"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
