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

from datetime import date, datetime, timezone

from app.coingecko_client import fetch_xstock_zar_prices
from app.finance_db import (
    dashboard_snapshot,
    get_hf_markets_schedule,
    get_luno_schedule,
    log_balance,
    mark_hf_markets_snapshotted,
    mark_luno_snapshotted,
)
from app.hf_markets_client import read_balance as read_hf_markets_balance
from app.luno_client import fetch_balances, fetch_zar_prices


async def _fetch_luno_asset_totals() -> dict[str, float] | None:
    """Shared by the daily snapshot writer below and `live_finance_dashboard`
    -- both need the exact same real thing discovered live (2026-08-24,
    first real test against Josh's actual account): Luno splits each asset
    across multiple sub-accounts -- Transactional, Staking, Bundle, Earn,
    Prediction -- so one asset like ADA can appear as three separate
    balance entries (e.g. 0, 0, 11.004303) in the same API response.
    Summed by asset first so callers get exactly one honest total per
    asset: the true amount Josh holds across every Luno sub-account, not
    an arbitrary one of them. Returns None (not {}) on a fetch failure,
    so callers can distinguish "Luno unreachable right now" from
    "genuinely holds nothing" -- fail-soft, matching every other external
    integration in this codebase."""
    balances = await fetch_balances()
    if not balances:
        return None
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
    return totals


async def maybe_snapshot_luno(postgres_conn=None) -> None:
    """Runs at most once per calendar day. Records one balance_snapshots
    row per non-zero asset Luno reports (ZAR cash, XBT, ETH, etc.) --
    purely historical record-keeping (trend math, the daily digest), not
    what the Finance tab actually displays as "current" holdings anymore;
    see `live_finance_dashboard` below for why that distinction is real."""
    schedule = await get_luno_schedule(postgres_conn)
    today = date.today().isoformat()
    if schedule["last_snapshot_date"] == today:
        return

    totals = await _fetch_luno_asset_totals()
    if not totals:
        return

    for asset, amount in totals.items():
        if amount == 0:
            continue
        await log_balance("Luno", amount, asset=asset, notes="auto", postgres_conn=postgres_conn)

    await mark_luno_snapshotted(today, postgres_conn)


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
    # Per-asset ZAR value (2026-09-06, systems audit §4's concentration
    # metric) -- additive only, existing keys/callers untouched. Lets
    # compute_concentration_metrics() below report "which Luno asset is
    # biggest" without a second, duplicate pricing pass.
    per_asset_zar_value: dict[str, float] = {}
    for holding in holdings:
        asset = holding["asset"]
        balance = holding["balance"]
        if asset == "ZAR":
            total += balance
            priced_assets.append(asset)
            per_asset_zar_value[asset] = balance
            continue
        price = prices.get(asset)
        if price is None:
            unpriced_assets.append(asset)
            continue
        value = balance * price
        total += value
        priced_assets.append(asset)
        per_asset_zar_value[asset] = value
    return {
        "estimated_zar_value": total,
        "priced_assets": priced_assets,
        "unpriced_assets": unpriced_assets,
        "per_asset_zar_value": per_asset_zar_value,
    }


# The four genuinely ZAR-denominated accounts -- Luno can also hold real
# ZAR cash alongside its crypto/tokenized-asset positions, but that
# balance is already covered by the Luno-holdings concentration view
# below; including it here too would double-count the same rand.
_ZAR_ACCOUNT_NAMES = {"Liberty Stash", "EasyEquities", "Ashburton Stable Income Fund", "Nasdaq / Markets"}


