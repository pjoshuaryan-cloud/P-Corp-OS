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

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    # No global threshold -- overdue-ness is per-person via
    # people_db.py's own follow_up_cadence_days column, not one cutoff
    # shared across everyone the way client_contact_gap's 21 days is.
    "relationship_follow_up_overdue": None,
    # No configurable threshold column here either -- market_movers.py
    # hardcodes its "notable move" percentage in the checker itself,
    # same pattern as every threshold_days=None rule above.
    "market_mover": None,
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
                send_hour INTEGER NOT NULL DEFAULT 6
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM digest_schedule WHERE id = 1")
        (count,) = await cursor.fetchone()
        if count == 0:
            await db.execute("INSERT INTO digest_schedule (id, last_sent_date, send_hour) VALUES (1, NULL, 6)")

        # market_movers.py's price history -- a market price isn't tied
        # to any one account/holding (unlike Finance's balance_snapshots),
        # so it lives here as its own table rather than in finance_db.py.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS market_price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                price_zar REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS market_movers_snapshot_schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_snapshot_date TEXT
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM market_movers_snapshot_schedule WHERE id = 1")
        (count,) = await cursor.fetchone()
        if count == 0:
            await db.execute(
                "INSERT INTO market_movers_snapshot_schedule (id, last_snapshot_date) VALUES (1, NULL)"
            )

        for rule_type, threshold in RULE_TYPES.items():
            await db.execute(
                "INSERT OR IGNORE INTO trigger_rules (rule_type, enabled, threshold_days) VALUES (?, 1, ?)",
                (rule_type, threshold),
            )
        await db.commit()


