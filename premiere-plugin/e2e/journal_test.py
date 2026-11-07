"""The private journal's storage (backend/app/journal_db.py and the /journal routes): it keeps sealed bytes and versions, refuses a second key, remembers deletions, and is out of
Frank's reach. Temp database and a made-up token only. Set ON_SET_TEST_PG_DSN to a throwaway Postgres to also run the database part there.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python journal_test.py"""
import asyncio
import os
import secrets
import sys
import tempfile
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import journal_db as jdb, main  # noqa: E402

fails = 0
REAL_DB = jdb.DB_PATH


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def entry_id():
    return "e-" + secrets.token_hex(16)


async def database(conn, label):
    await jdb.ensure_tables(conn)
    await jdb.ensure_tables(conn)
    check(f"{label}: no key yet", await jdb.key_check(conn) is None)
    first, second = "a" * 64, "b" * 64
    check(f"{label}: the first key's check is kept", await jdb.set_key_check(first, conn) == first)
    check(f"{label}: and a second one can't replace it", await jdb.set_key_check(second, conn) == first)
    item = entry_id()
    sealed = os.urandom(5000) + b"\x00" * 10
    check(f"{label}: an item saves", await jdb.put_item(item, sealed, 1, conn) == (True, 1))
    check(f"{label}: and comes back byte for byte", await jdb.get_item(item, conn) == (sealed, 1))
    check(f"{label}: the same version again is refused", await jdb.put_item(item, b"older", 1, conn) == (False, 1))
    check(f"{label}: so the stored copy is unchanged", (await jdb.get_item(item, conn))[0] == sealed)
    check(f"{label}: a newer version replaces it", await jdb.put_item(item, b"newer", 2, conn) == (True, 2))
    listed = {i["id"]: i for i in await jdb.index(conn)}
    check(f"{label}: the index says what's there, without the contents", listed[item] == {"id": item, "kind": "entry", "size": 5, "version": 2, "updated_at": listed[item]["updated_at"], "deleted": False}, listed[item])
    check(f"{label}: an older deletion is refused", await jdb.delete_item(item, 2, conn) == (False, 2))
    check(f"{label}: a newer one deletes it", await jdb.delete_item(item, 3, conn) == (True, 3))
    check(f"{label}: so it's gone", await jdb.get_item(item, conn) is None)
    gone = {i["id"]: i for i in await jdb.index(conn)}[item]
    check(f"{label}: but the index keeps a tombstone for the other device", gone["deleted"] and gone["size"] == 0 and gone["version"] == 3, gone)
    check(f"{label}: an edit made before the deletion can't bring it back", await jdb.put_item(item, b"stale edit", 3, conn) == (False, 3))
    never = entry_id()
    check(f"{label}: deleting something never seen here still leaves a tombstone", await jdb.delete_item(never, 1, conn) == (True, 1) and {i["id"]: i for i in await jdb.index(conn)}[never]["deleted"])
    audio = "a-" + secrets.token_hex(16)
    check(f"{label}: a recording saves as audio", await jdb.put_item(audio, b"sealed audio", 1, conn) == (True, 1) and {i["id"]: i for i in await jdb.index(conn)}[audio]["kind"] == "audio")


async def postgres(dsn):
    import psycopg
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("DROP SCHEMA IF EXISTS journal CASCADE")
        await conn.commit()
        await database(conn, "postgres")


