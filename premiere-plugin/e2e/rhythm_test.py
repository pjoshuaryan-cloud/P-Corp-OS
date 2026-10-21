"""Tests for the rhythm study (backend/learning/rhythm.py) and the source frame rate the project reader now records (learning/prproj.py).
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python rhythm_test.py"""
import gzip
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from learning import prproj, rhythm  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


def shot(t0, length, speed=1.0, track=1, clip="a.mp4", src_in=1.0, src_duration=30.0):
    return {"t0": t0, "t1": t0 + length, "src_in": src_in, "src_out": src_in + length * speed, "recorded_path": f"/x/{clip}", "src_duration": src_duration, "track": track, "speed": speed}


def edit(lengths, speeds=None, seconds=None, tracks=None, src_duration=30.0, name="Seq"):
    shots, t = [], 0.0
    for i, l in enumerate(lengths):
        shots.append(shot(t, l, (speeds or [1.0] * len(lengths))[i], (tracks or [1] * len(lengths))[i], clip=f"c{i}.mp4", src_duration=src_duration))
        t += l
    return {"sequence": name, "length": seconds if seconds is not None else t, "shots": shots, "variants": []}


# ---- measuring one edit ---------------------------------------------------------------------------------------------------------------------
m = rhythm.measure(edit([0.4, 0.4, 0.4, 0.6, 0.6, 0.8, 1.0, 2.5, 0.45, 0.5]))
check("shots, median shot and cut rate are read off the timeline", m and m["shots"] == 10 and abs(m["median_shot"] - 0.55) < 1e-9 and abs(m["cuts_per_second"] - round(10 / 7.65, 3)) < 1e-3, m and (m["median_shot"], m["cuts_per_second"]))
check("short and long shot shares (a shot of exactly half a second is not under half a second)", m["short_share"] == 0.4 and m["long_share"] == 0.1, (m["short_share"], m["long_share"]))
m = rhythm.measure(edit([0.5] * 10, speeds=[0.5, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0]))
check("slowed and sped-up shares are counted separately", m["slowed_share"] == 0.4 and m["sped_share"] == 0.1 and m["retimed_share"] == 0.5 and m["slowed_median_speed"] == 0.5, (m["slowed_share"], m["sped_share"]))
m = rhythm.measure(edit([0.5] * 10, speeds=[1.04] * 10))
check("speed within 5% of real time is not a retime", m["retimed_share"] == 0.0)
check("fewer than 8 shots has no rhythm", rhythm.measure(edit([0.5] * 7)) is None)
check("a test clip under 5 seconds is not an edit", rhythm.measure(edit([0.3] * 10)) is None)
check("a timeline over ten minutes is a working timeline", rhythm.measure(edit([0.5] * 10, seconds=700)) is None)
check("a list of whole clips is not an edit", rhythm.measure(edit([2.0] * 10, src_duration=2.2)) is None)
m = rhythm.measure(edit([0.5] * 10 + [0.5] * 4, tracks=[1] * 10 + [2] * 4))
check("only video 1 sets the rhythm; shots on other tracks only show as layering", m["shots"] == 10 and abs(m["layered_share"] - round(4 / 14, 3)) < 1e-3, (m["shots"], m["layered_share"]))
m = rhythm.measure(edit([0.4] * 6 + [1.0] * 6))
check("the pace change compares the last third with the first third", m["pace_change"] == 2.5, m["pace_change"])

# ---- loading the inventory ------------------------------------------------------------------------------------------------------------------
def record(project, file, edits, mtime=1.0):
    return {"project": project, "file": file, "mtime": mtime, "edits": edits}


good = edit([0.5, 0.6, 0.7, 0.4, 0.5, 0.6, 0.8, 0.5, 0.6])
other = edit([1.5, 1.2, 1.8, 1.1, 1.4, 1.6, 1.3, 1.5, 1.2])
inv = {"made": "x", "records": [
    record("Mine", "/Volumes/D/Mine.prproj", [good]),
    record("Mine copy", "/Volumes/D/Mine_1.prproj", [good], mtime=2.0),   # same cut in a second copy of the project
    record("Auto-saved", "/Users/j/Documents/Adobe/Premiere Pro/25.0/Adobe Premiere Pro Auto-Save/Auto-saved.prproj", [other]),
    record("Get Started", "/Users/Shared/Adobe/Premiere Pro (Beta)/27.0/Tutorial/Going Home project/Get Started.prproj", [good]),
]}
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "inventory.json"
    path.write_text(json.dumps(inv))
    edits, left = rhythm.load_edits(path)
