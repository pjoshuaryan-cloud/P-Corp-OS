"""
Proactive Triggers Layer (2026-08-21) — the persistence half. A genuinely
new concern (scheduled, not event-driven — see automations_db.py's own
"event-driven, not scheduled" scoping note, ROADMAP.md 2026-08-04), so it
gets its own file/DB, same reasoning already applied to automations.db and
alpha_mode.db: a cross-cutting system that happens to run inside this one
process, not something that belongs bolted onto db.py's app_state (which
is reserved for true global singleton values, not per-item records — see
db.py's own module docstring).

Two tables:

- `trigger_rules` — one row per rule TYPE (not per flagged item), holding
  enabled/disabled + a configurable threshold. This is the "data rows, not
  hardcoded, so new ones can be added without redeploying" requirement,
  scoped honestly: the four rule *types* below and their thresholds are
  data; the actual condition-checking logic per type still lives in code
  (triggers.py), one function per rule_type, exactly like
  automations_registry.py's existing trigger_tool → handler pattern. A
  fully generic "arbitrary condition as data" engine would need a query
  DSL this app has no other use for — real added complexity this
  codebase's own stated philosophy (alpha_mode_db.py's docstring: "added
  complexity should wait until real usage actually calls for it") argues
  against building speculatively for a four-rule system.

- `trigger_state` — one row per flagged ITEM (e.g. one specific overdue
  invoice), tracking the day-1/day-3/day-7/weekly decaying-cadence dedup
  requirement. Without this, every scheduled run would re-flag everything
  still true, which is exactly the "flood of pings" the spec explicitly
  rules out.

rule_type "stale_task" is deliberately NOT seeded here — no table in this
system tracks when a task was last updated (operations.db's tasks table
has no updated_at column at all), so there's no real data to check against.
Confirmed with Joshua (2026-08-21): drop it for v1 rather than fake it
against due_date instead, which would just be project_stage_stall's
sibling wearing a different name.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "triggers.db"

# Days-since-first-flagged at which a still-true item gets re-surfaced.
# Matches the spec exactly: day one, day three, day seven, then weekly.
CADENCE_DAYS = [1, 3, 7]
CADENCE_REPEAT_DAYS = 7

RULE_TYPES = {
    "invoice_overdue": None,
    "client_contact_gap": 21,
    "project_stage_stall": None,
    "deliverable_overdue": None,
}


async def init_triggers_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_type TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                threshold_days INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_state (
                item_key TEXT PRIMARY KEY,
                rule_type TEXT NOT NULL,
                first_flagged_at TEXT NOT NULL,
                last_notified_at TEXT,
                notify_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS digest_schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_sent_date TEXT,
                send_hour INTEGER NOT NULL DEFAULT 7
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM digest_schedule WHERE id = 1")
        (count,) = await cursor.fetchone()
        if count == 0:
            await db.execute("INSERT INTO digest_schedule (id, last_sent_date, send_hour) VALUES (1, NULL, 7)")

        for rule_type, threshold in RULE_TYPES.items():
            await db.execute(
                "INSERT OR IGNORE INTO trigger_rules (rule_type, enabled, threshold_days) VALUES (?, 1, ?)",
                (rule_type, threshold),
            )
        await db.commit()


async def list_rules() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT rule_type, enabled, threshold_days FROM trigger_rules ORDER BY rule_type")
        rows = await cursor.fetchall()
        return [{"rule_type": r["rule_type"], "enabled": bool(r["enabled"]), "threshold_days": r["threshold_days"]} for r in rows]


async def enabled_rule_thresholds() -> dict:
    """rule_type -> threshold_days for every enabled rule."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT rule_type, threshold_days FROM trigger_rules WHERE enabled = 1")
        rows = await cursor.fetchall()
        return {rule_type: threshold for rule_type, threshold in rows}


