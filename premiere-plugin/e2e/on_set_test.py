"""The on-set tracker (backend/app/on_set_db.py and its routes): one live list for two shooters, what a phone link can and can't reach, and how ticks reach the report.
Temp files and a stand-in for nothing else: no API call, no real data, no real database. Set ON_SET_TEST_PG_DSN to a throwaway Postgres to also run the database part there, with phones writing at the same time. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python on_set_test.py"""
import asyncio
import os
import re
import stat
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, on_set_db as db, post_coverage as cov, post_shoot_log as sl  # noqa: E402

fails = 0
REAL_DATA, REAL_DB = sl.DATA, db.DB_PATH
STATIC = ROOT / "backend" / "app" / "static"


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


ITEMS = [{"id": "i1", "moment": "Arrivals", "time": "10:00", "description": "Logo wall", "size": "wide", "size_label": "Wide", "priority": "must", "priority_label": "Must have", "owner": "A-cam"},
         {"id": "i2", "moment": "Music", "time": "15:00", "description": "DJ", "size": "any", "size_label": "", "priority": "should", "priority_label": "Should have", "owner": ""}]
FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
PAST = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
SETTINGS = {"soon_minutes": 30, "now_minutes": 15, "poll_seconds": 5}


def event(n, item="i1", done=True, by="A-cam", at=None, note=""):
    return {"event_id": f"event-{n:04d}", "item": item, "done": done, "by": by, "note": note, "at": at}


