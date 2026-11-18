"""Tests for backend/app/post_finishing.py (reel autopilot phase 3 step 3): where the blur moves go, their whooshes, the music tail-off.
Synthetic shots and a made-up sound index only: no files, no network."""
import sys
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_finishing as fin

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

FPS = 25.0
def shots_for(sections, frames=25, src=2.0):
    out = []
    for i, sec in enumerate(sections):
        out.append({"index": i + 1, "file_id": 100 + i, "start_frame": i * frames, "duration_frames": frames, "source_in": src, "source_out": src + frames / FPS, "section": sec})
    return out
CLIPS = {100 + i: {"duration": 10.0} for i in range(80)}

# 35 s at 1 s a shot: open 0-3, place 3-7, people 7-16, details 16-22, main 22-31, close 31-35
secs = ["open"] * 3 + ["place"] * 4 + ["people"] * 9 + ["details"] * 6 + ["main moment"] * 9 + ["close"] * 4
S = shots_for(secs)
check("every change of section is a join", [b for a, b in fin.section_joins(S)] == [3, 7, 16, 22, 31])
moves, cands = fin.choose_moves(S, FPS, CLIPS)
check("2-4 blur moves", fin.MIN_MOVES <= len(moves) <= fin.MAX_MOVES, moves)
check("they lead into the place, main moment and close first", [m["into_section"] for m in moves][:4] == ["place", "details", "main moment", "close"] or
      {"place", "main moment", "close"} <= {m["into_section"] for m in moves}, [m["into_section"] for m in moves])
check("never closer than 5 s", all(b["cut_frame"] - a["cut_frame"] >= 5 * FPS for a, b in zip(moves, moves[1:])), [m["cut_frame"] for m in moves])
check("in timeline order, Premiere's whip, 0.4 s centred on the cut", [m["cut_frame"] for m in moves] == sorted(m["cut_frame"] for m in moves)
      and all(m["transition"] == "AE.ADBE Whip" and m["frames"] == 10 and m["alignment"] == "centre" for m in moves))
check("each move sits on a real cut between the named shots", all(S[m["to_shot"] - 1]["start_frame"] == m["cut_frame"] and m["from_shot"] == m["to_shot"] - 1 for m in moves))

# no footage beyond the cut -> no move there
S2 = shots_for(secs)
for s in S2:
    if s["section"] == "place":
        s["source_in"] = 0.1   # the place shots start right at the top of their clips: no handle before the cut into place
moves2, cands2 = fin.choose_moves(S2, FPS, CLIPS)
check("a join without footage either side of the cut gets no blur move", "place" not in [m["into_section"] for m in moves2] and any(not c["handles"] for c in cands2), moves2)
S3 = shots_for(secs)
S3[30]["source_out"] = 9.9   # last main-moment shot ends 0.1 s before its clip does: no handle after the cut into close
check("...on either side", "close" not in [m["into_section"] for m in fin.choose_moves(S3, FPS, CLIPS)[0]])
S4 = shots_for(secs)
S4[3]["file_id"] = S4[2]["file_id"]
check("the same clip either side of a section change isn't a change of place", "place" not in [m["into_section"] for m in fin.choose_moves(S4, FPS, CLIPS)[0]])
check("no sections, no moves", fin.choose_moves(shots_for([None] * 10), FPS, CLIPS)[0] == [])

# whooshes
IDX = [{"role": "whoosh", "path": f"/x/W{k}.wav", "name": f"W{k}.wav", "seconds": 3.0, "peak_seconds": 1.0, "tail_seconds": 0.5} for k in range(5)] + \
      [{"role": "whoosh", "path": "/x/late.wav", "name": "late.wav", "seconds": 6.0, "peak_seconds": 4.0, "tail_seconds": 0.5},
       {"role": "hit", "path": "/x/hit.wav", "name": "hit.wav", "seconds": 1.0, "peak_seconds": 0.05, "tail_seconds": 0.3}]
wh = fin.plan_whooshes(moves, FPS, IDX)
check("one whoosh per blur move, on A4", len(wh) == len(moves) and all(w["track"] == 4 and w["role"] == "whoosh" for w in wh))
check("its loudest moment lands on the cut", all(w["start_frame"] + 25 == w["under_move_at"] for w in wh), [(w["start_frame"], w["under_move_at"]) for w in wh])
check("only usable whooshes (no hits, no late-peaking files)", all(w["name"].startswith("W") for w in wh))
check("different whooshes for different moves", len({w["name"] for w in wh}) == len(wh))
check("no library, no whooshes", fin.plan_whooshes(moves, FPS, None) == [] and fin.plan_whooshes(moves, FPS, IDX[-1:]) == [])

# the whole finishing on a plan
plan = {"shots": S, "music": {"in_seconds": 10.0, "fade_out_seconds": 2.4}}
f = fin.plan_finishing(plan, FPS, CLIPS, sfx_index=IDX)
check("the music tails off over 4 s, on the plan itself", plan["music"]["fade_out_seconds"] == 4.0 and f["music_fade_seconds"] == 4.0)
check("the finishing says it isn't placed by Premiere yet", f["built_by_premiere"] is False and any("phase 4" in n for n in f["notes"]))
check("the notes say where the moves go and that the rest are hard cuts", "hard cut" in f["notes"][0] and "into place" in f["notes"][0])
f2 = fin.plan_finishing({"shots": S, "music": {}}, FPS, CLIPS, sfx_index=None)
check("with no whooshes catalogued the plan says to plug in the SSD", f2["sfx"] == [] and any("Joshx SSD" in n for n in f2["notes"]))

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
