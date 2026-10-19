"""Score any shot-picking rule against what the editor actually chose.

For every labelled shot: take the raw clip, slide a window the length of the editor's shot across it, and ask the rule to rank those windows.
A rule HITS when its pick covers at least half of the moment the editor used. Reported: top-1 hit rate, top-3 hit rate (the editor's pick is one good
choice among several, so top-3 is the fairer yardstick), how the editor's window ranks among all windows of its own clip, and a bootstrap range.
A rule has to beat RANDOM to mean anything; random is computed exactly from the clip lengths involved.

Rules take the clip's analysis (post_steady.measure) and return one score per candidate start (higher = better). Add a rule by adding it to RULES.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from learning import footage

STEP = 0.125            # seconds between candidate window starts
HIT_OVERLAP = 0.5       # a pick hits when it covers this share of the editor's shot
MIN_WINDOW = 0.25
MEASURE_DIR = footage.DEFAULT_DATA / "measure"


@dataclass
class Sample:
    project: str
    path: str
    src_in: float
    src_out: float
    src_duration: float
    speed: float | None

    @property
    def length(self) -> float:
        return max(MIN_WINDOW, self.src_out - self.src_in)


def sample_shots(inventory: dict, per_project: int = 8, seed: int = 1, max_clip_seconds: float = 90.0, min_project_shots: int = 10) -> list[Sample]:
    """A fixed, seeded sample of labelled shots: up to `per_project` per project, only projects with enough usable shots, only clips short enough to read quickly."""
    rng = random.Random(seed)
    out: list[Sample] = []
    seen: set[tuple[str, float]] = set()
    for record in inventory["records"]:
        pool = []
        for edit in record["edits"]:
            for s in edit["shots"]:
                if not s["real_path"] or not s["src_duration"] or s["src_duration"] > max_clip_seconds or s["src_out"] - s["src_in"] < 0.2:
                    continue
                key = (s["real_path"], round(s["src_in"], 1))
                if key in seen:      # the same moment cut into several versions of an edit counts once
                    continue
                seen.add(key)
                pool.append(Sample(record["project"], s["real_path"], s["src_in"], s["src_out"], s["src_duration"], s["speed"]))
        if len(pool) >= min_project_shots:
            rng.shuffle(pool)
            out += pool[:per_project]
    return out


def cache_file(path: str) -> Path:
    st = os.stat(path)
    return MEASURE_DIR / (hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest() + ".json")


def load_measure(path: str) -> dict | None:
    f = cache_file(path)
    return json.loads(f.read_text()) if f.exists() else None


def starts_for(duration: float, length: float) -> np.ndarray:
    hi = max(duration - length - 0.04, 0.0)
    return np.arange(0.0, hi + 1e-9, STEP)


# ----------------------------------------------------------------------------------------------------------------------------------------------- rules
def window_table(m: dict, starts: np.ndarray, length: float) -> dict[str, np.ndarray]:
    """Per-window facts from the clip analysis, for every start."""
    from app import post_steady
    rows = [post_steady.score_window(m, float(s), length) for s in starts]
    return {k: np.array([r[k] for r in rows], dtype=float) for k in ("score", "mean_motion", "peak_motion", "jerk", "blur", "luma", "exposure")}


def _rule_steadiest(t, starts, dur, L):  return -t["score"]                      # the corporate engine's rule
def _rule_most_motion(t, starts, dur, L): return t["mean_motion"]
def _rule_least_motion(t, starts, dur, L): return -t["mean_motion"]
def _rule_sharpest(t, starts, dur, L):   return -t["blur"]
def _rule_middle(t, starts, dur, L):     return -np.abs(starts + L / 2 - dur / 2)
def _rule_start(t, starts, dur, L):      return -starts


RULES: dict[str, Callable] = {
    "steadiest (the corporate engine's rule)": _rule_steadiest, "most motion": _rule_most_motion, "least motion": _rule_least_motion,
    "sharpest": _rule_sharpest, "middle of the clip": _rule_middle, "start of the clip": _rule_start,
}


# ------------------------------------------------------------------------------------------------------------------------------------------ scoring
def overlap(a: float, b: float, length: float) -> float:
    return max(0.0, min(a, b) + length - max(a, b)) / length


def top_k(scores: np.ndarray, starts: np.ndarray, length: float, k: int) -> list[float]:
    """The k best starts, at least half a window apart (so three picks aren't one moment three times)."""
    chosen: list[float] = []
    for i in np.argsort(-scores, kind="stable"):
        s = float(starts[i])
        if all(abs(s - c) >= length * 0.5 for c in chosen):
            chosen.append(s)
            if len(chosen) == k:
                break
    return chosen


def evaluate_rule(samples: list[Sample], rule: Callable | None, measures: dict[str, dict], seed: int = 1) -> dict:
    """Hit rates for one rule over the samples ('random' when rule is None). Returns per-sample hits so projects can be broken out and bootstrapped."""
    rng = random.Random(seed)
    results = []
    for s in samples:
        m = measures.get(s.path)
        if not m:
            continue
        dur = min(s.src_duration, m["seconds"]); L = min(s.length, dur - 0.05)
        starts = starts_for(dur, L)
        if len(starts) < 4 or s.src_in + L > dur + 0.05:
            continue
        if rule is None:   # random: exact expectation for top-1, simulated for top-3
            p1 = float(np.mean([overlap(float(x), s.src_in, L) >= HIT_OVERLAP for x in starts]))
            hit3 = 0
            for _ in range(60):
                picks = top_k(np.array([rng.random() for _ in starts]), starts, L, 3)
                hit3 += any(overlap(p, s.src_in, L) >= HIT_OVERLAP for p in picks)
            results.append({"project": s.project, "hit1": p1, "hit3": hit3 / 60, "rank": 0.5, "windows": len(starts)})
            continue
        table = window_table(m, starts, L)
        scores = rule(table, starts, dur, L)
        picks = top_k(scores, starts, L, 3)
        truth = int(np.argmin(np.abs(starts - s.src_in)))
        rank = float(np.mean(scores < scores[truth]) + 0.5 * np.mean(scores == scores[truth]))   # 1.0 = the rule's favourite window is the editor's
        results.append({"project": s.project, "hit1": float(overlap(picks[0], s.src_in, L) >= HIT_OVERLAP), "hit3": float(any(overlap(p, s.src_in, L) >= HIT_OVERLAP for p in picks)),
                        "rank": rank, "windows": len(starts)})
    return {"n": len(results), "results": results}


def bootstrap(values: list[float], n: int = 1000, seed: int = 1) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(float(np.mean([rng.choice(values) for _ in values])) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def summarise(evaluation: dict) -> dict:
    rs = evaluation["results"]
    out = {"n": len(rs)}
    for key in ("hit1", "hit3", "rank"):
        vals = [r[key] for r in rs]
        out[key] = float(np.mean(vals)) if vals else 0.0
        out[key + "_ci"] = bootstrap(vals)
    return out


# ------------------------------------------------------------------------------------------------------------------------ candidate generators
def evaluate_candidates(samples: list[Sample], measures: dict[str, dict], k: int = 6, seed: int = 1) -> dict:
    """How often the editor's moment is INSIDE the k candidates app.post_candidates proposes (recall), against k random picks, and each view's own hit rate."""
    from app import post_candidates
    rng = random.Random(seed)
    rows = []
    for s in samples:
        m = measures.get(s.path)
        if not m:
            continue
        dur = min(s.src_duration, m["seconds"]); L = min(s.length, dur - 0.05)
        starts = starts_for(dur, L)
        if len(starts) < 4 or s.src_in + L > dur + 0.05:
            continue
        cands = post_candidates.candidates(m, dur, L, k=k)
        hit_by_view = {c["view"]: overlap(c["start"], s.src_in, L) >= HIT_OVERLAP for c in cands}
        rnd = 0
        for _ in range(60):
            picks = top_k(np.array([rng.random() for _ in starts]), starts, L, len(cands) or k)
            rnd += any(overlap(p, s.src_in, L) >= HIT_OVERLAP for p in picks)
        rows.append({"project": s.project, "n_cands": len(cands), "any": any(hit_by_view.values()), "random": rnd / 60, "views": hit_by_view})
    return {"n": len(rows), "rows": rows}
