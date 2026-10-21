"""Tests for the taste ranker (backend/learning/taste.py): the features, the leave-one-project-out machinery on synthetic data with a KNOWN taste (it must find it) and with
none (it must not claim to), the adoption gate, and the training data read from Learn From My Edit logs and review logs.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python taste_test.py"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from learning import taste  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


# ---- features -------------------------------------------------------------------------------------------------------------------------------
f = taste.feature_vector({"t": 1.0, "kind": "hero", "punch": 9}, 0, 20.0, True)
check("the features describe a moment: punch, kind, where in the clip, rank", f["punch"] == 0.9 and f["punch_ge8"] == 1 and f["kind_hero"] == 1 and f["kind_action"] == 0 and f["rank0"] == 1 and f["people"] == 1, f)
check("a moment in the first fifth of the clip is 'early', a middle one is not", f["early"] == 1 and taste.feature_vector({"t": 10.0, "kind": "action", "punch": 5}, 2, 20.0, False)["early"] == 0)
check("position is clamped to the clip and t_abs capped at 4 s", taste.feature_vector({"t": 99.0, "kind": "action", "punch": 5}, 1, 20.0, False)["pos"] == 1.0 and taste.feature_vector({"t": 15.0, "kind": "action", "punch": 5}, 1, 20.0, False)["t_abs"] == 4.0)
check("every feature a model arm asks for exists", all(n in f for names in taste.FEATURE_SETS.values() for n in names))

# ---- picking the top k ------------------------------------------------------------------------------------------------------------------------
g = {"L": 1.0, "cands": [{"start": 5.0, "hit": False}, {"start": 5.2, "hit": True}, {"start": 9.0, "hit": False}, {"start": 12.0, "hit": True}]}
check("top-3 skips a candidate less than half a window from one already taken", taste._topk_hits([0, 1, 2, 3], g, 3) == [False, False, True], taste._topk_hits([0, 1, 2, 3], g, 3))
check("top-1 is just the first", taste._topk_hits([1, 0, 2, 3], g, 1) == [True])


# ---- the machinery on data with a known taste --------------------------------------------------------------------------------------------------
def synthetic(rule, projects=6, per_project=8, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for p in range(projects):
        for _ in range(per_project):
            kinds = list(rng.permutation(["hero", "action", "reveal", "reaction", "camera_move"]))
            cands = []
            for rank in range(5):
                e = {"t": 2.0 + 4.0 * rank, "kind": kinds[rank], "punch": 9 - rank}
                cands.append({"t": e["t"], "kind": e["kind"], "punch": float(e["punch"]), "rank": rank, "start": e["t"] - 0.3, "hit": False,
                              "feats": taste.feature_vector(e, rank, 20.0, False)})
            target = rule(cands, rng)
            cands[target]["hit"] = True
            out.append({"project": f"p{p}", "path": "x", "src_in": 0.0, "L": 0.6, "dur": 20.0, "cands": cands})
    return out


known = synthetic(lambda cands, rng: next(i for i, c in enumerate(cands) if c["kind"] == "reaction"))
res = taste.evaluate_arms(known)
claude, learned = res["claude's order only (punch rank)"], res["kind + punch"]
check("Claude's order finds a taste that has nothing to do with punch only by chance (about 1 in 5)", claude["top1"] < 0.4, claude["top1"])
check("when he always picks the same kind, the model finds it on projects it never saw", learned["top1"] > 0.9 and learned["top3"] > 0.97, (learned["top1"], learned["top3"]))
gate = taste.adoption_gate(res)
check("and the adoption gate opens", gate["met"] and gate["net_top1"] >= taste.GATE_MIN_NET_SHOTS and gate["net_top3"] >= 0, gate)
none = synthetic(lambda cands, rng: int(rng.integers(0, 5)), seed=11)
res_none = taste.evaluate_arms(none)
gate_none = taste.adoption_gate(res_none)
check("when his choice is random the gate stays closed (the model does not claim a taste that isn't there)", not gate_none["met"], gate_none)
check("the gate needs BOTH top 1 and top 3", not taste.adoption_gate({"claude's order only (punch rank)": {"h1": [False] * 20, "h3": [False] * 20}, "a": {"h1": [True] * 12 + [False] * 8, "h3": [False] * 20}})["met"])
check("and it counts net shots, not rates", taste.adoption_gate({"claude's order only (punch rank)": {"h1": [True] * 12 + [False] * 8, "h3": [True] * 20}, "a": {"h1": [False] * 12 + [True] * 8, "h3": [True] * 20}})["arms"]["a"]["net_top1"] == -4)
check("a shot with no usable candidate counts as a miss, not as missing", len(taste.evaluate_arms(known + [{"project": "p0", "path": "x", "src_in": 0, "L": 0.6, "dur": 20.0, "cands": []}])["kind + punch"]["h1"]) == len(known) + 1)

# ---- weights are only written when the gate is met ---------------------------------------------------------------------------------------------
model = taste.fit_final(known)
check("the full model lists its features and their weights, and notes how much it was trained on", len(model["weights"]) == len(model["features"]) == len(model["mean"]) == len(model["std"]) and model["trained_on_shots"] == len(known) and model["trained_on_projects"] == 6)
rank_of = {n: w for n, w in zip(model["features"], model["weights"])}
check("on known data the weight on the kind he always picks is the biggest", max(rank_of, key=lambda n: rank_of[n]) == "kind_reaction", rank_of)

# ---- training data from Learn From My Edit logs ---------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    shots = [{"order": 1, "name": "A.MP4", "source_in": 5.7, "source_out": 6.3, "clip_seconds": 20.0, "people": True,
              "candidates": [{"rank": 1, "t": 6.0, "kind": "action", "punch": 9}, {"rank": 2, "t": 14.0, "kind": "reveal", "punch": 6}]},
             {"order": 2, "name": "B.MP4", "source_in": 3.0, "source_out": 3.5, "clip_seconds": 10.0, "people": False, "candidates": []},            # clip never described
             {"order": 3, "name": "C.MP4", "source_in": 1.0, "source_out": 1.5}]                                                                       # an older log without candidates
    (d / "job1_a.json").write_text(json.dumps({"shoot": "GWM", "his_shots": shots}))
    (d / "job1_b.json").write_text(json.dumps({"shoot": "GWM", "his_shots": shots[:1]}))                                                          # the same edit clicked again later
    (d / "index.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"job_id": 1, "sequence": "Edit 1", "file": "job1_a.json"}, {"job_id": 1, "sequence": "Edit  1", "file": "job1_b.json"})) + "\n")
    groups = taste.groups_from_feedback(d)
    check("only shots whose clip was described become training groups, and an edit clicked twice counts once", len(groups) == 1 and groups[0]["project"] == "GWM", len(groups))
    c = groups[0]["cands"]
    check("the moment he cut on is the hit, the other is not, and ranks run from 0", [x["hit"] for x in c] == [True, False] and [x["rank"] for x in c] == [0, 1] and c[0]["feats"]["people"] == 1.0, [(x["rank"], x["hit"]) for x in c])
    check("no log, no groups", taste.groups_from_feedback(Path(tmp) / "nope") == [])

# ---- review log ---------------------------------------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    log = Path(tmp) / "review_log.jsonl"
    rows = [{"action": "approve", "slot": {"index": 1}},
            {"action": "swap", "slot": {"index": 2}, "chosen": {"origin": "same_clip", "kind": "action"}, "passed_over": [{"kind": "hero", "origin": "current"}, {"kind": "reveal", "origin": "other_clip"}]},
            {"action": "swap", "slot": {"index": 2}, "chosen": {"origin": "same_clip", "kind": "reaction"}, "passed_over": [{"kind": "action", "origin": "current"}]},   # changed his mind: the last one counts
            {"action": "swap", "slot": {"index": 3}, "chosen": {"origin": "other_clip", "kind": "reveal"}, "passed_over": [{"kind": "hero", "origin": "current"}]}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    s = taste.review_summary(log)
    check("the review summary counts approvals and swaps, and takes the last choice for each slot", (s["decisions"], s["approved_as_planned"], s["swapped"], s["slots_swapped"]) == (4, 1, 3, 2), s)
    check("it says whether he stayed in the same clip and what kinds he chose against what he passed over", s["chosen_from_same_clip"] == 1 and s["chosen_kinds"]["reaction"] == 1 and s["chosen_kinds"]["reveal"] == 1 and s["passed_over_kinds"]["action"] == 1 and s["passed_over_kinds"]["hero"] == 1, s)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
