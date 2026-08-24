"""
Real ZAR pricing for Luno's tokenized xStock products -- 2026-08-24.
Luno's own public price feed has no data for these at all (confirmed
live against all 145 of Luno's real trading pairs before writing
luno_client.py's fetch_zar_prices()), but xStocks are a shared
tokenization standard (Backed's xStocks, also listed on Kraken) that
CoinGecko tracks independently with real live USD/ZAR pricing. Free,
public, no API key needed, same "read-only, no credential to manage"
shape as Luno's own public tickers endpoint.

Two id maps: `_ASSET_TO_COINGECKO_ID` covers just Josh's real xStock
holdings (Finance's Luno total, finance.py's compute_luno_zar_value());
`_ALL_XSTOCK_IDS` is the full known xStock universe (confirmed live
against CoinGecko's own search API, 2026-08-24) -- market_movers.py's
"biggest movers" screener over the whole tracked universe, not just what
Josh already owns, deliberately keeps this to a real, bounded, checked
list rather than an unbounded market scan.
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

# The full xStock universe CoinGecko tracks, confirmed live (2026-08-24)
# against its own search API -- every one of these ids was verified to
# exist before being hardcoded here, same discipline as the holdings-only
# map above. Includes Josh's own holdings plus everything else on the
# same tokenization standard.
_ALL_XSTOCK_IDS = {
    "STRCX": "strategy-pp-variable-xstock",
    "BSPX": "bending-spoons-xstock",
    "CRCLX": "circle-xstock",
    "TSLAX": "tesla-xstock",
    "MSTRX": "microstrategy-xstock",
    "SPYX": "sp500-xstock",
    "SPCXX": "spacex-xstocks",
    "GOOGLX": "alphabet-xstock",
    "NVDAX": "nvidia-xstock",
    "QQQX": "nasdaq-xstock",
    "AAPLX": "apple-xstock",
    "COINX": "coinbase-xstock",
    "SNDKX": "sandisk-corporation-xstock",
    "INTCX": "intel-xstock",
    "GLDX": "gold-xstock",
    "HOODX": "robinhood-xstock",
    "SKHYX": "sk-hynix-xstock",
    "METAX": "meta-xstock",
    "AMZNX": "amazon-xstock",
    "MSFTX": "microsoft-xstock",
    "MRVLX": "marvell-xstock",
    "AMDX": "amd-xstock",
    "TQQQX": "tqqq-xstock",
    "AVGOX": "broadcom-xstock",
    "TSMX": "tsmc-xstock",
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
_holdings_cache: dict = {"prices": {}, "time": 0.0}
_universe_cache: dict = {"prices": {}, "time": 0.0}


async def _fetch(id_map: dict[str, str], cache_state: dict) -> dict[str, float]:
    if cache_state["prices"] and (time.monotonic() - cache_state["time"]) < _CACHE_TTL_SECONDS:
        return cache_state["prices"]

    ids = ",".join(id_map.values())
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(COINGECKO_PRICE_URL, params={"ids": ids, "vs_currencies": "zar"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        # Fall back to the last known-good prices, even if stale,
        # rather than an empty dict -- see module comment above.
        return cache_state["prices"]

    prices: dict[str, float] = {}
    for asset, coin_id in id_map.items():
        zar = data.get(coin_id, {}).get("zar")
        if zar is not None:
            prices[asset] = float(zar)

    if prices:
        cache_state["prices"] = prices
        cache_state["time"] = time.monotonic()
    return prices or cache_state["prices"]


async def fetch_xstock_zar_prices() -> dict[str, float]:
    """Just Josh's real xStock holdings -- backs Finance's Luno total."""
    return await _fetch(_ASSET_TO_COINGECKO_ID, _holdings_cache)


async def fetch_all_xstock_zar_prices() -> dict[str, float]:
    """The full tracked xStock universe -- backs market_movers.py's
    biggest-movers screener."""
    return await _fetch(_ALL_XSTOCK_IDS, _universe_cache)
