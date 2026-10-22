"""Tests for the auto-save watch (backend/app/post_autosave.py) and the plan matching it relies on (post_plan_history.plan_for_build_time):
synthetic projects with a stand-in reader, then Josh's real GWM auto-saves when the SSD is mounted (read-only; everything it writes goes to a temp folder).
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python autosave_test.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_autosave as pa, post_learn, post_plan_history as ph  # noqa: E402
from app.ssd_guard import DriveNotConnected  # noqa: E402
from learning import prproj  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


def shot(clip, a, b, t0, length=None, dur=30.0, track=1):
    length = (b - a) if length is None else length
    return prproj.Shot(t0=t0, t1=t0 + length, src_in=a, src_out=b, path=f"/x/{clip}", name=clip, track=track, src_duration=dur)


def seq(name, n=6, whole=False, start=0):
    shots = [shot(f"C{start + i}.MP4", 1.0 + i, (30.0 if whole else 1.6 + i), 2.0 * i, 0.6 if not whole else 29.0) for i in range(n)]
    return prproj.Sequence(name=name, out_mark=None, in_mark=None, tracks=[shots])


# ---- names and folders ------------------------------------------------------------------------------------------------------------------
check("an auto-save's time is read from its name", abs(pa.stamp_of("GWM--b995-2026-10-15_18-44-39.prproj") - time.mktime((2026, 10, 15, 18, 44, 39, 0, 0, -1))) < 1 and pa.stamp_of("GWM.prproj") is None)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    proj_dir = root / "shoot" / "10_PREMIERE"
    beta = proj_dir / "Adobe Premiere Pro (Beta) Auto-Save"
    rel = proj_dir / "Adobe Premiere Pro Auto-Save"
    beta.mkdir(parents=True); rel.mkdir(parents=True)
    project = proj_dir / "GWM.prproj"
    project.write_bytes(b"main")
    old = time.time() - 3 * 3600
    files = {}
    for name, folder, at in (("GWM--u-2026-10-15_10-00-00.prproj", beta, old), ("GWM--u-2026-10-15_10-06-00.prproj", beta, old + 360), ("GWM--u-2026-10-15_10-12-00.prproj", rel, old + 720)):
        p = folder / name; p.write_bytes(name.encode()); os.utime(p, (at, at)); files[name] = p
    (beta / "._GWM--u-2026-10-15_10-18-00.prproj").write_bytes(b"x")
    (beta / "notes.txt").write_text("x")
    os.utime(project, (old + 900, old + 900))
    sources = pa.list_sources(str(project))
    check("it finds the auto-saves in both Premiere folder names and the saved project, oldest first", [os.path.basename(s["path"]) for s in sources][-1] == "GWM.prproj" and len(sources) == 4 and sources[-1]["main"] and [s["at"] for s in sources] == sorted(s["at"] for s in sources), [os.path.basename(s["path"]) for s in sources])
    check("it ignores hidden copies and files that aren't projects", not any("._" in s["path"] or s["path"].endswith(".txt") for s in sources))
    check("a project with no auto-save folder just has itself", [s["main"] for s in pa.list_sources(str(root / "nowhere" / "X.prproj"))] == [])

    # ---- snapshots ---------------------------------------------------------------------------------------------------------------------
    def reader_for(content):
        return lambda path: content[os.path.basename(path)]

    edit_name = "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z"
    snaps = pa.snapshot_sequences("x.prproj", lambda p: [seq(edit_name, 6), seq("tiny", 3), seq("GWM - Highlight Video", 8, whole=True), prproj.Sequence("two tracks", None, None, [[], [shot("A.MP4", 1, 2, 0, track=2)] * 6])])
    by = {s["sequence"]: s for s in snaps}
    check("a sequence with fewer than five shots on video 1 is not an edit (nor is footage only on video 2)", set(by) == {edit_name, "GWM - Highlight Video"}, list(by))
    check("a sequence of mostly whole clips is flagged as a clip list, not an edit", by["GWM - Highlight Video"]["whole_clip"] and not by[edit_name]["whole_clip"])
    check("the build time comes from the sequence's name and shots are compact rows", by[edit_name]["built_at"] is not None and len(by[edit_name]["shots"][0]) == 7 and by[edit_name]["shots"][0][0] == "C0.MP4")

    # ---- scanning ----------------------------------------------------------------------------------------------------------------------
    store = pa.Store(root / "store")
    job = {"id": 7, "premiere_project_path": str(project), "shoot_name": "GWM", "profile": "alpha_mode", "destination_root": str(root / "shoot")}
    content = {n: [seq(edit_name, 6 + i)] for i, n in enumerate(files)}        # each auto-save has one more shot than the one before
    content["GWM.prproj"] = [seq(edit_name, 9)]
    r = pa.scan_job(store, job, budget=2, reader=reader_for(content))
    check("it reads at most `budget` files a pass, oldest first", r["read"] == 2 and r["pending"] == 2 and r["new_states"] == 2, r)
    r = pa.scan_job(store, job, budget=10, reader=reader_for(content))
    check("the next pass reads the rest and not the ones it already read", r["read"] == 2 and r["pending"] == 0 and r["new_states"] == 2, r)
    states = store.snapshots(7)
    check("each different state of the sequence is kept in order, with its time", [s["n"] for s in states] == [6, 7, 8, 9] and [s["at"] for s in states] == sorted(s["at"] for s in states), [s["n"] for s in states])
    r = pa.scan_job(store, job, budget=10, reader=reader_for(content))
    check("nothing new on a third pass", r["read"] == 0 and r["new_states"] == 0 and r["pending"] == 0, r)
    os.utime(project, (old + 5000, old + 5000)); content["GWM.prproj"] = [seq(edit_name, 12)]
    r = pa.scan_job(store, job, budget=10, reader=reader_for(content))
    check("when the saved project file changes it is read again, and the new state is kept", r["read"] == 1 and store.snapshots(7)[-1]["n"] == 12, r)
    content["GWM.prproj"] = [seq(edit_name, 12)]
    os.utime(project, (old + 6000, old + 6000))
    check("a re-save with the same shots adds no new state", pa.scan_job(store, job, budget=10, reader=reader_for(content))["new_states"] == 0)

    # a file Premiere is still writing, and a file that can't be read
    fresh = beta / "GWM--u-2026-10-21_09-00-00.prproj"; fresh.write_bytes(b"new")
    r = pa.scan_job(store, job, budget=10, reader=reader_for({**content, fresh.name: [seq(edit_name, 13)]}))
    check("a file touched in the last 20 seconds is left for next time", r["read"] == 0 and len(store.snapshots(7)) == 5, r)
    os.utime(fresh, (time.time() - 60, time.time() - 60))
    calls = []
    def broken(path):
        calls.append(path); raise ValueError("truncated gzip")
    for _ in range(5):
        pa.scan_job(store, job, budget=10, reader=broken)
    check("an unreadable file is tried three times and then left alone", len(calls) == 3, len(calls))
    check("and it does not stop the other files being read", pa.scan_job(store, job, budget=10, reader=reader_for({**content, fresh.name: [seq(edit_name, 13)]}))["read"] == 0)

    # ---- the drive guard ----------------------------------------------------------------------------------------------------------------
    try:
        pa.scan_job(store, {"id": 8, "premiere_project_path": "/Volumes/ZZ Not Plugged In/x/GWM.prproj"}, reader=reader_for({}))
        raised = False
    except DriveNotConnected:
        raised = True
    check("a shoot on a drive that isn't plugged in is skipped with the drive guard's error, never read", raised)
    check("a shoot with no Premiere project yet is skipped quietly", pa.scan_job(store, {"id": 9, "premiere_project_path": None}, reader=reader_for({})) == {"read": 0, "new_states": 0, "failed": 0, "pending": 0})

    # ---- switching it off ---------------------------------------------------------------------------------------------------------------
    check("it is on by default", store.enabled())
    store.set_enabled(False)
    off = not store.enabled()
    store.set_enabled(True)
    check("the off switch sticks, and switching it back on works", off and store.enabled())

    # ---- finished edits become automatic learn records -------------------------------------------------------------------------------------
    plans = root / "shoot" / "10_PREMIERE" / "edit_plans"
    plans.mkdir(parents=True)
    def write_plan(name, tag, at, clips):
        p = plans / name
        p.write_text(json.dumps({"style": "corporate-highlight-calm", "duration_seconds": 40.0, "tag": tag,
                                 "shots": [{"index": i + 1, "name": c, "path": f"/y/{c}", "source_in": 1.0 + i, "source_out": 3.0 + i, "file_id": i} for i, c in enumerate(clips)]}))
        os.utime(p, (at, at))
    built = prproj_built = post_learn.built_at(edit_name)
    write_plan("edit_plan_prev_20261015T154553.json", "the plan it was built from", built - 700, [f"C{i}.MP4" for i in range(6)])
    write_plan("edit_plan_prev_20261015T160141.json", "a later selects plan", built + 400, [f"Z{i}.MP4" for i in range(6)])
    write_plan("edit_plan_latest.json", "newest", built + 5 * 86400, [f"Y{i}.MP4" for i in range(6)])
    plan, fname, basis, made = ph.plan_for_build_time(plans, built)
    check("the plan a sequence was built from is the newest one that existed when it was built", plan["tag"] == "the plan it was built from" and basis == "matched" and fname == "edit_plan_prev_20261015T154553.json", (plan["tag"], basis))
    check("a sequence with no build time is compared with the current plan, and says so", ph.plan_for_build_time(plans, None)[0]["tag"] == "newest" and ph.plan_for_build_time(plans, None)[2] == "latest")
    check("when every saved plan is newer than the sequence the basis says so", ph.plan_for_build_time(plans, built - 10 * 86400)[2] == "newer")
    check("a job with no saved plan has none", ph.plan_for_build_time(root / "nothing", built) == (None, None, "none", None))

    post_learn.FEEDBACK_DIR = root / "feedback"
    job["destination_root"] = str(root / "shoot")
    now = time.time()
    logged = pa.settle_job(store, job, now=now)
    check("an edit that has not changed for 45 minutes is logged once, automatically", logged == [edit_name], logged)
    idx = [json.loads(l) for l in (root / "feedback" / "index.jsonl").read_text().splitlines()]
    check("the record says it came from the auto-saves, was compared with the plan it was built from, and is not flagged stale", len(idx) == 1 and idx[0]["source"] == "auto-save" and idx[0]["stale_plan"] is False, idx)
    check("it is not logged again while its state is the same", pa.settle_job(store, job, now=now + 10) == [])
    store2 = pa.Store(root / "store2"); job2 = {**job, "id": 11}
    store2.append_snapshot(11, {"file": "f", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600)), "sequence": edit_name, "built_at": built, "seconds": 5.0, "n": 6, "whole_clip": False, "hash": "a", "shots": [[f"C{i}.MP4", 1, 2, i, 1, 1.0, 30.0] for i in range(6)]})
    check("an edit changed ten minutes ago is not finished yet", pa.settle_job(store2, job2, now=now) == [])
    store2.append_snapshot(11, {"file": "g", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600)), "sequence": "Clip list", "built_at": None, "seconds": 5.0, "n": 8, "whole_clip": True, "hash": "b", "shots": [[f"C{i}.MP4", 0, 30, i, 30, 1.0, 30.0] for i in range(8)]})
    store2.append_snapshot(11, {"file": "h", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 300)), "sequence": edit_name, "built_at": built, "seconds": 5.0, "n": 7, "whole_clip": False, "hash": "a2", "shots": [[f"C{i}.MP4", 1, 2, i, 1, 1.0, 30.0] for i in range(7)]})
    check("a clip list (whole clips) is never logged as an edit, however old", pa.settle_job(store2, job2, now=now + 86400) == [edit_name], "the edit (seen changing, now settled) is logged; the clip list never is")
    # what counts as HIS edit
    def put(st, jid, seq_name, shots, built, whole=False, mins_ago=600):
        st.append_snapshot(jid, {"file": "f", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - mins_ago * 60)), "sequence": seq_name, "built_at": built, "seconds": 9.0,
                                 "n": len(shots), "whole_clip": whole, "hash": seq_name[:6] + str(len(shots)), "shots": shots})
    rows_like_plan = [[f"C{i}.MP4", 1.0 + i, 3.0 + i, 2 * i, 2.0, 1.0, 30.0] for i in range(6)]            # exactly the plan's six shots (plan: C{i} at 1+i .. 3+i)
    st3 = pa.Store(root / "store3"); job3 = {**job, "id": 12}
    untouched = "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z"
    put(st3, 12, untouched, rows_like_plan, built)
    check("an edit Assemble Edit built that still matches its plan shot for shot is not logged (abandoned looks the same as approved)", pa.settle_job(st3, job3, now=now) == [])
    changed = [r[:] for r in rows_like_plan]; changed[2][1], changed[2][2] = 20.0, 20.6
    st3b = pa.Store(root / "store3b"); put(st3b, 12, untouched, changed, built)
    check("a build that differs from its plan but was only ever seen in ONE state is not logged (can't tell an edit from a plan that is gone)", pa.settle_job(st3b, job3, now=now) == [])
    put(st3b, 12, untouched, changed + [["C9.MP4", 5, 6, 12, 1, 1.0, 30.0]], built, mins_ago=300)
    check("once the auto-saves show him changing it (two states) and it differs from its plan, it is his edit and is logged", pa.settle_job(st3b, job3, now=now) == [untouched])
    st4 = pa.Store(root / "store4"); job4 = {**job, "id": 13}
    put(st4, 13, "JD Sports - MOA Store Opening - Rough Cut 2026-10-06T19:46:10", [[f"C{i}.MP4", 1, 2, i, 1, 1.0, 30.0] for i in range(40)], None)
    check("the machine's rough cuts are never logged as his edits", pa.settle_job(st4, job4, now=now) == [])
    put(st4, 13, "draft 01", [[f"D{i}.MP4", 1, 2, i, 1, 1.0, 30.0] for i in range(8)], None)
    check("an edit he made by hand, the size of a cut, is logged (compared with the current plan, flagged indicative)", pa.settle_job(st4, job4, now=now) == ["draft 01"])
    last = [json.loads(l) for l in (root / "feedback" / "index.jsonl").read_text().splitlines()][-1]
    check("and its record is flagged stale so it stays out of the plan-agreement totals", last["sequence"] == "draft 01" and last["stale_plan"] is True and last["source"] == "auto-save", last)
    put(st4, 13, "Sequence 01", [[f"E{i}.MP4", 1, 2, i, 1, 1.0, 30.0] for i in range(200)], None)
    check("a hand-made sequence of 200 shots is a pool of selects, not a cut, and is not logged", "Sequence 01" not in pa.settle_job(st4, job4, now=now + 1000))
    check("looked at once, a state is not looked at again until it changes", pa.settle_job(st4, job4, now=now + 2000) == [])

    summary = pa.status(store, [job])
    check("the status says what has been seen", summary["enabled"] and summary["jobs"][0]["sequences"][0]["sequence"] == edit_name and summary["jobs"][0]["sequences"][0]["states"] == 5 and summary["jobs"][0]["sequences"][0]["logged"], summary["jobs"][0]["sequences"])

# ---- Josh's real GWM project (read-only; skipped when the drive is not mounted) --------------------------------------------------------------------
PROJECT = "/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video/10_PREMIERE/GWM - Highlight Video.prproj"
if os.path.exists(PROJECT):
    with tempfile.TemporaryDirectory() as tmp:
        store = pa.Store(Path(tmp) / "store")
        post_learn.FEEDBACK_DIR = Path(tmp) / "feedback"
        real_job = {"id": 48, "premiere_project_path": PROJECT, "shoot_name": "GWM - Highlight Video", "profile": "alpha_mode", "destination_root": "/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video"}
        before = {p: os.stat(p).st_mtime for p in [s["path"] for s in pa.list_sources(PROJECT)]}
        # ...and the job's plans folder, where the learning-event copy of a log would go (2026-10-22: it did, from this very test, until post_learn checked)
        PLANS = Path(PROJECT).parent / "edit_plans"
        plans_before = {p.name: p.stat().st_mtime for p in PLANS.iterdir()} if PLANS.is_dir() else {}
        t0 = time.time(); total = {"read": 0, "new_states": 0}
        while True:
            r = pa.scan_job(store, real_job, budget=15)
            total["read"] += r["read"]; total["new_states"] += r["new_states"]
            if r["pending"] == 0:
                break
        rows = store.snapshots(48)
        edit = [x for x in rows if x["sequence"].startswith("GWM - Highlight Video - Edit 2026-10-15")]
        check("the real GWM auto-saves are read", total["read"] > 10 and len(rows) > 10, (total, f"{time.time() - t0:.0f}s"))
        check("it sees the edit grow: more than one state, ending at the 46 shots of the saved cut", len(edit) > 3 and edit[-1]["n"] == 46, [x["n"] for x in edit][:12])
        check("the project's starting sequence (a clip list) is not mistaken for an edit", any(x["whole_clip"] for x in rows if x["sequence"] == "GWM - Highlight Video") or not any(x["sequence"] == "GWM - Highlight Video" for x in rows))
        logged = pa.settle_job(store, real_job)
        idx = [json.loads(l) for l in (Path(tmp) / "feedback" / "index.jsonl").read_text().splitlines()] if (Path(tmp) / "feedback" / "index.jsonl").exists() else []
        mine = [i for i in idx if i["sequence"].startswith("GWM - Highlight Video - Edit 2026-10-15")]
        check("the finished GWM edit is logged against the plan it was BUILT from (the 40 s, 16-shot plan, not the later selects)", len(mine) == 1 and mine[0]["stale_plan"] is False and mine[0]["summary"]["plan_shots"] == 16, [(i["summary"]["plan_shots"], i["stale_plan"]) for i in mine])
        check("nothing on the SSD was touched", all(os.stat(p).st_mtime == t for p, t in before.items()))
        plans_after = {p.name: p.stat().st_mtime for p in PLANS.iterdir()} if PLANS.is_dir() else {}
        check("...not even the job's plans folder: no file added or changed there (a test log never writes learning events into his real job)", plans_after == plans_before,
              sorted(set(plans_after.items()) ^ set(plans_before.items()))[:4])
else:
    print("SKIP the real GWM checks (drive not mounted)")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
