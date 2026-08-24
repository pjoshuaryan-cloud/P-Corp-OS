"""
"Market movers" -- the Triggers Layer's rule for Josh's "always look for
lucrative investment opportunities" ask (2026-08-25). Deliberately
scoped and named to stay on the safe side of a real line: this app is
built to never give personalized investment advice (a standing rule for
every domain here, not new to this one). What it actually does is a
"biggest movers" screener -- the same category of feature as a stock
screener's "today's gainers" list or CoinMarketCap's trending page,
purely OBJECTIVE price-movement facts over a real, bounded universe.

It never says "opportunity," "buy," "consider," or anything implying a
recommendation or suitability judgment -- only "X moved Y% since Z,"
which Josh evaluates himself. Confirmed with Josh directly (2026-08-24)
that the scope should include assets outside his current holdings, not
just what he already owns -- accepted specifically because the content
stays factual regardless of scope; a fact about an asset he doesn't own
is exactly as much "not advice" as a fact about one he does.

Universe, deliberately bounded rather than an unbounded market scan: all
26 assets Luno quotes directly against ZAR, plus the 25 xStock products
CoinGecko tracks (a real, checked list -- see coingecko_client.py). Both
are sources this app already has real, live, working access to; nothing
here is a new data source invented for this feature.

Price history lives in triggers_db.py's market_price_snapshots table
(not finance_db.py -- a market price isn't tied to any Finance account).
Snapshotted once a day via the same shared scheduler tick as Luno/HF
Markets' own balance snapshots. "Notable move" is a flat day-over-day
percent threshold, hardcoded here (not a configurable trigger_rules
column) -- same pattern as every other threshold-less rule_type.
"""

from datetime import date

from app.coingecko_client import fetch_all_xstock_zar_prices
from app.luno_client import fetch_zar_prices
from app.triggers_db import (
    get_market_movers_schedule,
    get_price_change,
    mark_market_movers_snapshotted,
    record_price_snapshots,
)

NOTABLE_MOVE_THRESHOLD_PCT = 10.0
LOOKBACK_DAYS = 1


async def maybe_snapshot_market_prices() -> None:
    """Runs at most once per calendar day, same cadence as Luno/HF
    Markets' own snapshots. Records today's price for every asset in the
    tracked universe, so tomorrow's check has something real to compare
    against."""
    schedule = await get_market_movers_schedule()
    today = date.today().isoformat()
    if schedule["last_snapshot_date"] == today:
        return

    luno_prices = await fetch_zar_prices()
    xstock_prices = await fetch_all_xstock_zar_prices()
    combined = {**luno_prices, **xstock_prices}
    if not combined:
        return

    await record_price_snapshots(combined)
    await mark_market_movers_snapshotted(today)


async def check_market_movers(threshold_days: int | None) -> list[dict]:
    """Trigger rule checker (registered in triggers.py's RULE_CHECKERS).
    `threshold_days` is unused -- kept only to match every other
    checker's call signature (RULE_CHECKERS.get(rule_type)(threshold)).

    item_key includes today's date, not just the asset -- a market move
    is a today-specific fact, not a persistent condition like an overdue
    invoice, so there's nothing to decay/resurface on day 3/7 the way
    the Triggers Layer's cadence does for other rules. Each day's move
    for a given asset is simply a new, distinct item; the existing
    dedup logic already handles "first sighting = always due" correctly
    for that shape, no special-casing needed."""
    luno_prices = await fetch_zar_prices()
    xstock_prices = await fetch_all_xstock_zar_prices()
    universe = sorted({**luno_prices, **xstock_prices}.keys())

    today = date.today().isoformat()
    items: list[dict] = []
    for asset in universe:
        change = await get_price_change(asset, LOOKBACK_DAYS)
        if change is None or change["previous_price"] == 0:
            continue
        pct = (change["current_price"] - change["previous_price"]) / change["previous_price"] * 100
        if abs(pct) < NOTABLE_MOVE_THRESHOLD_PCT:
            continue
        direction = "up" if pct > 0 else "down"
        items.append(
            {
                "item_key": f"market_mover:{asset}:{today}",
                "title": f"{asset} {direction} {abs(pct):.1f}%",
                "detail": (
                    f"R{change['current_price']:,.2f}, was R{change['previous_price']:,.2f} "
                    f"{LOOKBACK_DAYS}d ago"
                ),
            }
        )
    return items
