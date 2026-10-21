"""Tests for the slow-motion study (backend/learning/slowmo.py): which of his shots from 48+ fps footage does he slow down?
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python slowmo_test.py"""
import gzip
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from learning import prproj, slowmo  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


# ---- the scores -----------------------------------------------------------------------------------------------------------------------------
check("AUC is 1 when every slowed shot outscores every normal one", slowmo.auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0)
check("AUC is 0 when the ranking is exactly backwards", slowmo.auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0)
check("AUC counts ties as half", slowmo.auc([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == 0.5)
check("an edit with only one kind of shot has no AUC (and no precision lift)", slowmo.auc([0.1, 0.2], [True, True]) is None and slowmo.precision_lift([0.1, 0.2], [False, False]) is None)
check("precision lift of a perfect ranking is 1 minus the blind rate", abs(slowmo.precision_lift([9, 8, 7, 1, 2, 3, 4, 5], [True, True, True, False, False, False, False, False]) - (1.0 - 3 / 8)) < 1e-9)
check("precision lift of a ranking that picks all the wrong ones is minus the blind rate", abs(slowmo.precision_lift([1, 2, 9, 8, 7, 6], [True, True, False, False, False, False]) - (0.0 - 2 / 6)) < 1e-9)
sc = slowmo.score_edits({"a": ([0.9, 0.1], [True, False]), "b": ([0.1, 0.9], [True, False]), "c": ([0.1, 0.2], [True, True])})
check("each edit counts once, and an edit with one kind of shot is left out", sc["edits"] == 2 and sc["auc"] == 0.5, sc)

# ---- the gate (fixed before the first run) ----------------------------------------------------------------------------------------------------
good = {"auc": 0.65, "lift": 0.10, "edits": 50}
iv = {"auc": (0.55, 0.70), "lift": (0.02, 0.2)}
check("the gate needs AUC 0.62 or more, a 90% range clear of 0.5, and a precision lift of 0.08 or more", slowmo.gate(good, iv))
check("an AUC under 0.62 fails the gate", not slowmo.gate({**good, "auc": 0.61}, iv))
check("an interval that includes 0.5 fails the gate", not slowmo.gate(good, {**iv, "auc": (0.48, 0.70)}))
check("a lift under 0.08 fails the gate", not slowmo.gate({**good, "lift": 0.07}, iv))
check("the numbers were fixed as stated (62, 8 points, 8+ shots an edit)", slowmo.GATE_MIN_AUC == 0.62 and slowmo.GATE_MIN_LIFT == 0.08 and slowmo.MIN_SHOTS_IN_EDIT == 8)

# ---- the model ------------------------------------------------------------------------------------------------------------------------------
rng = np.random.default_rng(4)
x = rng.normal(size=(600, 2))
y = (x[:, 0] * 2.0 + rng.normal(scale=0.5, size=600) > 0).astype(float)
model = slowmo.fit_logistic(x, y)
p = slowmo.predict(model, x)
check("logistic regression finds a real relationship (weight on feature 0, none on feature 1)", model[0][0] > 1.0 and abs(model[0][1]) < 0.3, model[0])
check("and its predictions rank the labels well", slowmo.auc(list(p), [bool(v) for v in y]) > 0.9)


def make_rows(n_projects=12, edits_per=2, shots=14, rule=lambda L, r: 0.4, seed=1):
    """Synthetic shots. `rule(len, rng) -> probability slowed`; each edit also has its own rate shift so edits differ, as his do."""
    r = random.Random(seed)
    rows = []
    for p in range(n_projects):
        for e in range(edits_per):
            edit_shift = r.uniform(-0.15, 0.15)
            t = 0.0
            for i in range(shots):
                length = r.choice([0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.5])
                prob = min(0.95, max(0.05, rule(length, r) + edit_shift))
                rows.append({"project": f"P{p}", "edit": f"P{p}|E{e}", "index": i, "shots_in_edit": shots, "t0": t, "len": length, "speed": 0.5, "slowed": r.random() < prob, "fps": 50.0,
                             "clip": r.uniform(5, 30), "src_in": r.uniform(0, 3), "src_out": 4, "path": f"/x/c{p}{e}{i}.mp4", "edit_seconds": shots * 0.9})
                t += length
    slowmo.add_structure(rows)
    return rows


learnable = make_rows(rule=lambda L, r: 0.1 + 0.8 * min(1.0, L / 2.5))
scores = slowmo.lopo_scores(learnable, slowmo.STRUCTURE_FEATURES)
res = slowmo.score_edits(scores)
iv = slowmo.bootstrap_projects(scores, {e: v[0]["project"] for e, v in slowmo.by_edit(learnable).items()})
check("finds a rule that exists (slower when the slot is long): held-out within-edit AUC well above 0.62 and the gate is met", res["auc"] > 0.7 and slowmo.gate(res, iv), (res, iv))
noise = make_rows(rule=lambda L, r: 0.4, seed=2)
nscores = slowmo.lopo_scores(noise, slowmo.STRUCTURE_FEATURES)
nres = slowmo.score_edits(nscores)
niv = slowmo.bootstrap_projects(nscores, {e: v[0]["project"] for e, v in slowmo.by_edit(noise).items()})
check("refuses a rule that isn't there (labels unrelated to anything): AUC near 0.5 and the gate is not met", abs(nres["auc"] - 0.5) < 0.08 and not slowmo.gate(nres, niv), (nres, niv))
check("a one-number rule with no learning scores the same edits", set(slowmo.single_feature_scores(learnable, "log_len")) == set(scores))
only_len = slowmo.score_edits(slowmo.single_feature_scores(learnable, "log_len"))
check("longest-first is a good rule when long slots really are slowed, and a bad one reversed", only_len["auc"] > 0.7 and slowmo.score_edits(slowmo.single_feature_scores(learnable, "log_len", -1.0))["auc"] < 0.3)

# a project is never used to predict itself: only P0 has a real rule (long slots slowed); every other project is noise. A model that had seen P0 would score high on it; a
# leave-one-project-out model can only see the noise, so it must score near a coin on P0. (The in-sample fit proves the test has the power to tell the two apart.)
only0 = make_rows(n_projects=3, edits_per=6, rule=lambda L, r: 0.4, seed=3)
r0 = random.Random(8)
for r in only0:
    if r["project"] == "P0":
        r["slowed"] = r0.random() < (0.05 + 0.9 * min(1.0, r["len"] / 2.5))
fs = slowmo.lopo_scores(only0, slowmo.STRUCTURE_FEATURES)
p0 = {e: v for e, v in fs.items() if e.startswith("P0|")}
leaky = slowmo.fit_logistic(np.array([[r["f"][f] for f in slowmo.STRUCTURE_FEATURES] for r in only0], float), np.array([r["slowed"] for r in only0], float))
p0_rows = [r for r in only0 if r["project"] == "P0"]
leaky_auc = slowmo.auc(list(slowmo.predict(leaky, np.array([[r["f"][f] for f in slowmo.STRUCTURE_FEATURES] for r in p0_rows], float))), [r["slowed"] for r in p0_rows])
check("leave-one-project-out: the one project with a real rule scores near a coin, because it was never in its own training set", p0 and slowmo.score_edits(p0)["auc"] < 0.65, slowmo.score_edits(p0))
check("...while a model that HAD seen it scores clearly higher on it (so this test could tell the difference)", leaky_auc > slowmo.score_edits(p0)["auc"] + 0.12, (leaky_auc, slowmo.score_edits(p0)["auc"]))
few = make_rows(shots=5, n_projects=6)
check("edits with fewer than 8 high-fps shots are not scored", slowmo.lopo_scores(few, slowmo.STRUCTURE_FEATURES) == {} and slowmo.single_feature_scores(few, "log_len") == {})

# ---- plan-time features -----------------------------------------------------------------------------------------------------------------------
rows = make_rows(n_projects=2, edits_per=1, shots=9)
one = [r for r in rows if r["edit"] == "P0|E0"]
mid = sorted(one, key=lambda r: r["len"])[len(one) // 2]
check("rel_len is zero for the edit's median-length shot and positive for a longer one", abs(mid["f"]["rel_len"]) < 1e-9 and max(r["f"]["rel_len"] for r in one) > 0)
check("position is 0 to 1 and the squared term follows", all(0 <= r["f"]["pos"] <= 1 and abs(r["f"]["pos_sq"] - r["f"]["pos"] ** 2) < 1e-12 for r in rows))
check("every feature the model uses is known before the planner cuts (none comes from the speed itself)", "speed" not in slowmo.STRUCTURE_FEATURES and all(f in rows[0]["f"] for f in slowmo.STRUCTURE_FEATURES))

# ---- between-edit variation and runs ------------------------------------------------------------------------------------------------------------
def edit_rows(edit, labels):
    return [{"project": edit, "edit": edit, "index": i, "slowed": v, "len": 0.5, "t0": i, "edit_seconds": 20, "clip": 10, "src_in": 0} for i, v in enumerate(labels)]


all_or_nothing = edit_rows("a", [True] * 10) + edit_rows("b", [False] * 10) + edit_rows("c", [True] * 10) + edit_rows("d", [False] * 10)
check("when every edit is all slowed or all normal, the whole variation is between edits", slowmo.edit_level(all_or_nothing)["share_of_variance_between_edits"] > 0.95)
mixed = [r for e in "abcd" for r in edit_rows(e, [i % 2 == 0 for i in range(10)])]
check("when every edit has the same mix, none of it is between edits", slowmo.edit_level(mixed)["share_of_variance_between_edits"] < 0.05)
blocks = [r for e in "abcdefgh" for r in edit_rows(e, [True] * 4 + [False] * 6)]
rr = slowmo.runs_within_edits(blocks, shuffles=200)
check("runs: slowed shots in blocks clearly beat the shuffled edits", rr["p_slowed_after_slowed"] > rr["shuffled_p95"] and rr["longest_run"] > rr["shuffled_longest_p95"], rr)
alt = [r for e in "abcdefgh" for r in edit_rows(e, [i % 2 == 0 for i in range(10)])]
rr = slowmo.runs_within_edits(alt, shuffles=200)
check("runs: perfectly alternating shots are LESS clustered than shuffled ones (no run at all)", rr["p_slowed_after_slowed"] < rr["shuffled_mean"] and rr["longest_run"] == 1.0, rr)

# ---- reading real project files: only 48+ fps shots, with the slowed flag ----------------------------------------------------------------------
TICKS = 254016000000
GUID = prproj.VIDEO_TRACK_GROUP


def project_xml(items):
    """items = [(start_s, end_s, in_s, out_s, fps)] on video 1; a zero start / in point is left out of the file, as Premiere does."""
    parts = ["<PremiereData>"]
    for i, (start, end, c_in, c_out, fps) in enumerate(items):
        n = 100 * (i + 1)
        parts.append(f'<VideoStream ObjectID="{n}"><FrameRate>{int(TICKS / fps)}</FrameRate></VideoStream>')
        parts.append(f'<Media ObjectUID="m{n}"><VideoStream ObjectRef="{n}"/><ActualMediaFilePath>/v/clip{i}.mp4</ActualMediaFilePath></Media>')
        parts.append(f'<VideoMediaSource ObjectID="{n + 1}"><MediaSource><Media ObjectURef="m{n}"/></MediaSource><OriginalDuration>{30 * TICKS}</OriginalDuration></VideoMediaSource>')
        parts.append(f'<VideoClip ObjectID="{n + 2}"><Clip><Source ObjectRef="{n + 1}"/>' + (f"<InPoint>{int(c_in * TICKS)}</InPoint>" if c_in else "") + f"<OutPoint>{int(c_out * TICKS)}</OutPoint></Clip></VideoClip>")
        parts.append(f'<SubClip ObjectID="{n + 3}"><Clip ObjectRef="{n + 2}"/><Name>clip{i}</Name></SubClip>')
        parts.append(f'<VideoClipTrackItem ObjectID="{n + 4}"><ClipTrackItem><SubClip ObjectRef="{n + 3}"/><TrackItem>' + (f"<Start>{int(start * TICKS)}</Start>" if start else "") + f"<End>{int(end * TICKS)}</End></TrackItem></ClipTrackItem></VideoClipTrackItem>")
    parts.append('<VideoClipTrack ObjectUID="t1"><ClipTrack><ClipItems><TrackItems>')
    parts += [f'<TrackItem Index="{i}" ObjectRef="{100 * (i + 1) + 4}"/>' for i in range(len(items))]
    parts.append("</TrackItems></ClipItems></ClipTrack></VideoClipTrack>")
    parts.append('<VideoTrackGroup ObjectID="900"><Tracks><Track Index="0" ObjectURef="t1"/></Tracks></VideoTrackGroup>')
    parts.append(f'<Sequence ObjectUID="s1"><Name>Test</Name><Node><Properties><MZ.OutPoint>{6 * TICKS}</MZ.OutPoint></Properties></Node><TrackGroups><TrackGroup><First>{GUID}</First><Second ObjectRef="900"/></TrackGroup></TrackGroups></Sequence>')
    parts.append("</PremiereData>")
    return "".join(parts).encode()


items = [(0, 1.0, 0, 0.5, 50.0),        # 50 fps, half the source for the time: SLOWED to 0.5x
         (1.0, 2.0, 2.0, 3.0, 50.0),    # 50 fps, real time
         (2.0, 3.0, 4.0, 4.5, 59.94),   # 60 fps, slowed
         (3.0, 4.0, 6.0, 7.0, 25.0),    # 25 fps, real time (not a row)
         (4.0, 5.0, 8.0, 8.5, 25.0)]    # 25 fps, slowed (still not a row: only high-fps footage is studied)
with tempfile.TemporaryDirectory() as tmp:
    proj = Path(tmp) / "p.prproj"
    proj.write_bytes(gzip.compress(project_xml(items)))
    inv = Path(tmp) / "inventory.json"
    inv.write_text(json.dumps({"made": "x", "records": [{"project": "P", "file": str(proj), "mtime": 1, "edits": [{"sequence": "Test"}]}]}))
    got = slowmo.shot_rows(inv, kept=[{"project": "P", "sequence": "Test"}])
check("only the shots from 48+ fps footage become rows (the two 25 fps shots are not studied)", len(got) == 3 and all(r["fps"] >= 48 for r in got), [(r["fps"], r["slowed"]) for r in got])
check("a shot with half the source for its time is flagged slowed, a real-time one is not", [r["slowed"] for r in got] == [True, False, True], [r["slowed"] for r in got])
check("the first shot (zero start, zero in point, both left out of the file) is read, not dropped", got and got[0]["t0"] == 0.0 and got[0]["src_in"] == 0.0)
with tempfile.TemporaryDirectory() as tmp:
    proj = Path(tmp) / "p.prproj"
    proj.write_bytes(gzip.compress(project_xml(items)))
    inv = Path(tmp) / "inventory.json"
    inv.write_text(json.dumps({"made": "x", "records": [{"project": "P", "file": str(proj), "mtime": 1, "edits": [{"sequence": "Test"}]}]}))
    none = slowmo.shot_rows(inv, kept=[{"project": "P", "sequence": "Some other edit"}])
check("an edit the rhythm study left out is not studied here either", none == [])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
