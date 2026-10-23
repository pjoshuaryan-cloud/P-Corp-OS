"""Tests for learning from a project that is NOT a POST shoot (2026-10-22: Josh started a social commercial edit by hand and wants it learned from):
post_learn.learn_from_project / analyse_unplanned / write_unplanned_log / is_clip_list, the auto-save watch's opt-in project list and plan-less settling
(post_autosave), and the routes. Temp folders only: nothing is written to his real learning data or watch settings. One read-only check uses his real HAUS
project on Lexar A when it is mounted. Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python learn_from_project_test.py"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_autosave as pa, post_learn as pl, post_learning_events as le  # noqa: E402
from learning import prproj  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


TMP = Path(tempfile.mkdtemp(prefix="lfp_"))
REAL = (pl.FEEDBACK_DIR, pl._REAL_FEEDBACK_DIR, le.CENTRAL_EVENTS)
pl.FEEDBACK_DIR = pl._REAL_FEEDBACK_DIR = TMP / "feedback"   # this test plays the 'real' log, in a temp folder
le.CENTRAL_EVENTS = TMP / "central" / "events.jsonl"
PROJECT = "/Volumes/Lexar - A/CLIENTS/BTS/BTS Commercial.prproj"


def shot(i, src_in, length, clip_seconds, t0, name=None, speed=1.0):
    return prproj.Shot(t0=t0, t1=t0 + length, src_in=src_in, src_out=src_in + length * speed, path=f"/Volumes/Lexar - A/CLIENTS/BTS/{name or f'C{i:04d}.MP4'}",
                       name=name or f"C{i:04d}.MP4", track=1, src_duration=clip_seconds, src_fps=50.0)


CUT = []
t = 0.0
for i in range(1, 13):   # 12 shots, 0.4-0.9 s from 8-20 s clips, two slowed: a cut
    L = 0.4 + (i % 4) * 0.15
    CUT.append(shot(i, 1.0 + i * 0.3, L, 8.0 + i, t, speed=0.5 if i in (4, 9) else 1.0))
    t += L
STRINGOUT = [shot(i, 0.0, 7.0 + i % 3, 7.0 + i % 3, i * 8.0) for i in range(1, 10)]   # whole clips laid end to end

# ---- identity, analysis, clip lists ---------------------------------------------------------------------------------------------------------------------
k1, k2 = pl.project_key(PROJECT), pl.project_key("/Volumes/Lexar - A/CLIENTS/OTHER/Other.prproj")
check("a project that isn't a shoot gets a stable NEGATIVE id (never a shoot number), different per project", k1 < 0 and k2 < 0 and k1 != k2 and k1 == pl.project_key(PROJECT), (k1, k2))
r = pl.analyse_unplanned(CUT)
check("his cut is recorded as it is: every shot 'not in plan', with its clip, in/out, timeline place, speed and media path",
      len(r["his_shots"]) == 12 and {x["status"] for x in r["his_shots"]} == {"not_in_plan"} and all(x["path"] and x["source_fps"] == 50.0 for x in r["his_shots"])
      and [x["speed"] for x in r["his_shots"]].count(0.5) == 2, r["his_shots"][:2])
check("...no plan warnings (there is no plan), and the record says it had none", not any("plan" in w for w in r["warnings"]) and r["no_plan"] and r["summary"]["no_plan"]
      and r["plan_basis"] == "none" and r["plan_shots"] == [], r["warnings"])
check("a cut is not a clip list; whole clips laid end to end are", not pl.is_clip_list(CUT) and pl.is_clip_list(STRINGOUT))

# ---- the log and the learning events -------------------------------------------------------------------------------------------------------------------
path, edits = pl.write_unplanned_log(PROJECT, "BTS cut v1", r)
rec = json.loads(path.read_text())
check("the feedback record carries the project, its id, the sequence and 'no plan'", rec["job_id"] == k1 and rec["project_path"] == PROJECT and rec["sequence"] == "BTS cut v1"
      and rec["no_plan"] is True and rec["shoot"] == "BTS Commercial", {k: rec[k] for k in ("job_id", "sequence", "no_plan", "shoot")})
idx = [json.loads(x) for x in (pl.FEEDBACK_DIR / "index.jsonl").read_text().splitlines()]
check("its index line says 'no plan' and names the project file", idx[-1]["no_plan"] is True and idx[-1]["project"] == "BTS Commercial.prproj")
agg = pl.aggregate()
check("it counts as a logged edit but stays out of the plan-agreement totals", agg["edits"] == 1 and agg["edits_compared_with_their_own_plan"] == 0, agg)
ev = le.load_events(le.CENTRAL_EVENTS)
check("its learning events go to the central store (there is no job folder): one 'added' per shot plus the two slowed shots", sum(e["outcome"] == "added" for e in ev) == 12
      and sum(e["outcome"] == "slowed" for e in ev) == 2, [e["outcome"] for e in ev][:5])
check("...all marked uncertain, with the honest reason (no plan), never votes", all(e["confidence"] == "uncertain" and e["context"].get("no_plan") for e in ev)
      and "without a P Corp plan" in ev[0]["context"]["why_uncertain"] and le.kind_evidence(ev) == {} and le.summarize(ev)["taste_votes"] == 0)
pl.FEEDBACK_DIR = TMP / "redirected"   # a log sent somewhere else (as other tests do) writes no events into the store it isn't
before = len(le.load_events(le.CENTRAL_EVENTS))
pl.write_unplanned_log(PROJECT, "BTS cut v2", r)
check("a redirected log writes no learning events", len(le.load_events(le.CENTRAL_EVENTS)) == before)
pl.FEEDBACK_DIR = pl._REAL_FEEDBACK_DIR

# ---- learn_from_project end to end (the project reader stubbed with the shots above) ------------------------------------------------------------------------
real_read = pl.read_final_edit
pl.read_final_edit = lambda p, s: ("BTS cut v3", CUT)
try:
    out = asyncio.run(pl.learn_from_project(PROJECT, "BTS cut v3"))
    check("learn_from_project returns the plugin's report: what it read, that there's no plan, the pace", out["lines"][0].startswith("Read your edit \"BTS cut v3\"")
          and any("isn't one of P Corp OS's shoots" in x for x in out["lines"]) and any("median shot" in x for x in out["lines"]) and out["project_id"] == k1, out["lines"])
    pl.read_final_edit = lambda p, s: ("horizontal", STRINGOUT)
    n_before = len(list(pl.FEEDBACK_DIR.glob("project*.json")))
    try:
        asyncio.run(pl.learn_from_project(PROJECT, "horizontal"))
        check("a stringout is refused (it would teach the wrong thing), and nothing is saved", False)
    except pl.NotACutYet as exc:
        check("a stringout is refused (it would teach the wrong thing), and nothing is saved", "laid end to end" in str(exc) and len(list(pl.FEEDBACK_DIR.glob("project*.json"))) == n_before, str(exc))
finally:
    pl.read_final_edit = real_read
HAUS = "/Volumes/Lexar - A/ALPHA MODE MEDIA '26/october/projects/HAUS WINE  - CAMPAIGN.prproj"
if os.path.exists(HAUS):
    seq, shots = pl.read_final_edit(HAUS, "horizontal")
    check("his real HAUS project (read-only): its 'horizontal' sequence is read, and recognised as whole clips laid end to end", len(shots) == 54 and pl.is_clip_list(shots), (seq, len(shots)))
else:
    print("SKIP his real HAUS project (Lexar - A not mounted)")

# ---- the watch: opt-in projects, plan-less settling -----------------------------------------------------------------------------------------------------------
store = pa.Store(TMP / "watch")
check("a project is added to the watch once", store.add_project(PROJECT) and not store.add_project(PROJECT) and len(store.projects()) == 1)
store.set_enabled(False)
check("switching the watch off (or on) never drops the projects list", store.projects()[0]["path"] == PROJECT and not store.enabled())
store.set_enabled(True)
pj = pa.project_job(PROJECT)
check("a watched project is a plan-less 'job' with the project's id", pj["id"] == k1 and pj["no_plan"] and pj["premiere_project_path"] == PROJECT)
now = time.time()


def snap(seq, shots, minutes_ago, h):
    rows = [[os.path.basename(s.path), round(s.src_in, 3), round(s.src_out, 3), round(s.t0, 3), round(s.length, 3), round(s.speed, 3), s.src_duration] for s in shots]
    shares = [(x[2] - x[1]) / x[6] for x in rows]
    import statistics
    store.append_snapshot(pj["id"], {"file": "a", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - minutes_ago * 60)), "sequence": seq,
                                     "built_at": None, "seconds": 9.0, "n": len(rows), "whole_clip": statistics.median(shares) >= pa.WHOLE_CLIP_SHARE, "hash": h, "shots": rows})


snap("BTS cut", CUT, 10, "h1")
snap("vertical", STRINGOUT, 60, "h2")
check("a cut changed 10 minutes ago is not finished yet; a clip list is never logged", pa.settle_job(store, pj, now=now) == [])
snap("BTS cut", CUT, 50, "h3")
check("once it has stopped changing for 45 minutes, his cut is logged by itself", pa.settle_job(store, pj, now=now) == ["BTS cut"])
check("...as a plan-less record of this project", json.loads(sorted(pl.FEEDBACK_DIR.glob("project*.json"))[-1].read_text())["source"] == "auto-save")
check("...and not again while it stays the same", pa.settle_job(store, pj, now=now + 600) == [])
st = pa.status(store, [])
check("the watch's status lists the project and what it saw", st["projects"][0]["project"] == PROJECT and {s["sequence"] for s in st["projects"][0]["sequences"]} == {"BTS cut", "vertical"}
      and next(s for s in st["projects"][0]["sequences"] if s["sequence"] == "BTS cut")["logged"] is True, st["projects"])
check("a project can be removed from the watch", store.remove_project(PROJECT) and store.projects() == [])

# ---- the routes ---------------------------------------------------------------------------------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402

calls = []


class TmpStore(pa.Store):
    def __init__(self, directory=TMP / "route_watch"):
        super().__init__(directory)


async def fake_jobs(status=None, postgres_conn=None):
    return [{"id": 48, "shoot_name": "GWM", "premiere_project_path": "/Volumes/Joshx SSD/GWM/10_PREMIERE/GWM.prproj"}]


async def fake_learn_edit(job, seq, path):
    calls.append(("shoot", job["id"]))
    return {"sequence": seq, "summary": {"his_shots": 3}, "lines": ["compared with the plan"]}


async def fake_learn_project(path, seq):
    calls.append(("project", path))
    if seq == "stringout":
        raise pl.NotACutYet("\"stringout\" is your clips laid end to end")
    if seq == "missing":
        raise pl.LearnError("The saved project has no sequence called \"missing\"")
    return {"sequence": seq, "summary": {"his_shots": 12}, "lines": ["Read your edit"]}


async def fake_audit(*a, **k):
    pass


saved = (main.list_post_jobs, pl.learn_from_edit, pl.learn_from_project, pa.Store, main.record_tool_call)
main.list_post_jobs, pl.learn_from_edit, pl.learn_from_project, pa.Store, main.record_tool_call = fake_jobs, fake_learn_edit, fake_learn_project, TmpStore, fake_audit
main.app.dependency_overrides[main.verify_token] = lambda: None
try:
    c = TestClient(main.app)
    r1 = c.post("/post/learn-from-project", json={"project_path": "/Volumes/Joshx SSD/GWM/10_PREMIERE/GWM.prproj", "sequence_name": "Edit"})
    check("a shoot's own project goes through the shoot's route (compared with its plan), and isn't added to the extra watch list",
          r1.status_code == 200 and calls[-1] == ("shoot", 48) and TmpStore().projects() == [], r1.text[:200])
    r2 = c.post("/post/learn-from-project", json={"project_path": PROJECT, "sequence_name": "BTS cut"})
    check("a project of his own is learned from as it is, and added to the watch", r2.status_code == 200 and calls[-1] == ("project", PROJECT) and r2.json()["watching"] is True
          and TmpStore().projects()[0]["path"] == PROJECT and any("Watching this project" in x for x in r2.json()["lines"]), r2.text[:300])
    r3 = c.post("/post/learn-from-project", json={"project_path": PROJECT, "sequence_name": "stringout"})
    check("a stringout: nothing saved, a plain explanation, and the project is still watched (so the cut is logged when it exists)",
          r3.status_code == 200 and r3.json()["logged"] is False and "laid end to end" in r3.json()["lines"][0] and any("already was" in x for x in r3.json()["lines"]), r3.text[:300])
    r4 = c.post("/post/learn-from-project", json={"project_path": PROJECT, "sequence_name": "missing"})
    check("a real problem (no such sequence) is a 400 with the reason", r4.status_code == 400 and "no sequence called" in r4.json()["detail"], r4.text[:200])
    r5 = c.post("/post/autosave-watch", json={"remove_project": PROJECT})
    check("the watch route removes a project", r5.status_code == 200 and TmpStore().projects() == [] and r5.json()["projects"] == [], r5.text[:200])
    r6 = c.post("/post/autosave-watch", json={"add_project": "/nowhere/x.prproj"})
    check("...and refuses to add something that isn't a saved project", r6.status_code == 400)
finally:
    main.list_post_jobs, pl.learn_from_edit, pl.learn_from_project, pa.Store, main.record_tool_call = saved
    main.app.dependency_overrides.clear()
    pl.FEEDBACK_DIR, pl._REAL_FEEDBACK_DIR, le.CENTRAL_EVENTS = REAL

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
