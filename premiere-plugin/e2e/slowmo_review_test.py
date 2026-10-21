"""Tests for the per-shot slow-motion toggle (2026-10-21): review logic (backend/app/post_review.py), the route in main.py, the slowed preview renders, the preview fingerprint,
Learn From My Edit's slow-motion line, and the review page's script.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python slowmo_review_test.py"""
import asyncio
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_edit_plan as pe, post_learn, post_review as pr  # noqa: E402
from learning import prproj  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


FPS = 25.0


def clip(file_id, name, fps, duration=20.0, scene="", events=None):
    return {"file_id": file_id, "name": name, "path": f"/x/{name}", "duration": duration, "created": "", "picks": [], "fps": fps, "scene": scene, "people": False,
            "events": events if events is not None else []}


def ev(t, kind="action", punch=8, what="something happens"):
    return {"t": t, "kind": kind, "punch": punch, "what": what}


def shot(index, role, c, source_in, frames=25, start=0):
    return {"index": index, "role": role, "file_id": c["file_id"], "name": c["name"], "path": c["path"], "source_in": source_in, "source_out": round(source_in + frames / FPS, 3),
            "start_frame": start, "duration_frames": frames, "moment_source": "event (action): something happens"}


A = clip(1, "A.MP4", 50.0, scene="kitchen", events=[ev(3.0), ev(9.0, "reveal", 7)])
B = clip(2, "B.MP4", 25.0, scene="street", events=[ev(5.0)])
C = clip(3, "C.MP4", 50.0, scene="beach", events=[ev(6.0)])
D = clip(4, "D.MP4", None, scene="forest", events=[ev(4.0)])
E = clip(5, "E.MP4", 59.94, scene="harbour", events=[ev(4.0)])
F = clip(6, "F.MP4", 50.0, duration=0.6, scene="tiny")
G = clip(7, "G.MP4", 25.0, scene="market", events=[ev(7.0, "reaction", 9)])   # a 25 fps clip the plan does not use, so the review offers it as a swap
CLIPS = [A, B, C, D, E, F, G]


def make_plan():
    shots = [shot(0, "opener", A, 1.0, 50, 0), shot(1, "body", A, 2.5, 25, 50), shot(2, "body", B, 4.5, 25, 75), shot(3, "body", D, 3.5, 25, 100), shot(4, "body", E, 3.5, 25, 125),
             shot(5, "body", F, 0.0, 10, 150), shot(6, "end_card", A, 1.0, 50, 160)]
    return {"mode": "reel", "fps": FPS, "style": "your-usual-pace", "duration_seconds": 8.4, "shots": shots,
            "zooms": {"items": [{"shot_index": 1, "direction": "in"}, {"shot_index": 2, "direction": "out"}]}}


# ---- who is offered slow motion --------------------------------------------------------------------------------------------------------------
plan = make_plan()
ok_a, why_a = pr.slow_check(plan, A, plan["shots"][1])
check("a body shot from a 50 fps clip in a 25 fps edit can be slowed", ok_a and why_a is None)
ok, why = pr.slow_check(plan, B, plan["shots"][2])
check("a 25 fps clip can't, and the reason says why in plain words", not ok and "25 fps" in why and "stutter" in why, why)
ok, why = pr.slow_check(plan, D, plan["shots"][3])
check("a clip with no known frame rate can't, and the reason says to run Analyze Media", not ok and "Analyze Media" in why, why)
ok, _ = pr.slow_check(plan, E, plan["shots"][4])
check("a 59.94 fps clip can", ok)
ok, why = pr.slow_check(plan, F, {**plan["shots"][5], "duration_frames": 50})
check("a clip too short to cut a half-speed window from can't (a 2 s slot needs 1 s of source; the clip has 0.6 s)", not ok and "too short" in why, why)
check("but a short slot on that same short clip can (0.2 s of source from 0.6 s)", pr.slow_check(plan, F, plan["shots"][5])[0])
check("the opening and closing cards are never offered it (no reason shown either)", pr.slow_check(plan, A, plan["shots"][0]) == (False, None) and pr.slow_check(plan, A, plan["shots"][6]) == (False, None))
check("a multicam interview is never offered it (its timing is the dialogue's)", pr.slow_check({**plan, "mode": "multicam"}, A, plan["shots"][1]) == (False, None))
ok, why = pr.slow_check({**plan, "fps": 50.0}, A, plan["shots"][1])
check("a 50 fps clip in a 50 fps edit can't (half speed would be 25 fps)", not ok and "stutter" in why, why)

