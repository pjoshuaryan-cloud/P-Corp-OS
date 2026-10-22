"""Tests for the path from Josh's recorded decisions to the planner (backend/learning/adopt_preferences.py, post_learning_events.adopted_preferences, the planner
hooks) and for the timing/order events of Learn From My Edit (shortened, extended, moved). Synthetic data and temp folders only: nothing is written to his real
learning store or to any job folder. Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python adopt_preferences_test.py"""
import asyncio
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from app import post_learning_events as le, post_learn, post_style  # noqa: E402
from learning import adopt_preferences as ap  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


TMP = Path(tempfile.mkdtemp(prefix="adopt_"))
REAL = (le.CENTRAL_EVENTS, le.ADOPTED_PREFERENCES)
def _state(f):
    return (f.exists(), f.stat().st_mtime if f.exists() else None, f.stat().st_size if f.exists() else None)
REAL_STATE = (_state(REAL[0]), _state(REAL[1]))
le.CENTRAL_EVENTS, le.ADOPTED_PREFERENCES = TMP / "central" / "events.jsonl", TMP / "adopted.json"   # never his real store


def vote(kind, kept, n):
    return le.make_event(category="explicit_feedback", confidence="confirmed", outcome="approved" if kept else "swapped", source="review_page", job_id=1,
                         ts=f"2026-10-22T10:{n // 60:02d}:{n % 60:02d}", slot={"index": n, "role": "body", "seconds": 0.5, "cut_at": None},
                         planned={"name": f"V{n:03d}.MP4", "source_in": 1.0, "source_out": 1.5, "kind": kind})


# ---- the reader the planner uses ---------------------------------------------------------------------------------------------------------------------------
good = {"schema": 1, "by_kind": {"hero": 0.15, "reaction": -0.1}, "gate": {"met": True, "net_top1": 12, "net_top3": 14}}
cases = {"a valid adopted file": (good, {"hero": 0.15, "reaction": -0.1}),
         "a failed gate": ({**good, "gate": {"met": False}}, None), "no gate at all": ({k: v for k, v in good.items() if k != "gate"}, None),
         "another schema": ({**good, "schema": 2}, None), "a value beyond +-0.15": ({**good, "by_kind": {"hero": 0.3}}, None),
         "an unknown kind": ({**good, "by_kind": {"explosion": 0.1}}, None), "an empty nudge": ({**good, "by_kind": {}}, None),
         "a 'met' that is only truthy": ({**good, "gate": {"met": "yes"}}, None)}
cases["a value that isn't a finite number (NaN)"] = ({**good, "by_kind": {"hero": float("nan")}}, None)
for label, (body, want) in cases.items():
    le.ADOPTED_PREFERENCES.write_text(json.dumps(body))
    check(f"adopted_preferences: {label} -> {'used' if want else 'ignored'}", le.adopted_preferences() == want, le.adopted_preferences())
le.ADOPTED_PREFERENCES.write_text("{not json")
check("adopted_preferences: an unreadable file is ignored", le.adopted_preferences() is None)
le.ADOPTED_PREFERENCES.unlink()
check("adopted_preferences: no file -> None (the planner is unchanged)", le.adopted_preferences() is None)

# ---- the decision: not enough / tested; held out; both outcomes of the gate -------------------------------------------------------------------------------
few = [vote("hero", True, i) for i in range(10)]
check("fewer than 30 votes: nothing is proposed or tested", ap.decide(few, None)["stage"] == "not_enough")


def group(name, kinds_hits, project="p"):
    """A labelled shot: its clip's described moments, Claude's order = punch order, each with whether it would hit his shot."""
    cands = [{"kind": k, "punch": p, "rank": r, "start": r * 2.0, "hit": h} for r, (k, p, h) in enumerate(kinds_hits)]
    return {"project": project, "path": f"/x/{name}", "src_in": 0.0, "L": 0.5, "dur": 10.0, "cands": cands}


# 20 shots where his moment is the hero Claude ranked FOURTH (outside the top three), 4 where Claude's first pick (a reaction) was right: a hero-up /
# reaction-down nudge should win 20 and lose 4 on both first pick and top three = +16 net, over the bar
helps = [group(f"H{i}.MP4", [("reaction", 9, False), ("action", 8.5, False), ("reveal", 8.2, False), ("hero", 8, True)]) for i in range(20)] + \
        [group(f"R{i}.MP4", [("reaction", 9, True), ("action", 8.5, False), ("reveal", 8.2, False), ("hero", 8, False)]) for i in range(4)]
