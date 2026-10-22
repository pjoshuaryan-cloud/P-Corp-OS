"""WHERE around Claude's moment should a shot start? The planner has two rules that were never compared: the highlight / story planner centres the window on the
described moment (post_steady._event_windows: start = t - L/2), the music-reel planner starts it just before (post_edit_plan._event_window: start = t - 0.12 s).
Josh's shots are about half a second long and a pick only counts when it covers half of his shot, so the placement alone can decide a hit.

This tests placement rules on the 168 labelled shots, with Claude's cached descriptions (no API calls) and the cached clip measurements (no drive needed):
  * the two rules the app uses today,
  * fixed offsets (start = t - a*L - b) over a grid, with (a, b) learned on the OTHER projects for each held-out project (leave-one-project-out),
  * the same, learned separately per kind of moment,
  * action-aware: when the moment sits inside a burst of motion (learning/post_candidates.motion_events), start just before that burst begins.
Candidates are taken in Claude's own order (strongest punch first) exactly as the planner does: a window with a hard cut inside or a black picture is skipped,
top-3 = the first three windows at least half a window apart.

GATE, fixed before the first run: a new rule replaces the planner's current centred rule only if, on held-out projects, it hits at least GATE_NET_SHOTS more
shots than it loses on BOTH the first pick and the top three.

Run from backend/:   .venv/bin/python -m learning.placement
"""
from __future__ import annotations

import itertools
import json
import sys
from typing import Any, Callable

import numpy as np

from learning import evaluate, footage, vision_eval

GATE_NET_SHOTS = 10
FIRST_PASS_MODEL = "claude-sonnet-5-5"
REEL_LEAD_SECONDS = 0.12          # post_edit_plan.EVENT_LEAD_SECONDS today
GRID_A = (0.0, 0.25, 0.5, 0.75, 1.0)
GRID_B = (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3)
ONSET_LEAD = 0.15                 # post_candidates.ONSET_LEAD_SECONDS


def load_shots(inventory_name: str = "inventory_before_zero_fix.json") -> list[dict[str, Any]]:
    """One record per labelled shot that has a cached measurement and a cached first-pass description: {project, src_in, L, dur, m, events (best first)}."""
    from app import post_moments
    vision_eval.MODEL = FIRST_PASS_MODEL
    inv = json.loads((footage.DEFAULT_DATA / inventory_name).read_text())
    out = []
    for s in evaluate.sample_shots(inv):
        m = evaluate.load_measure(s.path)
        f = vision_eval._reply_file(s.path, s.src_in, s.length, "moments")
        if not m or not f.exists():
            continue
        dur = min(s.src_duration, m["seconds"])
        L = min(s.length, dur - 0.05)
        if L <= 0 or s.src_in + L > dur + 0.05:
            continue
        parsed = post_moments.parse_moments_reply(json.loads(f.read_text())["raw"], dur)
        out.append({"project": s.project, "path": s.path, "src_in": s.src_in, "L": L, "dur": dur, "m": m, "events": (parsed or {}).get("events", [])})
    return out


def _bounds(shot: dict[str, Any]) -> tuple[float, float]:
    from app.post_media import COMPOSE_MIN_START
    lo = min(COMPOSE_MIN_START, max(shot["dur"] - shot["L"], 0.0))
    hi = max(shot["dur"] - shot["L"] - 0.04, 0.0)
    return lo, hi


def windows(shot: dict[str, Any], start_for: Callable[[dict[str, Any], dict[str, Any]], float], k: int = 3) -> list[float]:
    """The first k usable window starts in Claude's order (no cut inside, not black, half a window apart), as the planner would offer them."""
    from app import post_steady
    lo, hi = _bounds(shot)
    out: list[float] = []
    for e in shot["events"]:
        start = min(max(start_for(shot, e), lo), hi)
        rec = post_steady.score_window(shot["m"], start, shot["L"])
        if rec["cuts"] or rec["dark"]:
            continue
        if all(abs(start - c) >= shot["L"] * 0.5 for c in out):
            out.append(start)
        if len(out) == k:
            break
    return out


def hits(shot: dict[str, Any], starts: list[float]) -> tuple[bool, bool]:
    flags = [evaluate.overlap(x, shot["src_in"], shot["L"]) >= evaluate.HIT_OVERLAP for x in starts]
    return bool(flags and flags[0]), any(flags)