# ---- the review shows it ------------------------------------------------------------------------------------------------------------------
rv = pr.build_review(plan, CLIPS)
slot = {s["index"]: s for s in rv["slots"]}
check("every slot says its speed, whether it can be slowed, and why not", all({"speed", "can_slow", "slow_note"} <= set(s) for s in rv["slots"]) and slot[1]["can_slow"] and not slot[2]["can_slow"] and slot[2]["slow_note"], slot[2])
check("nothing is slowed in a fresh plan", rv["slowed"] == 0 and all(s["speed"] == 1.0 for s in rv["slots"]))

# ---- slowing a shot ---------------------------------------------------------------------------------------------------------------------------
before = copy.deepcopy(plan)
out = pr.set_speed(plan, CLIPS, 1, 0.5)
s1 = plan["shots"][1]
check("slowing a shot keeps its slot exactly (cut timing never changes)", s1["start_frame"] == 50 and s1["duration_frames"] == 25)
check("it now shows HALF as much source: the window is the slot length times 0.5", abs((s1["source_out"] - s1["source_in"]) - 0.5) < 1e-9 and s1["speed"] == 0.5, (s1["source_in"], s1["source_out"]))
check("the half window is centred where the real-time window was (2.5-3.5 s -> 2.75-3.25 s)", abs(s1["source_in"] - 2.75) < 1e-9 and abs(s1["source_out"] - 3.25) < 1e-9, (s1["source_in"], s1["source_out"]))
check("the real-time window is remembered", s1["speed_original"] == {"source_in": 2.5, "source_out": 3.5}, s1.get("speed_original"))
check("its slow zoom is dropped (that timing assumed real time) and other shots' zooms are not", [z["shot_index"] for z in plan["zooms"]["items"]] == [2])
check("it counts as reviewed", 1 in plan["review"]["approved"])
check("the other shots are untouched", [s for s in plan["shots"] if s["index"] != 1] == [s for s in before["shots"] if s["index"] != 1])
rv = pr.build_review(plan, CLIPS)
slot = {s["index"]: s for s in rv["slots"]}
check("the review reports it: speed 0.5, one slowed, and its picture is the half-length window at that speed", slot[1]["speed"] == 0.5 and rv["slowed"] == 1 and slot[1]["current"]["speed"] == 0.5
      and abs(slot[1]["current"]["seconds"] - 0.5) < 1e-9 and slot[1]["can_slow"], slot[1]["current"])
check("the outcome carries what a taste model would want: the clip's frame rate, the slot length, the moment", out["clip"]["fps"] == 50.0 and out["slot"]["seconds"] == 1.0 and out["moment"]["kind"] == "action" and out["speed"] == 0.5 and out["was"] == 1.0, out)
again = copy.deepcopy(plan)
pr.set_speed(again, CLIPS, 1, 0.5)
check("slowing a slowed shot changes nothing", again["shots"] == plan["shots"])

# ---- and back -----------------------------------------------------------------------------------------------------------------------------------
pr.set_speed(plan, CLIPS, 1, 1.0)
check("putting it back restores the exact real-time window and leaves no slow-motion fields", plan["shots"][1] == before["shots"][1], plan["shots"][1])
n = copy.deepcopy(plan)
pr.set_speed(n, CLIPS, 3, 1.0)
check("setting a normal shot to normal changes nothing but marks it reviewed", n["shots"] == plan["shots"] and 3 in n["review"]["approved"])

