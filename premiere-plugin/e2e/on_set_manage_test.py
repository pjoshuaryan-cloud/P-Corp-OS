"""Making shot lists from the owner's phone with no Mac (backend/app/on_set_manage.py and its routes): the one-time setup, what the phone login can and can't reach, lists, drafting from a brief with its daily limit, and how a phone's list reaches the Mac.
Temp files and a stand-in for Claude: no API call, no real data, no real database. Set ON_SET_TEST_PG_DSN to a throwaway Postgres (dbname=onset on 127.0.0.1) to also run the database part there. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python on_set_manage_test.py"""
import asyncio
import base64
import json
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
import anyio.from_thread  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main, on_set_db as db, on_set_manage as om, post_coverage as cov, post_shoot_log as sl  # noqa: E402

fails = 0
REAL_DATA, REAL_DB = sl.DATA, db.DB_PATH
STATIC = ROOT / "backend" / "app" / "static"
STARTER = "t0000000000a1"
today = date.today().isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:320]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def login(key):
    return {"Cookie": f"onset_manager={key}"}


class Block:
    type = "text"
    def __init__(self, text): self.text = text


class FakeMessages:
    def __init__(self): self.calls = []; self.reply = None; self.boom = None; self.hold = None
    async def create(self, **kw):
        self.calls.append(kw)
        if self.hold:
            await self.hold.wait()
        if self.boom:
            raise self.boom
        return type("R", (), {"content": [Block(self.reply)], "usage": type("U", (), {"input_tokens": 1000, "output_tokens": 800})()})()


class FakeClient:
    def __init__(self): self.messages = FakeMessages()


async def database(conn, label):
    """The same promises on both databases, for the parts a phone adds."""
    await db.ensure_tables(conn)
    await db.ensure_tables(conn)
    check(f"{label}: no lists yet is an empty answer", await db.all_lists(conn) == [])
    mid, code = await db.new_setup("Phone", conn)
    check(f"{label}: a setup waits to be scanned", [m["id"] for m in await db.list_managers(conn)] == [mid])
    key = await db.claim_setup(code, conn)
    check(f"{label}: a setup code gives a key once", key and len(key) >= 40)
    check(f"{label}: and never again", await db.claim_setup(code, conn) is None)
    found = await db.find_manager(key, conn)
    check(f"{label}: the key is known", found and found["id"] == mid, found)
    check(f"{label}: a wrong key isn't", await db.find_manager(key + "x", conn) is None)
    check(f"{label}: using it is noted", (await db.list_managers(conn))[0]["last_used_at"])
    await db.publish(f"c{label[:6]:0<12}", "t" * 44, "Shoot", "Client", today, [{"id": "a", "description": "One"}], {}, db.expiry_for(today, 3), conn, source="phone")
    plan = f"c{label[:6]:0<12}"
    rows = await db.all_lists(conn)
    check(f"{label}: a list comes with its link and where it was made", rows[0]["share_token"] == "t" * 44 and rows[0]["source"] == "phone" and rows[0]["items"][0]["id"] == "a", rows)
    check(f"{label}: the link can be read back by the owner's side", (await db.get_share(plan, conn)) == {"token": "t" * 44, "source": "phone"})
    def add(link):
        link["items"].append({"id": "b", "description": "Two"}); link["name"] = "Renamed"
    changed = await db.change_list(plan, add, conn)
    check(f"{label}: a change goes in and bumps the version", changed["list_version"] == 2 and len(changed["items"]) == 2 and changed["name"] == "Renamed", changed)
    def bad(link):
        link["name"] = "Half done"
        raise ValueError("no")
    try:
        await db.change_list(plan, bad, conn)
    except ValueError:
        pass
    check(f"{label}: a change that fails leaves the list alone", (await db.get_link(plan, conn))["name"] == "Renamed")
    check(f"{label}: a list that doesn't exist can't be changed", await db.change_list("c000000000000", add, conn) is None)
    await db.new_address(plan, "n" * 44, db.expiry_for(today, 3), conn)
    check(f"{label}: a new address kills the old one", await db.find_link("t" * 44, conn) is None and (await db.find_link("n" * 44, conn))["plan_id"] == plan)
    check(f"{label}: and is what the owner's side reads", (await db.get_share(plan, conn))["token"] == "n" * 44)
    await db.replace_templates([{"id": "t1", "name": "B", "items": []}, {"id": "t2", "name": "A", "items": [{"description": "x"}]}], conn)
    check(f"{label}: templates come back by name", [t["name"] for t in await db.load_templates(conn)] == ["A", "B"])
    await db.replace_templates([{"id": "t3", "name": "Only", "items": []}], conn)
    check(f"{label}: and get replaced as a set", [t["id"] for t in await db.load_templates(conn)] == ["t3"])
    check(f"{label}: no drafts yet", await db.drafts_last_day(conn) == {"count": 0, "usd": 0.0})
    await db.record_draft(mid, plan, 0.0101, 1, conn)
    await db.record_draft(mid, plan, 0.02, 2, conn)
    used = await db.drafts_last_day(conn)
    check(f"{label}: drafts and their cost add up", used["count"] == 2 and abs(used["usd"] - 0.0301) < 1e-6, used)
    await db.revoke_manager(mid, conn)
    check(f"{label}: a turned-off phone is locked out at once", await db.find_manager(key, conn) is None and await db.list_managers(conn) == [])


