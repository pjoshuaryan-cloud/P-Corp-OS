"""Drives the REAL local backend for the end-to-end Premiere tests (token never printed)."""
import sys, time, json
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
import httpx
from app.auth import get_or_create_token
BASE = "http://127.0.0.1:8731"; _tok = get_or_create_token()
def call(method, path, **kw):
    params = {"token": _tok, **kw.pop("params", {})}
    r = httpx.request(method, BASE + path, params=params, timeout=kw.pop("timeout", 120), **kw)
    return r
def ok(method, path, **kw):
    r = call(method, path, **kw)
    if r.status_code >= 400: raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}
def job(job_id): return ok("GET", f"/post/jobs/{job_id}")
def wait_status(job_id, want, timeout=300, poll=2):
    t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        j = job(job_id); st = j["status"]
        if st != last: print(f"   job #{job_id}: {st}", flush=True); last = st
        if st in want: return j
        if st in ("ingest_failed", "cancelled"): raise RuntimeError(f"job #{job_id} {st}: {j.get('error_message')}")
        time.sleep(poll)
    raise RuntimeError(f"job #{job_id} didn't reach {want} in {timeout}s (at {last})")