check("an edit stored in two project copies counts once", sum(1 for e in edits if e["project"].startswith("Mine")) == 1 and left["copy of an edit already counted"] == 1, left)
check("the newest copy of a cut is the one kept", [e["project"] for e in edits if e["project"].startswith("Mine")] == ["Mine copy"])
check("Adobe's tutorial project is left out", all(e["project"] != "Get Started" for e in edits) and left["tutorial or sample project"] == 1, left)
check("his OWN projects under Documents/Adobe/Premiere Pro are NOT mistaken for tutorials (the first version of the filter threw ~120 of them away)", any(e["project"] == "Auto-saved" for e in edits))
check("different cuts with different shots have different fingerprints", rhythm.fingerprint(good) != rhythm.fingerprint(other) and rhythm.fingerprint(good) == rhythm.fingerprint(json.loads(json.dumps(good))))

# ---- grouping -------------------------------------------------------------------------------------------------------------------------------
rng = np.random.default_rng(3)
blob = lambda centre, n: [centre + rng.normal(0, 0.15, 5) for _ in range(n)]
x = np.array(blob(np.array([-2.0] * 5), 30) + blob(np.array([2.0] * 5), 30))
labels, centres, _ = rhythm.kmeans(x, 2)
check("k-means separates two clearly different groups perfectly", len(set(labels[:30])) == 1 and len(set(labels[30:])) == 1 and labels[0] != labels[30])
check("the silhouette is high for clear groups", rhythm.silhouette(x, labels) > 0.7, round(rhythm.silhouette(x, labels), 2))
smear = np.array(blob(np.array([0.0] * 5), 60))
check("a single smear scores much lower than two clear groups", rhythm.silhouette(smear, rhythm.kmeans(smear, 2)[0]) < rhythm.silhouette(x, labels) - 0.2)


def fake_edit(project, median, seconds=20.0):
    return {"project": project, "sequence": "s", "median_shot": median, "seconds": seconds, "cv": 0.5, "short_share": 0.3, "slowed_share": 0.1, "mtime": 1}


two = [fake_edit(f"fast{i}", 0.5 + 0.01 * (i % 3), 15 + i) for i in range(15)] + [fake_edit(f"slow{i}", 8.0 + 0.1 * (i % 3), 130 + i) for i in range(15)]
k, scores = rhythm.choose_k(two)
check("choose_k finds two groups in two clearly different kinds of edit", k == 2, scores)

# ---- the hold-out ---------------------------------------------------------------------------------------------------------------------------
same = [fake_edit(f"p{i}", 0.6, 20.0) for i in range(14)]
rows = rhythm.holdout_pace(same, {"fast": 0.6, "calm": 2.0})
names = [r[0] for r in rows]
check("a preset that is far off ranks last, and the learned constant is exact when every edit is the same", names[-1] == "preset: calm" and dict((r[0], r[1]) for r in rows)["constant (median of your other edits)"] < 1e-9 and abs(dict((r[0], r[1]) for r in rows)["preset: calm"] - math.log(2.0 / 0.6)) < 1e-9, rows)
met, learned, preset = rhythm.pace_gate(rows)
check("the gate is NOT met when a preset is already as good as the learned pace", not met and abs(learned - preset) < 1e-9, (met, learned, preset))
met, _, _ = rhythm.pace_gate(rhythm.holdout_pace(same, {"calm": 2.0}))
check("the gate IS met when every preset is far off and the learned pace is right", met)
met, _, _ = rhythm.pace_gate([("constant (median of your other edits)", 0.25, 0.4), ("preset: x", 0.39, 0.3)])
check("beating the best preset by less than the bar (0.15) is not enough", not met)
met, _, _ = rhythm.pace_gate([("constant (median of your other edits)", 0.25, 0.4), ("preset: x", 0.40, 0.3)])
check("beating it by exactly the bar counts", met)
errs = rhythm.holdout_errors([fake_edit("odd", 3.0)] + [fake_edit(f"p{i}", 0.6) for i in range(12)], {})
odd = [d for p, d in errs["constant (median of your other edits)"] if p == "odd"]
check("a project is never used to predict itself (the odd project is predicted from the 12 others only)", len(odd) == 1 and abs(odd[0] - math.log(3.0 / 0.6)) < 1e-9, odd)
check("with fewer than 10 other edits there is nothing to predict from", rhythm.holdout_errors([fake_edit(f"p{i}", 0.6) for i in range(10)], {})["constant (median of your other edits)"] == [])

