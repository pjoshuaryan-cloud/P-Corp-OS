"""
Trading Division — read-only reporting over the trading robot's own real
outputs (research.sqlite), not a rebuild of the trading robot inside P
Corp (TRADING_DIVISION.md's explicit decision) and not an agent with any
write/execute capability at all. Confirmed directly with Joshua
(2026-08-17), overriding TRADING_DIVISION.md's "not until the trading
robot is stable" timing note: the robot itself is genuinely still early
(its own README calls itself "Phase 1: Scaffolding," and its results
database has exactly one backtest and zero walk-forward/Monte Carlo runs
as of this writing) -- built anyway, on the explicit reasoning that it'll
correctly report that sparse real state today and pick up more without
any further changes as the trading robot actually produces results.

Genuinely cross-repo: the trading robot lives entirely in its own
separate project ("AMM - APP", a sibling of this repo on Joshua's Desktop,
not nested inside it), exactly matching TRADING_DIVISION.md's own decided
boundary -- "it does not get rebuilt inside P Corp." This reads that
repo's real SQLite database directly, read-only (`mode=ro` in the
connection URI, not just "we don't happen to write to it" -- SQLite
itself enforces it), and nothing here ever writes to it, touches the EA
source, or reaches a live broker account. That boundary is structural,
not just a comment: there is no write path anywhere in this file.

Fails soft everywhere (empty dict/string, never an exception) if the
other repo's database is missing or relocated -- this app has no business
crashing over a completely separate project's file layout changing.
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path.home() / "Desktop" / "AMM - APP" / "research" / "data" / "research.sqlite"


def _read_only_uri() -> str:
    return f"file:{DB_PATH}?mode=ro"


async def dashboard_snapshot() -> dict:
    """Backs the desktop Trading Division tab. Backtests and walk-forward
    runs both live in the same `runs` table, split by `run_type` -- kept
    as separate lists here since they're conceptually different things to
    show, not because the underlying query differs much."""
    if not DB_PATH.exists():
        return {"backtests": [], "walkforward_runs": [], "montecarlo_runs": []}

    try:
        async with aiosqlite.connect(_read_only_uri(), uri=True) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """SELECT run_id, symbol, entry_timeframe, start_at, end_at, created_at,
                          total_trades, win_rate_pct, profit_factor, max_drawdown_pct, total_pnl
                   FROM runs WHERE run_type = 'BACKTEST' ORDER BY created_at DESC"""
            )
            backtests = [dict(r) for r in await cursor.fetchall()]

            cursor = await db.execute(
                """SELECT run_id, symbol, entry_timeframe, start_at, end_at, created_at,
                          total_trades, win_rate_pct, profit_factor, max_drawdown_pct, total_pnl
                   FROM runs WHERE run_type = 'WALK_FORWARD' ORDER BY created_at DESC"""
            )
            walkforward_runs = [dict(r) for r in await cursor.fetchall()]

            cursor = await db.execute(
                """SELECT run_id, created_at, num_simulations, probability_of_ruin_pct,
                          final_balance_p5, final_balance_p50, final_balance_p95,
                          max_drawdown_p50, max_drawdown_p95
                   FROM montecarlo_runs ORDER BY created_at DESC"""
            )
            montecarlo_runs = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return {"backtests": [], "walkforward_runs": [], "montecarlo_runs": []}

    return {"backtests": backtests, "walkforward_runs": walkforward_runs, "montecarlo_runs": montecarlo_runs}


async def summarize() -> str:
    """Plain-text snapshot for the Trading Division Agent's system prompt
    -- same style as alpha_mode_db.summarize(). An honest "nothing yet"
    is a real, expected answer right now, not an error state."""
    snapshot = await dashboard_snapshot()
    if not snapshot["backtests"] and not snapshot["walkforward_runs"] and not snapshot["montecarlo_runs"]:
        return "No backtest, walk-forward, or Monte Carlo runs recorded yet — the trading robot is still in early development (its own README calls itself \"Phase 1: Scaffolding\")."

    lines: list[str] = []
    if snapshot["backtests"]:
        lines.append(f"Backtests ({len(snapshot['backtests'])} run(s)):")
        for r in snapshot["backtests"]:
            lines.append(
                f"  - Run {r['run_id']} ({r['symbol']}, {r['entry_timeframe']}): "
                f"{r['total_trades']} trades, {r['win_rate_pct']:.1f}% win rate, "
                f"profit factor {r['profit_factor']:.2f}, max drawdown {r['max_drawdown_pct']:.1f}%, "
                f"total P&L {r['total_pnl']:.2f}"
            )
    if snapshot["walkforward_runs"]:
        lines.append(f"Walk-forward runs ({len(snapshot['walkforward_runs'])}):")
        for r in snapshot["walkforward_runs"]:
            lines.append(f"  - Run {r['run_id']} ({r['symbol']}, {r['entry_timeframe']}): {r['total_trades']} trades")
    else:
        lines.append("No walk-forward runs yet.")
    if snapshot["montecarlo_runs"]:
        lines.append(f"Monte Carlo runs ({len(snapshot['montecarlo_runs'])}):")
        for r in snapshot["montecarlo_runs"]:
            lines.append(
                f"  - Run {r['run_id']}: {r['num_simulations']} simulations, "
                f"{r['probability_of_ruin_pct']:.2f}% probability of ruin"
            )
    else:
        lines.append("No Monte Carlo runs yet.")
    return "\n".join(lines)
