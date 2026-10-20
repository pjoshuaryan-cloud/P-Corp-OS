"""Tests for 'Learn From My Edit' (backend/app/post_learn.py): synthetic plans and edits with known answers, plus a regression check against Josh's real GWM
project when its drive is mounted.   Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python learn_from_edit_test.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_learn  # noqa: E402
from learning import prproj, plan_vs_final  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


def shot(name, a, b, t0=0.0, length=None, track=1):
    length = (b - a) if length is None else length
    return prproj.Shot(t0=t0, t1=t0 + length, src_in=a, src_out=b, path=f"/x/{name}", name=name, track=track, src_duration=30.0)


def plan_shot(i, name, a, b):
    return {"index": i, "name": name, "path": f"/y/{name}", "source_in": a, "source_out": b, "moment_source": "event pick"}


plan = {"style": "test", "shots": [plan_shot(1, "A.MP4", 1.0, 3.0), plan_shot(2, "B.MP4", 5.0, 7.0), plan_shot(3, "C.MP4", 2.0, 4.0), plan_shot(4, "E.MP4", 8.0, 9.0)]}
moments = {"a.mp4": {"duration": 20.0, "events": [{"t": 2.0, "kind": "hero", "punch": 9, "what": "logo"}, {"t": 12.0, "kind": "action", "punch": 5, "what": "wave"}]},
           "b.mp4": {"duration": 20.0, "events": [{"t": 3.0, "kind": "reveal", "punch": 7, "what": "pan"}]}}
his = [shot("A.MP4", 1.5, 2.2, 0.0),                    # inside the planned stretch, trimmed shorter -> the plan's moment; sits on A's first-choice event (t=2.0)
       shot("B.MP4", 10.0, 10.6, 0.7),                  # same clip, a different moment, nowhere near B's only event
       shot("D.MP4", 4.0, 5.0, 1.3, length=2.0),        # a clip the plan never used, retimed to half speed
       shot("E.MP4", 8.2, 8.7, 3.3)]                    # the plan's moment of E; E has no description
r = post_learn.analyse(plan, his, moments)
s = r["summary"]
check("his shots are counted", s["his_shots"] == 4 and s["his_clips"] == 4, s)
check("a shot inside the planned stretch is the plan's moment (even trimmed)", [x["status"] for x in r["his_shots"]] == ["same_moment", "other_moment", "not_in_plan", "same_moment"], [x["status"] for x in r["his_shots"]])
check("the matching plan slot is recorded", r["his_shots"][0]["plan_slot"] == 1 and r["his_shots"][3]["plan_slot"] == 4)
check("the plan's slots are kept / changed / dropped", [x["state"] for x in r["plan_shots"]] == ["kept", "different_moment", "dropped", "kept"], [x["state"] for x in r["plan_shots"]])
check("the summary counts add up", (s["plan_shots_kept"], s["plan_shots_different_moment"], s["plan_shots_dropped"]) == (2, 1, 1) and (s["his_shots_same_moment"], s["his_shots_other_moment_of_plan_clip"], s["his_shots_clip_not_in_plan"]) == (2, 1, 1), s)
check("his clips that are in the plan are counted", s["his_clips_in_plan"] == 3, s["his_clips_in_plan"])
check("a shot on Claude's first-choice moment is found, with its rank", r["his_shots"][0]["event"] and r["his_shots"][0]["event"]["rank"] == 1 and r["his_shots"][0]["event"]["kind"] == "hero", r["his_shots"][0]["event"])
check("a shot away from every described moment has no event", r["his_shots"][1]["event"] is None)
check("only shots on described clips are checked", s["described_shots_checked"] == 2 and s["at_a_described_moment"] == 1 and s["at_the_first_choice_moment"] == 1, s)
check("the chance of sitting on a described moment is reported next to it", 0.0 < s["chance_at_a_described_moment"] < 0.5 and 0.0 < s["chance_at_the_first_choice"] <= s["chance_at_a_described_moment"], (s["chance_at_a_described_moment"], s["chance_at_the_first_choice"]))
check("a retimed shot is counted", s["retimed_shots"] == 1, s["retimed_shots"])
check("the median shot length is his timeline length", abs(s["median_shot_seconds"] - 0.7) < 0.01 or abs(s["median_shot_seconds"] - 0.6) < 0.5, s["median_shot_seconds"])
check("a very small edit is flagged", any("small sample" in w for w in r["warnings"]), r["warnings"])
wrong = post_learn.analyse({"style": "other", "shots": [plan_shot(1, "Z1.MP4", 1, 2), plan_shot(2, "Z2.MP4", 1, 2)]}, his, moments)
check("an edit that shares almost nothing with the plan warns that it may be the wrong plan", any("wrong plan" in w for w in wrong["warnings"]), wrong["warnings"])
text = " ".join(post_learn.lines("Edit 1", "test", r))
check("the report is plain English with the key numbers", "2 kept" in text and "Claude's described moments" in text and "by chance" in text, text[:200])
check("with no descriptions it says so instead of inventing numbers", "None of the clips in your edit have been described" in " ".join(post_learn.lines("E", "t", post_learn.analyse(plan, his, {}))))

# ---- the log and the running totals -----------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    post_learn.FEEDBACK_DIR = Path(tmp)
    job = {"id": 7, "shoot_name": "T"}
    p1, n1 = post_learn._write_log(job, "Edit 1", "test", r)
    p2, n2 = post_learn._write_log(job, "Edit  1", "test", r)          # the same edit saved again (odd spacing): replaces, doesn't double count
    p3, n3 = post_learn._write_log({"id": 8, "shoot_name": "U"}, "Edit 1", "test", r)
    check("each click writes its own detailed file", p1.exists() and p2.exists() and p1 != p2 or p1.name != p2.name, (p1.name, p2.name))
    check("the same edit logged twice counts once in the totals", (n1, n3) == (1, 2), (n1, n2, n3))
    agg = post_learn.aggregate()
    check("the totals add up over edits", agg["edits"] == 2 and agg["shots"] == 8 and abs(agg["share_same_moment_as_plan"] - 0.5) < 1e-6, agg)
    check("a logged file holds every shot and slot", len(json.loads(p3.read_text())["his_shots"]) == 4 and len(json.loads(p3.read_text())["plan_shots"]) == 4)

# ---- a plan made AFTER the sequence was built is not the plan it was built from ---------------------------------------------------------
import calendar
built = calendar.timegm((2026, 10, 15, 13, 57, 37, 0, 0, 0))
name = "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z"
check("the build time is read from the sequence's name (UTC)", post_learn.built_at(name) == built and post_learn.built_at("My own sequence") is None, post_learn.built_at(name))
check("a plan saved just after the build is the plan it was built from", post_learn.stale_plan_warning(name, built + 60) is None and post_learn.stale_plan_warning(name, built - 3600) is None)
warn = post_learn.stale_plan_warning(name, built + 5 * 86400)
check("a plan saved days later is flagged, saying when both were made", warn is not None and "after this sequence was built" in warn and "newer plan" in warn, warn)
check("a sequence with no build time is never flagged", post_learn.stale_plan_warning("Edit by hand", built + 5 * 86400) is None)
with tempfile.TemporaryDirectory() as tmp:
    post_learn.FEEDBACK_DIR = Path(tmp)
    own, stale = {**r, "stale_plan": False}, {**r, "stale_plan": True}
    post_learn._write_log({"id": 1, "shoot_name": "A"}, "Edit A", "t", own)
    post_learn._write_log({"id": 2, "shoot_name": "B"}, "Edit B", "t", stale)
    agg = post_learn.aggregate()
    check("an edit compared with a newer plan is left out of the plan-agreement totals but still counted", agg["edits"] == 2 and agg["edits_compared_with_their_own_plan"] == 1 and agg["shots"] == 8 and abs(agg["share_same_moment_as_plan"] - 0.5) < 1e-6, agg)
    check("its described-moment check still counts (that doesn't depend on the plan)", agg["described_shots_checked"] == 4, agg)

# ---- errors a person can fix -------------------------------------------------------------------------------------------------------------
for label, path in (("a project that isn't saved yet", "/nonexistent/x.prproj"), ("a file that isn't a project", __file__)):
    try:
        post_learn.read_final_edit(path, "Edit")
        ok = False
    except post_learn.LearnError as exc:
        ok = "Save it" in str(exc) or "can't find" in str(exc)
    check(f"{label} gives a plain message", ok)

# ---- Josh's real GWM project (skipped when the drive is not mounted) --------------------------------------------------------------------
PROJECT = "/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video/10_PREMIERE/GWM - Highlight Video.prproj"
OLD_PLAN = Path(__file__).resolve().parents[2] / "backend" / "data" / "learning" / "gwm_plan_steadiest_2026-10-15.json"
MOMENTS = "/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video/10_PREMIERE/edit_plans/moments.json"
if os.path.exists(PROJECT) and OLD_PLAN.exists() and os.path.exists(MOMENTS):
    name, shots = post_learn.read_final_edit(PROJECT, "Edit 2026-10-15")
    check("the real project: his sequence is found by a part of its name", "Edit 2026-10-15" in name.replace("  ", " ") and len(shots) == 46, (name, len(shots)))
    real = post_learn.analyse(json.load(open(OLD_PLAN)), shots, post_learn.moments_by_clip_name(json.load(open(MOMENTS))))
    ref = plan_vs_final.compare(plan_vs_final.his_shots(PROJECT, "Edit 2026-10-15")[1], json.load(open(OLD_PLAN)))
    rs = real["summary"]
    check("the real project agrees with the plan_vs_final tool (clips in the plan, shots on the plan's moment)", rs["his_clips_in_plan"] == ref["his_clips_in_plan"] == 25 and rs["his_shots_same_moment"] == ref["on_his_moment"] == 2, (rs["his_clips_in_plan"], rs["his_shots_same_moment"]))
    check("the real project: the counts add up", rs["his_shots_same_moment"] + rs["his_shots_other_moment_of_plan_clip"] + rs["his_shots_clip_not_in_plan"] == rs["his_shots"] == 46 and rs["plan_shots_kept"] + rs["plan_shots_different_moment"] + rs["plan_shots_dropped"] == 78)
    check("the real project: a described-moment comparison is made", rs["described_shots_checked"] > 30 and 0 < rs["chance_at_a_described_moment"] < 1, (rs["described_shots_checked"], rs["at_a_described_moment"], rs["chance_at_a_described_moment"]))
    try:
        post_learn.read_final_edit(PROJECT, "No such sequence")
        ok = False
    except post_learn.LearnError as exc:
        ok = "no sequence called" in str(exc)
    check("the real project: a sequence that isn't in the saved file is explained", ok)
else:
    print("SKIP the real GWM project checks (drive not mounted or plan copy missing)")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