# ---- his usual pace, as the planner's default style ---------------------------------------------------------------------------------------------------
q = rhythm.weighted_quantiles([1.0, 2.0, 3.0, 4.0], [1, 1, 1, 1], 4)
check("weighted quantiles of an even sample are the sample's own quartile midpoints", q == [1.0, 2.0, 3.0, 4.0], q)
q = rhythm.weighted_quantiles([1.0, 5.0], [9, 1], 10)
check("a value carrying 90% of the weight fills 90% of the quantiles", q.count(1.0) == 9 and q.count(5.0) == 1, q)


def measured(lengths, name, seconds=None):
    m = rhythm.measure(edit(lengths, seconds=seconds))
    return {"project": name, "sequence": "s", **m} if m else None


small = measured([0.4] * 10 + [3.0], "small")                     # 10 body shots of 0.4 s, then a 3 s closing hold
large = measured([1.2] * 100 + [3.0], "large", seconds=125.0)    # 100 body shots of 1.2 s, but 125 s long
mid = measured([1.2] * 40 + [3.0], "mid")                         # 40 body shots of 1.2 s, 51 s long
pace = rhythm.usual_pace([e for e in (small, large, mid) if e], opener_seconds=1.87, closing_hold_seconds=6.2)
check("an edit over two minutes is not part of the usual pace", pace["from_edits"] == 2 and pace["from_projects"] == 2, (pace["from_edits"], pace["from_projects"]))
check("the closing hold (each edit's last shot) is left out", 3.0 not in pace["body_lengths"] and pace["shots_pooled"] == 50, (pace["shots_pooled"], max(pace["body_lengths"])))
check("every EDIT counts equally, however many shots it has (10 shots of 0.4 s weigh as much as 40 of 1.2 s)", pace["body_lengths"].count(0.4) == 50 and pace["body_lengths"].count(1.2) == 50, (pace["body_lengths"].count(0.4), pace["body_lengths"].count(1.2)))
check("it is stored as 100 quantiles, sorted", len(pace["body_lengths"]) == rhythm.USUAL_POINTS and pace["body_lengths"] == sorted(pace["body_lengths"]))
tiny = rhythm.usual_pace([measured([0.1] * 6 + [0.5] * 6 + [3.0], "tiny")], 1.87, 6.2)
check("the shortest shot is lifted to the floor the planner may cut at", min(tiny["body_lengths"]) == rhythm.USUAL_MIN_SHOT, min(tiny["body_lengths"]))
long_shots = rhythm.usual_pace([measured([0.5] * 8 + [9.0] * 2 + [3.0], "longs")], 1.87, 6.2)
check("a very long shot is capped at the highlight planner's longest", max(long_shots["body_lengths"]) <= rhythm.USUAL_MAX_SHOT, max(long_shots["body_lengths"]))
check("the card timings are carried along so the style needs no reference file at run time", pace["opener_seconds"] == 1.87 and pace["closing_hold_seconds"] == 6.2)
try:
    rhythm.usual_pace([large], 1.87, 6.2)
    check("no short, fast edits is an error, not an empty style", False)
except ValueError as exc:
    check("no short, fast edits is an error, not an empty style", "no short, fast edits" in str(exc))

# ---- the project reader: source frame rate and zero values -----------------------------------------------------------------------------------
TICKS = 254016000000
GUID = prproj.VIDEO_TRACK_GROUP