async def postgres(dsn):
    import psycopg
    if "dbname=onset" not in dsn or "127.0.0.1" not in dsn:
        print("SKIP postgres: this only runs on a throwaway local database called onset")
        return
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("DROP SCHEMA IF EXISTS on_set CASCADE")
        await conn.commit()
        check("postgres: before any tables, a phone is just not set up", await db.find_manager("x" * 44, conn) is None and await db.claim_setup("y" * 32, conn) is None and await db.list_managers(conn) == [] and await db.all_lists(conn) == [] and await db.get_share("c1", conn) is None and await db.load_templates(conn) == [])
        check("postgres: and the connection still works after that", (await (await conn.execute("SELECT 1")).fetchone())[0] == 1)
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await database(conn, "postgres")
        _, code = await db.new_setup("Race", conn)
        await db.publish("crace00000000", "r" * 44, "Race", "", today, [], {}, db.expiry_for(today, 3), conn)

    async def claim():
        async with await psycopg.AsyncConnection.connect(dsn) as c:
            return await db.claim_setup(code, c)
    claims = await asyncio.gather(*(claim() for _ in range(6)))
    check("postgres: six phones scanning at once, one key", sum(1 for k in claims if k) == 1, claims)

    async def adder(n):
        async with await psycopg.AsyncConnection.connect(dsn) as c:
            for i in range(10):
                await db.change_list("crace00000000", lambda link, x=f"{n}-{i}": link["items"].append({"id": x, "description": x}), c)
    await asyncio.gather(*(adder(n) for n in range(4)))
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        final = await db.get_link("crace00000000", conn)
    check("postgres: 4 people editing at once, 40 edits, none lost", len(final["items"]) == 40 and final["list_version"] == 41, (len(final["items"]), final["list_version"]))