async def contract(conn, label):
    """The same promises on both databases."""
    T = "tok-" + label + "-" + "x" * 40
    await db.ensure_tables(conn)
    await db.ensure_tables(conn)
    check(f"{label}: making the tables twice is fine", True)
    check(f"{label}: a link that was never made opens nothing", await db.find_link(T, conn) is None)
    link = await db.publish("cplan1", T, "Shoot", "Client", "2026-11-06", ITEMS, SETTINGS, FUTURE, conn)
    check(f"{label}: a new link starts at version 1", link["list_version"] == 1 and link["revoked_at"] is None, link)
    found = await db.find_link(T, conn)
    check(f"{label}: the token opens its list", found and found["plan_id"] == "cplan1" and found["items"][0]["description"] == "Logo wall", found)
    check(f"{label}: a different token opens nothing", await db.find_link(T + "y", conn) is None)
    out = await db.add_ticks(found, [event(1), event(2, "i2", by="B-cam")], conn)
    check(f"{label}: ticks go in", out == {"accepted": 2, "duplicates": 0, "rejected": 0, "full": 0}, out)
    out = await db.add_ticks(found, [event(1)], conn)
    check(f"{label}: the same tick sent twice counts once", out["accepted"] == 0 and out["duplicates"] == 1, out)
    out = await db.add_ticks(found, [event(3, "i99"), {**event(4), "event_id": "bad id!"}, {**event(5), "by": "  "}], conn)
    check(f"{label}: an unknown shot, a bad id and a blank name are refused", out["rejected"] == 3 and out["accepted"] == 0, out)
    rows = await db.ticks_since("cplan1", 0, conn)
    check(f"{label}: both phones' ticks read back in order", [r["by"] for r in rows] == ["A-cam", "B-cam"] and all(isinstance(r["done"], bool) for r in rows), rows)
    last = rows[-1]["id"]
    check(f"{label}: a phone only gets what's new", await db.ticks_since("cplan1", last, conn) == [])
    await db.add_ticks(found, [event(6, "i1", done=False, by="B-cam")], conn)
    new = await db.ticks_since("cplan1", last, conn)
    check(f"{label}: and then the new one", len(new) == 1 and new[0]["done"] is False, new)
    now = db.current_ticks(await db.ticks_since("cplan1", 0, conn))
    check(f"{label}: the latest action wins", now["i1"]["done"] is False and now["i1"]["by"] == "B-cam" and now["i2"]["done"] is True, now)
    await db.add_ticks(found, [{**event(7, "i2"), "note": "Night\x00 shot\x07 "}], conn)
    check(f"{label}: control characters come out", (await db.ticks_since("cplan1", 0, conn))[-1]["note"] == "Night shot")
    await db.add_ticks(found, [event(8, "i1", at="2099-01-01T00:00:00Z"), event(9, "i2", at="1999-01-01T00:00:00Z"), event(10, "i2", at="not a time")], conn)
    tail = (await db.ticks_since("cplan1", 0, conn))[-3:]
    stamp = db.now_iso()
    check(f"{label}: a wrong phone clock can't land in the future or before the link existed", tail[0]["at"] <= stamp and tail[1]["at"] >= found["created_at"] and tail[2]["at"] <= stamp, tail)
    again = await db.publish("cplan1", T, "Shoot two", "Client", "2026-11-07", ITEMS[:1], SETTINGS, FUTURE, conn)
    check(f"{label}: a new list bumps the version, and ticks stay", again["list_version"] == 2 and again["name"] == "Shoot two" and len(await db.ticks_since("cplan1", 0, conn)) >= 2, again)
    out = await db.add_ticks(await db.find_link(T, conn), [event(11, "i2")], conn)
    check(f"{label}: a shot taken off the list can't be ticked", out["rejected"] == 1, out)
    T2 = "tok-new-" + label + "-" + "z" * 40
    await db.publish("cplan1", T2, "Shoot two", "Client", "2026-11-07", ITEMS, SETTINGS, FUTURE, conn)
    check(f"{label}: a new address kills the old one", await db.find_link(T, conn) is None and await db.find_link(T2, conn) is not None)
    await db.revoke("cplan1", conn)
    check(f"{label}: a stopped link opens nothing", await db.find_link(T2, conn) is None)
    check(f"{label}: a stopped link is still known to the Mac", (await db.get_link("cplan1", conn))["revoked_at"] is not None)
    await db.publish("cplan2", T + "2", "Old", "", "2026-11-06", ITEMS, SETTINGS, PAST, conn)
    check(f"{label}: a link past its date opens nothing", await db.find_link(T + "2", conn) is None)
    await db.publish("cplan3", T + "3", "Other job", "", "2026-11-06", ITEMS, SETTINGS, FUTURE, conn)
    other = await db.find_link(T + "3", conn)
    await db.add_ticks(other, [event(1)], conn)
    check(f"{label}: the same event id on another job is its own tick", len(await db.ticks_since("cplan3", 0, conn)) == 1)
    check(f"{label}: one job's ticks never show on another", all(r["by"] == "A-cam" for r in await db.ticks_since("cplan3", 0, conn)) and len(await db.ticks_since("cplan3", 0, conn)) == 1)


async def sqlite_cap():
    await db.publish("ccap", "t" * 40, "Cap", "", "2026-11-06", ITEMS, SETTINGS, FUTURE)
    link = await db.find_link("t" * 40)
    keep, db.MAX_TICKS_PER_LINK = db.MAX_TICKS_PER_LINK, 3
    out = await db.add_ticks(link, [event(n) for n in range(1, 6)])
    db.MAX_TICKS_PER_LINK = keep
    check("a job's ticks have a ceiling, so a link can't fill the database", out["accepted"] == 3 and out["full"] == 2, out)


