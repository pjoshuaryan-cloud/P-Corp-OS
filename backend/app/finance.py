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

from app.finance_db import get_luno_schedule, log_balance, mark_luno_snapshotted
from app.luno_client import fetch_balances


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
