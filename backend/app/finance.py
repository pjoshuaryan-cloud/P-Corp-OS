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
    row per non-zero asset Luno reports (ZAR cash, XBT, ETH, etc. --
    however many accounts/assets are genuinely there), never a fabricated
    single total. If LUNO_API_KEY_ID/SECRET aren't set, fetch_balances()
    returns an empty list and this silently does nothing -- same
    fail-soft posture as the rest of Finance's external-data handling."""
    schedule = await get_luno_schedule()
    today = date.today().isoformat()
    if schedule["last_snapshot_date"] == today:
        return

    balances = await fetch_balances()
    if not balances:
        return

    for entry in balances:
        asset = entry.get("asset")
        balance = entry.get("balance")
        if not asset or balance is None:
            continue
        try:
            amount = float(balance)
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue
        await log_balance("Luno", amount, asset=asset, notes="auto")

    await mark_luno_snapshotted(today)