async def postgres(dsn):
    """Phones writing at the same moment, with another phone reading along. It must never miss a tick, however they interleave."""
    import psycopg
    if "dbname=onset" not in dsn or "127.0.0.1" not in dsn:
        print("SKIP postgres: this only runs on a throwaway local database called onset")
        return
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("DROP SCHEMA IF EXISTS on_set CASCADE")
        await conn.commit()
        check("postgres: before any link exists, a phone just gets 'not active'", await db.find_link("x" * 40, conn) is None)
        check("postgres: and the connection still works after that", (await (await conn.execute("SELECT 1")).fetchone())[0] == 1)
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await contract(conn, "postgres")
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        T = "race-" + "r" * 40
        await db.publish("crace", T, "Race", "", "2026-11-06", ITEMS, SETTINGS, FUTURE, conn)
        link = await db.find_link(T, conn)
    total, writers = 60, 4
    done = asyncio.Event()

    async def writer(w):
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            for n in range(total):
                await db.add_ticks(link, [{**event(n, "i1" if n % 2 else "i2", by=f"cam{w}"), "event_id": f"w{w}-{n:04d}-event"}], conn)

    seen, since = {}, 0

    async def reader():
        nonlocal since
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            while True:
                for row in await db.ticks_since("crace", since, conn):
                    seen[row["id"]] = row
                    since = max(since, row["id"])
                if done.is_set():
                    for row in await db.ticks_since("crace", since, conn):
                        seen[row["id"]] = row
                    return
                await asyncio.sleep(0.002)

    read = asyncio.create_task(reader())
    await asyncio.gather(*(writer(w) for w in range(writers)))
    done.set()
    await read
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        everything = await db.ticks_since("crace", 0, conn)
    check("postgres: 4 phones, 240 ticks, all stored", len(everything) == total * writers, len(everything))
    check("postgres: a phone reading along never missed one", len(seen) == total * writers, (len(seen), total * writers))


def as_header(token):
    return {"X-Set-Token": token}