def project_xml(items):
    """A minimal Premiere project: one sequence, one video track, items = [(start_ticks or None, end_ticks, in_ticks or None, out_ticks, fps)]. A zero start / in point is LEFT OUT, as Premiere does."""
    parts = ['<PremiereData>']
    for i, (start, end, c_in, c_out, fps) in enumerate(items):
        n = 100 * (i + 1)
        parts.append(f'<VideoStream ObjectID="{n}"><FrameRate>{int(TICKS / fps)}</FrameRate></VideoStream>')
        parts.append(f'<Media ObjectUID="m{n}"><VideoStream ObjectRef="{n}"/><ActualMediaFilePath>/v/clip{i}.mp4</ActualMediaFilePath></Media>')
        parts.append(f'<VideoMediaSource ObjectID="{n + 1}"><MediaSource><Media ObjectURef="m{n}"/></MediaSource><OriginalDuration>{30 * TICKS}</OriginalDuration></VideoMediaSource>')
        parts.append(f'<VideoClip ObjectID="{n + 2}"><Clip><Source ObjectRef="{n + 1}"/>' + (f"<InPoint>{c_in}</InPoint>" if c_in else "") + f"<OutPoint>{c_out}</OutPoint></Clip></VideoClip>")
        parts.append(f'<SubClip ObjectID="{n + 3}"><Clip ObjectRef="{n + 2}"/><Name>clip{i}</Name></SubClip>')
        parts.append(f'<VideoClipTrackItem ObjectID="{n + 4}"><ClipTrackItem><SubClip ObjectRef="{n + 3}"/><TrackItem>' + (f"<Start>{start}</Start>" if start else "") + f"<End>{end}</End></TrackItem></ClipTrackItem></VideoClipTrackItem>")
    parts.append('<VideoClipTrack ObjectUID="t1"><ClipTrack><ClipItems><TrackItems>')
    parts += [f'<TrackItem Index="{i}" ObjectRef="{100 * (i + 1) + 4}"/>' for i in range(len(items))]
    parts.append('</TrackItems></ClipItems></ClipTrack></VideoClipTrack>')
    parts.append('<VideoTrackGroup ObjectID="900"><Tracks><Track Index="0" ObjectURef="t1"/></Tracks></VideoTrackGroup>')
    parts.append(f'<Sequence ObjectUID="s1"><Name>Test</Name><Node><Properties><MZ.OutPoint>{3 * TICKS}</MZ.OutPoint></Properties></Node><TrackGroups><TrackGroup><First>{GUID}</First><Second ObjectRef="900"/></TrackGroup></TrackGroups></Sequence>')
    parts.append('</PremiereData>')
    return "".join(parts).encode()


items = [(None, TICKS * 1, None, TICKS * 1, 50.0),          # starts at timeline 0 AND at clip frame 0: both values left out of the file
         (TICKS * 1, TICKS * 2, TICKS * 4, TICKS * 5, 25.0),
         (TICKS * 2, TICKS * 3, TICKS * 10, TICKS * 11, 29.97)]
with tempfile.TemporaryDirectory() as tmp:
    pr = Path(tmp) / "t.prproj"
    pr.write_bytes(gzip.compress(project_xml(items)))
    seq = prproj.read_sequences(str(pr))
shots = seq[0].shots if seq else []
check("the synthetic project reads as one sequence with three shots", len(seq) == 1 and len(shots) == 3, len(shots))
check("a shot that starts at timeline 0 and at the head of its clip is kept (Premiere leaves zero out of the file)", shots and shots[0].t0 == 0.0 and shots[0].src_in == 0.0 and shots[0].src_out == 1.0)
check("each shot carries the frame rate of its source file", [s.src_fps for s in shots] == [50.0, 25.0, round(TICKS / int(TICKS / 29.97), 3)], [s.src_fps for s in shots])
check("a shot that spans half as much source as timeline time reads as speed 0.5", abs(prproj.Shot(t0=0, t1=2, src_in=0, src_out=1, path="x", name="x", track=1, src_duration=9).speed - 0.5) < 1e-9)
check("a Shot built without a frame rate (the old way) still works", prproj.Shot(t0=0, t1=1, src_in=0, src_out=1, path="x", name="x", track=1, src_duration=9).src_fps is None)

real = Path("/Volumes/Joshx SSD/JD Sports/JD Sports - MOA Store Opening/10_PREMIERE/JD Sports - MOA Store Opening.prproj")
if real.exists():
    seqs = prproj.read_sequences(str(real))
    rates = [s.src_fps for q in seqs for s in q.delivered_shots()]
    check("his real JD Sports project: most shots are 50 fps footage and every shot has a rate", rates and all(r for r in rates) and sum(1 for r in rates if r == 50.0) > 0.9 * len(rates), (len(rates), sum(1 for r in rates if r == 50.0)))
else:
    print("SKIP the real JD Sports project (the drive isn't mounted)")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
