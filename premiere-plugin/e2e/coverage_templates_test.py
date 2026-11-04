"""Saved shot lists to start coverage plans from (backend/app/post_coverage.py and its routes). Temp files only: no drive, no API call, nothing under backend/data is touched. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python coverage_templates_test.py"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, post_coverage as cov, post_shoot_log as sl  # noqa: E402

fails = 0
REAL_DATA = sl.DATA
STARTER = "t0000000000a1"


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def refused(fn, *args):
    try:
        fn(*args)
        return False
    except sl.ShootLogError:
        return True


tmp = Path(tempfile.mkdtemp())
sl.DATA = tmp / "shoot_logs"
main.AUTH_TOKEN = "main-secret-token-for-this-test"
MAIN = {"token": main.AUTH_TOKEN}
pushed = []


async def fake_push(plan_id):
    pushed.append(plan_id)
main._on_set_push_quietly = fake_push
web = TestClient(main.app)

# ---- the starter list
listed = cov.list_templates()
check("the JD store opening list is there from the start", [t["name"] for t in listed] == ["JD store opening"] and listed[0]["shots"] == 20, listed)
starter = cov.load_template(STARTER)
check("it has no times, because every run sheet differs", all("time" not in i for i in starter["items"]))
check("it starts as a list of real must-haves and should-haves", listed[0]["must"] == 11 and {i["priority"] for i in starter["items"]} == {"must", "should"}, listed)
check("every shot uses the words the rest of coverage understands", all(i["shot_size"] in cov.SHOT_SIZES and i["priority"] in cov.PRIORITIES for i in starter["items"]))
check("its moments run in the order of a store opening", list(dict.fromkeys(i["moment"] for i in starter["items"])) == ["Outside", "Opening", "In store", "Entertainment", "Reactions"])
check("it's offered on the Coverage page", web.get("/post/coverage", params=MAIN).json()["templates"][0]["id"] == STARTER)

# ---- a plan from a template
made = web.post("/post/coverage", params=MAIN, json={"name": "JD Monday", "client": "JD Sports", "template": STARTER}).json()
check("a new plan can start from it", len(made["items"]) == 20 and made["client"] == "JD Sports", made)
check("it's still a draft a person has to read and approve", made["approved_at"] is None)
check("its shots get their own ids, in order", [i["id"] for i in made["items"]][:3] == ["i1", "i2", "i3"] and made["next_item"] == 21)
check("they're marked as coming from a template", {i["source"] for i in made["items"]} == {"template"})
check("they start with no time, ready for this shoot's run sheet", all(i["time"] == "" for i in made["items"]))
check("each moment gets its number, for By Moment bins", made["moment_ids"] == {"Outside": 1, "Opening": 2, "In store": 3, "Entertainment": 4, "Reactions": 5}, made["moment_ids"])
pid = made["id"]
check("it can be approved straight away", cov.approve(pid, True)["approved_at"])
before = len(cov.list_plans())
bad = web.post("/post/coverage", params=MAIN, json={"name": "Bad", "template": "t" + "f" * 12})
check("a template that doesn't exist is refused, and leaves no empty plan behind", bad.status_code == 400 and len(cov.list_plans()) == before, bad.text)
for name in ("../../secret", "t123", "c" + "0" * 12, ""):
    check(f"{name!r} can't be read as a template", refused(cov.load_template, name))
check("a path in the address can't reach a file", web.delete("/post/coverage-templates/..%2F..%2Fplan", params=MAIN).status_code in (400, 404))

# ---- editing never reaches back
cov.update_item(pid, "i1", {"description": "Changed for this job", "time": "09:00"})
check("changing a plan doesn't change the template", cov.load_template(STARTER)["items"][0]["description"] == "JD logo with the venue sign")
second = cov.new_plan("Next JD", template=STARTER)
check("the next plan gets the template as it was", second["items"][0]["description"] == "JD logo with the venue sign" and second["id"] != pid)

# ---- saving your own
cov.update_item(pid, "i2", {"owner": "A-cam"})
cov.approve(pid, True)
saved = web.post(f"/post/coverage/{pid}/save-template", params=MAIN, json={"name": "Store opening, my version"}).json()
check("a plan can be saved as a template", saved["shots"] == 20 and saved["replaced"] is False, saved)
mine = cov.load_template(saved["id"])
check("it keeps the shots as you changed them, and who's shooting them", mine["items"][0]["description"] == "Changed for this job" and mine["items"][1]["owner"] == "A-cam")
check("it leaves times and plan history behind", all(set(i) == set(cov.TEMPLATE_FIELDS) for i in mine["items"]), mine["items"][0])
check("saving doesn't change the plan or its approval", cov.load_plan(pid)["approved_at"] and cov.load_plan(pid)["items"][0]["time"] == "09:00")
check("both show on the list, by name", [t["name"] for t in cov.list_templates()] == ["JD store opening", "Store opening, my version"])
cov.update_item(pid, "i3", {"description": "Another change"})
again = cov.save_template(pid, "STORE OPENING, my version")
check("the same name replaces the old one, whatever the capitals", again["replaced"] and again["id"] == saved["id"] and len(cov.list_templates()) == 2, again)
check("and holds the new shots", cov.load_template(saved["id"])["items"][2]["description"] == "Another change")
check("a template needs a name", refused(cov.save_template, pid, "   "))
check("an empty list can't be saved", refused(cov.save_template, cov.new_plan("Empty")["id"], "Nothing"))
check("a long name is cut to size", len(cov.save_template(pid, "x" * 200)["name"]) == 80)
cov.delete_template(cov.list_templates()[-1]["id"])

# ---- adding to a plan that already has shots
plain = cov.new_plan("Has shots")
kept = cov.add_item(plain["id"], {"moment": "Outside", "description": "Full store front", "time": "10:00", "owner": "B-cam", "priority": "should"})
own = cov.add_item(plain["id"], {"moment": "Backstage", "description": "Staff briefing"})
cov.approve(plain["id"], True)
out = web.post(f"/post/coverage/{plain['id']}/add-template", params=MAIN, json={"template": STARTER}).json()
now = cov.load_plan(plain["id"])
check("adding a template to a plan leaves out what it already has", out == {"added": 19, "skipped": 1} and len(now["items"]) == 21, out)
check("a shot you already had keeps your details", next(i for i in now["items"] if i["id"] == kept["id"])["time"] == "10:00" and next(i for i in now["items"] if i["id"] == kept["id"])["owner"] == "B-cam")
check("and your other shots stay", any(i["id"] == own["id"] for i in now["items"]))
check("a changed list needs approving again", now["approved_at"] is None)
check("phones get the new list if there's a live link", pushed == [plain["id"]], pushed)
cov.approve(plain["id"], True)
out = cov.add_from_template(plain["id"], STARTER)
check("adding it twice changes nothing, and keeps the approval", out == {"added": 0, "skipped": 20} and cov.load_plan(plain["id"])["approved_at"], out)

# ---- deleting
web.delete(f"/post/coverage-templates/{saved['id']}", params=MAIN)
check("a saved template can be deleted", [t["id"] for t in cov.list_templates()] == [STARTER])
check("plans made from a deleted template don't change", len(cov.load_plan(pid)["items"]) == 20)
web.delete(f"/post/coverage-templates/{STARTER}", params=MAIN)
check("the starter list can be deleted too", cov.list_templates() == [])
check("and it stays deleted, rather than coming back", cov.list_templates() == [] and refused(cov.load_template, STARTER))
check("deleting one that's gone says so", web.delete(f"/post/coverage-templates/{STARTER}", params=MAIN).status_code == 400)
keep_seed = cov.CONFIG["starter_templates"]
cov.CONFIG["starter_templates"] = [*keep_seed, {"id": "t0000000000a2", "name": "New starter", "items": [{"moment": "M", "description": "A shot", "priority": "must"}]}]
check("a new starter added later comes in, without bringing a deleted one back", [t["name"] for t in cov.list_templates()] == ["New starter"])
cov.CONFIG["starter_templates"] = keep_seed

# ---- who can do this
for method, path, body in (("GET", "/post/coverage", None), ("POST", f"/post/coverage/{pid}/save-template", {"name": "x"}), ("POST", f"/post/coverage/{pid}/add-template", {"template": STARTER}), ("DELETE", f"/post/coverage-templates/{STARTER}", None)):
    check(f"{method} {path.split('/')[-1]} needs the main token", web.request(method, path, params={"token": "wrong"}, json=body).status_code == 403)
check("nothing landed in the real data folder", sl.DATA != REAL_DATA and not (REAL_DATA / "coverage_templates" / "seeded-by-test").exists())
config = json.loads((Path(cov.__file__).parent / "shoot_log_config.json").read_text())
check("the starter list ships with the code, so it isn't lost with the data folder", config["coverage"]["starter_templates"][0]["id"] == STARTER)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
