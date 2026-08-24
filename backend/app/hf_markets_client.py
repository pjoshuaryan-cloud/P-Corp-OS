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

BALANCE_FILE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "net.metaquotes.wine.metatrader5"
    / "drive_c"
    / "Program Files"
    / "MetaTrader 5"
    / "MQL5"
    / "Files"
    / "pcorp_balance.json"
)


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
