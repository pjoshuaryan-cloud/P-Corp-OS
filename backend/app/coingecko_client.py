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


async def fetch_xstock_zar_prices() -> dict[str, float]:
    """Fails soft (empty dict) on any error -- same posture as
    luno_client.py's external-call handling. A failure here just means
    compute_luno_zar_value() reports those assets as unpriced rather
    than the dashboard breaking."""
    ids = ",".join(_ASSET_TO_COINGECKO_ID.values())
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(COINGECKO_PRICE_URL, params={"ids": ids, "vs_currencies": "zar"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return {}
    prices: dict[str, float] = {}
    for asset, coin_id in _ASSET_TO_COINGECKO_ID.items():
        zar = data.get(coin_id, {}).get("zar")
        if zar is not None:
            prices[asset] = float(zar)
    return prices