evidence = [vote("hero", True, i) for i in range(20)] + [vote("reaction", False, 100 + i) for i in range(20)]
d = ap.decide(evidence, helps)
check("with 40 votes (heroes kept, reactions changed) a nudge is proposed: heroes up, reactions down", d["stage"] == "tested" and d["proposal"]["by_kind"]["hero"] > 0 > d["proposal"]["by_kind"]["reaction"], d["proposal"])
check("...and on labelled shots where his moment IS that hero, it clears the bar (+16 net on first pick and on top three)",
      d["test"]["met"] is True and d["test"]["net_top1"] == 16 and d["test"]["net_top3"] == 16, d["test"])
check("...first pick goes from 4 of 24 to 20 of 24", d["test"]["base"]["top1"] == round(4 / 24, 4) and d["test"]["nudged"]["top1"] == round(20 / 24, 4), d["test"])
hurts = [group(f"X{i}.MP4", [("reaction", 9, True), ("action", 8.5, False), ("reveal", 8.2, False), ("hero", 8, False)]) for i in range(24)]
d2 = ap.decide(evidence, hurts)
check("the same nudge on shots where his moment is the reaction: it loses, and the gate says so", d2["test"]["met"] is False and d2["test"]["net_top1"] == -24, d2["test"])
check("a gain on first pick alone is not enough: the bar is on BOTH", ap.decide(evidence, [group(f"T{i}.MP4", [("reaction", 9, False), ("hero", 8, True), ("action", 6, False)]) for i in range(24)])["test"]["met"] is False)
leaky = helps + [group("V005.MP4", [("reaction", 9, False), ("action", 8.5, False), ("reveal", 8.2, False), ("hero", 8, True)])]
d3 = ap.decide(evidence, leaky)
check("a labelled shot whose clip is in the events is left out of the test (never tested on what it learned from)", d3["test"]["excluded"] == 1 and d3["test"]["shots"] == 24, d3["test"])
check("the order with no nudge is exactly Claude's order", ap._order(helps[0], {}) == [0, 1, 2, 3])

# ---- save: written only when met, removed when a later test fails ----------------------------------------------------------------------------------------
target = TMP / "adopted_test.json"
check("not enough evidence: no file", ap.save(ap.decide(few, None), target).startswith("unchanged") and not target.exists())
met = ap.decide(evidence, helps)
if met["test"]["met"]:
    msg = ap.save(met, target)
    check("a met gate writes the adopted file, which the planner's reader accepts", msg.startswith("ADOPTED") and le.adopted_preferences(target) == met["proposal"]["by_kind"], msg)
    check("...and it records the test that justified it", json.loads(target.read_text())["gate"]["shots"] == 24)
    msg2 = ap.save(d2, target)
    check("a later failed test removes it again", msg2.startswith("gate not met: removed") and not target.exists(), msg2)
else:
    check("the synthetic 'helps' case meets the gate", False, met["test"])

# ---- import: logs and job files into the central store, idempotent ---------------------------------------------------------------------------------------
fb, ed = TMP / "feedback", TMP / "job" / "edit_plans"
fb.mkdir(); ed.mkdir(parents=True)
learn_rec = {"ts": "2026-10-21T07:00:00", "job_id": 5, "sequence": "Edit 1", "source": "button", "plan_basis": "matched", "stale_plan": False,
             "plan_shots": [{"index": 1, "name": "A.MP4", "source_in": 1.0, "source_out": 2.0, "state": "kept", "moment": "event (hero): x"},
                            {"index": 2, "name": "B.MP4", "source_in": 3.0, "source_out": 3.5, "state": "kept", "moment": "event (action): y"},
                            {"index": 3, "name": "C.MP4", "source_in": 0.0, "source_out": 0.6, "state": "kept", "moment": "event (reveal): z"}],
             "his_shots": [{"order": 1, "name": "B.MP4", "source_in": 3.0, "source_out": 3.5, "timeline_seconds": 0.5, "speed": 1.0, "status": "same_moment", "plan_slot": 2},
                           {"order": 2, "name": "A.MP4", "source_in": 1.0, "source_out": 1.4, "timeline_seconds": 0.4, "speed": 1.0, "status": "same_moment", "plan_slot": 1},
                           {"order": 3, "name": "C.MP4", "source_in": 0.0, "source_out": 0.9, "timeline_seconds": 0.9, "speed": 1.0, "status": "same_moment", "plan_slot": 3}]}
(fb / "job5_20261021T070000.json").write_text(json.dumps(learn_rec))
(ed / "review_log.jsonl").write_text(json.dumps({"ts": "2026-10-20T10:00:00", "job_id": 5, "style": "s", "action": "approve", "slot": {"index": 4, "role": "body", "seconds": 0.5},
                                                 "chosen": {"id": "4:1000", "file_id": 4, "name": "D.MP4", "source_in": 1.0, "seconds": 0.5, "origin": "current", "kind": "hero"},
                                                 "passed_over": [], "kept_current": True}) + "\n")
