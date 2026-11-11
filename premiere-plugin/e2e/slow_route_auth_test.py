"""A device sign-in (his iPhone's) on a slow route (2026-11-11). Slow routes like Scan Now get no database connection from the middleware,
so verify_token used to check a device token against the empty local SQLite file and refuse it. Now it borrows a connection for just
that lookup. A fake pool and fake session checks only: no real token, database or Claude call.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python slow_route_auth_test.py"""
import asyncio
import contextlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi import HTTPException  # noqa: E402
from app import main  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


class FakePool:
    def __init__(self):
        self.checkouts = 0
        self.open = 0

    @contextlib.asynccontextmanager
    async def connection(self):
        self.checkouts += 1
        self.open += 1
        try:
            yield "pooled-conn"
        finally:
            self.open -= 1


seen = []


async def fake_verify(token, conn):
    seen.append((token, conn))
    return token == "phone-device-token" and conn == "pooled-conn"


async def allowed(token, request):
    try:
        await main.verify_token(token, request)
        return True
    except HTTPException as e:
        return e.status_code


real_verify, real_backend, real_token = main.verify_device_session, main.DATA_BACKEND, main.AUTH_TOKEN
pool = FakePool()
main.verify_device_session = fake_verify
main.DATA_BACKEND = "postgres"
main.AUTH_TOKEN = "made-up-main-token"
main.app.state.postgres_pool = pool
try:
    slow = SimpleNamespace(state=SimpleNamespace())  # what a slow route's request looks like: no connection on it
    check("the phone's device token now works on a slow route", asyncio.run(allowed("phone-device-token", slow)) is True)
    check("checked against the shared database, not the local file", seen[-1] == ("phone-device-token", "pooled-conn"))
    check("using one borrowed connection, already given back", pool.checkouts == 1 and pool.open == 0)
    check("a made-up token is still refused there", asyncio.run(allowed("made-up", slow)) == 403)
    check("and its connection is given back too", pool.open == 0)
    before = pool.checkouts
    check("the main token needs no database at all", asyncio.run(allowed("made-up-main-token", slow)) is True and pool.checkouts == before)
    fast = SimpleNamespace(state=SimpleNamespace(postgres_conn="pooled-conn"))  # a normal route already has one
    before = pool.checkouts
    check("a normal route still uses the connection it already has", asyncio.run(allowed("phone-device-token", fast)) is True and pool.checkouts == before)
    main.DATA_BACKEND = "sqlite"
    seen.clear()
    asyncio.run(allowed("phone-device-token", slow))
    check("on the Mac's own SQLite setup nothing changes", seen == [("phone-device-token", None)] and pool.checkouts == before)
finally:
    main.verify_device_session, main.DATA_BACKEND, main.AUTH_TOKEN = real_verify, real_backend, real_token
    del main.app.state.postgres_pool

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
