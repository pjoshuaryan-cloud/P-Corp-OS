"""Tests for backend/learning/verify_build.py, the frame-by-frame check of a built sequence against its plan that the real-Premiere checklist uses. The
sequences here are SYNTHETIC (built in memory the way learning/prproj.py reads a saved project), so this proves the comparison, not Premiere: reading real
saved projects is learning/prproj.py's job, tested on his real GWM project in learn_from_edit_test.py and autosave_test.py.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python verify_build_test.py"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from app import post_style, post_variants as pv  # noqa: E402
from learning import prproj  # noqa: E402
from learning.verify_build import compare_build  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
plan = pv.build_set(["high-energy-commercial", "music-led-montage"], profile=post_style.usual_pace_profile(), hits=beat_hits(160), music_in=10.0, duration=30.0, fps=25.0,
                    clips=CLIPS, set_id="x")["plans"][0]
plan["graphics"] = {"cards": [{"role": "closer", "file": "/g/corp_card_closer_x.png", "start_frame": plan["shots"][-1]["start_frame"], "frames": plan["shots"][-1]["duration_frames"]}]}
FPS = plan["fps"]


def built(p, *, src_fps=50.0, card=True, name="S - Edit 2026-10-22T12:00:00.000Z"):
    """The sequence a correct build makes: one V1 item per shot (subclip of the planned window at its slot), the card on V2."""
    v1 = [prproj.Shot(t0=s["start_frame"] / FPS, t1=(s["start_frame"] + s["duration_frames"]) / FPS, src_in=s["source_in"], src_out=s["source_in"] + s["duration_frames"] / FPS,
                      path=f"/Volumes/Joshx SSD/Job/03_FOOTAGE/{s['name']}", name=s["name"], track=1, src_duration=40.0, src_fps=src_fps) for s in p["shots"]]
    v2 = [prproj.Shot(t0=c["start_frame"] / FPS, t1=(c["start_frame"] + c["frames"]) / FPS, src_in=0.0, src_out=c["frames"] / FPS, path=c["file"], name="card", track=2,
                      src_duration=None) for c in (p.get("graphics") or {}).get("cards", [])] if card else []
    return prproj.Sequence(name=name, out_mark=None, in_mark=None, tracks=[v1, v2])


r = compare_build(plan, built(plan))
check("a build that matches its plan passes every check", r["ok"], [c for c in r["checks"] if not c[1]])
check("...with zero frames of error anywhere", r["worst"] == {"source_frames": 0.0, "start_frames": 0.0, "length_frames": 0.0}, r["worst"])


def failing(seq, before=None, after=None):
    out = compare_build(plan, seq, before, after)
    return [c[0] for c in out["checks"] if not c[1]]


s = built(plan); s.tracks[0][4] = prproj.Shot(**{**s.tracks[0][4].__dict__, "src_in": s.tracks[0][4].src_in + 2.5 / 50})
check("a source in point 2.5 source frames off (at 50 fps) is caught, and only that", failing(s) == ["every source in point is within one source frame (or half a sequence frame) of the plan"], failing(s))
s = built(plan); s.tracks[0][4] = prproj.Shot(**{**s.tracks[0][4].__dict__, "src_in": s.tracks[0][4].src_in + 0.8 / 50})
check("...while less than one source frame (rounding to the frame grid) is accepted", failing(s) == [], failing(s))
s = built(plan); s.tracks[0][2] = prproj.Shot(**{**s.tracks[0][2].__dict__, "path": "/x/OTHER.MP4", "name": "OTHER.MP4"})
check("the wrong clip in a slot is caught", "every shot uses the planned clip" in failing(s), failing(s))
s = built(plan); del s.tracks[0][-1]
check("a missing shot is caught (count and total length)", {"every planned shot is on V1 (and nothing else is)", "the edit is the planned length"} <= set(failing(s)), failing(s))
s = built(plan); sh = s.tracks[0][3]; s.tracks[0][3] = prproj.Shot(**{**sh.__dict__, "t0": sh.t0 + 1 / FPS, "t1": sh.t1 + 1 / FPS})
check("a shot one frame late on the timeline is caught", "every shot starts on its planned frame" in failing(s), failing(s))
s = built(plan, card=False)
check("a brand card that wasn't placed is caught", failing(s) == ["every brand card is on V2 over its slot"], failing(s))
other = prproj.Sequence(name="His cut", out_mark=None, in_mark=None, tracks=[[prproj.Shot(t0=0, t1=1, src_in=0, src_out=1, path="/a/A.MP4", name="A", track=1, src_duration=9)]])
before = [copy.deepcopy(other)]
after_same = [other, built(plan)]
check("with a copy saved before the build: an untouched existing sequence passes", failing(built(plan), before, after_same) == [])
changed = copy.deepcopy(other); changed.tracks[0][0] = prproj.Shot(**{**changed.tracks[0][0].__dict__, "t1": 2})
check("...an existing sequence that changed is caught", failing(built(plan), before, [changed, built(plan)]) == ["no existing sequence was changed or removed"])
check("...and one that disappeared is caught", failing(built(plan), before, [built(plan)]) == ["no existing sequence was changed or removed"])
slow = copy.deepcopy(plan)
sh = next(x for x in slow["shots"] if x["role"] == "body")
real_in = sh["source_in"]
sh.update({"speed": 0.5, "speed_original": {"source_in": real_in, "source_out": sh["source_out"]}, "source_in": round(real_in + sh["duration_frames"] / FPS / 4, 3),
          "source_out": round(real_in + sh["duration_frames"] / FPS / 4 + sh["duration_frames"] / FPS / 2, 3)})
out = compare_build(slow, built(slow))   # built(...) does what index.js does: source_in, duration_frames, real time
check("a slowed plan shot is expected exactly as the plugin builds it (from its source_in, at real time), with a note saying so", out["ok"] and out["notes"] and "no speed API" in out["notes"][0], (out["notes"], [c for c in out["checks"] if not c[1]]))
check("...and a build from the real-time in point instead would be caught (the reviewer's simulated false FAIL is now the right answer)", not compare_build(slow, built(plan))["ok"])
hi = copy.deepcopy(plan)
seq_hi = built(hi, src_fps=59.94)
for i, x in enumerate(seq_hi.tracks[0]):   # the plugin snaps the in point to the 25 fps sequence grid: up to half a sequence frame = 1.2 frames of 59.94 fps footage
    seq_hi.tracks[0][i] = prproj.Shot(**{**x.__dict__, "src_in": round(x.src_in * FPS) / FPS})
check("59.94 fps footage in a 25 fps edit: in points snapped to the sequence frame grid still pass (up to 1.2 source frames)", compare_build(hi, seq_hi)["ok"], [c for c in compare_build(hi, seq_hi)["checks"] if not c[1]])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