def centred(shot, e):
    return float(e["t"]) - shot["L"] / 2.0


def reel_lead(shot, e):
    return float(e["t"]) - REEL_LEAD_SECONDS


def offset_rule(a: float, b: float):
    return lambda shot, e: float(e["t"]) - a * shot["L"] - b


def action_aware(fallback):
    """Start just before the burst of motion that contains the moment (its onset); the fallback rule when the moment isn't inside one."""
    from app import post_candidates

    def rule(shot, e):
        t = float(e["t"])
        bursts = shot.setdefault("_bursts", post_candidates.motion_events(shot["m"]))
        inside = [b for b in bursts if b["onset"] - 0.1 <= t <= b["settle"] + 0.1]
        if inside:
            return min(inside, key=lambda b: abs(b["peak"] - t))["onset"] - ONSET_LEAD
        return fallback(shot, e)
    return rule


def score(shots: list[dict[str, Any]], rule) -> tuple[np.ndarray, np.ndarray]:
    r = [hits(s, windows(s, rule)) for s in shots]
    return np.array([x[0] for x in r], float), np.array([x[1] for x in r], float)


def lopo_offsets(shots: list[dict[str, Any]], by_kind: bool = False) -> tuple[np.ndarray, np.ndarray, dict]:
    """For each held-out project: the (a, b) that hit the most top-3 then top-1 shots on the other projects (optionally per kind of moment, judged by the
    kind of the shot's first usable moment), applied to the held-out one."""
    grid = list(itertools.product(GRID_A, GRID_B))
    cache: dict[tuple[float, float], tuple[np.ndarray, np.ndarray]] = {g: score(shots, offset_rule(*g)) for g in grid}
    kinds = [(s["events"][0].get("kind") if s["events"] else None) for s in shots]
    projects = np.array([s["project"] for s in shots])
    h1, h3 = np.zeros(len(shots)), np.zeros(len(shots))
    chosen: dict[str, Any] = {}
    for p in sorted(set(projects)):
        test, train = projects == p, projects != p
        groups = sorted(set(kinds)) if by_kind else [None]
        for kind in groups:
            mask_k = np.array([(k == kind) if by_kind else True for k in kinds])
            tr = train & mask_k
            if by_kind and tr.sum() < 10:   # too few examples of this kind elsewhere: use all kinds
                tr = train
            best = max(grid, key=lambda g: (cache[g][1][tr].sum(), cache[g][0][tr].sum(), -abs(g[0] - 0.5) - abs(g[1])))
            sel = test & mask_k
            h1[sel], h3[sel] = cache[best][0][sel], cache[best][1][sel]
            chosen.setdefault(str(kind), []).append(best)
    return h1, h3, chosen