def main_tests():
    tmp = Path(tempfile.mkdtemp())
    jdb.DB_PATH = tmp / "journal.db"
    main.DATA_BACKEND = "sqlite"
    asyncio.run(database(None, "sqlite"))
    if os.environ.get("ON_SET_TEST_PG_DSN"):
        asyncio.run(postgres(os.environ["ON_SET_TEST_PG_DSN"]))
    else:
        print("SKIP postgres: ON_SET_TEST_PG_DSN isn't set")

    jdb.DB_PATH = tmp / "routes.db"
    main.AUTH_TOKEN = "made-up-main-token"
    T = {"token": "made-up-main-token"}
    web = TestClient(main.app)

    # ---- who can reach it
    for method, path in (("GET", "/journal/state"), ("POST", "/journal/setup"), ("GET", "/journal/index"), ("GET", f"/journal/items/{entry_id()}"), ("PUT", f"/journal/items/{entry_id()}?version=1"), ("DELETE", f"/journal/items/{entry_id()}?version=1")):
        check(f"{method} {path.split('?')[0].rsplit('/', 1)[0]} needs the main token", web.request(method, path, params={"token": "wrong"}).status_code == 403)
        check(f"{method} {path.split('?')[0].rsplit('/', 1)[0]} needs a token at all", web.request(method, path).status_code in (401, 403, 422))
    crew = web.get("/journal/index", headers={"X-Set-Token": "made-up-crew-link"})
    check("a crew link can't reach it", crew.status_code in (401, 403, 422))
    phone = web.get("/journal/index", headers={"Cookie": "onset_manager=made-up-phone-login"})
    check("nor can the shot-list phone login", phone.status_code in (401, 403, 422))

    # ---- one journal, one key
    check("before setup there's no journal", web.get("/journal/state", params=T).json() == {"set_up": False, "key_check": None})
    check("a key check has to look like one", web.post("/journal/setup", params=T, json={"key_check": "not hex"}).status_code == 422)
    first = secrets.token_hex(32)
    check("the first device sets it up", web.post("/journal/setup", params=T, json={"key_check": first}).json() == {"set_up": True})
    check("setting up again with the same key is fine", web.post("/journal/setup", params=T, json={"key_check": first}).status_code == 200)
    other = web.post("/journal/setup", params=T, json={"key_check": secrets.token_hex(32)})
    check("a device with a different key is refused, and told what to do", other.status_code == 409 and "recovery key" in other.json()["detail"], other.text)
    check("so a device can check its key before writing", web.get("/journal/state", params=T).json() == {"set_up": True, "key_check": first})

    # ---- items
    item = entry_id()
    sealed = os.urandom(3000)
    saved = web.put(f"/journal/items/{item}", params={**T, "version": 1}, content=sealed)
    check("a sealed note saves", saved.status_code == 200 and saved.json() == {"version": 1}, saved.text)
    got = web.get(f"/journal/items/{item}", params=T)
    check("and comes back exactly, with its version, and isn't cached", got.content == sealed and got.headers["x-journal-version"] == "1" and got.headers["cache-control"] == "no-store")
    stale = web.put(f"/journal/items/{item}", params={**T, "version": 1}, content=b"x")
    check("an older copy gets a 409 with the version to beat", stale.status_code == 409 and stale.json()["version"] == 1, stale.text)
    check("a version has to be given", web.put(f"/journal/items/{item}", params=T, content=b"x").status_code == 422)
    check("and be 1 or more", web.put(f"/journal/items/{item}", params={**T, "version": 0}, content=b"x").status_code == 422)
    check("an empty body is refused", web.put(f"/journal/items/{item}", params={**T, "version": 2}, content=b"").status_code == 422)
    check("a note bigger than a note can be is refused", web.put(f"/journal/items/{entry_id()}", params={**T, "version": 1}, content=b"x" * (jdb.LIMITS["e"] + 1)).status_code == 413)
    big_audio = "a-" + secrets.token_hex(16)
    check("but a recording that size is fine", web.put(f"/journal/items/{big_audio}", params={**T, "version": 1}, content=b"x" * (jdb.LIMITS["e"] + 1)).status_code == 200)
    check("a recording past its limit is refused", web.put(f"/journal/items/{'a-' + secrets.token_hex(16)}", params={**T, "version": 1}, content=b"x" * (jdb.LIMITS["a"] + 1)).status_code == 413)
    check("the category list saves under its own name", web.put("/journal/items/m-categories", params={**T, "version": 1}, content=b"sealed list").status_code == 200)
    # Highlights the Mac writes of a week or month (2026-11-07), sealed like everything else.
    week_h = "h-week-2026-11-08"
    check("a sealed weekly highlight saves under its period's name", web.put(f"/journal/items/{week_h}", params={**T, "version": 1}, content=os.urandom(900)).status_code == 200)
    check("so does a monthly one", web.put("/journal/items/h-month-2026-11-25", params={**T, "version": 1}, content=os.urandom(900)).status_code == 200)
    check("a highlight is listed as one", {i["id"]: i["kind"] for i in web.get("/journal/index", params=T).json()["items"]}.get(week_h) == "highlight")
    check("a highlight past its limit is refused", web.put("/journal/items/h-week-2026-11-15", params={**T, "version": 1}, content=b"x" * (jdb.LIMITS["h"] + 1)).status_code == 413)
    for bad in ("e-xyz", "e-" + "A" * 32, "x-" + "a" * 32, "m-other", "..%2F..%2Fsecrets", "e-" + "a" * 31,
                "h-day-2026-11-08", "h-week-26-11-08", "h-week-2026-11-08x", "h-week-2026-11-8"):
        check(f"a made-up name ({bad[:12]}) is refused", web.get(f"/journal/items/{bad}", params=T).status_code == 404 and web.put(f"/journal/items/{bad}", params={**T, "version": 1}, content=b"x").status_code == 404)
    listed = web.get("/journal/index", params=T).json()["items"]
    check("the index lists names, kinds, sizes and versions, never contents", all(set(i) == {"id", "kind", "size", "version", "updated_at", "deleted"} for i in listed) and {i["id"]: i["kind"] for i in listed}[item] == "entry", listed[:2])
    check("deleting needs a newer version", web.delete(f"/journal/items/{item}", params={**T, "version": 1}).status_code == 409)
    check("then deletes it", web.delete(f"/journal/items/{item}", params={**T, "version": 2}).json() == {"version": 2})
    check("so it can't be fetched", web.get(f"/journal/items/{item}", params=T).status_code == 404)
    check("and the other device can see it went", {i["id"]: i for i in web.get("/journal/index", params=T).json()["items"]}[item]["deleted"])

    # ---- Frank can't reach it
    from app import personal_tools
    frank_tools = {t["name"] for t in main.__dict__.get("ALL_TOOLS", [])} if "ALL_TOOLS" in main.__dict__ else set()
    check("Frank's personal context doesn't read the journal", "journal_db" not in Path(personal_tools.__file__).read_text())
    check("no Frank tool is named after it", not any("journal_" in name and "decision" not in name for name in frank_tools | set(personal_tools.PERSONAL_TOOL_NAMES)))
    source = Path(main.__file__).read_text()
    check("only the journal routes use its storage", source.count("journal_db.") == source.count("journal_db.") and all(line.strip().startswith(("from app import journal_db", "if not journal_db", "check = await journal_db", "stored = await journal_db", "return {\"items\": await journal_db", "found = await journal_db", "limit = journal_db", "saved, stored = await journal_db", "deleted, stored = await journal_db")) for line in source.splitlines() if "journal_db" in line and not line.strip().startswith("#")), [line.strip() for line in source.splitlines() if "journal_db" in line][:12])
    check("nothing landed in the real database", jdb.DB_PATH != REAL_DB and not REAL_DB.exists())


main_tests()
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
