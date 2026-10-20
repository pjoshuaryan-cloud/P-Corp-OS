"""Tests for the corporate shot picker (post_pick.py) and the picture signature / exposure additions to post_steady.py. Synthetic clips only -- the real-footage
check (contact sheets of real Diplomat footage, old vs new picks) is done separately. Run with the backend venv: python picker_test.py"""
import base64
import sys

sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
import numpy as np

from app import post_edit_story, post_pick, post_steady

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail != "" else ""))
    if not cond:
        fails += 1


rng = np.random.default_rng(11)
LOOKS = {k: rng.integers(0, 255, size=(9, 16), dtype=np.uint8) for k in "ABCDEFGHI"}


def steady(dur, look, *, cuts=(), luma=0.45, hi=0.0, motion=0.02, thumbs=True):
    n = int(dur * 8)
    m = {"fps": 8.0, "motion": [motion] * n, "sharp": [0.002] * n, "luma": [luma] * n, "hi": [hi] * n, "spikes": list(cuts), "seconds": float(dur)}
    if thumbs:
        th = np.stack([LOOKS[look]] * int(dur))
        m["thumbs"], m["thumb_n"] = base64.b64encode(th.tobytes()).decode(), int(dur)
    return m


def clip(i, look, dur=30, scene="", **kw):
    m = steady(dur, look, **kw)
    return {"file_id": i, "name": f"C{i}.MP4", "path": f"/x/C{i}.MP4", "duration": float(dur), "steady": m, "thumbs": post_steady.decode_thumbs(m), "scene": scene}


def slots(lengths, end_card=False):
    out, f = [], 0
    for k, sec in enumerate(lengths):
        out.append({"role": "end_card" if (end_card and k == len(lengths) - 1) else "body", "start_frame": f, "frames": int(sec * 24)})
        f += int(sec * 24)
    return out


def run(clips, lengths, **kw):
    return post_edit_story.assign_clips_to_slots(slots(lengths, kw.pop("end_card", False)), fps=24, clips=clips, bookend_file_id=None, **kw)


# ---- the picture signature -------------------------------------------------------------------------------------------------------------
frames_a = np.zeros((24, 90, 160), dtype=np.uint8); frames_a[:, :, :80] = 200            # left half bright
frames_b = np.zeros((24, 90, 160), dtype=np.uint8); frames_b[:, :45, :] = 200            # top half bright
ma, mb = post_steady.measure(frames_a), post_steady.measure(frames_b)
ta, tb = post_steady.decode_thumbs(ma), post_steady.decode_thumbs(mb)
check("measure() stores one thumbnail per second", ma["thumb_n"] == 3 and ta.shape == (3, 144), (ma["thumb_n"], None if ta is None else ta.shape))
check("a picture matches itself", abs(post_steady.similarity(ta, ta) - 1.0) < 1e-4, post_steady.similarity(ta, ta))
check("different layouts are not alike", post_steady.similarity(ta, tb) < 0.2, post_steady.similarity(ta, tb))
dim = (frames_a.astype(np.float32) * 0.5 + 30).astype(np.uint8)
check("the same layout at another brightness still matches", post_steady.similarity(ta, post_steady.decode_thumbs(post_steady.measure(dim))) > 0.99)
check("an analysis without thumbnails never crashes and counts as unlike", post_steady.decode_thumbs({}) is None and post_steady.similarity(None, ta) == 0.0)

# ---- exposure -------------------------------------------------------------------------------------------------------------------------
white = np.full((24, 90, 160), 255, dtype=np.uint8); grey = np.full((24, 90, 160), 120, dtype=np.uint8); murky = np.full((24, 90, 160), 12, dtype=np.uint8)
sw, sg, sm = (post_steady.score_window(post_steady.measure(x), 0.5, 2.0) for x in (white, grey, murky))
check("a blown-out window scores worse than a well exposed one", sw["score"] > sg["score"] + 0.3 and sw["exposure"] > 0.3, (round(sw["score"], 3), round(sg["score"], 3)))
check("an underexposed window scores worse than a well exposed one", sm["score"] > sg["score"] + 0.2, (round(sm["score"], 3), round(sg["score"], 3)))
check("a well exposed window carries no exposure penalty", sg["exposure"] == 0.0, sg["exposure"])

