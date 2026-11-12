"""Settings' live connection check also updates the Situation Room's banner (2026-11-12). Before, a failed 15-minute check (one made
during an app rebuild) kept "Supabase disconnected" on the banner after Settings already showed it connected. Fake checks and a
made-up token only: no Gmail, Calendar or Supabase call is made.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python connected_apps_cache_test.py"""
import asyncio
import os
import sys
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import connected_apps, main, situation_room  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


state = {"supabase": False}


async def fake_status(postgres_conn=None):
    return [{"name": "Gmail", "connected": True, "last_synced_at": None},
            {"name": "Supabase (Alpha Mode Media)", "connected": state["supabase"], "last_synced_at": None}]


real_compute, real_cache = connected_apps.compute_connected_apps_status, connected_apps._cached_status
connected_apps.compute_connected_apps_status = fake_status
main.compute_connected_apps_status = fake_status
try:
    asyncio.run(connected_apps.refresh_connected_apps_cache())   # the 15-minute tick, made while Supabase was failing
    alerts = asyncio.run(situation_room._connected_apps_alerts())
    check("a failed scheduled check puts Supabase on the banner", [a["title"] for a in alerts] == ["Supabase (Alpha Mode Media) disconnected"], alerts)

    state["supabase"] = True
    main.AUTH_TOKEN = "made-up"
    web = TestClient(main.app)
    live = web.get("/connected-apps", params={"token": "made-up"})
    check("Settings' live check shows it connected again", live.status_code == 200 and all(r["connected"] for r in live.json()), live.text)
    check("and the banner clears straight away, not 15 minutes later", asyncio.run(situation_room._connected_apps_alerts()) == [])

    state["supabase"] = False
    web.get("/connected-apps", params={"token": "made-up"})
    check("a live check that fails puts it back on the banner too", len(asyncio.run(situation_room._connected_apps_alerts())) == 1)
    check("the live check still needs the token", web.get("/connected-apps").status_code in (403, 422))
finally:
    connected_apps.compute_connected_apps_status = real_compute
    main.compute_connected_apps_status = real_compute
    connected_apps._cached_status = real_cache

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
