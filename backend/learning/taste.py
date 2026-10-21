"""Learn Josh's taste for WHICH of Claude's described moments to cut on, from the edits he has already finished.

The planner cuts a clip on one of the moments Describe clips found in it (up to five, each with a time, a kind, a 0-10 punch score) and today takes them in Claude's
own order, strongest punch first. This asks: given a clip's candidate moments, can his past choices predict which one he used better than Claude's order does?

Data: every labelled shot of the evaluation sample (a raw clip, the part of it Josh used) with the first-pass description of its clip. A candidate is one described moment, turned
into the window the planner would cut around it; it is a HIT when that window covers at least half of his shot (the same yardstick as every other test). A conditional-logit ranker
learns weights over the candidate's features (punch, kind, where in the clip it sits, ...) and is tested LEAVE-ONE-PROJECT-OUT: always on a project it never saw. Compared with
Claude's order and with simpler models, so a feature earns its place only if it helps on held-out projects.

Read-only on everything; writes only data/learning/ and, with `--save`, the small weights file the planner reads.
Run from backend/:  .venv/bin/python -m learning.taste            (evaluate)
                    .venv/bin/python -m learning.taste --save     (also write app/post_taste_model.json)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from learning import evaluate, footage, rank_local, vision_eval

KINDS = ("action", "camera_move", "reveal", "hero", "reaction")
MODEL_PATH = Path(__file__).resolve().parents[1] / "app" / "post_taste_model.json"
FEEDBACK_DIR = Path(__file__).resolve().parents[1] / "data" / "learning" / "feedback"
# Decided BEFORE looking at results: a learned ordering goes into the planner only if, on projects it never saw, it beats Claude's own order on BOTH top 1 and top 3 by at
# least this many shots more than it loses (a gap smaller than that is what chance alone produces at this sample size).
GATE_MIN_NET_SHOTS = 10
FIRST_PASS_MODEL = "claude-sonnet-5-5"
FIRST_PASS_VARIANT = "moments"
COMPOSE_MIN_START = 0.3

FEATURE_SETS: dict[str, list[str]] = {
    "claude's order only (punch rank)": ["punch", "rank0", "rank_le1"],
    "where in the clip only": ["pos", "pos_sq", "early", "t_abs"],
    "kind + punch": ["punch", "punch_ge8", "rank0", "rank_le1", *[f"kind_{k}" for k in KINDS]],
    "all of them": ["punch", "punch_ge8", "rank0", "rank_le1", *[f"kind_{k}" for k in KINDS], "pos", "pos_sq", "early", "t_abs", "people"],
}


def feature_vector(event: dict[str, Any], rank: int, dur: float, people: bool) -> dict[str, float]:
    """Everything the planner knows about a candidate moment BEFORE it has looked at the pixels around it (so the same features exist at plan time)."""
    t = float(event["t"])
    pos = min(max(t / max(dur, 1e-6), 0.0), 1.0)
    punch = float(event.get("punch", 0.0))
    feats = {"punch": punch / 10.0, "punch_ge8": float(punch >= 8), "rank0": float(rank == 0), "rank_le1": float(rank <= 1),
             "pos": pos, "pos_sq": pos * pos, "early": float(pos < 0.2), "t_abs": min(t, 4.0), "people": float(bool(people))}
    for k in KINDS:
        feats[f"kind_{k}"] = float(event.get("kind") == k)
    return feats


def build_groups(inventory_name: str = "inventory_before_zero_fix.json") -> list[dict[str, Any]]:
    """One group per labelled shot that has a first-pass description: its usable candidate moments (best punch first) with their windows, hit flags and features."""
    from app import post_moments, post_steady
    vision_eval.MODEL = FIRST_PASS_MODEL
    inv = json.loads((footage.DEFAULT_DATA / inventory_name).read_text())
    measures = {s.path: evaluate.load_measure(s.path) for s in evaluate.sample_shots(inv) if os.path.exists(s.path)}
    groups = []
    for s in evaluate.sample_shots(inv):
        m = measures.get(s.path)
        f = vision_eval._reply_file(s.path, s.src_in, s.length, FIRST_PASS_VARIANT)
        if not m or not f.exists():
            continue
        dur = min(s.src_duration, m["seconds"]); L = min(s.length, dur - 0.05)
        if L <= 0 or s.src_in + L > dur + 0.05:
            continue
        parsed = post_moments.parse_moments_reply(json.loads(f.read_text())["raw"], dur)
        if not parsed:
            continue
        lo, hi = min(COMPOSE_MIN_START, max(dur - L, 0.0)), max(dur - L - 0.04, 0.0)
        cands = []
        for rank, e in enumerate(parsed["events"]):   # parse_moments_reply sorts best punch first
            start = min(max(float(e["t"]) - L / 2.0, lo), hi)
            rec = post_steady.score_window(m, start, L)
            if rec["cuts"] or rec["dark"]:
                continue   # the planner would skip it
            cands.append({"t": float(e["t"]), "kind": e.get("kind"), "punch": float(e.get("punch", 0)), "rank": rank, "start": start,
                          "hit": evaluate.overlap(start, s.src_in, L) >= evaluate.HIT_OVERLAP, "feats": feature_vector(e, rank, dur, parsed.get("people", False))})
        groups.append({"project": s.project, "path": s.path, "src_in": s.src_in, "L": L, "dur": dur, "cands": cands})
    post_steady.clear_series_cache()
    return groups


def design(group: dict[str, Any], names: list[str]) -> np.ndarray:
    return np.array([[c["feats"][n] for n in names] for c in group["cands"]], dtype=float)


def _topk_hits(order: list[int], group: dict[str, Any], k: int) -> list[bool]:
    """Hit flags of the first k candidates in `order`, skipping a candidate whose window is less than half a window from one already taken."""
    chosen: list[int] = []
    for i in order:
        c = group["cands"][i]
        if all(abs(c["start"] - group["cands"][j]["start"]) >= group["L"] * 0.5 for j in chosen):
            chosen.append(i)
        if len(chosen) == k:
            break
    return [group["cands"][i]["hit"] for i in chosen]


def evaluate_arms(groups: list[dict[str, Any]], l2: float = 1.0) -> dict[str, dict[str, Any]]:
    """Top-1 / top-3 hit rate of every arm over ALL shots (a shot with no usable candidate counts as a miss), each learned arm tested leave-one-project-out."""
    projects = sorted({g["project"] for g in groups})
    results: dict[str, dict[str, Any]] = {}
    for arm, names in FEATURE_SETS.items():
        h1, h3 = [], []
        if arm.startswith("claude"):
            for g in groups:
                flags = _topk_hits(list(range(len(g["cands"]))), g, 3)
                h1.append(bool(flags and flags[0])); h3.append(any(flags))
        else:
            for p in projects:
                train = [(design(g, names), np.array([c["hit"] for c in g["cands"]], dtype=float)) for g in groups if g["project"] != p and g["cands"] and any(c["hit"] for c in g["cands"])]
                model = rank_local.fit(train, l2=l2) if len(train) >= 5 else None
                for g in (g for g in groups if g["project"] == p):
                    if not g["cands"]:
                        h1.append(False); h3.append(False); continue
                    order = list(np.argsort(-rank_local.predict(model, design(g, names)), kind="stable")) if model is not None else list(range(len(g["cands"])))
                    flags = _topk_hits(order, g, 3)
                    h1.append(bool(flags and flags[0])); h3.append(any(flags))
        results[arm] = {"top1": float(np.mean(h1)), "top3": float(np.mean(h3)), "top3_ci": evaluate.bootstrap([float(x) for x in h3]), "top1_ci": evaluate.bootstrap([float(x) for x in h1]), "h1": h1, "h3": h3}
    return results


def adoption_gate(results: dict[str, dict[str, Any]], baseline: str = "claude's order only (punch rank)") -> dict[str, Any]:
    """Whether any learned arm clears the bar for going into the planner: {"met": bool, "best_arm": name, "net_top1": n, "net_top3": n, "arms": {...}}."""
    base = results[baseline]
    arms = {}
    for name, r in results.items():
        if name == baseline:
            continue
        net1 = sum(1 for a, b in zip(base["h1"], r["h1"]) if b and not a) - sum(1 for a, b in zip(base["h1"], r["h1"]) if a and not b)
        net3 = sum(1 for a, b in zip(base["h3"], r["h3"]) if b and not a) - sum(1 for a, b in zip(base["h3"], r["h3"]) if a and not b)
        arms[name] = {"net_top1": net1, "net_top3": net3, "met": net1 >= GATE_MIN_NET_SHOTS and net3 >= GATE_MIN_NET_SHOTS}
    winners = [n for n, a in arms.items() if a["met"]]
    best = max(arms, key=lambda n: min(arms[n]["net_top1"], arms[n]["net_top3"]))
    return {"met": bool(winners), "best_arm": winners[0] if winners else best, "net_top1": arms[best]["net_top1"], "net_top3": arms[best]["net_top3"], "arms": arms}


def groups_from_feedback(feedback_dir: Path = FEEDBACK_DIR) -> list[dict[str, Any]]:
    """Training groups from the Learn From My Edit logs: one per shot of the finished edit whose clip was described. The log keeps the clip's whole candidate set, so
    nothing else has to be looked up. The latest click of each edit (job + sequence) is used, so an edit clicked twice counts once."""
    index = feedback_dir / "index.jsonl"
    if not index.exists():
        return []
    latest: dict[tuple, dict[str, Any]] = {}
    for line in index.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        latest[(row["job_id"], "".join(row["sequence"].split()).lower())] = row
    groups = []
    for row in latest.values():
        try:
            record = json.loads((feedback_dir / row["file"]).read_text())
        except (OSError, ValueError):
            continue
        for shot in record.get("his_shots", []):
            cands, dur = shot.get("candidates"), shot.get("clip_seconds")
            if not cands or not dur:
                continue
            L = max(evaluate.MIN_WINDOW, float(shot["source_out"]) - float(shot["source_in"]))
            L = min(L, dur - 0.05)
            if L <= 0:
                continue
            lo, hi = min(COMPOSE_MIN_START, max(dur - L, 0.0)), max(dur - L - 0.04, 0.0)
            out = []
            for c in cands:
                e = {"t": c["t"], "kind": c.get("kind"), "punch": c.get("punch") or 0.0}
                start = min(max(float(c["t"]) - L / 2.0, lo), hi)
                out.append({"t": float(c["t"]), "kind": c.get("kind"), "punch": float(e["punch"]), "rank": c["rank"] - 1, "start": start,
                            "hit": evaluate.overlap(start, float(shot["source_in"]), L) >= evaluate.HIT_OVERLAP, "feats": feature_vector(e, c["rank"] - 1, dur, shot.get("people", False))})
            groups.append({"project": record.get("shoot") or f"job {row['job_id']}", "path": shot["name"], "src_in": float(shot["source_in"]), "L": L, "dur": float(dur), "cands": out})
    return groups


def review_summary(log_path: Path) -> dict[str, Any]:
    """What a plan's review log says about taste (read from review_log.jsonl: one line per decision). Swaps are disagreements with the plan's pick by definition, so
    'what he swapped TO' is biased against whatever the planner prefers (it picks high-punch moments, so his swaps look low-punch); the share he APPROVED is the fairer
    first-try number."""
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    last: dict[Any, dict] = {}
    for r in rows:
        if r.get("action") == "swap" and r.get("passed_over"):
            last[r["slot"]["index"]] = r
    chosen = [r["chosen"] for r in last.values()]
    passed = [p for r in last.values() for p in r["passed_over"]]
    kinds = lambda items: {k: sum(1 for i in items if i.get("kind") == k) for k in KINDS}
    return {"decisions": len(rows), "approved_as_planned": sum(1 for r in rows if r.get("action") != "swap"), "swapped": sum(1 for r in rows if r.get("action") == "swap"),
            "slots_swapped": len(last), "chosen_from_same_clip": sum(1 for c in chosen if c.get("origin") == "same_clip"), "chosen_kinds": kinds(chosen), "passed_over_kinds": kinds(passed)}


def fit_final(groups: list[dict[str, Any]], arm: str = "all of them", l2: float = 1.0) -> dict[str, Any]:
    names = FEATURE_SETS[arm]
    train = [(design(g, names), np.array([c["hit"] for c in g["cands"]], dtype=float)) for g in groups if g["cands"] and any(c["hit"] for c in g["cands"])]
    model = rank_local.fit(train, l2=l2)
    d = len(names)
    return {"features": names, "weights": [float(x) for x in model[:d]], "mean": [float(x) for x in model[d:2 * d]], "std": [float(x) for x in model[2 * d:]],
            "l2": l2, "trained_on_shots": len(train), "trained_on_projects": len({g["project"] for g in groups if g["cands"] and any(c["hit"] for c in g["cands"])}),
            "arm": arm, "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "first_pass_model": FIRST_PASS_MODEL}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default="inventory_before_zero_fix.json")
    parser.add_argument("--feedback", action="store_true", help="also train and test on the edits logged by Learn From My Edit (backend/data/learning/feedback)")
    parser.add_argument("--save", action="store_true", help=f"write the weights of the full model to {MODEL_PATH.name} -- only if the adoption gate is met")
    parser.add_argument("--l2", type=float, default=1.0)
    parser.add_argument("--review", metavar="review_log.jsonl", help="just summarise a job's review log (what he approved, what he swapped to) and stop")
    args = parser.parse_args()
    if args.review:
        summary = review_summary(Path(args.review))
        print(json.dumps(summary, indent=1))
        return 0
    groups = build_groups(args.inventory)
    if args.feedback:
        extra = groups_from_feedback()
        print(f"added {len(extra)} shots from {len({g['project'] for g in extra})} logged edit(s)")
        groups += extra
    with_cands = [g for g in groups if g["cands"]]
    trainable = [g for g in groups if any(c["hit"] for c in g["cands"])]
    print(f"{len(groups)} shots with a description, {len(with_cands)} with a usable candidate, {len(trainable)} where one of Claude's moments is his ({len({g['project'] for g in groups})} projects)\n")
    res = evaluate_arms(groups, args.l2)
    base = res["claude's order only (punch rank)"]
    for arm, r in res.items():
        gain1 = sum(1 for a, b in zip(base["h1"], r["h1"]) if b and not a); lose1 = sum(1 for a, b in zip(base["h1"], r["h1"]) if a and not b)
        gain3 = sum(1 for a, b in zip(base["h3"], r["h3"]) if b and not a); lose3 = sum(1 for a, b in zip(base["h3"], r["h3"]) if a and not b)
        print(f"  {arm:36s} top 1 {r['top1']:5.1%} ({r['top1_ci'][0]:.0%}-{r['top1_ci'][1]:.0%})   top 3 {r['top3']:5.1%} ({r['top3_ci'][0]:.0%}-{r['top3_ci'][1]:.0%})"
              + ("" if arm is next(iter(res)) else f"   vs Claude's order: top 1 +{gain1}/-{lose1}, top 3 +{gain3}/-{lose3}"))
    gate = adoption_gate(res)
    print(f"\nAdoption gate (a learned arm must beat Claude's order by at least {GATE_MIN_NET_SHOTS} net shots on BOTH top 1 and top 3, on projects it never saw): "
          + ("MET by " + gate["best_arm"] if gate["met"] else f"NOT met -- the best arm ('{gate['best_arm']}') is {gate['net_top1']:+d} net shots on top 1 and {gate['net_top3']:+d} on top 3. The planner stays as it is."))
    model = fit_final(groups, l2=args.l2)
    print("\nweights of the full model (positive = he picks it more; features are standardised):")
    for n, w in sorted(zip(model["features"], model["weights"]), key=lambda x: -abs(x[1])):
        print(f"  {n:14s} {w:+.2f}")
    if args.save:
        if not gate["met"]:
            print("\nNOT saved: the adoption gate is not met, so nothing changes in the planner.")
            return 1
        MODEL_PATH.write_text(json.dumps(model, indent=1))
        print(f"\nsaved {MODEL_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