# ---- refusals leave the plan alone -------------------------------------------------------------------------------------------------------------------
for label, slot_index, speed, expect in (("a 25 fps clip", 2, 0.5, "25 fps"), ("a clip with no frame rate", 3, 0.5, "Analyze Media"), ("the opener", 0, 0.5, "can't be slowed"),
                                          ("an unknown shot", 99, 0.5, "no shot 99"), ("a speed that isn't offered", 1, 0.75, "1.0")):
    snapshot = copy.deepcopy(plan)
    try:
        pr.set_speed(plan, CLIPS, slot_index, speed)
        check(f"refuses {label}", False)
    except pr.ReviewError as exc:
        check(f"refuses {label}, in words, and the plan is untouched", expect in str(exc) and plan == snapshot, str(exc))

# ---- edges of the clip --------------------------------------------------------------------------------------------------------------------------
edge = make_plan()
edge["shots"][1]["source_in"], edge["shots"][1]["source_out"] = 0.0, 1.0
pr.set_speed(edge, CLIPS, 1, 0.5)
check("a shot at the very start of its clip stays inside it (window 0.25-0.75 s)", abs(edge["shots"][1]["source_in"] - 0.25) < 1e-9 and edge["shots"][1]["source_in"] >= 0)
late = make_plan()
late["shots"][1]["source_in"], late["shots"][1]["source_out"] = 19.0, 20.0
pr.set_speed(late, CLIPS, 1, 0.5)
check("a shot at the very end stays inside its clip", late["shots"][1]["source_out"] <= A["duration"] + 1e-9 and late["shots"][1]["source_out"] - late["shots"][1]["source_in"] == 0.5, (late["shots"][1]["source_in"], late["shots"][1]["source_out"]))

# ---- swapping the moment of a slowed shot --------------------------------------------------------------------------------------------------------
sw = make_plan()
pr.set_speed(sw, CLIPS, 1, 0.5)
options = {c["id"]: c for c in pr.build_review(sw, CLIPS)["slots"][1]["alternatives"]}
by_clip = {c["file_id"]: c for c in options.values()}
check("the swap options for a slowed shot exist, on clips with and without slow-motion frame rates", 3 in by_clip and 7 in by_clip, sorted(by_clip))
to_c = by_clip[3]
pr.apply_choice(sw, CLIPS, 1, to_c["file_id"], to_c["source_in"], "swap")
sc = sw["shots"][1]
check("swapping to another 50 fps clip keeps the slow motion, with the half window centred in the new moment", sc["file_id"] == 3 and sc["speed"] == 0.5 and abs((sc["source_out"] - sc["source_in"]) - 0.5) < 1e-9
      and abs(sc["source_in"] - (to_c["source_in"] + 0.25)) < 1e-3 and sc["speed_original"]["source_in"] == to_c["source_in"], (sc, to_c["source_in"]))
check("the 'original' option remembers the REAL-TIME window, not the slowed one", sw["review"]["original"]["1"]["source_in"] == 2.5, sw["review"]["original"])
sw2 = make_plan()
pr.set_speed(sw2, CLIPS, 1, 0.5)
to_g = {c["file_id"]: c for c in pr.build_review(sw2, CLIPS)["slots"][1]["alternatives"]}[7]
pr.apply_choice(sw2, CLIPS, 1, to_g["file_id"], to_g["source_in"], "swap")
sb = sw2["shots"][1]
check("swapping to a 25 fps clip puts the shot back to real time (it can't be slowed there), with a full-length window", sb["file_id"] == 7 and "speed" not in sb and "speed_original" not in sb and abs((sb["source_out"] - sb["source_in"]) - 1.0) < 1e-9, sb)
sw3 = make_plan()
alt_same = {c["source_in"]: c for c in pr.build_review(sw3, CLIPS)["slots"][1]["alternatives"] if c["file_id"] == 1}
pr.apply_choice(sw3, CLIPS, 1, 1, next(iter(alt_same)), "swap")
check("swapping a shot that was never slowed is exactly what it always was (full window, no slow-motion fields)", "speed" not in sw3["shots"][1] and abs((sw3["shots"][1]["source_out"] - sw3["shots"][1]["source_in"]) - 1.0) < 1e-9)

