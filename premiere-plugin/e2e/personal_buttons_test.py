"""Personal's Remove and Done buttons (2026-11-07): the routes take exactly one goal or habit by id, hide it rather than wipe it, and only with
the main token. Temp databases and a made-up token only; set ON_SET_TEST_PG_DSN to a throwaway Postgres to also run the database part there.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python personal_buttons_test.py"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import audit_db, main, personal_db as pdb  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


tmp = Path(tempfile.mkdtemp())
REAL_PERSONAL, REAL_AUDIT = pdb.DB_PATH, audit_db.DB_PATH
pdb.DB_PATH = tmp / "personal.db"
audit_db.DB_PATH = tmp / "audit.db"
asyncio.run(pdb.init_personal_db())
asyncio.run(audit_db.init_audit_db())
main.AUTH_TOKEN = "made-up-main-token"
T = {"token": "made-up-main-token"}
web = TestClient(main.app)


def dashboard():
    return web.get("/personal/dashboard", params=T).json()


def goal_id(title):
    return next(g["id"] for g in dashboard()["goals"] if g["title"] == title)


def habit_id(title):
    return next(h["id"] for h in dashboard()["habits"] if h["title"] == title)


for title in ("Gym", "Gym 3x a week", "Read 12 books"):
    web.post("/personal/goals", params=T, json={"title": title})
for title in ("Pray", "Pray with Robin"):
    web.post("/personal/habits", params=T, json={"title": title})

gym = goal_id("Gym")
removed = web.delete(f"/personal/goals/{gym}", params=T)
check("Remove takes away exactly the goal it names", removed.status_code == 200 and removed.json() == {"removed": "Gym"}, removed.text)
titles = [g["title"] for g in dashboard()["goals"]]
check("and not one whose title merely contains it", "Gym 3x a week" in titles and "Gym" not in titles, titles)
check("removing it again says it isn't there", web.delete(f"/personal/goals/{gym}", params=T).status_code == 404)
check("nor is a goal that never was", web.delete("/personal/goals/999999", params=T).status_code == 404)


async def still_kept(table, row_id):
    import aiosqlite
    async with aiosqlite.connect(pdb.DB_PATH) as db:
        cur = await db.execute(f"SELECT deleted_at FROM {table} WHERE id = ?", (row_id,))
        row = await cur.fetchone()
        return row is not None and row[0] is not None


check("a removed goal is hidden, not wiped, so a wrong tap can be undone", asyncio.run(still_kept("goals", gym)))

books = goal_id("Read 12 books")
done = web.post(f"/personal/goals/{books}/status", params=T, json={"status": "done"})
check("Done marks a goal done", done.status_code == 200 and {g["title"]: g["status"] for g in dashboard()["goals"]}["Read 12 books"] == "done", done.text)
check("and it stays on the list", "Read 12 books" in [g["title"] for g in dashboard()["goals"]])
again = web.post(f"/personal/goals/{books}/status", params=T, json={"status": "active"})
check("Not done puts it back to active", again.status_code == 200 and {g["title"]: g["status"] for g in dashboard()["goals"]}["Read 12 books"] == "active")
check("only active or done", web.post(f"/personal/goals/{books}/status", params=T, json={"status": "deleted"}).status_code == 422)
check("a removed goal can't be marked done", web.post(f"/personal/goals/{gym}/status", params=T, json={"status": "done"}).status_code == 404)

pray = habit_id("Pray")
gone = web.delete(f"/personal/habits/{pray}", params=T)
check("Remove takes away exactly the habit it names", gone.status_code == 200 and gone.json() == {"removed": "Pray"}, gone.text)
check("and leaves the one that only shares a word", [h["title"] for h in dashboard()["habits"]] == ["Pray with Robin"], dashboard()["habits"])
check("a removed habit is hidden, not wiped", asyncio.run(still_kept("habits", pray)))
check("removing it again says it isn't there", web.delete(f"/personal/habits/{pray}", params=T).status_code == 404)

for label, params in (("no token", {}), ("a wrong token", {"token": "nope"})):
    left = goal_id("Gym 3x a week")
    check(f"{label} can't remove a goal", web.delete(f"/personal/goals/{left}", params=params).status_code in (403, 422))
    check(f"{label} can't mark one done", web.post(f"/personal/goals/{left}/status", params=params, json={"status": "done"}).status_code in (403, 422))
    check(f"{label} can't remove a habit", web.delete(f"/personal/habits/{habit_id('Pray with Robin')}", params=params).status_code in (403, 422))
check("so nothing changed without the token", "Gym 3x a week" in [g["title"] for g in dashboard()["goals"]] and dashboard()["habits"])


async def audit_names():
    import aiosqlite
    async with aiosqlite.connect(audit_db.DB_PATH) as db:
        cur = await db.execute("SELECT tool_name FROM tool_calls")
        return [r[0] for r in await cur.fetchall()]


names = asyncio.run(audit_names())
check("each button press is in the audit log, like Frank's own changes", {"delete_goal_ui", "update_goal_status_ui", "delete_habit_ui"} <= set(names), names)
check("the real databases were never touched", pdb.DB_PATH != REAL_PERSONAL and audit_db.DB_PATH != REAL_AUDIT)


async def postgres(dsn):
    import psycopg
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("CREATE SCHEMA IF NOT EXISTS personal")
            await cur.execute("DROP TABLE IF EXISTS personal.goals, personal.habits")
            await cur.execute("CREATE TABLE personal.goals (id SERIAL PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', target_date TEXT, notes TEXT, created_at TIMESTAMP DEFAULT now(), deleted_at TIMESTAMP)")
            await cur.execute("CREATE TABLE personal.habits (id SERIAL PRIMARY KEY, title TEXT NOT NULL, cadence TEXT, notes TEXT, created_at TIMESTAMP DEFAULT now(), deleted_at TIMESTAMP)")
            await cur.execute("INSERT INTO personal.goals (title) VALUES ('Gym'), ('Gym 3x a week') RETURNING id")
            gym_pg, other_pg = [r[0] for r in await cur.fetchall()]
            await cur.execute("INSERT INTO personal.habits (title) VALUES ('Pray') RETURNING id")
            pray_pg = (await cur.fetchone())[0]
        await conn.commit()
        check("Postgres: Remove takes away exactly that goal", await pdb.remove_goal_by_id(gym_pg, conn) == "Gym")
        snap = await pdb.dashboard_snapshot(conn)
        check("Postgres: the other one stays", [g["title"] for g in snap["goals"]] == ["Gym 3x a week"], snap)
        check("Postgres: and again finds nothing", await pdb.remove_goal_by_id(gym_pg, conn) is None)
        check("Postgres: Done marks a goal done", await pdb.set_goal_status_by_id(other_pg, "done", conn) == "Gym 3x a week" and (await pdb.dashboard_snapshot(conn))["goals"][0]["status"] == "done")
        check("Postgres: a removed goal can't be marked done", await pdb.set_goal_status_by_id(gym_pg, "done", conn) is None)
        check("Postgres: Remove takes away a habit", await pdb.remove_habit_by_id(pray_pg, conn) == "Pray" and (await pdb.dashboard_snapshot(conn))["habits"] == [])
        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) FROM personal.goals WHERE deleted_at IS NOT NULL")
            check("Postgres: removed rows are kept, hidden", (await cur.fetchone())[0] == 1)
            await cur.execute("DROP TABLE personal.goals, personal.habits")
        await conn.commit()


dsn = os.environ.get("ON_SET_TEST_PG_DSN")
if dsn:
    asyncio.run(postgres(dsn))
else:
    print("SKIP Postgres: ON_SET_TEST_PG_DSN isn't set")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
