"""Tests for the section-ordered planning (reel autopilot phase 3 step 2, 2026-11-17): the picker's section bonus, keeping main moments for the peak,
returning to main clips in the peak, the softer shoot order, and the section report. Synthetic clips and windows only: no footage, no files, no network."""
import sys
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_pick as pp
from app.post_edit_highlight import section_report

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

def clip(fid, scene):
    return {"file_id": fid, "name": f"C{fid}.MP4", "duration": 10.0, "steady": {"seconds": 10.0}, "scene": scene}

def window(start, role, score=0.05, punch=6, kind="action"):
    return {"start": start, "duration": 0.6, "source": "test", "overlaps_earlier_use": False, "event_punch": punch, "event_kind": kind, "event_role": role,
            "steady": {"score": score, "cuts": 0, "static": False}}

def picker(clips, windows, **kw):
    p = pp.Picker(clips, **kw)
    p._candidates = lambda c, length: windows[c["file_id"]]
    p._signature = lambda c, w: None
    return p

A, B = clip(1, "store wide"), clip(2, "people dancing")
W = {1: [window(1.0, "place", score=0.10)], 2: [window(1.0, "person", score=0.02)]}

got = picker([A, B], W).pick(0.6, 0.5)
check("no section: the cleaner stretch wins, as before (people clip)", got["clip"]["file_id"] == 2, got["parts"])
got = picker([A, B], W).pick(0.6, 0.5, section_role="place")
check("a place section takes the place moment over a slightly cleaner person moment", got["clip"]["file_id"] == 1 and got["parts"]["section_bonus"] == pp.SECTION_ROLE_BONUS, got["parts"])
check("the chosen shot's role and section bonus are reported", got["parts"]["shot_role"] == "place")

M = clip(3, "ribbon cutting")
W2 = {1: [window(1.0, "place", score=0.05)], 3: [window(1.0, "main_moment", score=0.01, punch=9)]}
got = picker([A, M], W2).pick(0.6, 0.5, section_role="place")
check("outside the peak a main moment is held back (penalised) so the place shot wins", got["clip"]["file_id"] == 1, got["parts"])
got = picker([A, M], W2).pick(0.6, 0.5, section_role="main_moment")
check("in the peak the main moment wins", got["clip"]["file_id"] == 3)

# returning to a main clip in the peak
M2 = clip(4, "dancers")
W3 = {3: [window(1.0, "main_moment", score=0.01), window(5.0, "main_moment", score=0.01)], 4: [window(1.0, "person", score=0.01)]}
OTHER = clip(5, "crowd")
W3[5] = [window(1.0, "person", score=0.01)]
W3[4] = [window(1.0, "person", score=0.08)]   # a usable but shakier non-main shot
p = picker([M, M2, OTHER], W3, position_scale=0.25)   # as section mode runs it
first = p.pick(0.6, 0.5, section_role="main_moment")
p.register(first["clip"], first["window"])
p.register(OTHER, W3[5][0])          # a different shot in between: the peak cuts away and comes back
second = p.pick(0.6, 0.6, section_role="main_moment")
check("after cutting away, the peak goes back to the main clip for another of its moments rather than taking a non-main shot",
      second["clip"]["file_id"] == 3 and second["parts"]["reused_clip"], second["parts"])
p2 = picker([M, M2], W3)
f2 = p2.pick(0.6, 0.5, section_role="person")
p2.register(f2["clip"], f2["window"])
s2 = p2.pick(0.6, 0.6, section_role="person")
check("outside the peak, a clip already used is still avoided at the full reuse penalty", s2["clip"]["file_id"] != f2["clip"]["file_id"] or not s2["parts"]["reused_clip"], s2["parts"])

# shoot order counts less in section mode
early, late = clip(10, "a"), clip(11, "b")
W4 = {10: [window(1.0, "detail", score=0.05)], 11: [window(1.0, "detail", score=0.07)]}
p_full, p_soft = picker([early, late], W4), picker([early, late], W4, position_scale=0.25)
p_full.pool = p_soft.pool = [early]   # only the early clip can be picked, for a slot at the very end of the edit
full, soft = p_full.pick(0.6, 1.0), p_soft.pick(0.6, 1.0)
check("the shoot-order penalty is scaled down in section mode", soft["parts"]["position_penalty"] < full["parts"]["position_penalty"] and soft["parts"]["position_penalty"] == round(0.25 * full["parts"]["position_penalty"], 3),
      (full["parts"]["position_penalty"], soft["parts"]["position_penalty"]))

