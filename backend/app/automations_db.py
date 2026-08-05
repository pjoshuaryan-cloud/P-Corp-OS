"""
Persistent log of real automation firings -- what triggered, what the
consulted agent actually said, when. Backs the Automations nav section's
run history (GET /automations/runs), same "make it visible, not just
something that silently happened once" reasoning as Operations' task
list and Frank's own memory view.

Its own SQLite file (automations.db), same "genuinely separate,
cross-cutting concern" reasoning as operations.db -- automations aren't
tied to one business domain (a rule can trigger off any tool and
consult any agent), and shouldn't be commingled with pcorp.db's
conversations/memory either.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "automations.db"


async def init_automations_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                trigger_summary TEXT,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()


async def record_run(rule_id: str, rule_name: str, trigger_summary: str | None, result: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO automation_runs (rule_id, rule_name, trigger_summary, result) VALUES (?, ?, ?, ?)",
            (rule_id, rule_name, trigger_summary, result),
        )
        await db.commit()


async def list_runs() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, rule_id, rule_name, trigger_summary, result, created_at "
            "FROM automation_runs ORDER BY id DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "rule_name": row["rule_name"],
                "trigger_summary": row["trigger_summary"],
                "result": row["result"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