# ---- never two alike shots side by side ----------------------------------------------------------------------------------------------
pool = [clip(1, "A"), clip(2, "A"), clip(3, "B"), clip(4, "C"), clip(5, "D"), clip(6, "E")]  # clips 1 and 2 look the same
got = run(pool, [2.0] * 5)
ids = [s["file_id"] for s in got["shots"]]
check("two clips that look the same are never neighbours", not any({a, b} == {1, 2} for a, b in zip(ids, ids[1:])), ids)
check("five shots use five different looks when the shoot has them", got["repetition"]["distinct_looks"] == 5 and got["repetition"]["alike_neighbours"] == 0, got["repetition"])
dup_first = run([clip(1, "A"), clip(2, "A"), clip(3, "B")], [2.0, 2.0, 2.0])
check("with too few looks the repeat is pushed as far apart as it can go", [s["file_id"] for s in dup_first["shots"]][1] == 3, [s["file_id"] for s in dup_first["shots"]])
check("the report counts alike neighbours it could not avoid", run([clip(1, "A"), clip(2, "A")], [2.0, 2.0])["repetition"]["alike_neighbours"] == 1)

# ---- clean footage beats a shaky or cut clip, whatever order the shoot was in -------------------------------------------------------
cutty = clip(1, "A", cuts=list(range(3, 238, 6)))              # a hard cut every 0.75 s: no clean 2 s stretch anywhere
over = clip(2, "B", luma=0.95, hi=0.6)                         # blown out
fine = clip(3, "C")
g = run([cutty, over, fine], [2.0])
check("a clip with no clean stretch loses to a clean one", g["shots"][0]["file_id"] == 3, g["shots"][0]["file_id"])
g = run([cutty, over], [2.0])
check("when every clip has a flaw the milder one is used (blown-out beats a clip full of cuts)", g["shots"][0]["file_id"] == 2, g["shots"][0]["file_id"])
check("no shot is planned with a cut inside when a clean option exists", all(not (s.get("steady") or {}).get("cuts") for s in run([cutty, fine, clip(4, "D")], [2.0, 2.0])["shots"]))

# ---- Claude's scene labels work without thumbnails --------------------------------------------------------------------------------
bare = [clip(1, "A", scene="warehouse aisle", thumbs=False), clip(2, "A", scene="warehouse aisle", thumbs=False), clip(3, "B", scene="ceo interview", thumbs=False), clip(4, "C", scene="aerial site", thumbs=False)]
ids = [s["file_id"] for s in run(bare, [2.0] * 3)["shots"]]
check("clips Claude labelled with the same scene are not used back to back", not any({a, b} == {1, 2} for a, b in zip(ids, ids[1:])), ids)

# ---- the edit still follows the shoot, and a described event is covered ------------------------------------------------------------
ordered = [clip(i, "ABCDEFGH"[i]) for i in range(8)]
ids = [s["file_id"] for s in run(ordered, [2.0] * 4)["shots"]]
check("with nothing else to separate them the edit follows the shoot's order", ids == sorted(ids) and ids[0] <= 2 and ids[-1] >= 5, ids)
ev = clip(1, "A", dur=40); ev["events"] = [{"t": 22.0, "kind": "action", "punch": 9, "what": "hands the keys over"}]
w = post_steady.window_for_slot(ev, 2.0, [])
check("a clean clip's window covers its strongest described event", w["start"] <= 22.0 <= w["start"] + 2.0 and "event" in w["source"], (w["start"], w["source"][:60]))
plain = post_steady.window_for_slot(clip(1, "A", dur=40), 2.0, [])
check("without a description nothing changes: the usual steadiest window", "event" not in plain["source"])

