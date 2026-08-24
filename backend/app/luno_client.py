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