async def set_rule_enabled(rule_type: str, enabled: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE trigger_rules SET enabled = ? WHERE rule_type = ?", (1 if enabled else 0, rule_type))
        await db.commit()


def _next_due_day(notify_count: int) -> int:
    if notify_count < len(CADENCE_DAYS):
        return CADENCE_DAYS[notify_count]
    extra_steps = notify_count - len(CADENCE_DAYS) + 1
    return CADENCE_DAYS[-1] + extra_steps * CADENCE_REPEAT_DAYS


async def items_due_for_notification(rule_type: str, item_keys: list[str]) -> list[str]:
    """Given every item_key currently matching a rule's live condition,
    return only the ones due to be (re-)surfaced today per the decaying
    cadence — creating fresh state rows for items seen for the first
    time. Does NOT mark them notified; call mark_notified() after the
    digest actually sends, so a failed send doesn't silently burn a
    cadence slot."""
    today = date.today()
    due: list[str] = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for item_key in item_keys:
            cursor = await db.execute(
                "SELECT first_flagged_at, notify_count FROM trigger_state WHERE item_key = ?", (item_key,)
            )
            row = await cursor.fetchone()
            if row is None:
                await db.execute(
                    "INSERT INTO trigger_state (item_key, rule_type, first_flagged_at, notify_count) VALUES (?, ?, ?, 0)",
                    (item_key, rule_type, today.isoformat()),
                )
                due.append(item_key)
                continue
            first_flagged = date.fromisoformat(row["first_flagged_at"])
            age_days = (today - first_flagged).days
            if age_days >= _next_due_day(row["notify_count"]):
                due.append(item_key)
        await db.commit()
    return due


async def peek_due_status(rule_type: str, item_keys: list[str]) -> dict[str, bool]:
    """Read-only counterpart to items_due_for_notification() -- same
    cadence math, but never inserts/updates state. For the Triggers UI
    (2026-08-21): a live status view needs to show "would this be in
    today's digest" without a page load itself consuming a cadence slot
    or creating first-flagged state for items nobody's actually notified
    on yet (that's still run_daily_digest()'s job alone)."""
    today = date.today()
    result: dict[str, bool] = {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for item_key in item_keys:
            cursor = await db.execute(
                "SELECT first_flagged_at, notify_count FROM trigger_state WHERE item_key = ?", (item_key,)
            )
            row = await cursor.fetchone()
            if row is None:
                result[item_key] = True
                continue
            first_flagged = date.fromisoformat(row["first_flagged_at"])
            age_days = (today - first_flagged).days
            result[item_key] = age_days >= _next_due_day(row["notify_count"])
    return result


async def mark_notified(item_keys: list[str]) -> None:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        for item_key in item_keys:
            await db.execute(
                "UPDATE trigger_state SET last_notified_at = ?, notify_count = notify_count + 1 WHERE item_key = ?",
                (now, item_key),
            )
        await db.commit()


async def clear_resolved(rule_type: str, still_open_keys: list[str]) -> None:
    """Drop state for items that no longer match the rule's live
    condition (invoice got paid, client got contacted, etc.) so a future
    recurrence is treated as new rather than continuing a stale cadence."""
    async with aiosqlite.connect(DB_PATH) as db:
        if still_open_keys:
            placeholders = ",".join("?" for _ in still_open_keys)
            await db.execute(
                f"DELETE FROM trigger_state WHERE rule_type = ? AND item_key NOT IN ({placeholders})",
                (rule_type, *still_open_keys),
            )
        else:
            await db.execute("DELETE FROM trigger_state WHERE rule_type = ?", (rule_type,))
        await db.commit()


async def get_digest_schedule() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_sent_date, send_hour FROM digest_schedule WHERE id = 1")
        row = await cursor.fetchone()
        return {"last_sent_date": row[0], "send_hour": row[1]}


async def mark_digest_sent(sent_date: date) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE digest_schedule SET last_sent_date = ? WHERE id = 1", (sent_date.isoformat(),))
        await db.commit()
