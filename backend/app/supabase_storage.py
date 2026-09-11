"""
Supabase Storage client for generated documents (2026-09-11, iPhone
independence pass) -- reuses the same Supabase project already configured
for Alpha Mode Media's Postgres tables (supabase_client.py), a different
API surface (Storage, not PostgREST) but the same real project and the
same service_role key, already trusted server-side per that file's own
docstring.

Real gap this closes: documents.py's generate_pdf_document() writes to
local disk (backend/data/generated_documents/), and GET /documents/
{filename} reads it back from the same local disk -- fine on the
always-on Mac, but a real (previously silent) landmine on a stateless
cloud container: a redeploy wipes it, and a second instance would 404 on
a file it never wrote. Bucket is private (not public) -- access always
goes through this backend's own Depends(verify_token)-gated route, never
a public Supabase URL.
"""

import os
import time

import httpx

BUCKET = "pcorp-documents"


def _object_url(filename: str) -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + f"/storage/v1/object/{BUCKET}/{filename}"


def _headers(content_type: str | None = None) -> dict:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def upload_document(filename: str, content: bytes) -> None:
    """Uploads (or overwrites, via upsert) the given bytes under `filename`
    in the shared bucket. Raises on any real failure -- same "fail loud on
    the file itself" discipline documents.py's own docstring already
    commits to; a silent failure here would mean a document Frank told
    Josh was saved is actually nowhere either backend can find it."""
    headers = _headers("application/pdf")
    headers["x-upsert"] = "true"
    async with httpx.AsyncClient() as client:
        resp = await client.post(_object_url(filename), headers=headers, content=content, timeout=30.0)
        resp.raise_for_status()


async def download_document(filename: str) -> bytes | None:
    """Returns the raw bytes, or None if no object exists under this name
    (a real "not found", not swallowed into an empty-bytes false success)
    -- caller decides what "not found" means (main.py's route falls back
    to checking local disk, for documents generated before this existed).

    Real API quirk found live, not assumed from documentation: a missing
    object's outer HTTP status is 400, not 404 -- the real "not found"
    signal is nested in the JSON body instead
    ({"statusCode":"404","error":"not_found","code":"NoSuchKey"}).
    Checked explicitly rather than trusting the outer status code alone.

    A second real quirk found live: Supabase's edge CDN (Cloudflare, its
    own "smart CDN" feature) can keep serving a stale cached response for
    an exact URL even after a genuine overwrite -- confirmed directly:
    re-uploading to the same filename returned 200 with a new object Id
    each time, but a same-URL GET kept returning the ORIGINAL bytes
    indefinitely, while adding any cache-busting query param immediately
    returned the correct, current content. A `_cb` param is added to
    every request here rather than relying on the origin's own
    `cache-control: no-cache` header, which the edge cache demonstrably
    doesn't honor for this endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _object_url(filename), headers=_headers(), params={"_cb": str(time.time())}, timeout=30.0
        )
        if resp.status_code == 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("statusCode") == "404" or body.get("code") == "NoSuchKey":
                return None
        resp.raise_for_status()
        return resp.content
