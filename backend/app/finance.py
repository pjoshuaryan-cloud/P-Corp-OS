"""
Finance's daily Luno auto-snapshot (2026-08-21) -- mirrors triggers.py's
own split from triggers_db.py: finance_db.py is pure persistence, this
is the part that actually decides when to act. Reuses the Triggers
Layer's existing scheduler loop (main.py's _trigger_scheduler_loop, a
15-minute asyncio tick) rather than starting a second background loop
for one more daily job -- consistent with this codebase's own restraint
principle (alpha_mode_db.py's docstring: "added complexity should wait
until real usage actually calls for it").
"""

from datetime import date

from app.coingecko_client import fetch_xstock_zar_prices
from app.finance_db import (
    get_hf_markets_schedule,
    get_luno_schedule,
    log_balance,
    mark_hf_markets_snapshotted,
    mark_luno_snapshotted,
)
from app.hf_markets_client import read_balance as read_hf_markets_balance
from app.luno_client import fetch_balances, fetch_zar_prices


async def maybe_snapshot_luno() -> None:
    """Runs at most once per calendar day. Records one balance_snapshots
    row per non-zero asset Luno reports (ZAR cash, XBT, ETH, etc.).

    Real thing discovered live (2026-08-24, first real test against
    Josh's actual account): Luno splits each asset across multiple
    sub-accounts -- Transactional, Staking, Bundle, Earn, Prediction --
    so one asset like ADA can appear as three separate balance entries
    (e.g. 0, 0, 11.004303) in the same API response. Logging each one as
    its own snapshot would corrupt the trend math in finance_db.py's
    dashboard_snapshot() (which only looks at the two most recent rows
    per asset) -- whichever sub-account happened to be inserted last
    would silently become "the" balance, and the others would vanish
    from the trend entirely. Summed by asset first so each asset gets
    exactly one honest snapshot per day: the true total Josh holds in
    that asset across every Luno sub-account, not an arbitrary one of
    them."""
    schedule = await get_luno_schedule()
    today = date.today().isoformat()
    if schedule["last_snapshot_date"] == today:
        return

    balances = await fetch_balances()
    if not balances:
        return

    totals: dict[str, float] = {}
    for entry in balances:
        asset = entry.get("asset")
        balance = entry.get("balance")
        if not asset or balance is None:
            continue
        try:
            amount = float(balance)
        except (TypeError, ValueError):
            continue
        totals[asset] = totals.get(asset, 0.0) + amount

    for asset, amount in totals.items():
        if amount == 0:
            continue
        await log_balance("Luno", amount, asset=asset, notes="auto")

    await mark_luno_snapshotted(today)


async def compute_luno_zar_value(holdings: list[dict]) -> dict:
    """Real overall Luno value in rand, requested live (2026-08-24) after
    Josh noticed the Finance tab only showed per-asset lines. `holdings`
    is the Luno account's own `holdings` list from finance_db.py's
    dashboard_snapshot(). Priced live against Luno's own public price
    feed (luno_client.fetch_zar_prices()) at request time, not stored --
    a snapshotted value would go stale the moment the market moves,
    unlike the balance itself which only needs a daily refresh.

    Combines two real price sources: Luno's own feed (direct ZAR pairs
    plus a USDT cross-rate for BNB/PAXG) and CoinGecko's public pricing
    for Luno's tokenized xStock products (AAPLx, SPYx, QQQx, TQQQx,
    VTIx, GLDx), which have no price anywhere on Luno itself -- found
    live (2026-08-24) after Josh asked why 8 of his 17 assets were
    excluded from the first version of this total. Luno's own price
    wins if an asset were ever quoted by both (never happens today, but
    the real venue's price is more authoritative than an index's).
    Still reports `unpriced_assets` rather than silently excluding
    anything a price genuinely can't be found for -- the same "never
    fabricate, never silently omit" discipline as everywhere else in
    this app."""
    xstock_prices = await fetch_xstock_zar_prices()
    luno_prices = await fetch_zar_prices()
    prices = {**xstock_prices, **luno_prices}
    total = 0.0
    priced_assets: list[str] = []
    unpriced_assets: list[str] = []
    for holding in holdings:
        asset = holding["asset"]
        balance = holding["balance"]
        if asset == "ZAR":
            total += balance
            priced_assets.append(asset)
            continue
        price = prices.get(asset)
        if price is None:
            unpriced_assets.append(asset)
            continue
        total += balance * price
        priced_assets.append(asset)
    return {
        "estimated_zar_value": total,
        "priced_assets": priced_assets,
        "unpriced_assets": unpriced_assets,
    }


async def maybe_snapshot_hf_markets() -> None:
    """Runs at most once per calendar day, same cadence as Luno's own
    snapshot. Reads hf_markets_client.py's local file (written by
    PCorpBalanceExport.mq5 running inside Josh's real MT5 terminal) --
    no network call, no credentials, nothing that can fail except the
    file not existing yet (EA not attached/running), which this
    silently no-ops on, same fail-soft posture as the rest of Finance's
    automatic sources."""
    schedule = await get_hf_markets_schedule()
    today = date.today().isoformat()
    if schedule["last_snapshot_date"] == today:
        return

    data = read_hf_markets_balance()
    if data is None:
        return

    balance = data.get("balance")
    currency = data.get("currency", "ZAR")
    if balance is None:
        return
    try:
        amount = float(balance)
    except (TypeError, ValueError):
        return

    await log_balance("Nasdaq / Markets", amount, asset=currency, notes="auto")
    await mark_hf_markets_snapshotted(today)


def get_hf_markets_live_status() -> dict | None:
    """Real-time equity/floating-P&L for HF Markets, requested (2026-08-24)
    after Josh wanted to see live balance during open trades rather than
    only the once-a-day snapshot. Deliberately NOT stored/snapshotted --
    reads hf_markets_client.py's file fresh on every call, same "compute
    live, don't cache a number that goes stale the moment the market
    moves" reasoning already applied to Luno's own rand-value total.
    `balance` is the settled figure (what the daily snapshot tracks);
    `equity` reflects open positions; `floating_pnl` is the difference --
    positive means currently in profit, negative means currently in
    loss. Returns None if the EA isn't running/hasn't written a file yet,
    same fail-soft posture as everything else reading this file."""
    data = read_hf_markets_balance()
    if data is None:
        return None
    balance = data.get("balance")
    equity = data.get("equity")
    if balance is None or equity is None:
        return None
    return {
        "balance": balance,
        "equity": equity,
        "floating_pnl": equity - balance,
        "currency": data.get("currency", "ZAR"),
        "updated_at": data.get("updated_at"),
    }
