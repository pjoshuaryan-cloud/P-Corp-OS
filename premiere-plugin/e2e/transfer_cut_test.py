"""Tests for learning/transfer_cut.py (learn from a cut he made by hand in one orientation, re-make it in the other from different footage) and the parts of
post_learn / post_autosave it needs (a P Corp-built sequence in his own project is compared with its learned plan, never logged as his cut). Synthetic clips
with real steadiness measurements; temp folders only. Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python transfer_cut_test.py"""
import asyncio
import copy
import json
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import make_clips  # noqa: E402
from app import post_autosave as pa, post_learn as pl, post_learning_events as le  # noqa: E402
from learning import prproj, transfer_cut as tc  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
BY = {c["name"]: c for c in CLIPS}

# ---- small pieces ---------------------------------------------------------------------------------------------------------------------------------------
check("tokens keep the words that say what is in a shot, not filler", tc.tokens("A wide shot of the crew setting up lights in the kitchen") == {"crew", "setting", "lights", "kitchen"},
      tc.tokens("A wide shot of the crew setting up lights in the kitchen"))
c0 = next(c for c in CLIPS if c.get("events"))
e0 = max(c0["events"], key=lambda e: e["punch"])
check("the moment a window sits on: the strongest described one inside it", tc.moment_at(c0, e0["t"] - 0.3, e0["t"] + 0.3)["t"] == e0["t"] or tc.moment_at(c0, e0["t"] - 0.3, e0["t"] + 0.3)["punch"] >= e0["punch"] - 0)
check("a window covering half his shot is a hit; a quarter is not", tc._hit(1.0, 1.0, 1.5, 1.0) and not tc._hit(1.0, 1.0, 1.75, 1.0))
check("the chance a random window hits is exact (a 10 s clip, 1 s shot: about 1 in 9)", abs(tc._random_hit(10.0, 1.0, 4.0) - 1.0 / 9.0) < 1e-9, tc._random_hit(10.0, 1.0, 4.0))

# ---- placement: a habit that IS there is found on held-out shots; the gate decides --------------------------------------------------------------------------
described = [c for c in CLIPS if c.get("events") and c.get("steady")]
habit = []
for k, c in enumerate(described):   # "he" always starts 0.6 s after Claude's best moment would put a centred window
    L = 0.8
    m = tc._best_moment(c)
    start = round(float(m["t"]) - L / 2.0 + 0.6, 3)
    if tc._valid(c, start, L):
        habit.append({"order": k + 1, "name": c["name"], "source_in": start, "source_out": start + L, "length": L, "frames": 20})
pt = tc.placement_test(habit, BY)
check("a consistent habit (0.6 s after Claude's moment) is learned on held-out shots, and beats the default by the bar", pt["gate_met"] and pt["learned (held out)"] > pt["default"],
      pt)
check("...the learned offset is the habit's", abs(pt["params_on_all"]["offset"] - 0.6) < 0.01, pt["params_on_all"])
rng = random.Random(3)
noise = []
for k, c in enumerate(described):   # no habit: a random place in each clip
    L = 0.8
    for _ in range(20):
        start = round(rng.uniform(0, c["duration"] - L - 0.05), 3)
        if tc._valid(c, start, L):
            noise.append({"order": k + 1, "name": c["name"], "source_in": start, "source_out": start + L, "length": L, "frames": 20})
            break
pn = tc.placement_test(noise, BY)
check("with no habit the learned rule does not clear the bar (nothing is adopted)", not pn["gate_met"], pn)
check("the test reports what chance alone would get", pn["random_expected"] > 0 and pn["shots"] == len(noise))

