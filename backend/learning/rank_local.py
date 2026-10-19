"""Can the editor's choices be learned from the clip analysis alone? (No pictures, no Claude: frame-to-frame change, sharpness, brightness, cuts.)

A conditional-logit ranker: each window of a clip gets a score w . features; the model is trained so the editor's window beats the other windows of ITS OWN clip.
Evaluated leave-one-project-out, so it is always tested on a style it was not trained on. If this cannot beat random by a clear margin, the signals carry too
little about what the editor wants and a rule built on them -- however clever -- will not help; the choice needs to look at the pictures.
"""
from __future__ import annotations

import numpy as np

from learning import evaluate

FEATURES = ["pos", "pos_sq", "z_score", "z_motion", "z_peak", "z_jerk", "z_blur", "z_luma", "z_exposure", "motion_before", "motion_after", "inside_action", "to_action", "to_cut", "static"]


def window_features(m: dict, starts: np.ndarray, length: float, duration: float) -> np.ndarray:
    """One row per candidate start. Clip-relative (z-scored within the clip) so a shaky clip and a calm clip are judged on their own terms."""
    from app import post_candidates, post_steady
    table = evaluate.window_table(m, starts, length)
    z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
    fps = float(m["fps"]); motion = np.asarray(m["motion"], dtype=float); spikes = np.asarray(m.get("spikes", []), dtype=float) / fps
    events = post_candidates.motion_events(m)
    base = float(np.median(motion)) + 1e-6
    rows = []
    for i, s in enumerate(starts):
        a, b = int(s * fps), int((s + length) * fps)
        before = motion[max(0, a - int(0.5 * fps)): a].mean() / base if a > 0 else 1.0
        after = motion[b: b + int(0.5 * fps)].mean() / base if b < len(motion) else 1.0
        mid = s + length / 2
        inside = float(any(e["onset"] <= mid <= e["settle"] for e in events))
        to_action = min((abs(e["onset"] - s) for e in events), default=duration)
        to_cut = float(np.min(np.abs(spikes - mid))) if len(spikes) else duration
        rows.append([s / max(duration, 1e-9), (s / max(duration, 1e-9)) ** 2, 0, 0, 0, 0, 0, 0, 0, min(before, 5.0), min(after, 5.0), inside, min(to_action, 3.0), min(to_cut, 3.0), 0.0])
    x = np.array(rows, dtype=float)
    for col, key in ((2, "score"), (3, "mean_motion"), (4, "peak_motion"), (5, "jerk"), (6, "blur"), (7, "luma"), (8, "exposure")):
        x[:, col] = z(table[key])
    static = np.array([post_steady.score_window(m, float(s), length)["static"] for s in starts], dtype=float)
    x[:, 14] = static
    return x


def _softmax(scores: np.ndarray) -> np.ndarray:
    e = np.exp(scores - scores.max())
    return e / e.sum()


def fit(groups: list[tuple[np.ndarray, np.ndarray]], l2: float = 0.5, steps: int = 400, lr: float = 0.05) -> np.ndarray:
    """groups: [(features of all windows of one clip, 0/1 mask of the windows that hit the editor's shot)]. Maximises the probability of picking a hit window."""
    d = groups[0][0].shape[1]
    w = np.zeros(d); mean = np.mean(np.vstack([g[0] for g in groups]), axis=0); std = np.std(np.vstack([g[0] for g in groups]), axis=0) + 1e-9
    m1, m2 = np.zeros(d), np.zeros(d)
    for t in range(1, steps + 1):
        grad = -l2 * w
        for x, y in groups:
            xs = (x - mean) / std; p = _softmax(xs @ w); hit = y.astype(bool)
            if not hit.any():
                continue
            ph = p[hit].sum()
            grad += (xs[hit] * p[hit][:, None]).sum(axis=0) / ph - (xs * p[:, None]).sum(axis=0)
        grad /= max(len(groups), 1)
        m1 = 0.9 * m1 + 0.1 * grad; m2 = 0.999 * m2 + 0.001 * grad ** 2
        w = w + lr * (m1 / (1 - 0.9 ** t)) / (np.sqrt(m2 / (1 - 0.999 ** t)) + 1e-8)
    return np.concatenate([w, mean, std])


def predict(model: np.ndarray, x: np.ndarray) -> np.ndarray:
    d = x.shape[1]; w, mean, std = model[:d], model[d:2 * d], model[2 * d:]
    return ((x - mean) / std) @ w


def prepare(samples: list[evaluate.Sample], measures: dict[str, dict]) -> list[dict]:
    items = []
    for s in samples:
        m = measures.get(s.path)
        if not m:
            continue
        dur = min(s.src_duration, m["seconds"]); L = min(s.length, dur - 0.05)
        starts = evaluate.starts_for(dur, L)
        if len(starts) < 4 or s.src_in + L > dur + 0.05:
            continue
        hit = np.array([evaluate.overlap(float(x), s.src_in, L) >= evaluate.HIT_OVERLAP for x in starts], dtype=float)
        if not hit.any():
            continue
        items.append({"project": s.project, "starts": starts, "L": L, "x": window_features(m, starts, L, dur), "hit": hit})
    return items


def cross_validate(items: list[dict], l2: float = 0.5) -> dict:
    """Leave-one-project-out. Returns hit@1 / hit@3 of the learned ranker, and of random on the same items."""
    projects = sorted({i["project"] for i in items})
    if len(projects) < 2:   # a single project: split by clip instead
        folds = [[j for j in range(len(items)) if j % 5 == f] for f in range(5)]
    else:
        folds = [[j for j, i in enumerate(items) if i["project"] == p] for p in projects]
    hits1, hits3, rnd1, rnd3, per_project = [], [], [], [], {}
    for fold in folds:
        test = set(fold); train = [(items[j]["x"], items[j]["hit"]) for j in range(len(items)) if j not in test]
        if len(train) < 5:
            continue
        model = fit(train, l2=l2)
        for j in fold:
            it = items[j]; scores = predict(model, it["x"]); picks = evaluate.top_k(scores, it["starts"], it["L"], 3)
            h = lambda p: bool(it["hit"][int(np.argmin(np.abs(it["starts"] - p)))])
            hits1.append(h(picks[0])); hits3.append(any(h(p) for p in picks)); rnd1.append(float(it["hit"].mean()))
            rng = np.random.default_rng(j); r3 = 0
            for _ in range(60):
                rp = evaluate.top_k(rng.random(len(it["starts"])), it["starts"], it["L"], 3); r3 += any(h(p) for p in rp)
            rnd3.append(r3 / 60)
            per_project.setdefault(it["project"], []).append((hits3[-1], rnd3[-1]))
    return {"n": len(hits1), "hit1": float(np.mean(hits1)), "hit3": float(np.mean(hits3)), "random_hit1": float(np.mean(rnd1)), "random_hit3": float(np.mean(rnd3)),
            "hit3_ci": evaluate.bootstrap([float(x) for x in hits3]), "per_project": per_project}
