"""
Thin async PostgREST client for the real Alpha Mode Media Admin Supabase
project -- lets the Alpha Mode Agent's tools write directly into the same
database the real app reads, instead of a separate local copy that can
drift out of sync (confirmed 2026-08-02, see alpha_mode_supabase.py).

Uses the service_role key (full RLS bypass) -- correct here because this
only ever runs server-side inside the trusted P Corp OS backend process,
never shipped to a client. The Electron app itself deliberately can't use
this key (only the public anon key), per that app's own README -- a
service-role key must never ship inside a renderer.
"""

import os

import httpx


def _base_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"


def _headers() -> dict:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def insert_row(table: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{_base_url()}/{table}", headers=_headers(), json=data)
        resp.raise_for_status()
        return resp.json()[0]


async def select_rows(table: str, params: dict) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_base_url()}/{table}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def update_rows(table: str, filters: dict, data: dict) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{_base_url()}/{table}", headers=_headers(), params=filters, json=data)
        resp.raise_for_status()
        return resp.json()