first = ap.import_sources([ed], fb)
second = ap.import_sources([ed], fb)
check("import brings in the Learn records and the job's review log", first["learn_records"] > 0 and first["review_log"] == 1, first)
check("...and importing again adds nothing (deterministic ids)", sum(second.values()) == 0, second)

# ---- the timing and order of the shots he kept ----------------------------------------------------------------------------------------------------------------
ev = le.from_learn_record(learn_rec)
by = {(e["outcome"], e["slot"]["index"]) for e in ev}
check("a kept shot he trimmed from 1.0 s to 0.4 s is 'shortened'; one he lengthened from 0.6 to 0.9 s is 'extended'", ("shortened", 1) in by and ("extended", 3) in by, sorted(by))
check("...one kept at its planned length is neither", ("shortened", 2) not in by and ("extended", 2) not in by)
check("he put planned shot 2 before planned shot 1: exactly one 'moved' event (the fewest moves that explain his order)", sorted(i for o, i in by if o == "moved") in ([1], [2]), sorted(by))
plain = [e for e in ev if e["outcome"] not in ("shortened", "extended", "moved")]
check("timing and order events never vote: the kind evidence is the same with or without them", le.kind_evidence(ev) == le.kind_evidence(plain))
check("a sub-frame difference is not a trim", not any(e["outcome"] in ("shortened", "extended") for e in le.from_learn_record({**learn_rec, "his_shots": [
    {**learn_rec["his_shots"][1], "timeline_seconds": 0.97, "source_out": 1.97}]})))
real_fb = Path(__file__).resolve().parents[2] / "backend" / "data" / "learning" / "feedback" / "job48_20261021T072906.json"
if real_fb.exists():
    gwm = le.from_learn_record(json.loads(real_fb.read_text()))
    trims = [e for e in gwm if e["outcome"] in ("shortened", "extended")]
    check("on his real GWM edit: the one kept shot he cut down (3.84 s -> 0.76 s) is found, as observed (built from that plan)", len(trims) == 1 and trims[0]["outcome"] == "shortened"
          and trims[0]["confidence"] == "observed" and trims[0]["context"]["planned_seconds"] == 3.84, [(e["outcome"], e["context"]) for e in trims])

# ---- the mirror and the guard against tests writing into real job folders --------------------------------------------------------------------------------------
check("a folder in the system's temp space is a test folder (never mirrored)", not le._is_real_job_folder(ed) and le._is_real_job_folder(Path("/Volumes/Joshx SSD/X/edit_plans")))
real_check = le._is_real_job_folder
le._is_real_job_folder = lambda d: True
try:
    le.CENTRAL_EVENTS = TMP / "mirror" / "events.jsonl"
    one = le.make_event(category="explicit_feedback", confidence="confirmed", outcome="locked", source="review_page", job_id=5, ts=le.now_precise())
    le.record_for_job(TMP / "jobA", [one]); le.record_for_job(TMP / "jobA", [one])
    check("a real job's events are mirrored into the central store, once", len(le.load_events(le.CENTRAL_EVENTS)) == 1)
finally:
    le._is_real_job_folder = real_check
saved_fb, saved_real, saved_edit = post_learn.FEEDBACK_DIR, post_learn._REAL_FEEDBACK_DIR, None
from app import post_edit_plan as pe  # noqa: E402
saved_edit = pe.edit_dir
job_dir = TMP / "realjob" / "edit_plans"
job_dir.mkdir(parents=True)
pe.edit_dir = lambda job: job_dir
try:
    post_learn.FEEDBACK_DIR = TMP / "test_feedback"
    result = {"summary": {"his_shots": 3, "his_shots_same_moment": 3, "his_shots_clip_not_in_plan": 0, "described_shots_checked": 0, "at_a_described_moment": 0}, "warnings": [], **{k: learn_rec[k] for k in ("plan_shots", "his_shots", "plan_basis", "stale_plan")}}
    post_learn._write_log({"id": 5, "shoot_name": "S"}, "Edit 1", "s", result)
    check("a Learn log sent to a test folder writes NO learning events into the job's folder (what wrote 324 into GWM's folder today)", not (job_dir / le.EVENTS_FILE).exists())
    post_learn._REAL_FEEDBACK_DIR = post_learn.FEEDBACK_DIR   # pretend this is the real log
    post_learn._write_log({"id": 5, "shoot_name": "S"}, "Edit 2", "s", result)
    check("...while the real log does write them", (job_dir / le.EVENTS_FILE).exists() and len(le.load_events(job_dir / le.EVENTS_FILE)) > 0)