check("the default number of moments offered per clip is still the module's constant", pp.Picker([A]).event_candidates == pp.EVENT_CANDIDATES)
check("section mode can offer every described moment", pp.Picker([A], event_candidates=pp.SECTION_EVENT_CANDIDATES).event_candidates == 5)

# spreading the peak over the event's main clips
RIB = dict(clip(20, "ribbon"), main_clip=True)
DJ1, DJ2 = clip(21, "dj booth"), clip(22, "dj decks")
W5 = {20: [window(1.0, "main_moment", score=0.06)], 21: [window(1.0, "main_moment", score=0.01)], 22: [window(1.0, "main_moment", score=0.01)]}
got = picker([RIB, DJ1, DJ2], W5, position_scale=0.25).pick(0.6, 0.5, section_role="main_moment")
check("in the peak a named main clip (the ribbon) wins over a slightly cleaner main moment of another clip", got["clip"]["file_id"] == 20, got["parts"])
check("the main-clip bonus is never given outside the peak",
      picker([RIB, DJ1, DJ2], W5, position_scale=0.25).pick(0.6, 0.5, section_role="person")["parts"]["section_bonus"] <= 0)
p5 = picker([RIB, DJ1, DJ2], {20: [window(1.0, "main_moment", score=0.01), window(5.0, "main_moment", score=0.01)], 21: W5[21], 22: W5[22]}, position_scale=0.25)
a = p5.pick(0.6, 0.5, section_role="main_moment"); p5.register(a["clip"], a["window"], section_role="main_moment")
check("each peak shot taken from a clip is counted", p5.peak_uses == {a["clip"]["file_id"]: 1}, p5.peak_uses)
p5.register(DJ1, W5[21][0], section_role="person")
check("a shot outside the peak isn't counted", 21 not in p5.peak_uses)

# each clip's moments in the order they happened
from app.post_edit_highlight import order_peak
def shot(i, fid, src, frames=15, section="main moment", what=""):
    return {"index": i, "file_id": fid, "start_frame": i * 15, "duration_frames": frames, "source_in": src, "source_out": src + frames / 25,
            "moment_source": what, "section": section, "shot_role": "main_moment"}
sh = [shot(1, 20, 6.0, what="cheer"), shot(2, 21, 3.0), shot(3, 20, 2.8, what="cut"), shot(4, 20, 4.3, what="raise"), shot(5, 20, 1.0, section="people")]
moved = order_peak(sh, 25.0, {20: {"duration": 10.0}, 21: {"duration": 10.0}})
check("the peak plays the ribbon clip's moments in source order (cut, raise, cheer) in the same slots",
      [s["moment_source"] for s in sh if s["file_id"] == 20 and s["section"] == "main moment"] == ["cut", "raise", "cheer"] and [s["start_frame"] for s in sh[:4]] == [15, 30, 45, 60], sh)
check("source out follows each slot's own length, and the count is right", all(abs(s["source_out"] - (s["source_in"] + s["duration_frames"] / 25)) < 1e-6 for s in sh) and moved == 3, moved)
check("a shot outside the peak is left alone", sh[4]["source_in"] == 1.0)
sh2 = [shot(1, 20, 9.7, frames=5), shot(2, 20, 1.0, frames=20)]
check("a swap that would run past the end of the clip is skipped", order_peak(sh2, 25.0, {20: {"duration": 10.0}}) == 0 and sh2[0]["source_in"] == 9.7)

# the section report
shots = [{"section": "open", "shot_role": "person", "start_frame": 0, "duration_frames": 25},
         {"section": "place", "shot_role": "place", "start_frame": 25, "duration_frames": 15},
         {"section": "place", "shot_role": "detail", "start_frame": 40, "duration_frames": 15}]
secs = [{"name": "open", "role": "person", "until": 0.3}, {"name": "place", "role": "place", "until": 0.8}, {"name": "close", "role": "place", "until": 1.0}]
rep = section_report(shots, secs, 25.0)
check("section report: shots and matches per section, with times", rep[0] == {"name": "open", "role": "person", "shots": 1, "matched": 1, "start_seconds": 0.0, "end_seconds": 1.0}
      and rep[1]["shots"] == 2 and rep[1]["matched"] == 1 and rep[1]["end_seconds"] == 2.2, rep)
check("an empty section is reported with no times", rep[2] == {"name": "close", "role": "place", "shots": 0, "matched": 0, "start_seconds": None, "end_seconds": None}, rep[2])

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