# ---- the log ---------------------------------------------------------------------------------------------------------------------------------------
lp = make_plan()
out = pr.set_speed(lp, CLIPS, 1, 0.5)
back = pr.set_speed(lp, CLIPS, 1, 1.0)
with tempfile.TemporaryDirectory() as tmp:
    pr.log_speed_record(Path(tmp), 7, lp, out)
    pr.log_speed_record(Path(tmp), 7, lp, back)
    lines = [json.loads(l) for l in (Path(tmp) / "review_speed_log.jsonl").read_text().splitlines()]
    check("each decision is one line in its OWN file, 'slow' then 'normal', with the clip's frame rate and the slot", [l["action"] for l in lines] == ["slow", "normal"] and lines[0]["clip"]["fps"] == 50.0 and lines[0]["slot"]["index"] == 1 and lines[0]["job_id"] == 7, lines[0])
    check("and not in review_log.jsonl, which the taste tools read expecting a pick and what it passed over", not (Path(tmp) / "review_log.jsonl").exists())

# ---- the preview video and its fingerprint ------------------------------------------------------------------------------------------------------
plain = make_plan()
fp_plain = pe._shots_fingerprint({**plain, "music": {"cut_path": "x.wav", "in_seconds": 1.0}})
legacy_key = [[s["file_id"], s["source_in"], s["start_frame"], s["duration_frames"]] for s in plain["shots"]] + ["x.wav", 1.0]
check("a plan with no slow motion keeps exactly the fingerprint it always had (existing previews stay 'up to date')", fp_plain == hashlib.sha1(json.dumps(legacy_key).encode()).hexdigest()[:16])
slowed_plan = make_plan()
pr.set_speed(slowed_plan, CLIPS, 1, 0.5)
check("slowing a shot changes the fingerprint, so the old preview shows as out of date", pe._shots_fingerprint({**slowed_plan, "music": {"cut_path": "x.wav", "in_seconds": 1.0}}) != fp_plain)


class FakeProc:
    returncode = 0

    async def communicate(self):
        return b"", b""


def fake_exec_factory(calls):
    async def fake(*args, **kwargs):
        calls.append([str(a) for a in args])
        if "-vf" in args or "-c:v" in args and str(args[-1]).endswith(".mp4"):
            Path(str(args[-1])).write_bytes(b"x")   # the output file the caller checks for
        elif str(args[-1]).endswith(".mp4"):
            Path(str(args[-1])).write_bytes(b"x")
        return FakeProc()
    return fake


calls: list[list[str]] = []
real_exec = asyncio.create_subprocess_exec
asyncio.create_subprocess_exec = fake_exec_factory(calls)
try:
    with tempfile.TemporaryDirectory() as tmp:
        full = make_plan()
        pr.set_speed(full, CLIPS, 1, 0.5)   # shot 1 (A.MP4) slowed; shot 4 (E.MP4, 59.94 fps) left at normal speed
        pv = {"fps": FPS, "shots": [full["shots"][1], full["shots"][4]], "music": {"cut_path": "x.wav"}}
        asyncio.run(pe.render_preview(pv, "x.wav", str(Path(tmp) / "out.mp4"), str(Path(tmp) / "work")))
finally:
    asyncio.create_subprocess_exec = real_exec
per_shot = [c for c in calls if "-frames:v" in c]
vf = {c[c.index("-i") + 1]: c[c.index("-vf") + 1] for c in per_shot}
frames = {c[c.index("-i") + 1]: c[c.index("-frames:v") + 1] for c in per_shot}
check("the preview stretches a slowed shot's half window back to its slot (setpts 2x, then resample)", vf["/x/A.MP4"].startswith("setpts=2.0000*PTS,scale=") and "fps=25.0" in vf["/x/A.MP4"], vf)
check("a normal shot's preview command is exactly what it was (no setpts)", "setpts" not in vf["/x/E.MP4"], vf)
check("both still render exactly the slot's frames", frames["/x/A.MP4"] == "25" and frames["/x/E.MP4"] == "25", frames)