# ---- event first (2026-10-19): Claude's best described event wins over the steadiest stretch --------------------------------------------
two = clip(1, "A", dur=40); two["events"] = [{"t": 10.0, "kind": "reveal", "punch": 6, "what": "tilts up to the sign"}, {"t": 28.0, "kind": "action", "punch": 9, "what": "toast"}]
w = post_steady.window_for_slot(two, 2.0, [])
check("the stretch is centred on the strongest event, not just somewhere clean", abs((w["start"] + 1.0) - 28.0) < 0.01 and w["source"].startswith("event pick") and w["event_punch"] == 9, (w["start"], w["source"][:40]))
w2 = post_steady.window_for_slot(two, 2.0, [(w["start"], w["start"] + w["duration"])])
check("a second shot from the same clip goes to the next event, not a quarter second along the first", abs((w2["start"] + 1.0) - 10.0) < 0.01 and w2["event_punch"] == 6, (w2["start"], w2["event_punch"]))
w3 = post_steady.window_for_slot(two, 2.0, [(w["start"], w["start"] + 2.0), (w2["start"], w2["start"] + 2.0)])
check("with every described event used it falls back to a steady stretch", not w3["source"].startswith("event pick") and w3["overlaps_earlier_use"] is False, w3["source"][:40])
cut = clip(1, "A", dur=40, cuts=(28 * 8,)); cut["events"] = list(two["events"])
wc = post_steady.window_for_slot(cut, 2.0, [])
check("an event with a hard cut inside its stretch is skipped for the next one", abs((wc["start"] + 1.0) - 10.0) < 0.01 and wc["steady"]["cuts"] == 0, (wc["start"], wc["steady"]["cuts"]))
black = clip(1, "A", dur=40, luma=0.02); black["events"] = list(two["events"])
check("a black stretch is never chosen as an event", not post_steady.window_for_slot(black, 2.0, [])["source"].startswith("event pick"))
early = clip(1, "A", dur=40); early["events"] = [{"t": 0.2, "kind": "action", "punch": 8, "what": "first frame action"}]
check("an event at the very start keeps the settling margin", abs(post_steady.window_for_slot(early, 2.0, [])["start"] - 0.3) < 0.01, post_steady.window_for_slot(early, 2.0, [])["start"])
tail = clip(1, "A", dur=20); tail["events"] = [{"t": 19.9, "kind": "action", "punch": 8, "what": "last moment"}]
wt = post_steady.window_for_slot(tail, 2.0, [])
check("an event at the very end still gives a stretch that lies inside the clip", wt["start"] + wt["duration"] <= 20.0, (wt["start"], wt["duration"]))
post_steady.EVENT_FIRST = False
off = post_steady.window_for_slot(two, 2.0, [])
post_steady.EVENT_FIRST = True
check("switching the rule off restores the steadiest-window behaviour", not off["source"].startswith("event pick"), off["source"][:40])

# ---- a clip offers its best few moments, and the picker takes the one that adds variety ------------------------------------------------
ew = post_steady.event_windows(two, 2.0, [])
check("a described clip offers its moments best first, each a different stretch", [round(w["start"] + 1.0) for w in ew] == [28, 10] and ew[0]["event_punch"] == 9, [(w["start"], w["event_punch"]) for w in ew])
check("a moment already used from the clip is not offered again", [round(w["start"] + 1.0) for w in post_steady.event_windows(two, 2.0, [(ew[0]["start"], ew[0]["start"] + 2.0)])] == [10])
check("a clip with no description offers nothing (the picker uses its steadiest stretch)", post_steady.event_windows(clip(1, "A", dur=40), 2.0, []) == [])
post_steady.EVENT_FIRST = False
check("with the rule off nothing is offered", post_steady.event_windows(two, 2.0, []) == [])
post_steady.EVENT_FIRST = True