def main_tests():
    tmp = Path(tempfile.mkdtemp())
    sl.DATA = tmp / "shoot_logs"
    db.DB_PATH = tmp / "on_set.db"
    audit_lines = []

    async def fake_audit(name, details):
        audit_lines.append(name)
    main._shoot_log_audit = fake_audit
    main.AUTH_TOKEN = "main-secret-token-for-this-test"
    MAIN = {"token": main.AUTH_TOKEN}

    asyncio.run(contract(None, "sqlite"))
    asyncio.run(sqlite_cap())
    import sqlite3
    with sqlite3.connect(tmp / "on_set.db") as lite:
        stored = [r[0] for r in lite.execute("SELECT token_hash FROM on_set_links")]
    check("links are looked up by a hash, never the token itself", stored and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in stored), stored)
    if os.environ.get("ON_SET_TEST_PG_DSN"):
        asyncio.run(postgres(os.environ["ON_SET_TEST_PG_DSN"]))
    else:
        print("SKIP postgres: ON_SET_TEST_PG_DSN isn't set")

    web = TestClient(main.app)
    conf = cov.CONFIG["on_set"]
    db._limits.hits.clear()

    # ---- making the link, from the Mac
    plan = cov.new_plan("Birkenstock activation", "Birkenstock")
    pid = plan["id"]
    secret_words = "SECRET-BRIEF-WORDS"
    p = cov.load_plan(pid); p["brief"]["text"] = secret_words; p["log_key"] = None; cov.save_plan(p)
    today = date.today().isoformat()
    check("the Mac's routes need the main token", web.get(f"/post/coverage/{pid}/on-set").status_code in (401, 403, 422))
    check("making a link needs the main token", web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": today}, params={"token": "wrong"}).status_code == 403)
    r = web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": today}, params=MAIN)
    check("no shots, no link", r.status_code == 400 and "no shots" in r.json()["detail"], r.text)
    i1 = cov.add_item(pid, {"moment": "Arrivals", "time": "10:00", "description": "Logo wall, wide", "shot_size": "wide", "priority": "must", "owner": "A-cam"})
    i2 = cov.add_item(pid, {"moment": "Music", "time": "15:00", "description": "DJ at the booth", "priority": "must"})
    r = web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": today}, params=MAIN)
    check("a draft list doesn't go to the crew", r.status_code == 400 and "Approve" in r.json()["detail"], r.text)
    cov.approve(pid, True)
    r = web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": "next tuesday"}, params=MAIN)
    check("a shoot date has to be a date", r.status_code == 400, r.text)
    r = web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": today}, params=MAIN)
    check("an approved list gets a link", r.status_code == 200 and r.json()["live"], r.text)
    made = r.json()
    check("the link points at the cloud, with the token after a #, so no server ever logs it", made["url"].startswith(f"{conf['public_url']}/static/on_set.html#t="), made["url"])
    token = made["url"].split("#t=")[1]
    check("the token is long and random", len(token) >= 40 and re.fullmatch(r"[A-Za-z0-9_-]+", token) is not None, token)
    path = cov.plan_dir(pid) / "on_set.json"
    check("only this Mac's owner can read the saved token", stat.S_IMODE(path.stat().st_mode) == 0o600, oct(path.stat().st_mode))
    check("the coverage page's main data doesn't carry the token", token not in web.get(f"/post/coverage/{pid}", params=MAIN).text)
    check("nothing is out of sync yet", made["in_sync"] is True, made)
    check("the link runs a few days past the shoot", made["expires_at"][:10] >= (date.today() + timedelta(days=conf["link_days_after_shoot"])).isoformat(), made["expires_at"])
    again = web.post(f"/post/coverage/{pid}/on-set", json={"shoot_date": today}, params=MAIN).json()
    check("making it again keeps the same address", again["url"] == made["url"])

    # ---- what the link can reach
    A, B = as_header(token), as_header(token)
    state = web.get("/set/state", headers=A)
    check("the phone link opens its list", state.status_code == 200 and state.json()["list"]["name"] == "Birkenstock activation", state.text)
    text = state.text
    for word in (secret_words, pid, str(sl.DATA), "brief", "log_key", "usd", "approved_at", "path"):
        check(f"the phone never sees {word!r}", word not in text)
    check("nothing the phone gets is stored along the way, or indexed", state.headers["cache-control"] == "no-store" and state.headers["x-robots-tag"] == "noindex")
    check("no token, no list", web.get("/set/state").status_code == 404)
    check("the main token doesn't open it", web.get("/set/state", headers=as_header(main.AUTH_TOKEN)).status_code == 404)
    check("a made-up link gets the same answer as a stopped one", web.get("/set/state", headers=as_header("a" * 44)).json()["detail"] == db.NOT_ACTIVE)
    for route in ("/health", "/status", "/post/coverage", f"/post/coverage/{pid}", f"/post/coverage/{pid}/on-set", "/post/jobs", "/post/shoot-log/x/thumb/y/1"):
        got = web.get(route, params={"token": token})
        check(f"the phone link is refused on {route}", got.status_code == 403, got.status_code)
    for method, route in (("POST", f"/post/coverage/{pid}/items"), ("POST", f"/post/coverage/{pid}/check"), ("POST", f"/post/coverage/{pid}/draft"), ("DELETE", f"/post/coverage/{pid}/on-set")):
        got = web.request(method, route, params={"token": token}, json={})
        check(f"the phone link can't {method} {route.split('/')[-1]}", got.status_code in (403, 422) and got.status_code != 200, got.status_code)
    public = sorted({r.path for r in main.app.routes if getattr(r, "path", "").startswith("/set") and not r.path.startswith("/set/manage")})
    check("a crew link has only the two routes its page needs", public == ["/set/state", "/set/ticks"], public)
    for route in main.app.routes:
        if getattr(route, "path", "").startswith("/set/manage") and route.path != "/set/manage/claim":
            for method in route.methods:
                got = web.request(method, route.path.replace("{plan_id}", pid).replace("{item_id}", "i1"), headers=A, json={})
                check(f"a crew link can't {method} {route.path}", got.status_code == 404 and "isn't set up" in got.text, got.status_code)

    # ---- the spec's test: two shooters, one live list
    first = web.get("/set/state", headers=A).json()
    second = web.get("/set/state", headers=B).json()
    check("two shooters open the same list", first["list"] == second["list"] and len(first["list"]["items"]) == 2)
    since_a, since_b, v = first["last_id"], second["last_id"], first["list_version"]
    sent = web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-a-0001", "item": i1["id"], "done": True, "by": "A-cam", "note": "", "at": db.now_iso()}]})
    check("shooter A ticks a shot", sent.status_code == 200 and sent.json()["accepted"] == 1, sent.text)
    seen = web.get("/set/state", params={"since": since_b, "v": v}, headers=B).json()
    check("shooter B sees it on the next check, and doesn't get the whole list again", [t["by"] for t in seen["ticks"]] == ["A-cam"] and "list" not in seen, seen)
    since_b = seen["last_id"]
    sent = web.post("/set/ticks", headers=B, json={"events": [{"event_id": "phone-b-0001", "item": i2["id"], "done": True, "by": "B-cam", "note": "headphones on", "at": db.now_iso()}]})
    seen = web.get("/set/state", params={"since": since_a, "v": v}, headers=A).json()
    check("shooter A sees both, with B's note", [t["by"] for t in seen["ticks"]] == ["A-cam", "B-cam"] and seen["ticks"][1]["note"] == "headphones on", seen)
    replay = web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-a-0001", "item": i1["id"], "done": True, "by": "A-cam", "note": "", "at": db.now_iso()}]})
    check("a phone that lost signal and sent again doesn't double up", replay.json()["duplicates"] == 1 and replay.json()["accepted"] == 0, replay.text)
    waited = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    web.post("/set/ticks", headers=B, json={"events": [{"event_id": "phone-b-0002", "item": i1["id"], "done": False, "by": "B-cam", "note": "", "at": db.now_iso()}]})
    web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-a-0002", "item": i1["id"], "done": True, "by": "A-cam", "note": "", "at": waited}]})
    mac = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
    check("a tick that waited for signal doesn't override what happened after it", mac["ticks"][i1["id"]]["done"] is False and mac["ticks"][i1["id"]]["by"] == "B-cam", mac["ticks"])
    web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-a-0003", "item": i1["id"], "done": True, "by": "A-cam", "note": "", "at": db.now_iso()}]})

    # ---- bad input
    check("a bad tick is refused, not stored", web.post("/set/ticks", headers=A, json={"events": [{"event_id": "x"}]}).status_code == 422)
    check("nonsense is refused", web.post("/set/ticks", headers={**A, "Content-Type": "application/json"}, content=b"{not json").status_code == 422)
    check("too many at once is refused", web.post("/set/ticks", headers=A, json={"events": [{"event_id": f"phone-many-{n}", "item": i1["id"], "done": True, "by": "A"} for n in range(51)]}).status_code == 422)
    check("an over-long note is refused", web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-long-1", "item": i1["id"], "done": True, "by": "A", "note": "n" * 201}]}).status_code == 422)
    check("a huge body is cut off", web.post("/set/ticks", headers=A, content=b"x" * (db.MAX_BODY_BYTES + 1)).status_code == 413)
    check("a silly position in the list is refused", web.get("/set/state", params={"since": 10**30}, headers=A).status_code == 422)
    check("a huge body from a made-up link is cut off before any database work", web.post("/set/ticks", headers=as_header("b" * 44), content=b"x" * (db.MAX_BODY_BYTES + 1)).status_code == 413)
    check("a script in a name is just text to the server", web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-xss-01", "item": i2["id"], "done": True, "by": "<img src=x onerror=alert(1)>", "note": "<script>"}]}).json()["accepted"] == 1)

    # ---- floods
    limit = db.RateLimit()
    check("a window lets the limit through", all(limit.allow("k", 3, now=100.0) for _ in range(3)))
    check("and stops the next", limit.allow("k", 3, now=100.5) is False)
    check("and opens again after a minute", limit.allow("k", 3, now=161.0) is True)
    many = db.RateLimit(); many.MAX_KEYS = 5
    for n in range(50):
        many.allow(str(n), 1, now=1.0)
    check("the limiter's own memory is capped", len(many.hits) <= 5, len(many.hits))
    db._limits.hits.clear()
    keep = db.UNKNOWN_LINKS_PER_MINUTE
    db.UNKNOWN_LINKS_PER_MINUTE = 3
    codes = [web.get("/set/state", headers=as_header(f"{n:02d}" + "c" * 42)).status_code for n in range(6)]
    check("a flood of made-up links gets stopped before the database", codes[:3] == [404, 404, 404] and codes[3:] == [429, 429, 429], codes)
    check("the real link keeps working through a flood", web.get("/set/state", headers=A).status_code == 200)
    db.UNKNOWN_LINKS_PER_MINUTE = keep
    db._limits.hits.clear()
    keep = db.REQUESTS_PER_LINK_PER_MINUTE
    db.REQUESTS_PER_LINK_PER_MINUTE = 3
    codes = [web.get("/set/state", headers=A).status_code for _ in range(5)]
    check("one link can't hammer the server either", codes == [200, 200, 200, 429, 429], codes)
    db.REQUESTS_PER_LINK_PER_MINUTE = keep
    db._limits.hits.clear()

    # ---- a list that changes on the Mac
    v = web.get("/set/state", headers=A).json()["list_version"]
    i3 = web.post(f"/post/coverage/{pid}/items", params=MAIN, json={"moment": "Music", "description": "Crowd at peak", "priority": "should"}).json()
    now = web.get("/set/state", params={"v": v}, headers=A).json()
    check("a shot added on the Mac reaches the phones", now["list_version"] == v + 1 and any(i["id"] == i3["id"] for i in now["list"]["items"]), now)
    web.post(f"/post/coverage/{pid}/items/{i3['id']}", params=MAIN, json={"description": "Crowd dancing"})
    check("so does an edit", any(i["description"] == "Crowd dancing" for i in web.get("/set/state", headers=A).json()["list"]["items"]))
    web.delete(f"/post/coverage/{pid}/items/{i3['id']}", params=MAIN)
    check("and a removal", len(web.get("/set/state", headers=A).json()["list"]["items"]) == 2)
    check("and the Mac knows they're level", web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()["in_sync"] is True)
    cov.add_item(pid, {"moment": "Music", "description": "Added behind the routes' back"})
    behind = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
    check("a list that hasn't reached phones says so", behind["in_sync"] is False, behind)
    sent = web.post(f"/post/coverage/{pid}/on-set", params=MAIN, json={"shoot_date": behind["shoot_date"]}).json()
    check("and sending it brings them level", sent["in_sync"] is True, sent)

    # ---- ticks reach the report, and never change a verdict
    p = cov.load_plan(pid)
    report = {"items": {i["id"]: {"fingerprint": cov.fingerprint(i), "error": None, "matches": []} for i in p["items"]}, "checked_at": "2026-11-06T17:00:00", "log_key": None}
    cov._write_json(cov.plan_dir(pid) / "report.json", report)
    web.get(f"/post/coverage/{pid}/on-set", params=MAIN)
    ticks = cov.load_on_set_ticks(pid)
    v1 = cov.view(pid)
    by_id = {r["id"]: r for r in v1["rows"]}
    check("a tick doesn't make a shot covered: that comes from the footage", by_id[i1["id"]]["status"] == "missing" and ticks[i1["id"]]["done"] is True, by_id[i1["id"]])
    check("the counts ignore ticks too", v1["summary"]["counts"]["covered"] == 0)
    unfound = cov.on_set_unfound(p["items"], [{"status": r["status"]} for r in v1["rows"]], ticks)
    check("a shot ticked but not found is called out", i1["description"] in unfound and i2["description"] in unfound and "Added behind the routes' back" not in unfound, unfound)
    pdf = cov.report_pdf(pid)
    check("the report PDF still builds, with ticks in it", pdf[:4] == b"%PDF" and len(pdf) > 1000)
    check("a name nobody planned for doesn't break the PDF", cov._on_set_line({"done": True, "by": "<b>Zoë 📷", "at": "2026-11-06T09:00:00.000Z", "note": "ok"}).startswith("Ticked on set by"))
    check("an unticked shot has no line", cov._on_set_line({"done": False, "by": "A", "at": "x"}) == "" and cov._on_set_line(None) == "")

    # ---- stopping it
    stopped = web.delete(f"/post/coverage/{pid}/on-set", params=MAIN)
    check("stopping the link needs no more than a click", stopped.status_code == 200 and stopped.json()["live"] is False and "url" not in stopped.json(), stopped.text)
    check("phones lose the list straight away", web.get("/set/state", headers=A).status_code == 404)
    check("and can't tick", web.post("/set/ticks", headers=A, json={"events": [{"event_id": "phone-late-01", "item": i1["id"], "done": True, "by": "A"}]}).status_code == 404)
    check("the token is gone from this Mac too", token not in path.read_text())
    check("the ticks stay for the report", cov.load_on_set_ticks(pid)[i1["id"]]["done"] is True and stopped.json()["ticks"][i1["id"]]["done"] is True)
    check("with the list changed since, a new link waits for approval", web.post(f"/post/coverage/{pid}/on-set", params=MAIN, json={"shoot_date": today}).status_code == 400)
    cov.approve(pid, True)
    fresh = web.post(f"/post/coverage/{pid}/on-set", params=MAIN, json={"shoot_date": today}).json()
    new_token = fresh["url"].split("#t=")[1]
    check("a new link has a new address", fresh["live"] and new_token != token)
    check("the old one stays dead", web.get("/set/state", headers=A).status_code == 404)
    check("the new one carries on with the same ticks", len(web.get("/set/state", headers=as_header(new_token)).json()["ticks"]) >= 4)

    # ---- running out
    local = cov.on_set_local(pid)
    cov.save_on_set_local(pid, {**local, "expires_at": PAST})
    cov.add_item(pid, {"moment": "Music", "description": "Edited after the end"})
    pushed = web.post(f"/post/coverage/{pid}/items", params=MAIN, json={"moment": "Music", "description": "Edited after the end two"})
    check("an edit never brings a run-out link back to life", pushed.status_code == 200 and cov.on_set_local(pid)["expires_at"] == PAST)
    cov.save_on_set_local(pid, local)

    # ---- no signal on the Mac
    real_since = db.ticks_since

    async def no_signal(*a, **k):
        raise OSError("no route to host")
    db.ticks_since = no_signal
    quiet = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
    check("with no signal the Mac shows the last ticks seen, and says so", quiet["offline"] is True and quiet["ticks"][i1["id"]]["done"] is True, quiet)
    db.ticks_since = real_since

    # ---- the page itself
    page = (STATIC / "on_set.html").read_text()
    code = (STATIC / "on_set.js").read_text()
    check("the page allows no outside scripts or connections", "default-src 'none'" in page and "script-src 'self'" in page and "connect-src 'self'" in page)
    check("the page's scripts are files, not inline, so the policy can forbid inline ones", "<script>" not in page and "unsafe-inline'; connect" in page and "script-src 'self';" in page)
    check("the page sends no address to anyone, and asks not to be indexed", 'name="referrer" content="no-referrer"' in page and 'name="robots" content="noindex"' in page)
    check("only fixed markup ever goes in as HTML", len(re.findall(r"innerHTML", code)) == 1 and "fixed markup" in code)
    check("the token goes in a header, never an address", "X-Set-Token" in code and "token=" not in code)
    check("a stopped link wipes the list off the phone", "localStorage.removeItem(KEY)" in code)
    check("a new link opened in the same tab loads it, instead of staying on the old one", 'addEventListener("hashchange", () => location.reload())' in code)
    check("only the server's own words count as stopped, so a deploy can't wipe waiting ticks", "saysStopped" in code and db.NOT_ACTIVE.startswith("This link isn't active"))
    check("a route that doesn't exist yet doesn't read as a stopped link", web.get("/set/nothing", headers=A).status_code == 404 and "isn't active" not in web.get("/set/nothing", headers=A).text)
    worker = (STATIC / "on_set_sw.js").read_text()
    check("the offline copy is only the page's own files, not the list", "/set/" not in worker and "on_set.html" in worker)
    check("no public route touches Claude", "anthropic" not in (ROOT / "backend/app/on_set_db.py").read_text().lower())

    check("nothing landed in the real data folder", sl.DATA != REAL_DATA and db.DB_PATH != REAL_DB)
    check("the audit lines came out here, not in the real audit file", "post_coverage_on_set_ui" in audit_lines)


main_tests()
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
