"""WHICH of his shots from high-frame-rate footage does Josh slow down? (He slows about 40% of them, nearly always to half speed; the planner never does.)

learning/rhythm.py --slowmo showed that frame rate gates it (41% of 48+ fps shots are slowed, 1.5% of 24-31 fps shots) and that the share varies a lot from edit to edit (6% to
72%). This asks the next question: inside one edit, can anything the planner knows BEFORE it cuts say which shots he would slow? If it can, a planner that slows a chosen share of
its 50 fps shots can pick the right ones; if it cannot, slowing is just a dial and which shots are slowed is arbitrary.

  rows:      every video-1 shot of his measured edits whose source footage is 48 fps or faster (read from the project files, so no footage needs to be on a drive),
  target:    the shot is slowed (source seconds per timeline second under 0.95),
  features:  only what exists at plan time: the slot's length, how long it is next to the edit's other shots, where in the edit it sits, how long the source clip is and where in
             it the shot starts,
  test:      leave-one-PROJECT-out, scored WITHIN each edit (edit-level slowing rates differ, so an edit's own rate must not be what is being predicted):
               within-edit AUC     (0.5 = no better than a coin; 1.0 = every slowed shot ranked above every normal one),
               precision at k      (rank an edit's shots, take as many as he slowed, how many are right, minus what picking blindly would get).
  gate:      fixed BEFORE the first run (below). A rule goes into the planner only if it clears it on projects it never saw.

A second, smaller test adds what the clip itself shows (motion, sharpness, and the kind and punch of the moment Claude described) for the labelled shots that have footage on a drive.
It is exploratory: too few shots to gate on.

Run from backend/:   .venv/bin/python -m learning.slowmo
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

import numpy as np

from learning import rhythm

HIGH_FPS = 48.0
SLOWED_BELOW = 1 - rhythm.RETIME_TOLERANCE
MIN_SHOTS_IN_EDIT = 8            # an edit needs this many high-fps shots to say anything about which of them he slows
# Decided BEFORE looking at results: a slow-motion rule is adopted only if, on projects it never saw, BOTH hold.
GATE_MIN_AUC = 0.62              # mean within-edit AUC, and the lower end of its project-bootstrap interval must be above 0.5
GATE_MIN_LIFT = 0.08             # precision at k beats picking blindly by at least 8 points
BOOTSTRAPS = 400

STRUCTURE_FEATURES = ["log_len", "rel_len", "pos", "pos_sq", "rel_clip", "src_start"]


def shot_rows(inventory: Path = rhythm.INVENTORY, kept: list[dict] | None = None) -> list[dict]:
    """One row per video-1 shot of a measured edit whose source is 48+ fps. Needs the project files themselves (the inventory does not keep frame rates)."""
    from learning import dataset, prproj
    kept = rhythm.load_edits(inventory)[0] if kept is None else kept
    wanted = {(e["project"], e["sequence"]) for e in kept}
    rows: list[dict] = []
    for rec in json.loads(Path(inventory).read_text())["records"]:
        if not rec.get("edits") or not Path(rec["file"]).exists():
            continue
        try:
            sequences = prproj.read_sequences(rec["file"])
        except Exception:   # an unreadable project must not stop the rest
            continue
        for edit in dataset.delivered_edits(sequences):
            key = (rec["project"], edit["sequence"].name)
            if key not in wanted:
                continue
            shots = sorted((s for s in edit["shots"] if s.track == 1 and s.speed and s.src_fps), key=lambda s: s.t0)
            seconds = edit["sequence"].out_mark or (shots[-1].t1 if shots else 0.0)
            n_all = len(shots)
            for i, s in enumerate(shots):
                if s.src_fps < HIGH_FPS or not s.src_duration:
                    continue
                rows.append({"project": rec["project"], "edit": f"{key[0]}|{key[1]}", "index": i, "shots_in_edit": n_all, "t0": s.t0, "len": s.length, "speed": s.speed,
                             "slowed": s.speed < SLOWED_BELOW, "fps": s.src_fps, "clip": s.src_duration, "src_in": s.src_in, "src_out": s.src_out,
                             "path": s.path, "edit_seconds": seconds})
    return rows


def by_edit(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["edit"], []).append(r)
    return {k: sorted(v, key=lambda r: r["index"]) for k, v in out.items()}


def add_structure(rows: list[dict]) -> None:
    """Adds the plan-time features to every row in place. 'rel' ones compare a shot with the rest of ITS edit, so they carry no edit-level information."""
    for edit_rows in by_edit(rows).values():
        med_len = statistics.median(r["len"] for r in edit_rows)
        med_clip = statistics.median(math.log(r["clip"]) for r in edit_rows)
        for r in edit_rows:
            pos = min(1.0, max(0.0, r["t0"] / max(r["edit_seconds"], 1e-6)))
            r["f"] = {"log_len": math.log(max(r["len"], 0.05)), "rel_len": math.log(max(r["len"], 0.05)) - math.log(max(med_len, 0.05)), "pos": pos, "pos_sq": pos * pos,
                      "rel_clip": math.log(max(r["clip"], 0.05)) - med_clip, "src_start": min(1.0, max(0.0, (r["src_in"] or 0.0) / max(r["clip"], 1e-6)))}


# ---------------------------------------------------------------------------------------------------------------------------------------- the model
def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = 1.0, steps: int = 300) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """L2-regularised logistic regression by Newton steps on standardised features. Returns (weights, bias, mean, std)."""
    mean, std = x.mean(axis=0), x.std(axis=0) + 1e-9
    z = (x - mean) / std
    w, b = np.zeros(z.shape[1]), float(np.log((y.mean() + 1e-6) / (1 - y.mean() + 1e-6)))
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-(z @ w + b)))
        grad_w, grad_b = z.T @ (p - y) + l2 * w, float((p - y).sum())
        s = p * (1 - p) + 1e-9
        hess = (z * s[:, None]).T @ z + l2 * np.eye(z.shape[1])
        step = np.linalg.solve(hess, grad_w)
        w_new = w - step
        b -= grad_b / max(s.sum(), 1e-6)
        if np.max(np.abs(w_new - w)) < 1e-7:
            w = w_new
            break
        w = w_new
    return w, b, mean, std


def predict(model: tuple[np.ndarray, float, np.ndarray, np.ndarray], x: np.ndarray) -> np.ndarray:
    w, b, mean, std = model
    return 1.0 / (1.0 + np.exp(-(((x - mean) / std) @ w + b)))


def auc(scores: list[float], labels: list[bool]) -> float | None:
    """P(a slowed shot outscores a normal one); ties count half. None when an edit has only one kind."""
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def precision_lift(scores: list[float], labels: list[bool]) -> float | None:
    """Take as many top-scored shots as he slowed: share that are right, minus the share blind picking gets (= his slowed share)."""
    k, n = sum(labels), len(labels)
    if k == 0 or k == n:
        return None
    top = sorted(range(n), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in top) / k - k / n


def score_edits(edit_scores: dict[str, tuple[list[float], list[bool]]]) -> dict[str, float | None]:
    """Mean within-edit AUC and mean precision lift over the edits that have shots of both kinds (each edit counts once)."""
    aucs = [a for s, l in edit_scores.values() if (a := auc(s, l)) is not None]
    lifts = [v for s, l in edit_scores.values() if (v := precision_lift(s, l)) is not None]
    return {"auc": statistics.mean(aucs) if aucs else None, "lift": statistics.mean(lifts) if lifts else None, "edits": len(aucs)}


def bootstrap_projects(edit_scores: dict[str, tuple[list[float], list[bool]]], project_of: dict[str, str], n: int = BOOTSTRAPS, seed: int = 5) -> dict[str, tuple[float, float]]:
    """90% intervals of the two scores, resampling whole PROJECTS (an edit's cousins in the same project are not independent)."""
    rng = random.Random(seed)
    projects: dict[str, list[str]] = {}
    for e in edit_scores:
        projects.setdefault(project_of[e], []).append(e)
    names = sorted(projects)
    aucs, lifts = [], []
    for _ in range(n):
        picked = [e for p in (rng.choice(names) for _ in names) for e in projects[p]]
        s = score_edits({f"{i}": edit_scores[e] for i, e in enumerate(picked)})
        if s["auc"] is not None:
            aucs.append(s["auc"]); lifts.append(s["lift"])
    q = lambda v, f: sorted(v)[min(len(v) - 1, int(f * len(v)))]
    return {"auc": (q(aucs, 0.05), q(aucs, 0.95)), "lift": (q(lifts, 0.05), q(lifts, 0.95))} if aucs else {}


def lopo_scores(rows: list[dict], features: list[str], l2: float = 1.0) -> dict[str, tuple[list[float], list[bool]]]:
    """Leave-one-project-out predictions, grouped by edit. Only edits with enough high-fps shots are scored."""
    groups = by_edit(rows)
    eligible = {e for e, v in groups.items() if len(v) >= MIN_SHOTS_IN_EDIT}
    out: dict[str, tuple[list[float], list[bool]]] = {}
    for project in sorted({r["project"] for r in rows}):
        test_edits = [e for e in eligible if groups[e][0]["project"] == project]
        if not test_edits:
            continue
        train = [r for r in rows if r["project"] != project and r["edit"] in eligible]
        x = np.array([[r["f"][f] for f in features] for r in train], float)
        y = np.array([r["slowed"] for r in train], float)
        if len(train) < 50 or y.min() == y.max():
            continue
        model = fit_logistic(x, y, l2)
        for e in test_edits:
            xs = np.array([[r["f"][f] for f in features] for r in groups[e]], float)
            out[e] = (list(predict(model, xs)), [r["slowed"] for r in groups[e]])
    return out


def single_feature_scores(rows: list[dict], feature: str, sign: float = 1.0) -> dict[str, tuple[list[float], list[bool]]]:
    """A one-number rule (no learning, nothing to leak): score = sign * the feature. Same edits as lopo_scores."""
    return {e: ([sign * r["f"][feature] for r in v], [r["slowed"] for r in v]) for e, v in by_edit(rows).items() if len(v) >= MIN_SHOTS_IN_EDIT}


def random_scores(rows: list[dict], seed: int = 1) -> dict[str, tuple[list[float], list[bool]]]:
    rng = random.Random(seed)
    return {e: ([rng.random() for _ in v], [r["slowed"] for r in v]) for e, v in by_edit(rows).items() if len(v) >= MIN_SHOTS_IN_EDIT}


def gate(result: dict, interval: dict) -> bool:
    return bool(result["auc"] is not None and result["auc"] >= GATE_MIN_AUC and interval and interval["auc"][0] > 0.5 and result["lift"] >= GATE_MIN_LIFT)


# ---------------------------------------------------------------------------------------------------------------------------- what is known about a shot
def edit_level(rows: list[dict]) -> dict:
    """How much of the variation is BETWEEN edits (his mood for the brief) rather than between shots of one edit, and whether runs of slowed shots cluster."""
    groups = {e: v for e, v in by_edit(rows).items() if len(v) >= MIN_SHOTS_IN_EDIT}
    shares = [sum(r["slowed"] for r in v) / len(v) for v in groups.values()]
    overall = sum(r["slowed"] for v in groups.values() for r in v) / max(1, sum(len(v) for v in groups.values()))
    within = statistics.mean(s * (1 - s) for s in shares) if shares else 0.0
    total = overall * (1 - overall)
    after_slowed = [b["slowed"] for v in groups.values() for a, b in zip(v, v[1:]) if a["slowed"]]
    after_normal = [b["slowed"] for v in groups.values() for a, b in zip(v, v[1:]) if not a["slowed"]]
    return {"edits": len(groups), "overall_share": overall, "share_of_variance_between_edits": (1 - within / total) if total else 0.0,
            "p_slowed_after_slowed": sum(after_slowed) / max(1, len(after_slowed)), "p_slowed_after_normal": sum(after_normal) / max(1, len(after_normal))}


def by_bucket(rows: list[dict], feature: str, edges: list[float]) -> list[tuple[str, int, float]]:
    out = []
    for lo, hi in zip(edges, edges[1:]):
        v = [r for r in rows if lo <= r[feature] < hi]
        if v:
            out.append((f"{lo:g}-{hi:g}", len(v), sum(r["slowed"] for r in v) / len(v)))
    return out


def runs_within_edits(rows: list[dict], shuffles: int = 400, seed: int = 3) -> dict:
    """Do slowed shots come in RUNS beyond what each edit's own rate explains? Each edit's labels are shuffled in place (keeping its rate) and the share of slowed shots that follow a
    slowed shot is recomputed; the real value is compared with that. Also the longest run of slowed shots in an edit, real against shuffled."""
    rng = random.Random(seed)
    groups = [[r["slowed"] for r in v] for v in by_edit(rows).values() if len(v) >= MIN_SHOTS_IN_EDIT]

    def stats(gs: list[list[bool]]) -> tuple[float, float]:
        after = [b for g in gs for a, b in zip(g, g[1:]) if a]
        longest = []
        for g in gs:
            best = cur = 0
            for x in g:
                cur = cur + 1 if x else 0
                best = max(best, cur)
            longest.append(best)
        return sum(after) / max(1, len(after)), statistics.mean(longest)
    real_follow, real_longest = stats(groups)
    follow, longest = [], []
    for _ in range(shuffles):
        shuffled = [rng.sample(g, len(g)) for g in groups]
        f, l = stats(shuffled)
        follow.append(f); longest.append(l)
    return {"edits": len(groups), "p_slowed_after_slowed": real_follow, "shuffled_mean": statistics.mean(follow), "shuffled_p95": sorted(follow)[int(0.95 * shuffles)],
            "longest_run": real_longest, "shuffled_longest_run": statistics.mean(longest), "shuffled_longest_p95": sorted(longest)[int(0.95 * shuffles)]}


def labelled_subset(rows: list[dict]) -> list[dict]:
    """The labelled shots (the evaluation sample, footage on a drive, first-pass description) that are also high-fps rows, with what the CLIP shows in his window: where his window ranks
    among all windows of its own clip for motion / peak motion / blur / brightness (0-1), and the kind and punch of the described moment nearest it."""
    import os
    from app import post_moments, post_steady
    from learning import evaluate, footage, taste, vision_eval
    vision_eval.MODEL = taste.FIRST_PASS_MODEL
    inv = json.loads((footage.DEFAULT_DATA / "inventory_before_zero_fix.json").read_text())
    key = lambda project, path, src_in: (project, os.path.basename(path or "").lower(), round(src_in or 0.0, 1))
    by_key = {key(r["project"], r["path"], r["src_in"]): r for r in rows}
    out = []
    for smp in evaluate.sample_shots(inv):
        row = by_key.get(key(smp.project, smp.path, smp.src_in))
        if row is None or not os.path.exists(smp.path):
            continue
        m = evaluate.load_measure(smp.path)
        if not m:
            continue
        dur = min(smp.src_duration, m["seconds"]); L = min(smp.length, dur - 0.05)
        starts = evaluate.starts_for(dur, L)
        if len(starts) < 4 or L <= 0:
            continue
        table = evaluate.window_table(m, starts, L)
        mine = post_steady.score_window(m, smp.src_in, L)
        pct = lambda col, v: float(np.mean(table[col] <= v))
        rec = {"project": row["project"], "slowed": row["slowed"], "len": row["len"], "motion": pct("mean_motion", mine["mean_motion"]), "peak": pct("peak_motion", mine["peak_motion"]),
               "blur": pct("blur", mine["blur"]), "luma": pct("luma", mine["luma"]), "jerk": pct("jerk", mine["jerk"]), "kind": None, "punch": None, "dist": None}
        f = vision_eval._reply_file(smp.path, smp.src_in, smp.length, taste.FIRST_PASS_VARIANT)
        if f.exists():
            parsed = post_moments.parse_moments_reply(json.loads(f.read_text())["raw"], dur)
            if parsed and parsed["events"]:
                mid = smp.src_in + L / 2
                e = min(parsed["events"], key=lambda e: abs(float(e["t"]) - mid))
                rec.update({"kind": e.get("kind"), "punch": float(e.get("punch", 0)), "dist": abs(float(e["t"]) - mid)})
        out.append(rec)
    post_steady.clear_series_cache()
    return out


def print_subset(sub: list[dict]) -> None:
    n = len(sub)
    print(f"\nEXPLORATORY (too few shots to gate on): {n} labelled 48+ fps shots with footage on a drive from {len({r['project'] for r in sub})} projects; {round(100 * sum(r['slowed'] for r in sub) / max(n, 1))}% slowed")
    for name in ("motion", "peak", "blur", "luma", "jerk", "len"):
        scores = [r[name] for r in sub]
        a = auc(scores, [r["slowed"] for r in sub])
        low = [r for r in sub if r[name] <= sorted(scores)[len(scores) // 3]]
        high = [r for r in sub if r[name] >= sorted(scores)[(2 * len(scores)) // 3]]
        print(f"  {name:7s} pooled AUC {a:.2f}   slowed: lowest third {round(100 * sum(r['slowed'] for r in low) / max(1, len(low)))}%  highest third {round(100 * sum(r['slowed'] for r in high) / max(1, len(high)))}%")
    kinds = {}
    for r in sub:
        if r["kind"]:
            kinds.setdefault(r["kind"], []).append(r["slowed"])
    print("  slowed by the kind of the described moment nearest his window: " + ", ".join(f"{k} {round(100 * sum(v) / len(v))}% (n={len(v)})" for k, v in sorted(kinds.items(), key=lambda kv: -len(kv[1]))))
    pun = [r for r in sub if r["punch"] is not None]
    if pun:
        print(f"  punch of that moment: pooled AUC {auc([r['punch'] for r in pun], [r['slowed'] for r in pun]):.2f}")


def print_report(rows: list[dict]) -> None:
    add_structure(rows)
    eligible = [e for e, v in by_edit(rows).items() if len(v) >= MIN_SHOTS_IN_EDIT]
    print(f"{len(rows)} shots from 48+ fps footage, {len(by_edit(rows))} edits ({len(eligible)} with at least {MIN_SHOTS_IN_EDIT} such shots), "
          f"{len({r['project'] for r in rows})} projects; {round(100 * sum(r['slowed'] for r in rows) / len(rows))}% slowed")
    lvl = edit_level(rows)
    print(f"\nbetween edits or within them: {round(100 * lvl['share_of_variance_between_edits'])}% of whether a shot is slowed is explained by WHICH EDIT it is in (his rate for the edit); "
          f"after a slowed shot the next is slowed {round(100 * lvl['p_slowed_after_slowed'])}% of the time, after a normal one {round(100 * lvl['p_slowed_after_normal'])}% "
          f"(base {round(100 * lvl['overall_share'])}%)")
    print("\nshare slowed by the slot's length (timeline seconds):")
    for label, n, share in by_bucket(rows, "len", [0, 0.3, 0.45, 0.6, 0.8, 1.2, 2.0, 99]):
        print(f"  {label:9s} {n:5d} shots  {round(100 * share):3d}% slowed")
    print("\nshare slowed by position in the edit:")
    for label, n, share in by_bucket([{**r, "p": r["f"]["pos"]} for r in rows], "p", [0, 0.2, 0.4, 0.6, 0.8, 1.01]):
        print(f"  {label:9s} {n:5d} shots  {round(100 * share):3d}% slowed")
    rr = runs_within_edits(rows)
    print(f"\nRUNS: after a slowed shot the next is slowed {round(100 * rr['p_slowed_after_slowed'])}% of the time; if each edit's slowed shots were scattered at random (same rate) it would be "
          f"{round(100 * rr['shuffled_mean'])}% (95% of shuffles stay under {round(100 * rr['shuffled_p95'])}%). Longest run of slowed shots per edit: {rr['longest_run']:.1f} against {rr['shuffled_longest_run']:.1f} shuffled "
          f"(95% under {rr['shuffled_longest_p95']:.1f})")
    project_of = {e: by_edit(rows)[e][0]["project"] for e in eligible}
    print(f"\nHELD OUT (leave one project out), within each edit; gate: AUC >= {GATE_MIN_AUC} with the low end of its 90% range above 0.5, and precision lift >= {GATE_MIN_LIFT}")
    arms = [("blind picking", random_scores(rows)), ("longest slots first (no learning)", single_feature_scores(rows, "log_len")),
            ("longest next to its own edit's shots (no learning)", single_feature_scores(rows, "rel_len")), ("later in the edit first (no learning)", single_feature_scores(rows, "pos")),
            ("earlier in the edit first (no learning)", single_feature_scores(rows, "pos", -1.0)),
            ("learned from all plan-time facts", lopo_scores(rows, STRUCTURE_FEATURES)), ("learned from slot length only", lopo_scores(rows, ["log_len", "rel_len"]))]
    for name, scores in arms:
        scores = {e: v for e, v in scores.items() if e in project_of}
        res = score_edits(scores)
        iv = bootstrap_projects(scores, project_of)
        if res["auc"] is None:
            print(f"  {name:55s} (nothing to score)"); continue
        print(f"  {name:55s} AUC {res['auc']:.3f} ({iv['auc'][0]:.2f}-{iv['auc'][1]:.2f})  precision lift {res['lift']:+.3f} ({iv['lift'][0]:+.2f} to {iv['lift'][1]:+.2f})  over {res['edits']} edits"
              + ("   GATE MET" if gate(res, iv) else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--inventory", default=str(rhythm.INVENTORY))
    args = ap.parse_args(argv)
    rows = shot_rows(Path(args.inventory))
    if len(rows) < 200:
        print("too few shots from high-frame-rate footage to test")
        return 1
    print_report(rows)
    print_subset(labelled_subset(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