def two_look_clip(i):
    m = steady(40, "A"); th = np.stack([LOOKS["A"]] * 15 + [LOOKS["B"]] * 25)
    m["thumbs"], m["thumb_n"] = base64.b64encode(th.tobytes()).decode(), 40
    c = {"file_id": i, "name": f"C{i}.MP4", "path": f"/x/C{i}.MP4", "duration": 40.0, "steady": m, "thumbs": post_steady.decode_thumbs(m), "scene": ""}
    c["events"] = [{"t": 5.0, "kind": "hero", "punch": 9, "what": "logo, same look as the last shot"}, {"t": 25.0, "kind": "action", "punch": 7, "what": "a different scene"}]
    return c
prev, cand = clip(1, "A", dur=30), two_look_clip(2)
for candidates, expect_second in ((1, False), (3, True)):
    post_pick.EVENT_CANDIDATES = candidates
    pk = post_pick.Picker([prev, cand]); pk.register(prev, {"start": 1.0, "duration": 2.0})
    got = pk.pick(2.0, 0.5, exclude={1})
    check(f"with {candidates} moment(s) offered the picker {'avoids a shot that looks like the last one' if expect_second else 'takes the clip best moment'}", (got["window"]["start"] > 15) == expect_second, got["window"]["start"])
post_pick.EVENT_CANDIDATES = 3

# ---- the old path is untouched for clips that were never analysed -------------------------------------------------------------------
legacy = [{"file_id": i, "name": f"L{i}.MP4", "path": f"/x/L{i}.MP4", "duration": 20.0, "scene": ""} for i in range(1, 7)]
g = run(legacy, [2.0] * 3)
check("clips with no analysis still plan (the old even spread)", len(g["shots"]) == 3 and g["repetition"] is None and all(not s["moment_source"].startswith("steadiest") for s in g["shots"]), [s["file_id"] for s in g["shots"]])

# ---- the opener and closing hold are picked by the same rules ---------------------------------------------------------------------
pool = [clip(i, "ABCDEFGH"[i]) for i in range(7)] + [clip(7, "A", dur=30)]
g = run(pool, [2.0, 2.0, 2.0, 4.3], end_card=True)
ids = [s["file_id"] for s in g["shots"]]
check("the closing hold is not a repeat of the shot before it", not ({ids[-1], ids[-2]} <= {0, 7}), ids)
check("the plan says which shots look alike the previous one", all("alike_previous" in s for s in g["shots"]))

# ---- review step: ranked swaps for every shot, without needing Claude's descriptions --------------------------------------------------
from app import post_review
rev_pool = [clip(i, "ABCDEFGH"[i % 8], dur=30) for i in range(10)]
rev_pool.append(clip(10, "I" if "I" in LOOKS else "A", dur=30, cuts=list(range(3, 238, 6))))  # a clip with a cut every 0.75 s: never offered
rev = run(rev_pool, [2.0, 2.5, 2.0, 2.5])
plan = {"mode": "highlight", "fps": 24, "duration_seconds": 9.0, "style": "test", "shots": rev["shots"], "checks": {"bookend": False}}
alts = post_pick.alternatives(plan, rev_pool)
check("every shot gets swaps to choose from, no descriptions needed", all(1 <= len(v) <= 4 for v in alts.values()) and len(alts) == 4, {k: len(v) for k, v in alts.items()})
check("a swap is never a clip with a cut inside", all(a["steady"]["cuts"] == 0 and a["file_id"] != 10 for v in alts.values() for a in v))
check("a swap is never the shot's own current stretch", all(not (a["file_id"] == sh["file_id"] and abs(a["source_in"] - sh["source_in"]) < sh["duration_frames"] / 24) for sh in plan["shots"] for a in alts[sh["index"]]))
sig_of = lambda a: post_steady.window_signature(next(c for c in rev_pool if c["file_id"] == a["file_id"])["thumbs"], a["source_in"], a["seconds"])
check("the swaps offered for one shot look different from each other", all(post_steady.similarity(sig_of(x), sig_of(y)) < post_pick.ALIKE for v in alts.values() for i, x in enumerate(v) for y in v[i + 1:]))
rv = post_review.build_review(plan, rev_pool)
check("the review shows those swaps and tags the current shot", all(s["alternatives"] and s["current"].get("tag") in ("steady", "static") for s in rv["slots"]), [len(s["alternatives"]) for s in rv["slots"]])
slot2 = rv["slots"][1]; pick = slot2["alternatives"][0]
out = post_review.apply_choice(plan, rev_pool, 2, pick["file_id"], pick["source_in"], "swap")
check("a swap puts the new stretch in the plan and drops the measurements of the old one", plan["shots"][1]["file_id"] == pick["file_id"] and "steady" not in plan["shots"][1] and "alike_previous" not in plan["shots"][1], plan["shots"][1]["moment_source"])
other = next(c for c in rev_pool if c["file_id"] not in (10, plan["shots"][2]["file_id"]))
unlisted = post_review.apply_choice(plan, rev_pool, 3, other["file_id"], 12.0, "swap")
check("a clean stretch the list no longer shows is still accepted (the list shifts after other swaps)", plan["shots"][2]["file_id"] == other["file_id"] and plan["shots"][2]["source_in"] == 12.0)
def refused(slot, fid, start):
    try:
        post_review.apply_choice(plan, rev_pool, slot, fid, start, "swap"); return False
    except post_review.ReviewError:
        return True