def main_tests():
    tmp = Path(tempfile.mkdtemp())
    sl.DATA = tmp / "shoot_logs"
    db.DB_PATH = tmp / "on_set.db"

    async def fake_audit(name, details):
        return None
    main._shoot_log_audit = fake_audit
    main.AUTH_TOKEN = "main-secret-token-for-this-test"
    MAIN = {"token": main.AUTH_TOKEN}
    claude = FakeClient()
    main._coverage_client = lambda: claude

    asyncio.run(database(None, "sqlite"))
    if os.environ.get("ON_SET_TEST_PG_DSN"):
        asyncio.run(postgres(os.environ["ON_SET_TEST_PG_DSN"]))
    else:
        print("SKIP postgres: ON_SET_TEST_PG_DSN isn't set")
    db.DB_PATH = tmp / "fresh.db"
    db._limits.hits.clear()

    with anyio.from_thread.start_blocking_portal() as portal:   # one event loop throughout, so background drafts keep running between requests
        web = TestClient(main.app)
        web.portal = portal

        # ---- no phone yet
        web.post("/post/coverage-phone/sync", params=MAIN)
        check("with no phone set up, opening Coverage Plans sends no templates to the cloud", asyncio.run(db.load_templates()) == [])

        # ---- setting up a phone, from the Mac
        check("setting up a phone needs the main token", web.post("/post/coverage-phone", json={}, params={"token": "wrong"}).status_code == 403)
        check("seeing phones needs it too", web.get("/post/coverage-phone", params={"token": "wrong"}).status_code == 403)
        made = web.post("/post/coverage-phone", json={"label": "Josh's iPhone"}, params=MAIN).json()
        check("the Mac gets a QR link for the owner's page, with the code after a #", made["url"].startswith(cov.CONFIG["on_set"]["public_url"] + "/static/on_set_manage.html#s="), made["url"][:60])
        code = made["url"].split("#s=")[1]
        listed = web.get("/post/coverage-phone", params=MAIN)
        check("the phone shows as waiting for a scan", listed.json()["phones"][0]["label"] == "Josh's iPhone" and listed.json()["phones"][0]["claimed_at"] is None, listed.text)
        check("no code or key is ever listed", code not in listed.text and "hash" not in listed.text)
        claim = web.post("/set/manage/claim", json={"code": code})
        key = claim.cookies.get("onset_manager")
        check("scanning it logs the phone in", claim.status_code == 200 and key and len(key) >= 40, claim.text)
        check("the login never appears in anything a page or person could read or forward", key not in claim.text and claim.json() == {"ok": True}, claim.text)
        cookie = claim.headers["set-cookie"].lower()
        check("it's a cookie the page's scripts can't read and other sites can't trigger", "httponly" in cookie and "samesite=strict" in cookie and "path=/set/manage" in cookie, cookie)
        check("and it lasts, so a phone doesn't lose it at a venue", "max-age=34560000" in cookie, cookie)
        web.cookies.clear()   # from here on each request says who it is, so "no login" really means none
        secure = web.post("/post/coverage-phone", json={}, params=MAIN).json()["url"].split("#s=")[1]
        over_https = web.post("/set/manage/claim", json={"code": secure}, headers={"X-Forwarded-Proto": "https"})
        check("over https it's only ever sent over https", "secure" in over_https.headers["set-cookie"].lower(), over_https.headers["set-cookie"])
        web.cookies.clear()
        asyncio.run(db.revoke_manager(web.get("/post/coverage-phone", params=MAIN).json()["phones"][-1]["id"]))
        K = login(key)
        again = web.post("/set/manage/claim", json={"code": code})
        check("the same QR code never works twice, so a photo of it is worthless", again.status_code == 404 and "used or has run out" in again.text, again.text)
        check("the responses aren't stored along the way", claim.headers["cache-control"] == "no-store" and claim.headers["x-robots-tag"] == "noindex")
        keep = db.SETUP_MINUTES
        db.SETUP_MINUTES = -1
        late = web.post("/post/coverage-phone", json={}, params=MAIN).json()["url"].split("#s=")[1]
        db.SETUP_MINUTES = keep
        check("an old QR code has run out", web.post("/set/manage/claim", json={"code": late}).status_code == 404)
        check("a made-up code gets the same answer", web.post("/set/manage/claim", json={"code": "z" * 32}).status_code == 404)
        check("nonsense is refused", web.post("/set/manage/claim", json={"nope": 1}).status_code == 422)
        check("once scanned, it shows as set up", web.get("/post/coverage-phone", params=MAIN).json()["phones"][0]["claimed_at"])
        raw = db.DB_PATH.read_bytes()
        check("the database holds neither the key nor the code", key.encode() not in raw and code.encode() not in raw)

        # ---- what the phone login can't reach
        home = web.get("/set/manage/lists", headers=K)
        check("the phone login opens the list of lists", home.status_code == 200 and home.json()["lists"] == [], home.text)
        check("with the starter lists ready to use", [t["name"] for t in home.json()["templates"]] == ["Brand activation", "JD store opening"], home.json()["templates"])
        check("no key, no lists", web.get("/set/manage/lists").status_code == 404)
        check("the login can't be passed in a header", web.get("/set/manage/lists", headers={"X-Set-Manager": key}).status_code == 404)
        check("or in an address", web.get("/set/manage/lists", params={"token": key, "key": key, "k": key}).status_code == 404)
        check("and it says how to set up", "isn't set up" in web.get("/set/manage/lists").text)
        check("the main token isn't a phone login", web.get("/set/manage/lists", headers=login(main.AUTH_TOKEN)).status_code == 404)
        check("a used setup code isn't one", web.get("/set/manage/lists", headers=login(code)).status_code == 404)
        for route in ("/health", "/status", "/post/coverage", "/post/jobs", "/post/coverage-phone", "/ventures"):
            got = web.get(route, params={"token": key})
            check(f"the phone login is refused on {route}", got.status_code == 403, got.status_code)
        check("it can't be used as a crew link", web.get("/set/state", headers={"X-Set-Token": key}).status_code == 404)
        for method, route in (("POST", "/post/coverage-phone"), ("POST", "/post/coverage")):
            check(f"it can't {method} {route}", web.request(method, route, params={"token": key}, json={"name": "x", "label": "y"}).status_code == 403)
        for route in main.app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/set/manage") and path != "/set/manage/claim":
                for method in route.methods:
                    got = web.request(method, path.replace("{plan_id}", "c000000000000").replace("{item_id}", "i1"), json={})
                    check(f"{method} {path} needs a phone login", got.status_code == 404 and "isn't set up" in got.text, got.status_code)

        # ---- making a list
        check("a list needs a name", web.post("/set/manage/lists", headers=K, json={"name": "  ", "shoot_date": today}).status_code == 400)
        check("a list needs a real date", web.post("/set/manage/lists", headers=K, json={"name": "A", "shoot_date": "monday"}).status_code == 400)
        check("a template has to exist", web.post("/set/manage/lists", headers=K, json={"name": "A", "shoot_date": today, "template": "t" + "f" * 12}).status_code == 400)
        jd = web.post("/set/manage/lists", headers=K, json={"name": "JD Monday", "client": "JD Sports", "shoot_date": "2026-11-09", "template": STARTER}).json()
        check("a list made from the template has all its shots, ready to send", jd["total"] == 20 and jd["live"] and jd["token"] and jd["source"] == "phone", jd)
        check("it counts its must-haves", jd["must_left"] == 11, jd["must_left"])
        check("its shots are in the form phones read", {"id", "moment", "time", "description", "size", "size_label", "priority", "priority_label", "owner"} <= set(jd["items"][0]) and jd["items"][0]["size_label"] == "Wide", jd["items"][0])
        check("no times yet", all(i["time"] == "" for i in jd["items"]))
        pid, token = jd["id"], jd["token"]
        check("its id is the same kind a Mac plan has", re.fullmatch(r"c[0-9a-f]{12}", pid) is not None, pid)
        empty = web.post("/set/manage/lists", headers=K, json={"name": "Blank", "shoot_date": today}).json()
        check("an empty list works too", empty["total"] == 0 and empty["live"])
        lists = web.get("/set/manage/lists", headers=K)
        check("lists show latest shoot first", [l["name"] for l in lists.json()["lists"]][0] == "JD Monday", lists.text[:200])
        check("the list of lists doesn't carry the links", token not in lists.text)
        check("a list that doesn't exist says so", web.get("/set/manage/lists/c000000000000", headers=K).status_code == 404)

        # ---- crew, same as ever
        C = {"X-Set-Token": token}
        crew = web.get("/set/state", headers=C).json()
        check("a crew link opens the phone's list", crew["list"]["name"] == "JD Monday" and len(crew["list"]["items"]) == 20, crew)
        check("a crew member never gets the link back from the server, or anything else of the owner's", "share_token" not in json.dumps(crew) and key not in json.dumps(crew))
        check("a crew link can't reach the owner's page", web.get("/set/manage/lists", headers=login(token)).status_code == 404)
        first = jd["items"][0]["id"]
        web.post("/set/ticks", headers=C, json={"events": [{"event_id": "crew-a-0001", "item": first, "done": True, "by": "B-cam", "note": "got it"}]})
        seen = web.get(f"/set/manage/lists/{pid}", headers=K).json()
        check("the owner's phone sees the crew's ticks", seen["done"] == 1 and seen["ticks"][first]["by"] == "B-cam" and seen["must_left"] == 10, seen["ticks"])

        # ---- changing it
        v = crew["list_version"]
        added = web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "Store manager interview", "moment": "Opening", "priority": "must", "owner": "A-cam"}).json()
        new_item = next(i for i in added["items"] if i["description"] == "Store manager interview")
        check("a shot can be added", added["total"] == 21 and new_item["id"].startswith("p") and new_item["owner"] == "A-cam", new_item)
        update = web.get("/set/state", params={"v": v}, headers=C).json()
        check("crew phones get it on their next check", update["list_version"] == v + 1 and any(i["id"] == new_item["id"] for i in update["list"]["items"]))
        check("a shot needs words", web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "  "}).status_code == 400)
        check("sizes have to be real", web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "x", "size": "huge"}).status_code == 400)
        check("priorities too", web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "x", "priority": "urgent"}).status_code == 400)
        changed = web.post(f"/set/manage/lists/{pid}/items/{new_item['id']}", headers=K, json={"description": "Manager interview", "size": "close"}).json()
        item = next(i for i in changed["items"] if i["id"] == new_item["id"])
        check("a shot can be changed, keeping the rest", item["description"] == "Manager interview" and item["size_label"] == "Close" and item["owner"] == "A-cam", item)
        check("a shot that's gone says so", web.post(f"/set/manage/lists/{pid}/items/p000", headers=K, json={"description": "x"}).status_code == 400)
        gone = web.delete(f"/set/manage/lists/{pid}/items/{new_item['id']}", headers=K).json()
        check("a shot can be removed", gone["total"] == 20)
        check("removing it twice says so", web.delete(f"/set/manage/lists/{pid}/items/{new_item['id']}", headers=K).status_code == 400)
        timed = web.post(f"/set/manage/lists/{pid}/moment", headers=K, json={"moment": "Outside", "time": "10:00"}).json()
        check("a time goes on a whole moment", {i["time"] for i in timed["items"] if i["moment"] == "Outside"} == {"10:00"} and {i["time"] for i in timed["items"] if i["moment"] == "Opening"} == {""})
        cleared = web.post(f"/set/manage/lists/{pid}/moment", headers=K, json={"moment": "Outside", "time": ""}).json()
        check("and can come off again", {i["time"] for i in cleared["items"]} == {""})
        web.post(f"/set/manage/lists/{pid}/moment", headers=K, json={"moment": "Outside", "time": "10:00"})
        check("a moment that's gone says so", web.post(f"/set/manage/lists/{pid}/moment", headers=K, json={"moment": "Nope", "time": "1:00"}).status_code == 400)
        renamed = web.post(f"/set/manage/lists/{pid}", headers=K, json={"name": "JD Rosebank", "shoot_date": "2026-11-10"}).json()
        check("the name and date can change, and the link's end date follows", renamed["name"] == "JD Rosebank" and renamed["shoot_date"] == "2026-11-10" and renamed["expires_at"][:10] == "2026-11-13", renamed["expires_at"])
        check("a blank name is refused", web.post(f"/set/manage/lists/{pid}", headers=K, json={"name": "  "}).status_code == 400)
        check("a bad date is refused", web.post(f"/set/manage/lists/{pid}", headers=K, json={"shoot_date": "soon"}).status_code == 400)
        check("a huge body is cut off", web.post(f"/set/manage/lists/{pid}/items", headers=K, content=b"x" * (db.MAX_BODY_BYTES + 1)).status_code == 413)
        script = web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "<script>alert(1)</script>\x00", "moment": "Opening"}).json()
        check("a script is just text, and control characters come out", any(i["description"] == "<script>alert(1)</script>" for i in script["items"]))
        web.delete(f"/set/manage/lists/{pid}/items/{next(i['id'] for i in script['items'] if 'script' in i['description'])}", headers=K)

        # ---- only the owner starts or stops a link
        for who, headers in (("nobody logged in", {}), ("a crew link in the header", C), ("a crew link as the login", login(token)), ("the main token as the login", login(main.AUTH_TOKEN)), ("a made-up login", login("m" * 44))):
            check(f"{who} can't stop a link", web.delete(f"/set/manage/lists/{pid}/link", headers=headers).status_code == 404)
            check(f"{who} can't start one", web.post(f"/set/manage/lists/{pid}/link", headers=headers).status_code == 404)
            check(f"{who} can't make a list", web.post("/set/manage/lists", headers=headers, json={"name": "Sneaky", "shoot_date": today}).status_code == 404)
            check(f"{who} can't see the list's link", web.get(f"/set/manage/lists/{pid}", headers=headers).status_code == 404)
        for method, route in (("DELETE", f"/post/coverage/{pid}/on-set"), ("POST", f"/post/coverage/{pid}/on-set"), ("POST", "/post/coverage-phone")):
            check(f"a crew link can't {method} {route.split('/')[-1]} on the Mac's side", web.request(method, route, params={"token": token}, json={"shoot_date": today}).status_code == 403)
            check(f"nor can the phone login, which can't make more logins or reach the Mac", web.request(method, route, params={"token": key}, json={"shoot_date": today}).status_code == 403)
        check("after all that, the link is still live", web.get("/set/state", headers=C).status_code == 200)

        # ---- stopping and starting
        stopped = web.delete(f"/set/manage/lists/{pid}/link", headers=K).json()
        check("the phone can stop a link", stopped["stopped"] and not stopped["live"])
        check("crew lose the list at once", web.get("/set/state", headers=C).status_code == 404)
        check("a new date doesn't bring it back", (web.post(f"/set/manage/lists/{pid}", headers=K, json={"shoot_date": "2026-11-09"}).json()["stopped"] is True) and web.get("/set/state", headers=C).status_code == 404)
        back = web.post(f"/set/manage/lists/{pid}/link", headers=K).json()
        check("turning it back on gives a new address", back["live"] and back["token"] != token, back["token"])
        check("the old address stays dead", web.get("/set/state", headers=C).status_code == 404)
        token2 = back["token"]
        C2 = {"X-Set-Token": token2}
        check("the new one carries on with the same ticks", any(t["by"] == "B-cam" for t in web.get("/set/state", headers=C2).json()["ticks"]))
        asyncio.run(db.set_expiry(pid, PAST))
        ran = web.get(f"/set/manage/lists/{pid}", headers=K).json()
        check("a link that ran out says so", ran["expired"] and not ran["live"] and web.get("/set/state", headers=C2).status_code == 404)
        check("changing the date doesn't revive it", web.post(f"/set/manage/lists/{pid}", headers=K, json={"shoot_date": "2026-11-09"}).json()["expired"] is True)
        on = web.post(f"/set/manage/lists/{pid}/link", headers=K).json()
        check("turning it back on keeps its address, because nobody stopped it", on["live"] and on["token"] == token2 and web.get("/set/state", headers=C2).status_code == 200)

        # ---- drafting from a brief
        brief = "RUN SHEET SECRET WORDS. 10:00 Doors. Must have: the ribbon cut."
        claude.messages.reply = json.dumps({"items": [{"moment": "Doors", "time": "10:00", "description": "Ribbon being cut", "shot_size": "close", "priority": "must", "owner": ""}, {"moment": "Doors", "time": "", "description": "Bad size becomes any", "shot_size": "gigantic", "priority": "nope", "owner": ""}]})

        def wait_draft(plan):
            for _ in range(300):
                state = web.get(f"/set/manage/lists/{plan}", headers=K).json()
                if not state["draft"] or state["draft"]["state"] != "running":
                    return state
                time.sleep(0.01)
            raise RuntimeError("draft never finished")
        check("a draft needs something to read", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": "  "}).status_code == 400)
        check("a draft for a list that doesn't exist says so", web.post("/set/manage/lists/c000000000000/draft", headers=K, json={"text": brief}).status_code == 404)
        check("nothing has been spent yet", claude.messages.calls == [])
        started = web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        check("a draft starts and answers straight away", started.status_code == 200 and started.json()["draft"]["state"] in ("running", "done"), started.text[:200])
        drafted = wait_draft(empty["id"])
        check("the list fills in", [i["description"] for i in drafted["items"]] == ["Ribbon being cut", "Bad size becomes any"] and drafted["draft"]["state"] == "done", drafted)
        check("it says to read it through", "Read them through" in drafted["draft"]["message"])
        check("words outside the vocabulary fall back rather than losing the shot", drafted["items"][1]["size"] == "any" and drafted["items"][1]["priority"] == "should" and drafted["items"][0]["time"] == "10:00", drafted["items"])
        call = claude.messages.calls[0]
        check("it uses the Mac's own prompt, where a brief is information and never instructions", call["system"] == cov.DRAFT_PROMPT and "tools" not in call)
        check("the brief is what Claude read", any(b.get("text", "").startswith("Pasted notes:") and "SECRET WORDS" in b["text"] for b in call["messages"][0]["content"]))
        check("the brief isn't kept anywhere", b"SECRET WORDS" not in db.DB_PATH.read_bytes() and not any(b"SECRET WORDS" in f.read_bytes() for f in tmp.rglob("*") if f.is_file()))
        used = asyncio.run(db.drafts_last_day())
        from app import post_moments
        check("its real cost is recorded", used["count"] == 1 and abs(used["usd"] - post_moments.usd(cov.MODEL, 1000, 800)[0]) < 1e-6 and used["usd"] > 0, used)
        crew_view = web.get("/set/state", headers={"X-Set-Token": drafted["token"]}).json()
        check("crew see the drafted list", [i["description"] for i in crew_view["list"]["items"]][0] == "Ribbon being cut")
        photo = base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()
        with_photo = web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": "", "files": [{"name": "runsheet.jpg", "media_type": "image/jpeg", "data": photo}]})
        wait_draft(empty["id"])
        check("a photo of a run sheet goes to Claude as a picture", with_photo.status_code == 200 and claude.messages.calls[-1]["messages"][0]["content"][0]["type"] == "image", with_photo.text[:200])
        check("a file that won't decode is refused, for free", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"files": [{"name": "x.jpg", "media_type": "image/jpeg", "data": "!!!"}]}).status_code == 400)
        check("too many files are refused", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"files": [{"name": "x.jpg", "data": ""}] * 7}).status_code == 422)
        check("a body over the limit is cut off", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, content=b"x" * (om.MAX_DRAFT_BODY_BYTES + 1)).status_code == 413)
        check("with a dead key, a big body is refused before it's read", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=login("q" * 44), content=b"x" * (om.MAX_DRAFT_BODY_BYTES + 1)).status_code == 404)
        check("a crew link can't draft", web.post(f"/set/manage/lists/{empty['id']}/draft", headers=login(drafted["token"]), json={"text": brief}).status_code == 404)
        before = [i["description"] for i in wait_draft(empty["id"])["items"]]
        n = len(claude.messages.calls)
        claude.messages.reply = "not json at all"
        web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        failed = wait_draft(empty["id"])
        check("an unusable answer leaves the list as it was", failed["draft"]["state"] == "failed" and [i["description"] for i in failed["items"]] == before, failed["draft"])
        check("it tried once more first", len(claude.messages.calls) == n + 2)
        check("and that still counts toward the limit, because it cost money", asyncio.run(db.drafts_last_day())["count"] == 3)
        class APIConnectionError(Exception):
            pass
        claude.messages.boom = APIConnectionError("no route")
        web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        offline = wait_draft(empty["id"])
        check("no signal to Claude says so, and leaves the list", offline["draft"]["state"] == "failed" and "Couldn't reach Claude" in offline["draft"]["message"] and [i["description"] for i in offline["items"]] == before, offline["draft"])
        claude.messages.boom = None
        check("a failed call with no answer doesn't count", asyncio.run(db.drafts_last_day())["count"] == 3)
        # the daily ceiling
        limits = cov.CONFIG["on_set"]["phone_drafts"]
        keep_limits = dict(limits)
        n = len(claude.messages.calls)
        om._ON_SET["phone_drafts"]["per_day"] = 3
        capped = web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        check("at the day's count limit, a draft is refused before any call", capped.status_code == 400 and "most drafts allowed" in capped.text and len(claude.messages.calls) == n, capped.text)
        om._ON_SET["phone_drafts"]["per_day"] = keep_limits["per_day"]
        om._ON_SET["phone_drafts"]["max_usd_per_day"] = 0.001
        capped = web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        check("and at the day's money limit", capped.status_code == 400 and len(claude.messages.calls) == n, capped.text)
        om._ON_SET["phone_drafts"]["max_usd_per_day"] = keep_limits["max_usd_per_day"]
        check("the limit ships with sensible numbers", 0 < keep_limits["max_usd_per_day"] <= 2 and 0 < keep_limits["per_day"] <= 20, keep_limits)
        async def make_hold():
            return asyncio.Event()
        claude.messages.hold = portal.call(make_hold)
        claude.messages.reply = json.dumps({"items": [{"moment": "M", "time": "", "description": "Held", "shot_size": "any", "priority": "must", "owner": ""}]})
        web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        twice = web.post(f"/set/manage/lists/{empty['id']}/draft", headers=K, json={"text": brief})
        check("one draft at a time per list, so a double tap costs once", twice.status_code == 400 and "Already drafting" in twice.text, twice.text)
        other_a = web.post("/set/manage/lists", headers=K, json={"name": "Other A", "shoot_date": today}).json()["id"]
        other_b = web.post("/set/manage/lists", headers=K, json={"name": "Other B", "shoot_date": today}).json()["id"]
        web.post(f"/set/manage/lists/{other_a}/draft", headers=K, json={"text": brief})
        third = web.post(f"/set/manage/lists/{other_b}/draft", headers=K, json={"text": brief})
        check("and only a couple at once overall", third.status_code == 400 and "Another draft" in third.text, third.text)
        portal.call(claude.messages.hold.set)
        wait_draft(empty["id"]); wait_draft(other_a)
        claude.messages.hold = None

        # ---- the Mac picks it up
        synced = web.post("/post/coverage-phone/sync", params=MAIN).json()
        check("the Mac brings in lists made on the phone", synced["imported"] >= 2 and not synced["offline"], synced)
        check("once only", web.post("/post/coverage-phone/sync", params=MAIN).json()["imported"] == 0)
        check("syncing needs the main token", web.post("/post/coverage-phone/sync", params={"token": key}).status_code == 403)
        plan = cov.load_plan(pid)
        check("under the same id, with its shots", plan["name"] == "JD Rosebank" and len(plan["items"]) == 20 and plan["items"][0]["id"] == first, plan["name"])
        check("in the Mac's own form", plan["items"][0]["shot_size"] == "wide" and plan["items"][0]["source"] == "phone" and plan["moment_ids"]["Outside"] == 1)
        check("it counts as approved, since it already went to the crew", plan["approved_at"])
        path = cov.plan_dir(pid) / "on_set.json"
        check("its link is kept the way the Mac keeps its own", stat.S_IMODE(path.stat().st_mode) == 0o600)
        mac = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
        check("the Mac shows it live, with the same address and ticks", mac["live"] and mac["url"].endswith(f"#t={token2}") and mac["ticks"][first]["by"] == "B-cam" and mac["in_sync"], mac)
        check("the plan shows up on the Coverage page", any(p["id"] == pid for p in web.get("/post/coverage", params=MAIN).json()["plans"]))
        check("and its report works like any other", cov.report_pdf(pid)[:4] == b"%PDF")

        # ---- changes either way
        web.post(f"/set/manage/lists/{pid}/items/{first}", headers=K, json={"description": "Changed on the phone"})
        added = web.post(f"/set/manage/lists/{pid}/items", headers=K, json={"description": "New on the phone", "moment": "Backstage"}).json()
        new_id = next(i["id"] for i in added["items"] if i["description"] == "New on the phone")
        mac = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
        plan = cov.load_plan(pid)
        check("a change on the phone reaches the Mac", mac.get("adopted") and plan["items"][0]["description"] == "Changed on the phone" and any(i["id"] == new_id and i["source"] == "phone" for i in plan["items"]), mac)
        check("moments keep their numbers, and a new one gets its own", plan["moment_ids"]["Outside"] == 1 and plan["moment_ids"]["Backstage"] == 6, plan["moment_ids"])
        check("and the two are level", mac["in_sync"] is True and not web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json().get("adopted"))
        web.post(f"/post/coverage/{pid}/items/{first}", params=MAIN, json={"description": "Changed on the Mac"})
        check("a change on the Mac reaches the phone", next(i for i in web.get(f"/set/manage/lists/{pid}", headers=K).json()["items"] if i["id"] == first)["description"] == "Changed on the Mac")
        check("and doesn't come back around as a phone change", not web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json().get("adopted"))
        cov.update_item(pid, first, {"description": "Unsent edit on the Mac"})   # as if there was no signal when it was made
        web.post(f"/set/manage/lists/{pid}/items/{new_id}", headers=K, json={"owner": "C-cam"})
        mac = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
        check("a Mac edit that hasn't been sent isn't overwritten by a phone change", cov.load_plan(pid)["items"][0]["description"] == "Unsent edit on the Mac" and mac["in_sync"] is False and not mac.get("adopted"), mac)
        sent = web.post(f"/post/coverage/{pid}/on-set", params=MAIN, json={"shoot_date": mac["shoot_date"]}).json()
        check("sending it makes the Mac's list the live one", sent["in_sync"] is True and next(i for i in web.get(f"/set/manage/lists/{pid}", headers=K).json()["items"] if i["id"] == first)["description"] == "Unsent edit on the Mac")

        # ---- stopping from the phone, seen on the Mac
        web.delete(f"/set/manage/lists/{pid}/link", headers=K)
        mac = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
        check("a link stopped on the phone shows as stopped on the Mac", mac["live"] is False and "url" not in mac, mac)
        check("and the Mac forgets its address, so it can't bring it back", cov.on_set_local(pid)["token"] is None)
        check("the ticks stay for the report", mac["ticks"][first]["by"] == "B-cam")
        cov.approve(pid, True)
        remade = web.post(f"/post/coverage/{pid}/on-set", params=MAIN, json={"shoot_date": today}).json()
        check("a new link from the Mac has a new address", remade["live"] and not remade["url"].endswith(token2))
        check("and the old one stays dead", web.get("/set/state", headers=C2).status_code == 404)
        check("the phone sees the Mac's new address", web.get(f"/set/manage/lists/{pid}", headers=K).json()["token"] == remade["url"].split("#t=")[1])
        fresh = web.post(f"/set/manage/lists/{pid}/link", headers=K)   # already live: just pushes the date out
        check("turning on a live link changes nothing about its address", fresh.json()["token"] == remade["url"].split("#t=")[1])
        web.delete(f"/set/manage/lists/{pid}/link", headers=K)
        newer = web.post(f"/set/manage/lists/{pid}/link", headers=K).json()
        mac_after = web.get(f"/post/coverage/{pid}/on-set", params=MAIN).json()
        check("a stop and a new link on the phone, while the Mac was away, gives the Mac the new address", mac_after["live"] and mac_after["url"].endswith(newer["token"]), mac_after)

        # ---- a list made on the Mac, managed from the phone
        mplan = cov.new_plan("Made on the Mac", template=STARTER)
        cov.approve(mplan["id"], True)
        m = web.post(f"/post/coverage/{mplan['id']}/on-set", params=MAIN, json={"shoot_date": today}).json()
        on_phone = web.get(f"/set/manage/lists/{mplan['id']}", headers=K).json()
        check("a list made on the Mac shows on the phone, with its link", on_phone["token"] == m["url"].split("#t=")[1] and on_phone["source"] == "mac" and on_phone["total"] == 20, on_phone["source"])
        web.post(f"/set/manage/lists/{mplan['id']}/moment", headers=K, json={"moment": "Outside", "time": "09:00"})
        web.get(f"/post/coverage/{mplan['id']}/on-set", params=MAIN)
        check("times set on the phone reach the Mac", cov.load_plan(mplan["id"])["items"][0]["time"] == "09:00")

        # ---- templates
        tid = web.post(f"/post/coverage/{mplan['id']}/save-template", params=MAIN, json={"name": "My own list"}).json()["id"]
        names = [t["name"] for t in web.get("/set/manage/lists", headers=K).json()["templates"]]
        check("a template saved on the Mac is offered on the phone", names == ["Brand activation", "JD store opening", "My own list"], names)
        from_mine = web.post("/set/manage/lists", headers=K, json={"name": "From mine", "shoot_date": today, "template": tid}).json()
        check("and works there", from_mine["total"] == 20)
        web.delete(f"/post/coverage-templates/{tid}", params=MAIN)
        check("a deleted one goes away", [t["name"] for t in web.get("/set/manage/lists", headers=K).json()["templates"]] == ["Brand activation", "JD store opening"])
        from_brand = web.post("/set/manage/lists", headers=K, json={"name": "Any brand day", "shoot_date": today, "template": "t0000000000a2"}).json()
        check("a phone can start a list from the brand activation starter", from_brand["total"] == 20 and from_brand["must_left"] == 11, from_brand.get("total"))

        # ---- a starter that arrives in an update
        keep_seed, keep_replace, wrote = cov.CONFIG["starter_templates"], db.replace_templates, []
        async def spy_replace(templates, conn=None):
            wrote.append(len(templates))
            await keep_replace(templates, conn)
        db.replace_templates = spy_replace
        cov.CONFIG["starter_templates"] = [*keep_seed, {"id": "t0000000000f1", "name": "Arrived in an update", "items": [{"moment": "M", "description": "A shot", "priority": "must"}]}]
        on_phone_now = lambda: [t["name"] for t in web.get("/set/manage/lists", headers=K).json()["templates"]]
        check("a starter that arrives in an update isn't on a phone already set up", "Arrived in an update" not in on_phone_now())
        web.post("/post/coverage-phone/sync", params=MAIN)
        check("until Coverage Plans next opens on the Mac", on_phone_now() == ["Arrived in an update", "Brand activation", "JD store opening"], on_phone_now())
        web.post("/post/coverage-phone/sync", params=MAIN)
        check("and with nothing new, opening it again writes nothing", wrote == [3], wrote)
        web.delete("/post/coverage-templates/t0000000000f1", params=MAIN)
        db.replace_templates, cov.CONFIG["starter_templates"] = keep_replace, keep_seed

        # ---- turning the phone off
        phone_id = web.get("/post/coverage-phone", params=MAIN).json()["phones"][0]["id"]
        check("turning a phone off needs the main token", web.delete(f"/post/coverage-phone/{phone_id}", params={"token": key}).status_code == 403)
        check("turning it off works", web.delete(f"/post/coverage-phone/{phone_id}", params=MAIN).status_code == 200)
        check("it's locked out at once", web.get("/set/manage/lists", headers=K).status_code == 404)
        check("crew links it sent keep working until they're stopped", web.get("/set/state", headers={"X-Set-Token": m["url"].split("#t=")[1]}).status_code == 200)
        check("a new QR code gets a phone back in", web.post("/set/manage/claim", json={"code": web.post("/post/coverage-phone", json={}, params=MAIN).json()["url"].split("#s=")[1]}).status_code == 200)

        # ---- the pages
        page = (STATIC / "on_set_manage.html").read_text()
        code_js = (STATIC / "on_set_manage.js").read_text()
        qr = (STATIC / "on_set_qr.js").read_text()
        check("the owner's page allows no outside scripts or connections", "default-src 'none'" in page and "script-src 'self';" in page and "connect-src 'self'" in page)
        check("its scripts are files, so the policy can forbid inline ones", "<script>" not in page)
        check("no address leaks, and it asks not to be indexed", 'name="referrer" content="no-referrer"' in page and 'name="robots" content="noindex"' in page)
        check("nothing anyone typed goes in as HTML", "innerHTML" not in code_js and "innerHTML" not in qr and "insertAdjacentHTML" not in code_js)
        check("the page never touches the login: not in its address, its storage or its requests", "localStorage" not in code_js and "#k=" not in code_js and "X-Set-Manager" not in code_js and "token=" not in code_js and "document.cookie" not in code_js)
        check("a used setup code is taken out of the address", "history.replaceState" in code_js)
        check("it doesn't open as a separate Home Screen app, which wouldn't share the login", "apple-mobile-web-app-capable" not in page)
        check("QR codes are drawn on the page, not by an outside service", "http" not in qr.replace("http://www.w3.org/2000/svg", ""))
        worker = (STATIC / "on_set_sw.js").read_text()
        check("the offline copy never holds the owner's page", "manage" not in worker)

    check("nothing landed in the real data folder", sl.DATA != REAL_DATA and db.DB_PATH != REAL_DB and not (REAL_DB.parent / "fresh.db").exists())


main_tests()
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