async def list_rules(postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT rule_type, enabled, threshold_days FROM triggers.trigger_rules ORDER BY rule_type")
            rows = await cur.fetchall()
            return [{"rule_type": r[0], "enabled": bool(r[1]), "threshold_days": r[2]} for r in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT rule_type, enabled, threshold_days FROM trigger_rules ORDER BY rule_type")
        rows = await cursor.fetchall()
        return [{"rule_type": r["rule_type"], "enabled": bool(r["enabled"]), "threshold_days": r["threshold_days"]} for r in rows]


async def enabled_rule_thresholds(postgres_conn: Any = None) -> dict:
    """rule_type -> threshold_days for every enabled rule."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT rule_type, threshold_days FROM triggers.trigger_rules WHERE enabled = 1")
            rows = await cur.fetchall()
            return {rule_type: threshold for rule_type, threshold in rows}
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT rule_type, threshold_days FROM trigger_rules WHERE enabled = 1")
        rows = await cursor.fetchall()
        return {rule_type: threshold for rule_type, threshold in rows}


async def set_rule_enabled(rule_type: str, enabled: bool, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE triggers.trigger_rules SET enabled = %s WHERE rule_type = %s", (1 if enabled else 0, rule_type)
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE trigger_rules SET enabled = ? WHERE rule_type = ?", (1 if enabled else 0, rule_type))
        await db.commit()


def _next_due_day(notify_count: int) -> int:
    if notify_count < len(CADENCE_DAYS):
        return CADENCE_DAYS[notify_count]
    extra_steps = notify_count - len(CADENCE_DAYS) + 1
    return CADENCE_DAYS[-1] + extra_steps * CADENCE_REPEAT_DAYS


async def items_due_for_notification(rule_type: str, item_keys: list[str], postgres_conn: Any = None) -> list[str]:
    """Given every item_key currently matching a rule's live condition,
    return only the ones due to be (re-)surfaced today per the decaying
    cadence — creating fresh state rows for items seen for the first
    time. Does NOT mark them notified; call mark_notified() after the
    digest actually sends, so a failed send doesn't silently burn a
    cadence slot."""
    today = date.today()
    due: list[str] = []
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            for item_key in item_keys:
                await cur.execute(
                    "SELECT first_flagged_at, notify_count FROM triggers.trigger_state WHERE item_key = %s",
                    (item_key,),
                )
                row = await cur.fetchone()
                if row is None:
                    await cur.execute(
                        "INSERT INTO triggers.trigger_state (item_key, rule_type, first_flagged_at, notify_count) "
                        "VALUES (%s, %s, %s, 0)",
                        (item_key, rule_type, today.isoformat()),
                    )
                    due.append(item_key)
                    continue
                first_flagged = date.fromisoformat(str(row[0]))
                age_days = (today - first_flagged).days
                if age_days >= _next_due_day(row[1]):
                    due.append(item_key)
        await postgres_conn.commit()
        return due
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


async def peek_due_status(rule_type: str, item_keys: list[str], postgres_conn: Any = None) -> dict[str, bool]:
    """Read-only counterpart to items_due_for_notification() -- same
    cadence math, but never inserts/updates state. For the Triggers UI
    (2026-08-21): a live status view needs to show "would this be in
    today's digest" without a page load itself consuming a cadence slot
    or creating first-flagged state for items nobody's actually notified
    on yet (that's still run_daily_digest()'s job alone)."""
    today = date.today()
    result: dict[str, bool] = {}
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            for item_key in item_keys:
                await cur.execute(
                    "SELECT first_flagged_at, notify_count FROM triggers.trigger_state WHERE item_key = %s",
                    (item_key,),
                )
                row = await cur.fetchone()
                if row is None:
                    result[item_key] = True
                    continue
                first_flagged = date.fromisoformat(str(row[0]))
                age_days = (today - first_flagged).days
                result[item_key] = age_days >= _next_due_day(row[1])
        return result
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


async def mark_notified(item_keys: list[str], postgres_conn: Any = None) -> None:
    # Computed once in Python and reused for both backends, deliberately
    # -- this preserves the exact existing (local-time, not UTC) value
    # SQLite has always stored here, rather than introducing yet another
    # backend-specific timestamp inconsistency on top of it.
    now = datetime.now().isoformat()
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            for item_key in item_keys:
                await cur.execute(
                    "UPDATE triggers.trigger_state SET last_notified_at = %s, notify_count = notify_count + 1 "
                    "WHERE item_key = %s",
                    (now, item_key),
                )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for item_key in item_keys:
            await db.execute(
                "UPDATE trigger_state SET last_notified_at = ?, notify_count = notify_count + 1 WHERE item_key = ?",
                (now, item_key),
            )
        await db.commit()


async def clear_resolved(rule_type: str, still_open_keys: list[str], postgres_conn: Any = None) -> None:
    """Drop state for items that no longer match the rule's live
    condition (invoice got paid, client got contacted, etc.) so a future
    recurrence is treated as new rather than continuing a stale cadence."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            if still_open_keys:
                placeholders = ",".join("%s" for _ in still_open_keys)
                await cur.execute(
                    f"DELETE FROM triggers.trigger_state WHERE rule_type = %s AND item_key NOT IN ({placeholders})",
                    (rule_type, *still_open_keys),
                )
            else:
                await cur.execute("DELETE FROM triggers.trigger_state WHERE rule_type = %s", (rule_type,))
        await postgres_conn.commit()
        return
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


async def get_digest_schedule(postgres_conn: Any = None) -> dict:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT last_sent_date, send_hour FROM triggers.digest_schedule WHERE id = 1")
            row = await cur.fetchone()
            return {"last_sent_date": row[0], "send_hour": row[1]}
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_sent_date, send_hour FROM digest_schedule WHERE id = 1")
        row = await cursor.fetchone()
        return {"last_sent_date": row[0], "send_hour": row[1]}


async def claim_digest_send(sent_date: date, postgres_conn: Any = None) -> bool:
    """Atomically claims today's digest send -- Stage 6 prep (2026-09-10),
    replacing the old separate check-then-mark_digest_sent sequence, which
    had a real TOCTOU race: two concurrent schedulers (today's single Mac
    loop, and a future cloud worker during any migration overlap) could
    both read last_sent_date != today before either wrote, both send a
    real duplicate notification, and only then both harmlessly update the
    flag -- by then the damage is done. A single conditional UPDATE is
    atomic in both engines; the caller must check the returned rowcount
    (via this function's return value) BEFORE doing the actual send, not
    after -- only the winner should ever call run_daily_digest().
    Returns True if this call won the claim, False if another caller
    already claimed today's send.
    """
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE triggers.digest_schedule SET last_sent_date = %s "
                "WHERE id = 1 AND (last_sent_date IS NULL OR last_sent_date != %s)",
                (sent_date.isoformat(), sent_date.isoformat()),
            )
            won = cur.rowcount == 1
        await postgres_conn.commit()
        return won
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE digest_schedule SET last_sent_date = ? "
            "WHERE id = 1 AND (last_sent_date IS NULL OR last_sent_date != ?)",
            (sent_date.isoformat(), sent_date.isoformat()),
        )
        won = cursor.rowcount == 1
        await db.commit()
        return won


async def revert_digest_claim(previous_value: str | None, postgres_conn: Any = None) -> None:
    """Reverts a claim_digest_send() win back to its pre-claim value --
    only ever called by the one caller that just won that claim (never a
    race: nobody else could also be holding it), so this plain
    unconditional UPDATE needs no WHERE-conditional/rowcount check the way
    claim_digest_send() does. Exists so a real send failure still retries
    on the next scheduler tick, exactly like the pre-Stage-6 behavior --
    reordering the claim to happen before the send (to close the double-
    send race) would otherwise have silently broken that retry guarantee,
    since the claim would already be committed by the time the send fails.
    """
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE triggers.digest_schedule SET last_sent_date = %s WHERE id = 1", (previous_value,))
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE digest_schedule SET last_sent_date = ? WHERE id = 1", (previous_value,))
        await db.commit()


