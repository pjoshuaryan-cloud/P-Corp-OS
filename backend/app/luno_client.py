"""
Read-only Luno balance fetch (2026-08-21) -- the one Finance account with
a real official API. Auth is a scoped, revocable API key ID/secret pair
Josh generates himself in Luno's own settings (Settings -> API Keys),
restricted to read-only balance permission -- not his account password,
same category of credential as ANTHROPIC_API_KEY/SUPABASE_SERVICE_ROLE_KEY
already stored in .env, not the kind of login this app avoids handling.

Uses HTTP Basic Auth (key ID as username, key secret as password) against
GET https://api.luno.com/api/1/balance, matching Luno's documented REST
API. Fails soft (empty list) on any error -- missing/invalid credentials,
network issues, API changes -- same reasoning as alpha_mode_supabase.py's
external-call handling: one bad request here shouldn't break Finance's
whole dashboard, and the daily snapshot job just skips a day rather than
crashing the scheduler.
"""

import os

import httpx

LUNO_API_URL = "https://api.luno.com/api/1/balance"
LUNO_TICKERS_URL = "https://api.luno.com/api/1/tickers"


async def fetch_balances() -> list[dict]:
    key_id = os.environ.get("LUNO_API_KEY_ID")
    key_secret = os.environ.get("LUNO_API_KEY_SECRET")
    if not key_id or not key_secret:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(LUNO_API_URL, auth=(key_id, key_secret))
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []
    return data.get("balance", [])


async def fetch_zar_prices() -> dict[str, float]:
    """Real total-value support (2026-08-24): Josh asked why his Luno
    balance didn't show an overall figure -- a naive sum across mismatched
    assets (0.000071 XBT + 11.004303 ADA + ...) would be meaningless, but
    a real ZAR value computed from live market prices is legitimate, not
    fabrication. This is Luno's public `/tickers` endpoint -- no auth
    needed, unlike fetch_balances(), since prices aren't account-specific.

    Covers assets Luno quotes directly against ZAR (the crypto majors:
    XBT, ETH, ADA, SOL, XRP, DOT, AVAX, ATOM, USDC, etc.), plus a real
    cross-rate conversion (asset/USDT price times Luno's own USDTZAR
    rate) for the couple of assets Josh actually holds that Luno only
    quotes against USDT -- BNB and PAXG (confirmed live: no BNBZAR/
    PAXGZAR pair exists, but BNBUSDT/PAXGUSDT do). This is one extra
    real multiplication using Luno's own live numbers, not a guess.
    Luno's newer tokenized-stock products (AAPLx, SPYx, QQQx, TQQQx,
    VTIx, GLDx) have no price here at all, direct or via USDT -- see
    coingecko_client.py for how those get priced instead. Callers
    (finance.py's compute_luno_zar_value) are responsible for reporting
    whatever's still unpriced rather than treating it as worth zero.
    Fails soft (empty dict) on any error, same posture as fetch_balances()."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(LUNO_TICKERS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return {}

    prices: dict[str, float] = {}
    usdt_prices: dict[str, float] = {}
    usdt_zar_rate: float | None = None
    for ticker in data.get("tickers", []):
        pair = ticker.get("pair", "")
        if ticker.get("status") != "ACTIVE":
            continue
        try:
            last_trade = float(ticker["last_trade"])
        except (KeyError, TypeError, ValueError):
            continue
        if pair == "USDTZAR":
            # Checked before the generic ZAR-pair branch below, which
            # would otherwise also match "USDTZAR" (it does end with
            # "ZAR") and record it as a plain asset price -- real bug
            # caught live (2026-08-24): that ordering meant this branch
            # was unreachable and usdt_zar_rate stayed None forever, so
            # the BNB/PAXG cross-conversion below silently never ran.
            usdt_zar_rate = last_trade
        elif pair.endswith("ZAR"):
            prices[pair[: -len("ZAR")]] = last_trade
        elif pair.endswith("USDT"):
            usdt_prices[pair[: -len("USDT")]] = last_trade

    if usdt_zar_rate is not None:
        for asset in ("BNB", "PAXG"):
            if asset not in prices and asset in usdt_prices:
                prices[asset] = usdt_prices[asset] * usdt_zar_rate

    return prices