async def live_finance_dashboard(postgres_conn=None) -> dict:
    """Real gap found live (2026-09-11): the Finance tab's Luno holdings
    only ever reflected the once-a-day, Mac-scheduler-only snapshot
    (`maybe_snapshot_luno` above) -- genuinely fine back when the Mac was
    always the one thing running this app, but wrong the moment the
    phone stopped needing the Mac on at all: a closed laptop means that
    daily tick simply never fires, and the displayed balance can
    silently drift a day or more stale (confirmed live: the real last
    snapshot was ~24h old the moment Josh reported "incorrect amounts").
    Prices were already fetched live per request (`compute_luno_zar_value`
    above); balances are now too -- the same fix applied one level up.
    The daily snapshot itself is untouched and still runs (real
    historical record for trend math and the digest); this only changes
    what's *displayed* as "right now."

    Fails soft to the last snapshot, not a broken tab, if Luno's API is
    briefly unreachable -- a slightly-stale number beats no Finance tab
    at all. Only Luno is touched; every other account (manually-logged,
    or HF Markets' own separate live-status mechanism) is untouched."""
    snapshot = await dashboard_snapshot(postgres_conn)
    luno_account = next((a for a in snapshot["accounts"] if a["name"] == "Luno"), None)
    if luno_account is None:
        return snapshot

    try:
        live_totals = await _fetch_luno_asset_totals()
    except Exception as exc:
        print(f"[finance] live Luno fetch raised: {type(exc).__name__}: {exc}")
        return snapshot
    if live_totals is None:
        return snapshot

    now = datetime.now(timezone.utc).isoformat()
    merged_holdings = []
    seen_assets: set[str] = set()
    # Existing assets first, in their existing order -- keeps the tab's
    # layout stable rather than reshuffling on every refresh. Trend is
    # now live-balance-vs-last-snapshot, the same "up/down/flat" meaning
    # as before, just compared against a fresher current value.
    for previous in luno_account["holdings"]:
        asset = previous["asset"]
        live_balance = live_totals.get(asset)
        if not live_balance:  # None (not held live) or 0 (sold out) -- drop from "current," matching
            continue          # maybe_snapshot_luno's own "don't log a zero" convention.
        trend = "flat"
        if live_balance > previous["balance"]:
            trend = "up"
        elif live_balance < previous["balance"]:
            trend = "down"
        merged_holdings.append(
            {
                "asset": asset,
                "balance": live_balance,
                "recorded_at": now,
                "trend": trend,
                "previous_balance": previous["balance"],
            }
        )
        seen_assets.add(asset)
    # Any asset Luno reports live that has no prior snapshot at all yet
    # (Josh bought something new since the last daily tick) -- shown with
    # no trend, same honest "nothing to compare against yet" shape
    # dashboard_snapshot() itself already uses for a brand-new asset.
    for asset, live_balance in live_totals.items():
        if asset in seen_assets or not live_balance:
            continue
        merged_holdings.append(
            {"asset": asset, "balance": live_balance, "recorded_at": now, "trend": "flat", "previous_balance": None}
        )
    luno_account["holdings"] = merged_holdings
    return snapshot


async def compute_concentration_metrics(postgres_conn=None) -> dict:
    """Systems audit §4's concentration metric (2026-09-06) -- two
    separate, honestly-labeled views, never merged into one number.
    finance_db.py's own dashboard_snapshot() docstring already declines a
    blended cross-currency total ("summing those into one number would
    misrepresent the real portfolio"); combining the four *real* ZAR
    balances with Luno's *estimated*, live-priced ZAR value would repeat
    that exact mistake one level up -- a real number and a market-price
    estimate presented as equally certain. Kept apart instead:

    - `zar_accounts`: the four real ZAR-denominated accounts (see
      _ZAR_ACCOUNT_NAMES above), each as a % of their own real combined
      total -- genuinely the same currency, a legitimate comparison.
    - `luno_holdings`: each Luno asset's estimated ZAR value as a % of
      Luno's own total estimate, reusing compute_luno_zar_value()'s
      per_asset_zar_value directly rather than a second pricing pass --
      stays self-contained to the one account that estimate was already
      scoped to."""
    snapshot = await live_finance_dashboard(postgres_conn)

    zar_rows = []
    for account in snapshot["accounts"]:
        if account["name"] not in _ZAR_ACCOUNT_NAMES:
            continue
        zar_holding = next((h for h in account["holdings"] if h["asset"] == "ZAR"), None)
        if zar_holding is not None:
            zar_rows.append({"account": account["name"], "balance": zar_holding["balance"]})
    zar_total = sum(r["balance"] for r in zar_rows)
    zar_accounts = [
        {
            "account": r["account"],
            "balance": r["balance"],
            "percent_of_total": (r["balance"] / zar_total) if zar_total else None,
        }
        for r in zar_rows
    ]

    luno_account = next((a for a in snapshot["accounts"] if a["name"] == "Luno"), None)
    luno_holdings: list[dict] = []
    luno_total_estimate = None
    luno_unpriced_assets: list[str] = []
    if luno_account and luno_account["holdings"]:
        luno_value = await compute_luno_zar_value(luno_account["holdings"])
        luno_total_estimate = luno_value["estimated_zar_value"]
        luno_unpriced_assets = luno_value["unpriced_assets"]
        for asset, value in luno_value["per_asset_zar_value"].items():
            luno_holdings.append(
                {
                    "asset": asset,
                    "estimated_zar_value": value,
                    "percent_of_total": (value / luno_total_estimate) if luno_total_estimate else None,
                }
            )
        luno_holdings.sort(key=lambda h: h["estimated_zar_value"], reverse=True)

    return {
        "zar_accounts": zar_accounts,
        "zar_total": zar_total,
        "luno_holdings": luno_holdings,
        "luno_total_estimate": luno_total_estimate,
        "luno_unpriced_assets": luno_unpriced_assets,
    }


async def maybe_snapshot_hf_markets(postgres_conn=None) -> None:
    """Runs at most once per calendar day, same cadence as Luno's own
    snapshot. Reads hf_markets_client.py's local file (written by
    PCorpBalanceExport.mq5 running inside Josh's real MT5 terminal) --
    no network call, no credentials, nothing that can fail except the
    file not existing yet (EA not attached/running), which this
    silently no-ops on, same fail-soft posture as the rest of Finance's
    automatic sources."""
    schedule = await get_hf_markets_schedule(postgres_conn)
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

    await log_balance("Nasdaq / Markets", amount, asset=currency, notes="auto", postgres_conn=postgres_conn)
    await mark_hf_markets_snapshotted(today, postgres_conn)


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