finally:
    post_learn.FEEDBACK_DIR, post_learn._REAL_FEEDBACK_DIR, pe.edit_dir = saved_fb, saved_real, saved_edit

# ---- the planner hooks ------------------------------------------------------------------------------------------------------------------------------------------
from app import post_variants as pv  # noqa: E402
CLIPS, HITS, PROFILE = make_clips(), beat_hits(160), post_style.usual_pace_profile()
prefs = {"reveal": 0.15, "action": -0.15}
s1 = pv.build_set(["music-led-montage", "premium-luxury"], profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, set_id="x")
s2 = pv.build_set(["music-led-montage", "premium-luxury"], profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, set_id="x", preferences=prefs)
parts = [s["candidate"]["score"]["parts"] for p in s2["plans"] for s in p["shots"] if (s["candidate"].get("score") or {}).get("parts")]
check("a variant set with adopted preferences scores every picked shot with its kind's nudge", parts and all(abs(x["learned_preference"] - prefs.get(x["role"], 0.0)) < 1e-9 for x in parts))
check("...says so in its notes and confidence", all(any("Learned from your own" in n for n in p["notes"]) and "your own decisions taught" in p["variant"]["confidence"]["basis"] for p in s2["plans"]))
check("...and without them carries no nudge and no such note", all(x["learned_preference"] == 0 for p in s1["plans"] for s in p["shots"] for x in [(s["candidate"].get("score") or {}).get("parts") or {"learned_preference": 0}])
      and not any("Learned from your own" in n for p in s1["plans"] for n in p["notes"]))

from app import post_db, post_music, post_steady  # noqa: E402
root = TMP / "jobroot"
(root / "04_MUSIC").mkdir(parents=True)
song = root / "04_MUSIC" / "song.mp3"
song.write_bytes(b"x")
JOB = {"id": 9, "shoot_name": "S", "profile": "joshx", "destination_root": str(root), "media_analyzed_at": "2026-10-22", "frame_rate": 25}


async def fake_job(job_id, postgres_conn=None):
    return dict(JOB)


async def fake_clips(job_id, postgres_conn=None, order_names=None):
    return [copy.deepcopy(c) for c in CLIPS]


async def fake_analyse(clips, job_, *, concurrency=5, only_cached=False, always=None):
    return {"analysed": 0, "cached": len(clips), "unreadable": 0}


async def fake_music(path):
    return {"hits": HITS, "duration": 160.0, "tempo_bpm": 128.0}


async def fake_render(src, out, music_in, seconds, fade=1.5):
    Path(out).write_bytes(b"wav")


saved = (post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, pe.find_logo, pe.bring_song_into_project, pe.attach_moments)
post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut = fake_job, fake_clips, fake_analyse, fake_music, fake_render
pe.find_logo, pe.bring_song_into_project, pe.attach_moments = (lambda j: None), (lambda s, d: str(s)), (lambda clips, job: clips)
try:
    plain_plan = asyncio.run(pe.plan_for_job(9, style=[post_style.USUAL_PACE_SLUG], music_path=str(song), target_seconds=24.0, seed=3))
    le.ADOPTED_PREFERENCES.write_text(json.dumps({"schema": 1, "by_kind": prefs, "gate": {"met": True}}))
    nudged_plan = asyncio.run(pe.plan_for_job(9, style=[post_style.USUAL_PACE_SLUG], music_path=str(song), target_seconds=24.0, seed=3))
    le.ADOPTED_PREFERENCES.unlink()
    again = asyncio.run(pe.plan_for_job(9, style=[post_style.USUAL_PACE_SLUG], music_path=str(song), target_seconds=24.0, seed=3))
finally:
    (post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, pe.find_logo, pe.bring_song_into_project,
     pe.attach_moments) = saved
np_ = [s["candidate"]["score"]["parts"]["learned_preference"] for s in nudged_plan["shots"] if (s["candidate"].get("score") or {}).get("parts")]
check("Plan Edit (Your usual pace) applies an adopted file: the picked shots carry the nudge and the plan says so",
      any(v != 0 for v in np_) and any("Learned from your own" in n for n in nudged_plan["notes"]), (np_[:6], nudged_plan["notes"][-1:]))
check("...and with no adopted file the plan is exactly what it was before (same shots, no note)",
      [(s["file_id"], s["source_in"]) for s in again["shots"]] == [(s["file_id"], s["source_in"]) for s in plain_plan["shots"]] and not any("Learned from your own" in n for n in again["notes"]))

le.CENTRAL_EVENTS, le.ADOPTED_PREFERENCES = REAL
check("the test leaves his real learning store and adopted file exactly as they were (whether or not one has been adopted)", (_state(REAL[0]), _state(REAL[1])) == REAL_STATE)
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