check("a stretch with a cut in it is refused", refused(1, 10, 5.0))
check("a stretch past the end of the clip is refused", refused(1, other["file_id"], 29.5))
check("a clip that isn't in the job is refused", refused(1, 999, 1.0))
check("without analysis the review keeps its old event-based swaps", not post_review._is_steady_plan({"mode": "highlight"}, [{"file_id": 1}]))

# ---- a plan over DESCRIBED clips cuts on Claude's events, and the review offers them as swaps -------------------------------------------
desc_pool = []
for i in range(8):
    c = clip(i, "ABCDEFGH"[i], dur=30); c["events"] = [{"t": 9.0 + i, "kind": "action", "punch": 8, "what": f"thing {i}"}, {"t": 21.0, "kind": "reveal", "punch": 5, "what": "second"}]
    desc_pool.append(c)
dg = run(desc_pool, [2.0] * 4)
centre = lambda s: s["source_in"] + s["duration_frames"] / 24 / 2
check("a plan over described clips cuts on each clip's best event", all(s["moment_source"].startswith("event pick") and abs(centre(s) - (9.0 + s["file_id"])) < 0.3 for s in dg["shots"]),
      [(s["file_id"], round(centre(s), 1), s["moment_source"][:12]) for s in dg["shots"]])
check("the plan still counts those shots as event-based", dg["summary"]["moment_sources"]["event"] == 4 if "summary" in dg else True)
dplan = {"mode": "highlight", "fps": 24, "duration_seconds": 8.0, "style": "test", "shots": dg["shots"], "checks": {"bookend": False}}
dalts = post_pick.alternatives(dplan, desc_pool)
check("swaps for described clips are event picks too, and never have a cut inside", all(len(v) >= 1 for v in dalts.values()) and any("event pick" in a["note"] for v in dalts.values() for a in v)
      and all(a["steady"]["cuts"] == 0 for v in dalts.values() for a in v))

# ---- speed: a big shoot --------------------------------------------------------------------------------------------------------------
import time
big = [clip(i, "ABCDEFGH"[i % 8], dur=int(rng.integers(8, 90))) for i in range(200)]
t0 = time.time(); run(big, [2.0] * 17 + [4.3], end_card=True); dt = time.time() - t0
check("200 clips plan in under 15 seconds", dt < 15, round(dt, 1))
check("the analysis cache is versioned so older analyses are read again once", post_steady.CACHE_VERSION == 2)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