calls.clear()
asyncio.create_subprocess_exec = fake_exec_factory(calls)
try:
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(pr.render_review_clip("/x/A.MP4", 2.75, 0.5, Path(tmp) / "slow.mp4", 0.5))
        asyncio.run(pr.render_review_clip("/x/A.MP4", 2.5, 1.0, Path(tmp) / "normal.mp4"))
finally:
    asyncio.create_subprocess_exec = real_exec
slow_cmd, normal_cmd = calls[0], calls[1]
check("the review's small preview of a slowed shot plays the half window at half speed (setpts 2x) and its output limit is the stretched length (0.5 s of source = 1.0 s on screen)", slow_cmd[slow_cmd.index("-vf") + 1].startswith("setpts=2.0000*PTS,scale=-2:360,fps=25") and abs(float(slow_cmd[slow_cmd.index("-t") + 1]) - 1.0) < 1e-9, slow_cmd)
asyncio.create_subprocess_exec = fake_exec_factory(calls)
try:
    with tempfile.TemporaryDirectory() as tmp:
        calls.clear()
        asyncio.run(pr.render_review_clip("/x/A.MP4", 2.9, 0.2, Path(tmp) / "short.mp4", 0.5))
finally:
    asyncio.create_subprocess_exec = real_exec
check("a slowed shot too short to judge by eye still gets the 0.8 s minimum, measured in OUTPUT time (the -t limit applies after the slowdown)", abs(float(calls[0][calls[0].index("-t") + 1]) - 0.8) < 1e-9, calls[0])
check("a normal shot's small preview is exactly what it was", normal_cmd[normal_cmd.index("-vf") + 1] == "scale=-2:360,fps=25,format=yuv420p" and float(normal_cmd[normal_cmd.index("-t") + 1]) == 1.0, normal_cmd)
check("slowed and normal previews of the same window are cached under different names", pr.clip_cache_path(Path("/e"), 1, 2.5, 1.0, 0.5) != pr.clip_cache_path(Path("/e"), 1, 2.5, 1.0) and pr.clip_cache_path(Path("/e"), 1, 2.5, 1.0).name == "1_2500_1000.mp4")

# ---- with the real ffmpeg: the frames really are stretched, none dropped ------------------------------------------------------------------------------
import shutil as _shutil
import subprocess as _sp
from app.post_media import FFMPEG_PATH  # noqa: E402