async def get_market_movers_schedule(postgres_conn: Any = None) -> dict:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("SELECT last_snapshot_date FROM triggers.market_movers_snapshot_schedule WHERE id = 1")
            (last_snapshot_date,) = await cur.fetchone()
            return {"last_snapshot_date": last_snapshot_date}
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_snapshot_date FROM market_movers_snapshot_schedule WHERE id = 1")
        row = await cursor.fetchone()
        return {"last_snapshot_date": row[0]}


async def mark_market_movers_snapshotted(snapshot_date: str, postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE triggers.market_movers_snapshot_schedule SET last_snapshot_date = %s WHERE id = 1",
                (snapshot_date,),
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE market_movers_snapshot_schedule SET last_snapshot_date = ? WHERE id = 1", (snapshot_date,)
        )
        await db.commit()


async def record_price_snapshots(prices: dict[str, float], postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            for asset, price in prices.items():
                # recorded_at supplied explicitly -- same missing-DEFAULT
                # gap found repeatedly this migration.
                await cur.execute(
                    "INSERT INTO triggers.market_price_snapshots (asset, price_zar, recorded_at) "
                    "VALUES (%s, %s, (now() AT TIME ZONE 'utc'))",
                    (asset, price),
                )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for asset, price in prices.items():
            await db.execute(
                "INSERT INTO market_price_snapshots (asset, price_zar) VALUES (?, ?)", (asset, price)
            )
        await db.commit()


async def get_price_change(asset: str, lookback_days: int = 1, postgres_conn: Any = None) -> dict | None:
    """The most recent price for `asset`, plus the closest snapshot at
    least `lookback_days` old -- used to compute a real day-over-day (or
    N-day) percent change. Returns None if there isn't yet a snapshot old
    enough to compare against (e.g. the first day this asset was ever
    tracked)."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "SELECT price_zar, recorded_at FROM triggers.market_price_snapshots WHERE asset = %s "
                "ORDER BY recorded_at DESC LIMIT 1",
                (asset,),
            )
            latest = await cur.fetchone()
            if latest is None:
                return None

            # Real, pre-existing bug found live (2026-09-11), present in
            # the original SQLite code too, not introduced by this port:
            # recorded_at is stored as naive UTC in both backends
            # (SQLite's own datetime('now') default returns UTC, matching
            # the exact same Stage 8 local_node_last_seen_at bug class),
            # but this cutoff used Python's local-time datetime.now() --
            # on any machine not already at UTC+0, "1 day ago" was off by
            # the local UTC offset, comparing against the wrong snapshot.
            #
            # Second bug, found and fixed together (2026-09-11):
            # recorded_at is compared as plain TEXT in both backends (the
            # column is TEXT in SQLite and stayed TEXT through the
            # migration to Postgres too), but `.isoformat()` defaults to a
            # "T" date/time separator while both backends actually store
            # a space -- e.g. "2026-09-10 22:14:17". Since " " < "T"
            # ASCII-wise, any same-calendar-day snapshot string-sorted as
            # "older than" the cutoff regardless of its actual time,
            # silently picking a too-recent "previous" price and
            # understating real day-over-day moves. `sep=" "` matches the
            # stored format exactly, restoring correct lexicographic (and
            # therefore chronological) ordering.
            cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)).isoformat(
                sep=" "
            )
            await cur.execute(
                "SELECT price_zar, recorded_at FROM triggers.market_price_snapshots "
                "WHERE asset = %s AND recorded_at <= %s "
                "ORDER BY recorded_at DESC LIMIT 1",
                (asset, cutoff),
            )
            previous = await cur.fetchone()
            if previous is None:
                return None

        return {
            "current_price": latest[0],
            "previous_price": previous[0],
            "current_at": str(latest[1]) if latest[1] is not None else None,
            "previous_at": str(previous[1]) if previous[1] is not None else None,
        }
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT price_zar, recorded_at FROM market_price_snapshots WHERE asset = ? "
            "ORDER BY recorded_at DESC LIMIT 1",
            (asset,),
        )
        latest = await cursor.fetchone()
        if latest is None:
            return None

        # Same naive-UTC and separator fixes as the postgres path above.
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)).isoformat(
            sep=" "
        )
        cursor = await db.execute(
            "SELECT price_zar, recorded_at FROM market_price_snapshots WHERE asset = ? AND recorded_at <= ? "
            "ORDER BY recorded_at DESC LIMIT 1",
            (asset, cutoff),
        )
        previous = await cursor.fetchone()
        if previous is None:
            return None

    return {
        "current_price": latest["price_zar"],
        "previous_price": previous["price_zar"],
        "current_at": latest["recorded_at"],
        "previous_at": previous["recorded_at"],
    }
