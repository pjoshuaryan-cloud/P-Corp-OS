"""
Finance -- Josh's personal investment tracking (2026-08-21), scoped down
directly with him before building: real portfolio tracking across five
accounts (Liberty Stash, EasyEquities, Luno, Ashburton Stable Income
Fund, Nasdaq/Markets) plus daily updates. Opportunity-scanning ("always
look for lucrative investment opportunities") deliberately deferred --
its own real build (real market-data sourcing, careful scoping around
what Frank can flag vs. actual investment advice), not silently dropped.

Real technical constraint investigated before any code: only Luno has an
official public API (a scoped, revocable read-only key, not Josh's
account password). EasyEquities has no official API -- only unofficial
tools that require his real login credentials, which this app won't
handle (same credential-safety boundary as everywhere else). Liberty
Stash and Ashburton have no API at all. So this is a genuine hybrid:
Luno auto-snapshots daily via luno_client.py; the other four are tracked
the same honest way Joshx/Personal track anything with no external
API -- Josh tells Frank a balance when he checks it, Frank logs it.

One `accounts` table (the five tracked accounts, pre-seeded) plus one
`balance_snapshots` table (one row per observation, multiple assets per
account allowed -- Luno in particular can hold ZAR cash *and* crypto
assets like XBT/ETH simultaneously, and this app never fabricates a
single blended total across mismatched currencies/assets, same "never
fabricate metrics" discipline as everywhere else in this codebase).

Own SQLite file (finance.db), same "genuinely separate domain" reasoning
as joshx.db/personal.db/automations.db. Gitignored like every file under
backend/data/.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "finance.db"

# Pre-seeded on init -- these are Josh's actual five tracked accounts,
# named per his own words, not generic placeholders. is_automatic=1 only
# for Luno (the one account with a real API); the other four are
# manual-log-only.
_SEED_ACCOUNTS = [
    ("Liberty Stash", "tax_free_savings", 0),
    ("EasyEquities", "brokerage", 0),
    ("Luno", "crypto_exchange", 1),
    ("Ashburton Stable Income Fund", "unit_trust", 0),
    ("Nasdaq / Markets", "stock_market", 0),
]


async def init_finance_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                account_type TEXT,
                is_automatic INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                asset TEXT NOT NULL DEFAULT 'ZAR',
                balance REAL NOT NULL,
                notes TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS luno_snapshot_schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_snapshot_date TEXT
            )
            """
        )
        cursor = await db.execute("SELECT COUNT(*) FROM luno_snapshot_schedule WHERE id = 1")
        (count,) = await cursor.fetchone()
        if count == 0:
            await db.execute("INSERT INTO luno_snapshot_schedule (id, last_snapshot_date) VALUES (1, NULL)")

        for name, account_type, is_automatic in _SEED_ACCOUNTS:
            await db.execute(
                "INSERT OR IGNORE INTO accounts (name, account_type, is_automatic) VALUES (?, ?, ?)",
                (name, account_type, is_automatic),
            )
        await db.commit()


async def _find_account_id(db: aiosqlite.Connection, identifier: str) -> int | None:
    cursor = await db.execute(
        "SELECT id FROM accounts WHERE name = ? COLLATE NOCASE LIMIT 1", (identifier,)
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await db.execute("SELECT id FROM accounts WHERE name LIKE ? LIMIT 1", (f"%{identifier}%",))
        row = await cursor.fetchone()
    return row[0] if row else None


async def log_balance(identifier: str, balance: float, asset: str = "ZAR", notes: str | None = None) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        account_id = await _find_account_id(db, identifier)
        if account_id is None:
            return None
        await db.execute(
            "INSERT INTO balance_snapshots (account_id, asset, balance, notes) VALUES (?, ?, ?, ?)",
            (account_id, asset.upper(), balance, notes),
        )
        await db.commit()
        cursor = await db.execute("SELECT name FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        return row["name"]


async def get_luno_schedule() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_snapshot_date FROM luno_snapshot_schedule WHERE id = 1")
        row = await cursor.fetchone()
        return {"last_snapshot_date": row[0]}


async def mark_luno_snapshotted(snapshot_date: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE luno_snapshot_schedule SET last_snapshot_date = ? WHERE id = 1", (snapshot_date,)
        )
        await db.commit()


async def dashboard_snapshot() -> dict:
    """Backs GET /finance/dashboard. For each account, the latest
    snapshot per asset it's ever held, plus the trend versus the
    snapshot before that (up/down/flat) -- real, computed from actual
    logged history, never a fabricated number. No blended cross-currency
    total: an account can hold multiple assets (Luno's ZAR + XBT + ETH),
    and summing those into one number would misrepresent the real
    portfolio, so this deliberately doesn't attempt it."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, account_type, is_automatic FROM accounts ORDER BY id"
        )
        accounts = [
            {**dict(r), "is_automatic": bool(r["is_automatic"])} for r in await cursor.fetchall()
        ]

        for account in accounts:
            cursor = await db.execute(
                "SELECT DISTINCT asset FROM balance_snapshots WHERE account_id = ?", (account["id"],)
            )
            assets = [r["asset"] for r in await cursor.fetchall()]
            holdings = []
            for asset in assets:
                cursor = await db.execute(
                    "SELECT balance, recorded_at FROM balance_snapshots "
                    "WHERE account_id = ? AND asset = ? ORDER BY recorded_at DESC LIMIT 2",
                    (account["id"], asset),
                )
                rows = await cursor.fetchall()
                latest = rows[0]
                previous = rows[1] if len(rows) > 1 else None
                trend = "flat"
                if previous is not None:
                    if latest["balance"] > previous["balance"]:
                        trend = "up"
                    elif latest["balance"] < previous["balance"]:
                        trend = "down"
                holdings.append(
                    {
                        "asset": asset,
                        "balance": latest["balance"],
                        "recorded_at": latest["recorded_at"],
                        "trend": trend,
                        "previous_balance": previous["balance"] if previous else None,
                    }
                )
            account["holdings"] = holdings

    return {"accounts": accounts}


async def summarize() -> str:
    """Folded into Frank's own system prompt (finance_tools.build_finance_block())
    -- same mechanism as build_joshx_block()/build_personal_block()."""
    snapshot = await dashboard_snapshot()
    tracked = [a for a in snapshot["accounts"] if a["holdings"]]
    if not tracked:
        return ""
    lines: list[str] = ["Finance accounts (most recent logged balance per asset):"]
    for account in tracked:
        for holding in account["holdings"]:
            lines.append(
                f"  - {account['name']}: {holding['balance']:,.2f} {holding['asset']} "
                f"as of {holding['recorded_at']} ({holding['trend']})"
            )
    return "\n".join(lines)