if Path(FFMPEG_PATH).exists() and _shutil.which("ffprobe") or Path("/opt/homebrew/bin/ffprobe").exists():
    probe = "/opt/homebrew/bin/ffprobe" if Path("/opt/homebrew/bin/ffprobe").exists() else "ffprobe"

    def frames_and_seconds(path):
        out = _sp.run([probe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,r_frame_rate:format=duration", "-of", "json", str(path)], capture_output=True, text=True).stdout
        d = json.loads(out)
        return int(d["streams"][0]["nb_read_frames"]), float(d["format"]["duration"]), d["streams"][0]["r_frame_rate"]

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src50.mp4"
        _sp.run([FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=50:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
        slow_out, normal_out = Path(tmp) / "slow.mp4", Path(tmp) / "normal.mp4"
        asyncio.run(pr.render_review_clip(str(src), 1.0, 0.5, slow_out, 0.5))
        asyncio.run(pr.render_review_clip(str(src), 1.0, 1.0, normal_out))
        f_slow, d_slow, r_slow = frames_and_seconds(slow_out)
        f_norm, d_norm, _ = frames_and_seconds(normal_out)
        check("REAL ffmpeg: 0.5 s of 50 fps source at half speed is 25 frames played at 25 fps = 1.0 s, every frame kept", f_slow == 25 and abs(d_slow - 1.0) < 0.1 and r_slow == "25/1", (f_slow, d_slow, r_slow))
        check("REAL ffmpeg: a normal 1 s preview of the same footage is 25 frames (every other source frame)", f_norm == 25 and abs(d_norm - 1.0) < 0.1, (f_norm, d_norm))
        wav = Path(tmp) / "m.wav"
        _sp.run([FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "6", str(wav)], check=True)
        rp = make_plan()
        for c_ in (A, E):
            pass
        pv = {"fps": FPS, "music": {"cut_path": str(wav)}, "shots": []}
        slow_shot = {**rp["shots"][1], "path": str(src), "source_in": 1.25, "source_out": 1.75, "speed": 0.5, "start_frame": 0, "duration_frames": 25, "index": 1}    # a 1 s slot at half speed: 0.5 s of source
        normal_shot = {**rp["shots"][4], "path": str(src), "source_in": 0.0, "source_out": 1.0, "start_frame": 25, "duration_frames": 25, "index": 2}                 # a 1 s slot at normal speed: 1 s of source
        pv["shots"] = [slow_shot, normal_shot]
        out_mp4 = Path(tmp) / "preview.mp4"
        asyncio.run(pe.render_preview(pv, str(wav), str(out_mp4), str(Path(tmp) / "work")))
        f_pv, d_pv, _ = frames_and_seconds(out_mp4)
        check("REAL ffmpeg: the whole-edit preview of a slowed 1 s slot (0.5 s of source) plus a normal 1 s slot is 50 frames (2 s): the slowed shot fills its slot", f_pv == 50 and abs(d_pv - 2.0) < 0.2, (f_pv, d_pv))
else:
    print("SKIP the real-ffmpeg checks (ffmpeg/ffprobe not found)")

# ---- Learn From My Edit ------------------------------------------------------------------------------------------------------------------------
lp = make_plan()
pr.set_speed(lp, CLIPS, 1, 0.5)
pr.set_speed(lp, CLIPS, 4, 0.5)


def his(t0, length, clip_name, src_in, src_out):
    return prproj.Shot(t0=t0, t1=t0 + length, src_in=src_in, src_out=src_out, path=f"/x/{clip_name}", name=clip_name, track=1, src_duration=20.0)


mine = [his(0.0, 1.0, "A.MP4", 2.7, 3.2),      # the plan's slowed slot 1: he slowed it too (0.5 s of source in 1 s)
        his(1.0, 1.0, "E.MP4", 3.55, 3.95),     # the plan's slowed slot 4: he kept the shot but used it at normal speed ... 0.4 s source in 1.0 s = slowed too; make it normal below
        ]
mine[1] = his(1.0, 0.4, "E.MP4", 3.55, 3.95)    # 0.4 s of source in 0.4 s: real time
res = post_learn.analyse(lp, mine, {})
s_ = res["summary"]
check("Learn From My Edit counts the shots the plan slowed, how many he kept, and how many of those he slowed too", s_.get("plan_slowed_shots") == 2 and s_["plan_slowed_shots_kept"] == 2 and s_["plan_slowed_shots_you_slowed"] == 1 and s_["you_slowed_shots"] == 1, s_)
txt = " ".join(post_learn.lines("Seq", "style", res))
check("and says so in a plain sentence", "Slow motion: the plan slowed 2 shots; you kept 2 of them and slowed 1 of those" in txt, txt)
plain_res = post_learn.analyse(make_plan(), mine, {})
check("a plan with no slow motion reports exactly what it did before (no new fields, no new sentence)", "plan_slowed_shots" not in plain_res["summary"] and "Slow motion" not in " ".join(post_learn.lines("Seq", "style", plain_res)))
check("a plan's slot rows say which were slowed and whether he slowed them", [r.get("he_slowed") for r in res["plan_shots"] if r.get("speed")] == [True, False], [r for r in res["plan_shots"] if r.get("speed")])

# ---- the route --------------------------------------------------------------------------------------------------------------------------------------
import app.main as main  # noqa: E402
from fastapi import HTTPException  # noqa: E402

paths = {(r.path, tuple(sorted(r.methods))) for r in main.app.routes if hasattr(r, "methods")}
check("the speed route is registered as a POST beside the choice route", ("/post/jobs/{job_id}/edit-review/speed", ("POST",)) in paths and ("/post/jobs/{job_id}/edit-review/choice", ("POST",)) in paths)
check("the clip preview route takes a speed", "speed" in main.post_job_edit_review_clip.__code__.co_varnames)
with tempfile.TemporaryDirectory() as tmp:
    job = {"id": 5, "profile": "joshx", "destination_root": tmp, "shoot_name": "Test"}
    folder = Path(tmp) / "09_PROJECT FILES" / "edit_plans"
    folder.mkdir(parents=True)
    state = {"plan": make_plan()}
    (folder / "edit_plan_latest.json").write_text(json.dumps(state["plan"]))

    async def fake_context(job_id, request):
        return job, json.loads((folder / "edit_plan_latest.json").read_text()), CLIPS, None

    async def fake_on_drive(fn, *a, **kw):
        kw.pop("writing", None); kw.pop("timeout", None)
        return fn(*a, **kw)

    async def fake_record(*a, **kw):
        return None
    saved = (main._review_context, main.on_drive, main.record_tool_call)
    main._review_context, main.on_drive, main.record_tool_call = fake_context, fake_on_drive, fake_record
    try:
        res = asyncio.run(main.post_job_edit_review_speed(5, main.ReviewSpeedRequest(slot_index=1, speed=0.5), None, None))
        stored = json.loads((folder / "edit_plan_latest.json").read_text())
        check("the route slows the shot, saves the plan, and answers with the new card and the counts", res["slot"]["speed"] == 0.5 and res["slowed"] == 1 and res["approved"] >= 1 and stored["shots"][1]["speed"] == 0.5, res)
        check("and logs the decision", len((folder / "review_speed_log.jsonl").read_text().splitlines()) == 1)
        res = asyncio.run(main.post_job_edit_review_speed(5, main.ReviewSpeedRequest(slot_index=1, speed=1.0), None, None))
        stored = json.loads((folder / "edit_plan_latest.json").read_text())
        check("and puts it back", res["slowed"] == 0 and "speed" not in stored["shots"][1] and stored["shots"][1]["source_in"] == 2.5)
        for label, body, expect in (("a 25 fps clip", main.ReviewSpeedRequest(slot_index=2, speed=0.5), "25 fps"), ("an unknown shot", main.ReviewSpeedRequest(slot_index=99, speed=0.5), "no shot 99")):
            try:
                asyncio.run(main.post_job_edit_review_speed(5, body, None, None))
                check(f"the route refuses {label} with a plain 400", False)
            except HTTPException as exc:
                check(f"the route refuses {label} with a plain 400", exc.status_code == 400 and expect in str(exc.detail), exc.detail)
        check("a refusal saved and logged nothing", len((folder / "review_speed_log.jsonl").read_text().splitlines()) == 2)
        res = asyncio.run(main.post_job_edit_review_choice(5, main.ReviewChoiceRequest(slot_index=1, file_id=1, source_in=2.5, action="approve"), None, None))
        check("the existing choice route still works and now also reports the slowed count", res["slowed"] == 0 and res["slot"]["index"] == 1, res)
    finally:
        main._review_context, main.on_drive, main.record_tool_call = saved

# ---- the review page ---------------------------------------------------------------------------------------------------------------------------
html = (Path(__file__).resolve().parents[2] / "backend" / "app" / "static" / "edit_review.html").read_text()
check("the page posts to the speed route and asks for slowed previews", "/edit-review/speed" in html and "&speed=${c.speed || 1}" in html and "async function setSpeed" in html)
check("the page caches slowed and normal previews of the same window separately", "${c.speed || 1}`;" in html)
check("the page only offers the button where the backend says it can, and shows the reason otherwise", "slot.can_slow" in html and "slot.slow_note" in html)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
