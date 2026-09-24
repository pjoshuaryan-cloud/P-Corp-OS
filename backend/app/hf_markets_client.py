"""
Reads Josh's real HF Markets (MetaTrader 5) account balance from a local
file (2026-08-24) -- discovered live that MT5 (net.metaquotes.wine.
metatrader5, the official MetaQuotes Wine wrapper for Mac) already runs
locally on this same Mac, hosting his real ICT_NDX_EA trading robot. That
changes the picture entirely from the original "third-party bridge or
nothing" assessment: no need to trust an outside service like MetaApi.cloud
with his investor credentials at all.

Instead, `PCorpBalanceExport.mq5` (placed directly in this terminal's own
Experts folder) is a small, read-only Expert Advisor Josh compiles and
attaches to any chart in his own MT5 terminal. It only calls
AccountInfoDouble/AccountInfoString/AccountInfoInteger (queries) and
FileWrite, on a 60-second timer -- it never places, modifies, or closes a
trade, and runs alongside ICT_NDX_EA without touching it. This module
just reads the plain JSON file it writes. No credentials, no network
call, no third party -- the same "local file, no API needed" simplicity
as Trading Division's own read of research.sqlite.
"""

import json
from pathlib import Path
from typing import Any

MQL5_FILES_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "net.metaquotes.wine.metatrader5"
    / "drive_c"
    / "Program Files"
    / "MetaTrader 5"
    / "MQL5"
    / "Files"
)

BALANCE_FILE_PATH = MQL5_FILES_DIR / "pcorp_balance.json"

# Approval-gated trade execution bridge (2026-09-22) -- the same MQL5
# Files directory as the balance export above, now shared with
# PCorpExecutionBridge.mq5 (a separate EA, own magic number, see the plan
# doc). PENDING_ORDER is written here by the Mac-only proposal sync loop
# (main.py) only after Josh has approved a specific proposal; the bridge
# EA polls for it, validates it against real live broker state, and
# writes ORDER_RESULT back. Neither file gives the bridge any standing
# authority -- one file in, one result out, per approved trade.
PENDING_ORDER_FILE_PATH = MQL5_FILES_DIR / "pcorp_pending_order.json"
ORDER_RESULT_FILE_PATH = MQL5_FILES_DIR / "pcorp_order_result.json"


def read_balance() -> dict | None:
    """Fails soft (None) if the file doesn't exist yet (the EA hasn't
    been attached/run in MT5 yet) or is malformed -- same posture as
    every other external-data read in this app."""
    if not BALANCE_FILE_PATH.exists():
        return None
    try:
        with open(BALANCE_FILE_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_pending_order(command: dict[str, Any]) -> None:
    """Called only from the Mac (the bridge EA's polling loop can only
    ever see this Mac's own filesystem) and only after a proposal has
    already been approved -- this function itself has no approval logic
    of its own, it's a pure file write.

    Compact separators (no space after ','/':') deliberately -- MQL5 has
    no JSON library, so PCorpExecutionBridge.mq5 parses this with simple
    StringFind/StringSubstr key lookups (see its JsonGetString/
    JsonGetDouble helpers). A fixed, predictable format here is what
    makes that minimal parser reliable rather than a plain string dump."""
    MQL5_FILES_DIR.mkdir(parents=True, exist_ok=True)
    with open(PENDING_ORDER_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(command, f, separators=(",", ":"))


def read_order_result() -> dict | None:
    """Fails soft (None) if the bridge hasn't written a result yet -- the
    sync loop just keeps polling."""
    if not ORDER_RESULT_FILE_PATH.exists():
        return None
    try:
        with open(ORDER_RESULT_FILE_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_order_result() -> None:
    """Removes the consumed result file so the next proposal's result
    isn't mistaken for this one's. Safe to call even if it's already
    gone."""
    try:
        ORDER_RESULT_FILE_PATH.unlink()
    except FileNotFoundError:
        pass
