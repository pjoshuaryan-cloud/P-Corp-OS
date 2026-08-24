"""
Real ZAR pricing for Luno's tokenized xStock holdings (AAPLx, SPYx, QQQx,
TQQQx, GLDx, VTIx) -- 2026-08-24. Luno's own public price feed has no
data for these at all (confirmed live against all 145 of Luno's real
trading pairs before writing luno_client.py's fetch_zar_prices()), but
xStocks are a shared tokenization standard (Backed's xStocks, also
listed on Kraken) that CoinGecko tracks independently with real live
USD/ZAR pricing -- confirmed live against CoinGecko's own public search
API for exactly Josh's real holdings before writing this. Free, public,
no API key needed, same "read-only, no credential to manage" shape as
Luno's own public tickers endpoint.
"""

import time

import httpx

COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# Luno asset code -> CoinGecko coin id, confirmed live against
# CoinGecko's search API (2026-08-24) for exactly the xStock holdings
# Josh actually has on Luno. A deliberate, checked mapping -- extend it
# the same way (confirm the real coin id first) if new xStock holdings
# show up, don't guess at a pattern.
_ASSET_TO_COINGECKO_ID = {
    "AAPLX": "apple-xstock",
    "SPYX": "sp500-xstock",
    "QQQX": "nasdaq-xstock",
    "TQQQX": "tqqq-xstock",
    "GLDX": "gold-xstock",
    "VTIX": "vanguard-xstock",
}

# Real bug found live (2026-08-24): fetching fresh on every single
# GET /finance/dashboard call meant one transient CoinGecko hiccup (a
# free-tier rate limit brush, a slow response, anything) instantly made
# 6 real assets vanish from Josh's Luno total for that entire page load
# -- confirmed live (the exact same call succeeded on retry moments
# later). A personal portfolio doesn't need sub-5-minute price
# freshness, so a short cache absorbs normal fluctuation; more
# importantly, on a failed refresh this falls back to the last known-
# good prices instead of returning nothing, so a transient failure
# degrades to "slightly stale" rather than "silently missing."
_CACHE_TTL_SECONDS = 300
_cache: dict[str, float] = {}
_cache_time: float = 0.0


async def fetch_xstock_zar_prices() -> dict[str, float]:
    global _cache, _cache_time
    if _cache and (time.monotonic() - _cache_time) < _CACHE_TTL_SECONDS:
        return _cache

    ids = ",".join(_ASSET_TO_COINGECKO_ID.values())
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(COINGECKO_PRICE_URL, params={"ids": ids, "vs_currencies": "zar"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        # Fall back to the last known-good prices, even if stale,
        # rather than an empty dict -- see module comment above.
        return _cache

    prices: dict[str, float] = {}
    for asset, coin_id in _ASSET_TO_COINGECKO_ID.items():
        zar = data.get(coin_id, {}).get("zar")
        if zar is not None:
            prices[asset] = float(zar)

    if prices:
        _cache = prices
        _cache_time = time.monotonic()
    return prices or _cache