# ---- selection: real signal vs none ----------------------------------------------------------------------------------------------------------------------------
pool = [c for c in CLIPS if c.get("steady")]
feats = {c["name"]: tc.clip_features(c) for c in pool}
by_quality = sorted(pool, key=lambda c: -feats[c["name"]][0])
used_good = {c["name"] for c in by_quality[: len(pool) * 3 // 4]}
sg = tc.selection_test(pool, used_good)
check("if he keeps the steadiest clips, that is found (AUC well above 0.5, interval above 0.5)", sg["auc"] > 0.8 and sg["useful"], sg)
# one random draw can line up with these very regular synthetic clips by chance (seed 5 does: AUC 0.93); what matters is how OFTEN random choices are called useful
false_alarms = sum(tc.selection_test(pool, {c["name"] for c in random.Random(100 + k).sample(pool, len(pool) * 3 // 4)})["useful"] for k in range(30))
check("random choices are (almost) never called useful: at most 2 of 30 random labellings", false_alarms <= 2, false_alarms)

# ---- the alignment ----------------------------------------------------------------------------------------------------------------------------------------------
vert = [dict(c, scene=s, events=[{"t": 1.0, "kind": k, "punch": 7, "what": w}]) for c, (s, k, w) in zip(
    [c for c in CLIPS if c.get("steady")][:8],
    [("kitchen", "action", "chef plates the dish"), ("street", "camera_move", "car passes the shop"), ("kitchen", "hero", "the bottle on the counter"),
     ("stage", "reaction", "crowd laughs"), ("beach", "reveal", "sun over the water"), ("office", "action", "team reviews the monitor"),
     ("crowd", "reaction", "guests raise glasses"), ("kitchen", "hero", "wine poured into a glass")])]
his_p = [{"tokens": tc.tokens("chef plates the dish kitchen"), "kind": "action", "people": True},
         {"tokens": tc.tokens("crowd laughs stage"), "kind": "reaction", "people": True},
         {"tokens": tc.tokens("crowd laughs stage"), "kind": "reaction", "people": True},
         {"tokens": tc.tokens("wine poured glass kitchen"), "kind": "hero", "people": False}]
path = tc.align(his_p, [False, False, True, False], [0.8, 0.8, 0.8, 0.8], vert, [0.0] * len(vert))
check("the alignment never goes backwards in recording order", all(a <= b for a, b in zip(path, path[1:])), path)
check("...matches like with like (chef -> chef, crowd laughs -> crowd laughs, poured wine -> poured wine)", path[0] == 0 and path[1] == 3 and path[3] == 7, path)
check("...and repeats a clip where he did (two moments of one clip back to back)", path[2] == path[1], path)
path2 = tc.align(his_p, [False, False, False, False], [0.8] * 4, vert, [0.0] * len(vert))
check("where he did NOT repeat, it prefers another clip", path2[2] != path2[1], path2)
short = [dict(v) for v in vert]
short[3]["duration"] = 0.5
path3 = tc.align(his_p, [False, False, True, False], [0.8] * 4, short, [0.0] * len(short))
check("a clip too short for the slot is never used", 3 not in path3, path3)

# ---- aiming the window at the moment most like his shot (2026-10-23) --------------------------------------------------------------------------------------
base = next(c for c in CLIPS if c.get("steady") and c["duration"] >= 8 and tc._valid(c, 1.6, 0.8) and tc._valid(c, 5.6, 0.8))
clip = dict(base, events=[{"t": 2.0, "kind": "action", "punch": 5, "what": "Crew member with a tripod walks along the pool"},
                          {"t": 6.0, "kind": "reaction", "punch": 9, "what": "Woman laughs on the sofa"}])
walker = {"what": "Crew member walks across frame beside the umbrella light", "scene": "garden", "kind": "action"}
start, at = tc.aim_at_match(walker, clip, 0.8, 5.6, [])
check("the window moves to the clip's moment most like his shot (shared words), centred on it", at is not None and at["t"] == 2.0 and start == 1.6, (start, at))
smiler = {"what": "Hand on chest, smiling and looking down", "scene": "living room", "kind": "reaction"}
start, at = tc.aim_at_match(smiler, clip, 0.8, 1.6, [])
check("...but NOT for a moment that only shares the kind label ('reaction') and no words", at is None and start == 1.6, (start, at))
start, at = tc.aim_at_match(walker, clip, 0.8, 5.6, [(1.5, 2.5)])
check("...and not onto a stretch of the clip another slot already uses", at is None and start == 5.6, (start, at))
start, at = tc.aim_at_match(walker, dict(clip, duration=2.3), 0.8, 0.5, [])
check("...the aimed window stays inside the clip (clamped), or the rule's start stands", at is None or start + 0.8 <= 2.3 - 0.04, (start, at))

# ---- his music (2026-10-23: the learned plan of his FINISHED cut carries his song, as he set it) ------------------------------------------------------------
import math  # noqa: E402
import subprocess  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from app import post_music, post_reference  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tc_"))
song = {"name": "Song.mp3", "kind": "music", "start": 0.0, "end": 22.3}
crowd = {"name": "Crowd Chatter.mp3", "kind": "music", "start": 0.0, "end": 1.83}
whoosh = {"name": "Bass Pass 2 - Whoosh.wav", "kind": "sfx", "start": 1.8, "end": 4.4}
camera = {"name": "C2969.MP4", "kind": "camera_audio", "start": 0.0, "end": 22.3}
check("the song under the cut is picked over an ambience bed, a sound effect and camera sound", tc.pick_music_bed([crowd, whoosh, camera, song], 22.3) is song)
check("...and nothing is picked when no bed covers half the cut (a 1.8 s ambience bed is not 'the music')", tc.pick_music_bed([crowd, whoosh, camera], 22.3) is None)

ids = {}
item = ET.fromstring('<I><ClipTrackItem><ComponentOwner><Components ObjectRef="1"/></ComponentOwner></ClipTrackItem></I>')
ids["1"] = ET.fromstring('<Cs><Component ObjectRef="2"/></Cs>')
ids["2"] = ET.fromstring('<C><Param ObjectRef="3"/><Param ObjectRef="4"/></C>')
ids["3"] = ET.fromstring("<P><Name>Mute</Name></P>")
ids["4"] = ET.fromstring("<P><Name>Level</Name><StartKeyframe>-91445760000000000,0.099801637232,0,0,0,</StartKeyframe></P>")
check("Premiere's stored Volume Level reads as dB (his HAUS song: 0.0998 -> -5.0 dB; 0.1778 = 0 dB)", post_reference._audio_level_db(item, ids) == -5.02,
      post_reference._audio_level_db(item, ids))

click = TMP / "clicks.wav"   # 30 s of a click every half second (120 BPM), so the tempo reader has beats to find
subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*220*t)+if(lt(mod(t,0.5),0.02),0.4*sin(2*PI*1500*t),0)':s=48000:d=30",
                str(click)], check=True)


def rms(path, a=None, b=None):
    raw = subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    import numpy as np
    x = np.frombuffer(raw, dtype=np.float32)[(int(a * 48000) if a is not None else None):(int(b * 48000) if b is not None else None)]
    return float(np.sqrt(np.mean(x ** 2)))


cut = TMP / "cut.wav"
asyncio.run(post_music.render_music_cut(str(click), str(cut), 10.0, 5.0, fade_out=0.02, gain_db=-5.0))
check("a music cut rendered at his level is 5 dB down on the song", abs(20 * math.log10(rms(cut, 1, 4) / rms(click, 11, 14)) + 5.0) < 0.1,
      20 * math.log10(rms(cut, 1, 4) / rms(click, 11, 14)))
check("...and ends hard like his (no 1.5 s fade: the last 0.3 s is as loud as the middle)", rms(cut, 4.65, 4.95) > 0.9 * rms(cut, 2.0, 2.3))

saved_music = tc.his_music
try:
    tc.his_music = lambda p, s: {"name": "clicks.wav", "path": str(click), "timeline_start": 0.0, "timeline_end": 5.0, "in_seconds": 10.0, "level_db": -5.02}
    music, note = tc.music_for_plan("/x/HAUS.prproj", TMP, 120, 24.0)
    check("his song goes into the plan: cut from where his starts, the plan's length, at his level, no fade", Path(music["cut_path"]).exists() and music["in_seconds"] == 10.0
          and music["gain_db"] == -5.02 and music["fade_out_seconds"] == 0.02 and abs(rms(music["cut_path"]) - rms(cut)) < 0.01 and "-5.0 dB" in note, (music, note))
    check("...the cut is the plan's exact length (120 frames at 24 fps = 5.000 s)", abs(float(subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries",
          "format=duration", "-of", "csv=p=0", music["cut_path"]], capture_output=True, text=True).stdout) - 5.0) < 0.002)
    tc.his_music = lambda p, s: {"name": "clicks.wav", "path": str(click), "timeline_start": 0.5, "timeline_end": 5.0, "in_seconds": 10.0, "level_db": None}
    music, note = tc.music_for_plan("/x/HAUS.prproj", TMP, 120, 24.0)
    check("a song that starts later in his cut is NOT placed at the start (the build can only place from 0), and the note says why", music == {} and "starts 0.50 s" in note, note)
    tc.his_music = lambda p, s: {"name": "gone.mp3", "path": "/nowhere/gone.mp3", "timeline_start": 0.0, "timeline_end": 5.0, "in_seconds": 1.0, "level_db": None}
    music, note = tc.music_for_plan("/x/HAUS.prproj", TMP, 120, 24.0)
    check("a song whose file is missing is not placed; the note names it", music == {} and "gone.mp3" in note, note)
    tc.his_music = lambda p, s: None
    check("no music in his cut -> none in the plan", tc.music_for_plan("/x/HAUS.prproj", TMP, 120, 24.0) == ({}, "No music: your cut has none."))
finally:
    tc.his_music = saved_music

# ---- his own project: a P Corp-built sequence is compared with its learned plan, never logged as his cut -----------------------------------------------------
REAL = (pl.FEEDBACK_DIR, pl._REAL_FEEDBACK_DIR, le.CENTRAL_EVENTS)
pl.FEEDBACK_DIR, pl._REAL_FEEDBACK_DIR, le.CENTRAL_EVENTS = TMP / "fb", TMP / "fb_real_elsewhere", TMP / "central.jsonl"
PROJ = "/Volumes/Lexar - A/X/HAUS.prproj"
plan = {"fps": 25.0, "duration_frames": 60, "made_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600)), "style": "learned:horizontal - CUT LOCK",
        "learned_from": {"cut": "horizontal - CUT LOCK"}, "mode": "learned_transfer",
        "shots": [{"index": i + 1, "role": "body", "file_id": 2906 + i, "name": f"C{2906 + i}.MP4", "path": f"/x/C{2906 + i}.MP4", "start_frame": i * 20, "duration_frames": 20,
                   "source_in": 1.0, "source_out": 1.8, "moment_source": "matched to your horizontal shot"} for i in range(3)]}
built_name = "HAUS (vertical, learned) - Edit " + time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
his_version = [prproj.Shot(t0=0.0, t1=0.8, src_in=1.0, src_out=1.8, path="/x/C2906.MP4", name="C2906.MP4", track=1, src_duration=8.0),     # kept
               prproj.Shot(t0=0.8, t1=1.6, src_in=4.0, src_out=4.8, path="/x/C2907.MP4", name="C2907.MP4", track=1, src_duration=8.0)]     # another moment; C2908 dropped
saved = (pl.read_final_edit, tc.load_project_plan, tc.project_moments)
pl.read_final_edit = lambda p, s: (built_name, his_version)
tc.load_project_plan = lambda p: copy.deepcopy(plan)
tc.project_moments = lambda p: {"2906": {"name": "C2906.MP4", "duration": 8.0, "events": [{"t": 1.4, "kind": "action", "punch": 8, "what": "chef plates the dish"}]}}
try:
    out = asyncio.run(pl.learn_from_project(PROJ, built_name))
    s = out["summary"]
    check("Learn on the built vertical compares it with the learned plan: 1 kept, 1 moved to another moment, 1 dropped", out.get("learned_plan") and s["plan_shots_kept"] == 1
          and s["plan_shots_different_moment"] == 1 and s["plan_shots_dropped"] == 1, s)
    check("...and says it is the score of what P Corp learned", any("how much of it you kept" in x for x in out["lines"]), out["lines"])
    check("...with his project's clip descriptions (it passed none: his HAUS click said no clip was described, though all 117 were)",
          s["described_shots_checked"] == 1 and s["at_a_described_moment"] == 1 and any("Claude's described moments" in x for x in out["lines"]), s)
    check("...and a finishing it can't read (no real project here) is one line, never a failed click", any(x.startswith("Couldn't read the finishing") for x in out["lines"]))
    idx = json.loads((pl.FEEDBACK_DIR / "index.jsonl").read_text().splitlines()[-1])
    check("...logged as a learned-plan comparison (not as his cut, not in the P Corp planner's agreement totals)", idx["learned_plan"] and not idx["no_plan"]
          and pl.aggregate()["edits_compared_with_their_own_plan"] == 0, idx)
    tc.load_project_plan = lambda p: None
    try:
        asyncio.run(pl.learn_from_project(PROJ, built_name))
        check("a P Corp-built sequence with no learned plan is refused, never logged as his cut", False)
    except pl.LearnError as exc:
        check("a P Corp-built sequence with no learned plan is refused, never logged as his cut", "built by P Corp OS" in str(exc), str(exc))
finally:
    pl.read_final_edit, tc.load_project_plan, tc.project_moments = saved

store = pa.Store(TMP / "watch")
pj = pa.project_job(PROJ)
rows = [[f"C{2906 + i}.MP4", 1.0, 1.8, i * 0.8, 0.8, 1.0, 8.0] for i in range(6)]
store.append_snapshot(pj["id"], {"file": "a", "main": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600)), "sequence": built_name,
                                 "built_at": pl.built_at(built_name), "seconds": 4.8, "n": 6, "whole_clip": False, "hash": "b1", "shots": rows})
check("the auto-save watch never logs a P Corp-built sequence in his project as his cut", pa.settle_job(store, pj) == [])
pl.FEEDBACK_DIR, pl._REAL_FEEDBACK_DIR, le.CENTRAL_EVENTS = REAL

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
