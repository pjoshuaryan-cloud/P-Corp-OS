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

from app.finance import get_hf_markets_live_status_for_dashboard
from app.market_movers import NOTABLE_MOVE_THRESHOLD_PCT, check_stock_movers

DB_PATH = Path.home() / "Desktop" / "AMM - APP" / "research" / "data" / "research.sqlite"


def _read_only_uri() -> str:
    return f"file:{DB_PATH}?mode=ro"


async def _history_snapshot() -> dict:
    """The original dashboard_snapshot() body, unchanged -- split out
    (2026-09-18) so summarize() (called on every single turn via
    build_trading_division_block()) keeps reading only the cheap local
    SQLite history, not the live account/stock-movers fetches
    dashboard_snapshot() below now also does. Same "don't fetch live
    data speculatively on every turn" discipline email_tools.py already
    documents for its own list/search tools."""
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


async def dashboard_snapshot(postgres_conn=None) -> dict:
    """Backs the desktop/iOS Trading Division tab specifically -- unlike
    summarize() below (every turn's system prompt), a dashboard fetch is
    a deliberate, one-off "show me the tab" action, so the extra live
    calls here are the right cost/freshness tradeoff in a way they
    wouldn't be per-turn.

    live_account/stock_movers (2026-09-18) -- real gap found live: Josh
    asked for these via chat, got them, then looked at the actual
    dashboard tab and found nothing new there -- the chat-only delivery
    wasn't the full ask. Both reuse the exact same functions the chat
    agent already calls (live_account_summary/check_stock_movers below),
    just returning their raw structured data here instead of the
    plain-text version built for a system prompt."""
    history = await _history_snapshot()
    live_account = await get_hf_markets_live_status_for_dashboard(postgres_conn)
    stock_movers = await check_stock_movers(postgres_conn)
    return {**history, "live_account": live_account, "stock_movers": stock_movers}


async def summarize() -> str:
    """Plain-text snapshot for the Trading Division Agent's system prompt
    -- same style as alpha_mode_db.summarize(). An honest "nothing yet"
    is a real, expected answer right now, not an error state."""
    snapshot = await _history_snapshot()
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


async def live_account_summary(postgres_conn=None) -> str:
    """Real, deliberate extension of this module's own read-only-history
    boundary (2026-09-18) -- Josh asked directly for "how my open trades
    are doing." Confirmed which of two real things he meant first: an
    account-level summary (this) vs. a per-position breakdown (would need
    new code in the actual MT5 EA itself, a bigger lift touching the
    trading robot's own source, out of scope here). He chose the
    account-level summary.

    Deliberately account-level only, not per-position -- reuses
    finance.py's existing get_hf_markets_live_status_for_dashboard()
    (the same live balance/equity/floating-P&L bridge Finance's own
    dashboard already shows) rather than a new data source. No new
    write path, no deeper hook into the EA -- this is Trading Division
    surfacing data that already exists and already flows through this
    same shared Postgres, not a new capability being invented."""
    status = await get_hf_markets_live_status_for_dashboard(postgres_conn)
    if status is None:
        return "No live account data available right now -- the Mac may be asleep/closed, or the EA isn't running."
    direction = "profit" if status["floating_pnl"] >= 0 else "loss"
    return (
        f"Live account: balance {status['currency']} {status['balance']:,.2f}, "
        f"equity {status['currency']} {status['equity']:,.2f}, "
        f"floating {direction} of {status['currency']} {abs(status['floating_pnl']):,.2f} "
        f"(as of {status['updated_at']})."
    )


async def stock_movers_summary(postgres_conn=None) -> str:
    """Plain-text formatting of check_stock_movers' factual, non-advisory
    screener results (market_movers.py) -- backs Trading Division's
    "stocks doing well" report. Never names a recommendation, only
    objective price-movement facts, same framing check_market_movers
    already documents for the Triggers digest."""
    movers = await check_stock_movers(postgres_conn)
    if not movers:
        return f"No individual stock moved more than the {NOTABLE_MOVE_THRESHOLD_PCT:.0f}% notable-move threshold in the last day."
    lines = [f"Stocks that moved more than {NOTABLE_MOVE_THRESHOLD_PCT:.0f}% in the last day:"]
    for item in movers:
        lines.append(f"  - {item['title']} ({item['detail']})")
    return "\n".join(lines)


async def build_trading_division_block() -> str:
    """Real gap found live (2026-09-03, P Corp OS systems audit): every
    other business area (Alpha Mode, Joshx, Finance, Personal, Operations,
    People) gets its summarize() folded into Frank's own system prompt
    every turn, via main.py's build_*_block() concatenation -- Trading
    Division never did, despite summarize() above being written with
    exactly that in mind from the start ("for the Trading Division Agent's
    system prompt"). The practical effect: Frank had zero baseline
    awareness the trading robot even existed unless he happened to already
    know to call consult_trading_division_agent -- a broad "how's the
    business doing" could silently skip the one thing Joshua's own Mission
    Status card names as his top priority ("Finish trading robot V1
    ASAP"). Same shape as build_alpha_mode_block() -- no new formatting
    convention introduced."""
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## Trading Division — current research snapshot\n{snapshot}"