def per_kind_offsets(train: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """For each kind of moment: the (a, b) whose window hits the most of the TRAINING shots whose first usable moment is that kind (top-3, then top-1); kinds
    with fewer than 10 examples get the offset learned on all of them. Only training shots are looked at."""
    grid = list(itertools.product(GRID_A, GRID_B))
    cache = {g: score(train, offset_rule(*g)) for g in grid}
    kinds = [(s["events"][0].get("kind") if s["events"] else None) for s in train]
    def best(mask):
        return max(grid, key=lambda g: (cache[g][1][mask].sum(), cache[g][0][mask].sum(), -abs(g[0] - 0.5) - abs(g[1])))
    everything = best(np.ones(len(train), bool))
    out = {"*": everything}
    for k in set(kinds):
        mask = np.array([x == k for x in kinds])
        out[str(k)] = best(mask) if mask.sum() >= 10 else everything
    return out


def shifted_rule(offsets: dict[str, tuple[float, float]]):
    def rule(shot, e):
        a, b = offsets.get(str(e.get("kind")), offsets["*"])
        return float(e["t"]) - a * shot["L"] - b
    return rule


def mixed_alternatives(shots: list[dict[str, Any]], recipe: str) -> tuple[np.ndarray, np.ndarray]:
    """Held-out projects: the FIRST pick is always today's (centred on Claude's best usable moment); the other two slots of the three options follow `recipe`:
       'c1 s1 c2' = centred best, that same moment shifted by its kind's learned offset, centred second-best
       'c1 c2 s1' = centred best, centred second-best, the best moment shifted
       'c1 s1 s2' = centred best, then the best two moments shifted."""
    projects = sorted({s["project"] for s in shots})
    h1, h3 = np.zeros(len(shots)), np.zeros(len(shots))
    for p in projects:
        offsets = per_kind_offsets([s for s in shots if s["project"] != p])
        rule = shifted_rule(offsets)
        for i, s in enumerate(shots):
            if s["project"] != p:
                continue
            c = windows(s, centred, 3)
            sh = windows(s, rule, 3)
            pools = {"c1 s1 c2": [c[:1], sh[:1], c[1:2], c[2:], sh[1:]], "c1 c2 s1": [c[:1], c[1:2], sh[:1], c[2:], sh[1:]], "c1 s1 s2": [c[:1], sh[:1], sh[1:2], c[1:], sh[2:]]}[recipe]
            out: list[float] = []
            for part in pools:
                for x in part:
                    if all(abs(x - y) >= s["L"] * 0.5 for y in out):
                        out.append(x)
                    if len(out) == 3:
                        break
                if len(out) == 3:
                    break
            h1[i], h3[i] = hits(s, out)
    return h1, h3


def net(new: np.ndarray, base: np.ndarray) -> int:
    return int(((new == 1) & (base == 0)).sum() - ((new == 0) & (base == 1)).sum())


def gate(new1, new3, base1, base3) -> bool:
    return net(new1, base1) >= GATE_NET_SHOTS and net(new3, base3) >= GATE_NET_SHOTS


def main() -> int:
    shots = load_shots()
    shots = [s for s in shots if s["events"]]
    print(f"{len(shots)} labelled shots with a cached description and measurement, {len({s['project'] for s in shots})} projects (no API calls, no drive needed)")
    base1, base3 = score(shots, centred)
    rows = [("TODAY, highlight/story planner: centred on the moment", base1, base3, None)]
    r1, r3 = score(shots, reel_lead); rows.append((f"TODAY, music-reel planner: start {REEL_LEAD_SECONDS} s before the moment", r1, r3, None))
    a1, a3 = score(shots, action_aware(centred)); rows.append(("action-aware: start just before the burst of motion it sits in", a1, a3, None))
    l1, l3, chosen = lopo_offsets(shots); rows.append(("one offset learned on the other projects", l1, l3, chosen))
    k1, k3, chosen_k = lopo_offsets(shots, by_kind=True); rows.append(("an offset per kind of moment, learned on the other projects", k1, k3, chosen_k))
    print(f"\n{'rule':66s} top-1   top-3   net vs centred (top-1 / top-3)   gate ({GATE_NET_SHOTS}+ on both)")
    for name, h1, h3, _ in rows:
        n1, n3 = net(h1, base1), net(h3, base3)
        print(f"  {name:64s} {h1.mean():5.1%}  {h3.mean():5.1%}   {n1:+3d} / {n3:+3d}" + ("" if name.startswith("TODAY, highlight") else ("   MET" if gate(h1, h3, base1, base3) else "   not met")))
    print(f"\nALTERNATIVES ONLY (the first pick stays today's; gate, fixed before this run: the same three options hit {GATE_NET_SHOTS}+ more net shots than today's three)")
    for recipe in ("c1 s1 c2", "c1 c2 s1", "c1 s1 s2"):
        m1, m3 = mixed_alternatives(shots, recipe)
        n3 = net(m3, base3)
        print(f"  {recipe:64s} {m1.mean():5.1%}  {m3.mean():5.1%}   {net(m1, base1):+3d} / {n3:+3d}   " + ("MET" if n3 >= GATE_NET_SHOTS and net(m1, base1) >= 0 else "not met"))
    print("\noffsets chosen per held-out project (a, b): start = t - a*L - b")
    for k, v in chosen.items():
        print(f"  {k}: " + ", ".join(f"({a:g},{b:g})" for a, b in sorted(set(v), key=lambda x: -v.count(x))[:4]))
    for k, v in chosen_k.items():
        print(f"  kind {k}: most common " + ", ".join(f"({a:g},{b:g})x{v.count((a, b))}" for a, b in sorted(set(v), key=lambda x: -v.count(x))[:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
