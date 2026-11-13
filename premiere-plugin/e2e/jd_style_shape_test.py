"""The JD style taught from his Midlands DRAFT CUT - 01 (2026-11-13): a hero opening, a payoff close on people, a quarter of the shots at half speed, and
Learn From My Edit reading V2 as well as V1. Made-up clips and a made-up timeline: no drive, no database, no Claude call. The real JD references are read
from backend/data/post_references (read only).
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python jd_style_shape_test.py"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import post_edit_plan as ep, post_review, post_style  # noqa: E402
from learning.prproj import Sequence, Shot  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


# ---- V2 counts: what the viewer sees
def shot(t0, t1, src, path, track):
    return Shot(t0=t0, t1=t1, src_in=src, src_out=src + (t1 - t0), path=path, name=path, track=track, src_duration=20.0)


seq = Sequence(name="DRAFT", out_mark=None, in_mark=None, tracks=[
    [shot(0, 1, 2, "/c/A.MP4", 1), shot(2, 3, 5, "/c/B.MP4", 1), shot(3, 4, 1, "/c/C.MP4", 1)],
    [shot(1, 2, 4, "/c/D.MP4", 2), shot(3.5, 3.75, 7, "/c/E.MP4", 2), shot(0, 4, 0, "/c/LOGO.png", 2)],
    [Shot(t0=0, t1=1, src_in=None, src_out=None, path=None, name="Adjustment Layer", track=3, src_duration=None)],
])
v = seq.visible_shots()
check("a V2 shot filling a gap in V1 counts", [x.path[-5:] for x in v] == ["A.MP4", "D.MP4", "B.MP4", "C.MP4", "E.MP4", "C.MP4"], [x.path for x in v])
check("a V2 cutaway hides the V1 shot under it, which carries on after", [(round(x.t0, 2), round(x.t1, 2)) for x in v][3:] == [(3, 3.5), (3.5, 3.75), (3.75, 4)])
check("and the rest of that V1 shot starts later in its source", abs(v[5].src_in - 1.75) < 1e-6, v[5].src_in)
check("a logo on V2 and an adjustment layer on V3 hide nothing", all(not x.path.endswith(".png") for x in v) and len(v) == 6)
half = Sequence(name="S", out_mark=None, in_mark=None, tracks=[[Shot(t0=0, t1=2, src_in=4, src_out=5, path="/c/A.MP4", name="A", track=1, src_duration=9.0)],
                                                           [shot(0.5, 1, 1, "/c/B.MP4", 2)]])
pieces = half.visible_shots()
check("a slowed shot split by a cutaway keeps its speed in both pieces", [round(p.speed, 3) for p in pieces if p.path.endswith("A.MP4")] == [0.5, 0.5], [(p.src_in, p.src_out, p.speed) for p in pieces])

# ---- Build My Edit's copy of his finishing reads V2 the same way
from learning import transfer_finish as tf  # noqa: E402
fin = tf.visible_pieces([
    {"name": "A", "track": 1, "start": 0.0, "end": 2.0, "src_in": 5.0, "effects": ["zoom"], "params": {}, "punch_in": [(0.0, 100), (2.0, 110)], "motion_zoom": []},
    {"name": "RC_ED_2", "track": 2, "start": 0.5, "end": 1.0, "src_in": 1.0, "effects": ["bw"], "params": {}, "punch_in": [], "motion_zoom": []},
    {"name": "B", "track": 1, "start": 2.0, "end": 3.0, "src_in": 0.0, "effects": [], "params": {}, "punch_in": [], "motion_zoom": []},
    {"name": "C", "track": 2, "start": 3.0, "end": 3.5, "src_in": 0.0, "effects": [], "params": {}, "punch_in": [], "motion_zoom": []}])
check("finishing: a V2 cutaway and a V2 shot in a V1 gap are shots", [(x["name"], x["start"], x["end"]) for x in fin] == [("A", 0.0, 0.5), ("RC_ED_2", 0.5, 1.0), ("A", 1.0, 2.0), ("B", 2.0, 3.0), ("C", 3.0, 3.5)], fin)
check("the V2 shot keeps its own effect", fin[1]["effects"] == ["bw"])
check("the rest of a covered V1 shot keeps its effect but drops a punch-in timed from its start", fin[2]["effects"] == ["zoom"] and fin[2]["punch_in"] == [] and abs(fin[2]["src_in"] - 6.0) < 1e-9 and fin[0]["punch_in"])

# ---- the JD style
prof = post_style.profile_from_references(["jd-sports-store-opening"])
check("the JD style now pools all three JD edits", prof.notes and "jd-sports-midlands-draft-01" in prof.notes[0], prof.notes)
check("its length comes down to about 27 s (31.8, 22.1 and 27.3 s)", 26.5 <= prof.target_duration_seconds <= 27.5, prof.target_duration_seconds)
check("about a quarter of its shots are slowed, as measured (MOA 11/50, Midlands 16/60)", abs(prof.slow_motion_share - 27 / 110) < 0.01, prof.slow_motion_share)
check("it opens on a hero and closes on a payoff", prof.structure["open"] == "hero" and prof.structure["close"] == "payoff")
check("it still has accents", prof.accents is not None)
other = post_style.profile_from_references(["jd-sports-moa-draft-01"])
check("a single reference has no shape and no slow motion", other.structure is None and other.slow_motion_share == 0.0)

# made-up shoot: shoot order puts the ribbon cut late, the group wave in the middle
def clip(i, scene, events, people=True, fps=50.0):
    return {"file_id": i, "name": f"C{i:04d}.MP4", "path": f"/c/C{i:04d}.MP4", "duration": 12.0, "fps": fps, "picks": [], "scene": scene, "people": people,
            "events": [{"t": t, "kind": k, "punch": p, "what": w} for t, k, p, w in events]}


clips = []
for i in range(1, 71):
    clips.append(clip(i, f"store shelf {i % 7}", [(3.0, "camera_move", 9.0, "fast whip pan across the shelf"), (7.0, "hero", 6.0, "shoe with tag")], people=False))
clips[29] = clip(30, "ribbon cutting at the door", [(4.0, "action", 9.0, "ribbon cut, pieces fly"), (8.0, "reaction", 6.0, "crowd claps")])
clips[14] = clip(15, "staff at checkout", [(5.0, "action", 9.0, "staff raise hands in a group wave at camera")])
clips[20] = clip(21, "dancer", [(6.0, "action", 9.0, "arms raised in front of the group")])
for k, i in enumerate((5, 10, 25, 35)):
    clips[i - 1] = clip(i, f"customer {k}", [(2.0, "reaction", 8.0 + k * 0.2, "customer laughs with staff")])
clips[39] = clip(40, "phone footage", [(2.0, "reaction", 9.0, "crowd cheers")], fps=25.0)   # too low a frame rate for slow motion
rng = random.Random(3)
hits = sorted([[t, rng.uniform(55, 100)] for t in [x * 0.21 for x in range(1, 160)]])
plan = ep.build_plan(profile=prof, hits=hits, music_in=0.0, duration=prof.target_duration_seconds, fps=25.0, clips=clips, bookend_file_id=None)
sh = plan["shots"]
check("it opens on the ribbon cut, wherever it is in the shoot", sh[0]["file_id"] == 30 and sh[0]["structure"] == "hero", sh[0]["name"])
check("starting just before that moment", abs(sh[0]["source_in"] - (4.0 - ep.EVENT_LEAD_SECONDS)) < 0.01, sh[0]["source_in"])
check("and ends on the group wave (two cue words beat one)", sh[-1]["file_id"] == 15 and sh[-1]["structure"] == "final", sh[-1]["name"])
pay = [s for s in sh if s.get("structure") == "payoff"]
check("with people payoffs just before it", len(pay) == 3 and [s["index"] for s in pay] == [len(sh) - 3, len(sh) - 2, len(sh) - 1] and all(clips[s["file_id"] - 1]["people"] for s in pay), [(s["index"], s["name"]) for s in pay])
check("the hero and the payoffs aren't used again in the middle", all(sh.count(s) == 1 for s in sh) and sum(1 for s in sh if s["file_id"] == 30) == 1 and sum(1 for s in sh if s["file_id"] == 15) == 1)
mid = [s["file_id"] for s in sh if not s.get("structure")]
check("the middle keeps the shoot's order", mid == sorted(mid), mid)
check("the plan says what it did", any(n.startswith("Shape (from your JD Midlands draft)") for n in plan["notes"]))

slow = [s for s in sh if s.get("speed")]
body = sum(1 for s in sh if s["role"] == "body")
check("about a quarter of the shots are slowed", len(slow) == round(prof.slow_motion_share * body), (len(slow), body))
check("the final hold is one of them, the opening shot isn't", sh[-1].get("speed") == 0.5 and not sh[0].get("speed"))
check("never a clip too low a frame rate to slow smoothly", all(s["file_id"] != 40 for s in slow))
s = slow[0]
check("a slowed shot keeps its start and shows half as much source", abs((s["source_out"] - s["source_in"]) - s["duration_frames"] / 25.0 * 0.5) < 0.002 and s["source_in"] == s["speed_original"]["source_in"])
check("the plan lists them and says to set them with Cmd+R", plan["checks"]["slow_motion_shots"] == sorted(x["index"] for x in slow) and any("Cmd+R" in n for n in plan["notes"]))
before = dict(s["speed_original"])
post_review.set_speed(plan, clips, s["index"], 1.0)
check("review can put a style-slowed shot back to real speed exactly", "speed" not in s and s["source_in"] == before["source_in"] and s["source_out"] == before["source_out"])

plain = ep.build_plan(profile=other, hits=hits, music_in=0.0, duration=20.0, fps=25.0, clips=clips, bookend_file_id=None)
check("a style without a shape plans exactly as before: shoot order, no speed", not any(x.get("structure") or x.get("speed") for x in plain["shots"])
      and [x["file_id"] for x in plain["shots"][:-1]] == sorted(x["file_id"] for x in plain["shots"][:-1]))
chosen = ep.build_plan(profile=prof, hits=hits, music_in=0.0, duration=27.0, fps=25.0, clips=clips, bookend_file_id=3)
check("an opening clip he picks himself still wins over the hero rule", chosen["shots"][0]["file_id"] == 3 and not any(x.get("structure") for x in chosen["shots"]))

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
