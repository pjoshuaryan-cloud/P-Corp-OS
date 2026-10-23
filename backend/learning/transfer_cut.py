"""Learns from an edit Josh cut by hand in one orientation and plans the OTHER orientation of the same shoot from different footage -- a test of how much of his
cut the system can learn and re-make without him (2026-10-22, HAUS WINE - CAMPAIGN: he cut the horizontal; the vertical was shot earlier the same day, other clips).

Steps (run from backend/):
  .venv/bin/python -m learning.transfer_cut prepare   read every clip of both pools: length, frame rate, orientation, recording time, steadiness (local, free),
                                                      and describe them with Claude (Describe clips' own prompt and model; hard cap of one call per clip)
  .venv/bin/python -m learning.transfer_cut study     what his cut shows (pace, order, which clips and which part of each), and a held-out test of whether that
                                                      can be predicted at all, BEFORE anything is applied
  .venv/bin/python -m learning.transfer_cut look      (costs: about $0.50, capped at LOOK_MAX_USD) Claude compares a frame of each of his shots with up to 6
                                                      vertical candidates and ranks them (visual_matches.json; re-runs reuse unchanged rankings)
  .venv/bin/python -m learning.transfer_cut plan      the vertical plan: his rhythm and music, each slot re-picked from the vertical clips (by picture where
                                                      `look` ranked it, else by description), with his finishing copied slot for slot (learning/transfer_finish.py)

Everything is written to a local workspace in backend/data/learning/projects/<project id>/ (git-ignored), laid out like a job folder so the app's own caches
(steadiness.json, moments.json, api_usage.jsonl) are reused unchanged. Read-only on his project and footage.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from learning import prproj

DATA = Path(__file__).resolve().parents[1] / "data" / "learning" / "projects"
HAUS = "/Volumes/Lexar - A/ALPHA MODE MEDIA '26/october/projects/HAUS WINE  - CAMPAIGN.prproj"
POOLS = {"horizontal": "horizontal", "vertical": "vertical"}   # pool name -> the stringout sequence holding every clip of that orientation
CUT = "horizontal - CUT LOCK"
FFPROBE = "/opt/homebrew/bin/ffprobe"


def workspace(project_path: str) -> dict[str, Any]:
    """A job-shaped dict whose edit_dir is the local workspace (so post_steady / post_moments caches live there, not on his drives)."""
    from app.post_learn import project_key
    pid = project_key(project_path)
    root = DATA / str(-pid)
    root.mkdir(parents=True, exist_ok=True)
    return {"id": pid, "shoot_name": Path(project_path).stem, "profile": "joshx", "destination_root": str(root), "premiere_project_path": project_path, "frame_rate": 25}


def _file_id(name: str) -> int:
    digits = re.sub(r"\D", "", name)
    return int(digits) if digits else abs(hash(name)) % 10 ** 6


def probe(path: str) -> dict[str, Any]:
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path], capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout or "{}")
    vs = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    rot = next((sd.get("rotation") for sd in vs.get("side_data_list", []) if "rotation" in sd), None)
    num, _, den = str(vs.get("r_frame_rate", "25/1")).partition("/")
    return {"duration": float(d.get("format", {}).get("duration", 0) or 0), "fps": round(float(num) / float(den or 1), 3), "rotation": rot,
            "created": (d.get("format", {}).get("tags", {}) or {}).get("creation_time"), "size": [vs.get("width"), vs.get("height")]}


def pool_clips(project_path: str) -> dict[str, list[dict[str, Any]]]:
    """{pool: [clip]} from the stringout sequences: every clip of each orientation, in recording order, shaped like the planner's clips."""
    seqs = {s.name.strip(): s for s in prproj.read_sequences(project_path)}
    out: dict[str, list[dict[str, Any]]] = {}
    for pool, seq_name in POOLS.items():
        seen, clips = set(), []
        for s in sorted((x for x in seqs[seq_name].delivered_shots() if x.track == 1), key=lambda x: x.t0):
            name = os.path.basename(s.path or "")
            if name in seen:
                continue
            seen.add(name)
            p = probe(s.path)
            clips.append({"file_id": _file_id(name), "name": name, "path": s.path, "duration": round(p["duration"], 3), "fps": p["fps"], "created": p["created"] or "",
                          "rotation": p["rotation"], "picks": [], "pool": pool})
        out[pool] = sorted(clips, key=lambda c: c["created"])
    return out


async def prepare(project_path: str, describe: bool = True, steady: bool = True) -> dict[str, Any]:
    from dotenv import load_dotenv
    from app import post_moments, post_steady
    from app.post_edit_plan import DESCRIBE_MODEL_FOR_ESTIMATES, edit_dir
    job = workspace(project_path)
    pools = pool_clips(project_path)
    clips = [c for p in pools.values() for c in p]
    folder = edit_dir(job)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clips.json").write_text(json.dumps(pools, indent=1))
    print(f"{len(clips)} clips ({', '.join(f'{k} {len(v)}' for k, v in pools.items())}); workspace {folder}", flush=True)
    counts = None
    if steady:
        counts = await post_steady.analyse_clips(clips, job)
        print(f"steadiness: {counts}", flush=True)
    report = None
    if describe:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        usage: dict[str, int] = {}
        done = [0]

        def on_result(name: str, ok: bool) -> None:
            done[0] += 1
            if done[0] % 10 == 0 or not ok:
                print(f"  described {done[0]} ({name}: {'ok' if ok else 'FAILED'})", flush=True)
        report = await post_moments.probe_missing(client, DESCRIBE_MODEL_FOR_ESTIMATES, clips, folder, max_calls=len(clips), on_result=on_result, usage=usage)
        if usage.get("calls"):
            line = post_moments.record_usage(folder, job_id=job["id"], operation="describe_clips", model=DESCRIBE_MODEL_FOR_ESTIMATES, usage=usage,
                                             extra={"clips_described": report.get("probed"), "project": Path(project_path).name})
            print(f"usage: {usage}; ${line['usd']:.2f} ({line['price_basis']})", flush=True)
        print(f"describe report: { {k: v for k, v in report.items() if k != 'failed'} } failed={report.get('failed')}", flush=True)
    return {"clips": len(clips), "steadiness": counts, "describe": report}


# ================================================================================================ study: what his cut shows, and what can be predicted
GATE_NET_SHOTS = 5            # fixed before any result: a learned placement rule is used only if it gets at least 5 more of his 50 shots right than the default
HIT_SHARE = 0.5               # a window "is his shot" when it covers at least half of it (the yardstick of every other test)
_STOP = set("a an the and or of to in on at with for from by is are was be as it its this that into over under near while their his her they them two one "
            "shot clip frame camera wide close medium view scene still video footage moment".split())


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


FPS_CANDIDATES = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)


def detect_fps(ends: list[float]) -> float:
    """The sequence's frame rate, from where its cuts fall: the candidate whose frame grid they sit on (his HAUS sequences are 23.976 while the footage is 25)."""
    return min(FPS_CANDIDATES, key=lambda f: max((abs(t * f - round(t * f)) for t in ends), default=0.0))


def locked_cut(project_path: str) -> tuple[list[dict[str, Any]], str]:
    """His cut AS HE LOCKED IT: the latest Learn From My Edit record (his click) of the CUT sequence of this project, else the sequence as saved now.
    (2026-10-22: CUT LOCK was edited after his 20:33 click -- a shot shortened, a 1.67 s gap -- so the click, not the live file, is the version he declared done.)"""
    from app.post_learn import FEEDBACK_DIR, project_key
    pid = project_key(project_path)
    records = []
    for f in sorted(FEEDBACK_DIR.glob(f"project{-pid}_*.json")):
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if r.get("sequence") == CUT and r.get("source") == "button":
            records.append(r)
    if records:
        r = records[-1]
        his = [{"order": h["order"], "name": h["name"], "source_in": h["source_in"], "source_out": h["source_out"], "t0": h["timeline_start"], "length": h["timeline_seconds"],
                "speed": h.get("speed")} for h in r["his_shots"]]
        return his, f"your Learn click at {r['ts'][11:16]} on \"{CUT}\""
    seq = next(s for s in prproj.read_sequences(project_path) if s.name.strip() == CUT)
    his = [{"order": k, "name": os.path.basename(x.path or ""), "source_in": x.src_in, "source_out": x.src_out, "t0": x.t0, "length": x.length, "speed": x.speed}
           for k, x in enumerate(sorted((x for x in seq.delivered_shots() if x.track == 1 and x.src_in is not None), key=lambda x: x.t0), start=1)]
    return his, f"\"{CUT}\" as saved now"


def load(project_path: str) -> dict[str, Any]:
    """Both pools with their steadiness (from the workspace cache) and descriptions, and his cut's shots (as he locked it) with frames at his sequence's rate."""
    from app import post_steady
    from app.post_edit_plan import attach_moments, edit_dir
    job = workspace(project_path)
    folder = edit_dir(job)
    pools = json.loads((folder / "clips.json").read_text())
    clips = [c for p in pools.values() for c in p]
    asyncio.run(post_steady.analyse_clips(clips, job, only_cached=True))
    attach_moments(clips, job)
    for c in clips:
        if c.get("steady") and c.get("thumbs") is None:
            c["thumbs"] = post_steady.decode_thumbs(c["steady"])
    his, source = locked_cut(project_path)
    fps = detect_fps([h["t0"] + h["length"] for h in his])
    for h in his:   # from his cut points, not each length rounded on its own, so the cuts stay on his frames (and on the beat) all the way through
        h["frames"] = round((h["t0"] + h["length"]) * fps) - round(h["t0"] * fps)
    return {"job": job, "folder": folder, "pools": pools, "by_name": {c["name"]: c for c in clips}, "his": his, "fps": fps, "cut_source": source}


def moment_at(clip: dict[str, Any], a: float, b: float) -> dict[str, Any] | None:
    """The described moment his window [a, b] sits on: the strongest inside it (give or take 0.25 s), else the nearest within 0.75 s of its centre (as post_learn)."""
    events = [e for e in clip.get("events") or [] if e.get("t") is not None]
    inside = [e for e in events if a - 0.25 <= float(e["t"]) <= b + 0.25]
    if inside:
        return max(inside, key=lambda e: float(e.get("punch", 0)))
    centre = (a + b) / 2.0
    near = [e for e in events if abs(float(e["t"]) - centre) <= 0.75]
    return min(near, key=lambda e: abs(float(e["t"]) - centre)) if near else None


def _hit(start: float, length: float, truth_in: float, truth_len: float) -> bool:
    return max(0.0, min(start + length, truth_in + truth_len) - max(start, truth_in)) >= HIT_SHARE * truth_len


def _random_hit(dur: float, length: float, truth_in: float) -> float:
    """Exact chance that a uniformly random window of `length` in the clip covers half of his shot."""
    span = max(dur - length, 1e-6)
    lo, hi = max(truth_in - HIT_SHARE * length, 0.0), min(truth_in + HIT_SHARE * length, dur - length)
    return max(0.0, min(hi - lo, span)) / span


def _best_moment(clip: dict[str, Any]) -> dict[str, Any] | None:
    events = [e for e in clip.get("events") or [] if e.get("t") is not None]
    return max(events, key=lambda e: float(e.get("punch", 0))) if events else None


def _valid(clip: dict[str, Any], start: float, length: float) -> bool:
    from app import post_steady
    if start < 0 or start + length > clip["duration"] - 0.04:
        return False
    return not clip.get("steady") or not post_steady.score_window(clip["steady"], start, length)["cuts"]


def rule_start(rule: str, params: dict[str, float], clip: dict[str, Any], length: float, taken: list[tuple[float, float]]) -> float:
    """Where a rule puts a window of `length` in `clip`. 'default' = the planner's own choice (Claude's best usable moment, centred; else the steadiest stretch);
    'offset' = centred on the best moment, moved by a learned offset; 'position' = at a learned share of the clip. Falls back to the default when the rule's
    window is unusable (outside the clip, a cut inside, overlapping a stretch already used)."""
    from app import post_steady
    default = post_steady.window_for_slot(clip, length, taken)["start"]
    if rule == "default":
        return default
    if rule == "offset":
        m = _best_moment(clip)
        if m is None:
            return default
        start = float(m["t"]) - length / 2.0 + params["offset"]
    elif rule == "position":
        start = params["share"] * max(clip["duration"] - length, 0.0)
    else:
        raise ValueError(rule)
    start = round(min(max(start, 0.0), max(clip["duration"] - length - 0.04, 0.0)), 3)
    if not _valid(clip, start, length) or any(start < b and start + length > a for a, b in taken):
        return default
    return start


def fit_params(shots: list[dict[str, Any]], by_name: dict[str, dict[str, Any]]) -> dict[str, float]:
    """The learned numbers, from his shots: the median offset of his window from Claude's best moment, and the median share of the clip where he starts."""
    import statistics
    offs, shares = [], []
    for s in shots:
        clip, L = by_name[s["name"]], s["source_out"] - s["source_in"]
        m = _best_moment(clip)
        if m is not None:
            offs.append(s["source_in"] - (float(m["t"]) - L / 2.0))
        if clip["duration"] - L > 0:
            shares.append(s["source_in"] / (clip["duration"] - L))
    return {"offset": statistics.median(offs) if offs else 0.0, "share": min(max(statistics.median(shares), 0.0), 1.0) if shares else 0.5}


def placement_test(his: list[dict[str, Any]], by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Leave-one-shot-out: for each of his shots, does each rule put the window on it? The 'learned' arm picks, on the other shots only, whichever of offset /
    position fits them best, fits its number on them, and is then judged on the held-out shot (nothing about that shot is used to choose or fit)."""
    hits = {"default": [], "offset (fit on all)": [], "position (fit on all)": [], "learned (held out)": []}
    chance = []
    all_params = fit_params(his, by_name)
    for i, s in enumerate(his):
        clip, L = by_name[s["name"]], s["source_out"] - s["source_in"]
        if not clip.get("steady") or L <= 0:
            continue
        others = his[:i] + his[i + 1:]
        hits["default"].append(_hit(rule_start("default", {}, clip, L, []), L, s["source_in"], L))
        hits["offset (fit on all)"].append(_hit(rule_start("offset", all_params, clip, L, []), L, s["source_in"], L))
        hits["position (fit on all)"].append(_hit(rule_start("position", all_params, clip, L, []), L, s["source_in"], L))
        p = fit_params(others, by_name)
        score = {r: sum(_hit(rule_start(r, p, by_name[o["name"]], o["source_out"] - o["source_in"], []), o["source_out"] - o["source_in"], o["source_in"],
                             o["source_out"] - o["source_in"]) for o in others if by_name[o["name"]].get("steady")) for r in ("offset", "position")}
        best = max(score, key=score.get)
        hits["learned (held out)"].append(_hit(rule_start(best, p, clip, L, []), L, s["source_in"], L))
        chance.append(_random_hit(clip["duration"], L, s["source_in"]))
    n = len(hits["default"])
    learned_net = sum(1 for a, b in zip(hits["default"], hits["learned (held out)"]) if b and not a) - sum(1 for a, b in zip(hits["default"], hits["learned (held out)"]) if a and not b)
    return {"shots": n, "random_expected": round(sum(chance), 1), **{k: sum(v) for k, v in hits.items()}, "learned_net_vs_default": learned_net,
            "gate_met": learned_net >= GATE_NET_SHOTS, "params_on_all": {k: round(v, 3) for k, v in all_params.items()}}


def clip_features(clip: dict[str, Any], length: float = 2.0) -> list[float]:
    from app import post_steady
    w = post_steady.window_for_slot(clip, min(length, max(clip["duration"] - 0.3, 0.3)), []) if clip.get("steady") else None
    quality = 1.0 / (1.0 + w["steady"]["score"] / 0.3) if w else 0.0
    events = clip.get("events") or []
    return [quality, max((float(e.get("punch", 0)) for e in events), default=0.0) / 10.0, min(len(events), 5) / 5.0, float(bool(clip.get("people"))),
            min(clip["duration"], 30.0) / 30.0, float((clip.get("steady") or {}).get("static") or 0)]


def _logit_fit(X, y, l2: float = 1.0, steps: int = 2000):
    import numpy as np
    X = np.asarray(X, float); y = np.asarray(y, float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    w = np.zeros(Z.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y)
        w -= 0.5 * g
    return mu, sd, w


def _logit_predict(model, X):
    import numpy as np
    mu, sd, w = model
    Z = np.hstack([np.ones((len(X), 1)), (np.asarray(X, float) - mu) / sd])
    return 1 / (1 + np.exp(-Z @ w))


def _auc(scores: list[float], labels: list[int]) -> float:
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return float("nan")
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


def selection_test(pool: list[dict[str, Any]], used: set[str]) -> dict[str, Any]:
    """Leave-one-clip-out: can the clips he used be told from the ones he left out, from what is known about a clip before cutting? AUC 0.5 = no."""
    import random
    X = [clip_features(c) for c in pool]
    y = [int(c["name"] in used) for c in pool]
    scores = []
    for i in range(len(pool)):
        model = _logit_fit(X[:i] + X[i + 1:], y[:i] + y[i + 1:])
        scores.append(float(_logit_predict(model, [X[i]])[0]))
    auc = _auc(scores, y)
    rng = random.Random(7)
    boots = []
    for _ in range(1000):
        idx = [rng.randrange(len(pool)) for _ in pool]
        a = _auc([scores[j] for j in idx], [y[j] for j in idx])
        if a == a:
            boots.append(a)
    boots.sort()
    lo, hi = boots[int(0.05 * len(boots))], boots[int(0.95 * len(boots)) - 1]
    return {"clips": len(pool), "used": sum(y), "auc": round(auc, 3), "auc_90ci": [round(lo, 3), round(hi, 3)], "useful": lo > 0.5}


def study(project_path: str) -> dict[str, Any]:
    import statistics
    d = load(project_path)
    his, by_name = d["his"], d["by_name"]
    pool = d["pools"]["horizontal"]
    pool_names = [c["name"] for c in pool]
    used = {s["name"] for s in his}
    positions = [pool_names.index(s["name"]) for s in his]
    inversions = sum(1 for i in range(len(positions)) for j in range(i + 1, len(positions)) if positions[i] > positions[j])
    kinds, at_moment, described = [], 0, 0
    for s in his:
        c = by_name[s["name"]]
        if c.get("events"):
            described += 1
            m = moment_at(c, s["source_in"], s["source_out"])
            at_moment += m is not None
            kinds.append(m["kind"] if m else "none")
    L = [s["length"] for s in his]
    q = len(L) // 4
    out = {
        "cut_source": d["cut_source"],
        "shots": len(his), "seconds": round(sum(L), 2), "median_shot": round(statistics.median(L), 3),
        "quarter_means": [round(statistics.mean(L[i * q:(i + 1) * q] if i < 3 else L[3 * q:]), 3) for i in range(4)],
        "clips_used": len(used), "pool": len(pool), "repeats": len(his) - len(used), "out_of_recording_order_pairs": inversions,
        "described_clips_in_cut": described, "on_a_described_moment": at_moment, "kinds": {k: kinds.count(k) for k in sorted(set(kinds))},
        "unused": sorted(set(pool_names) - used),
        "placement": placement_test(his, by_name),
        "selection": selection_test(pool, used),
    }
    (d["folder"] / "study.json").write_text(json.dumps(out, indent=1))
    return out


# ================================================================================================ plan: the vertical, re-made from his cut
REPEAT_PENALTY = 0.6          # using the same clip for two slots in a row, where he did not
SKIP_PENALTY = 0.04           # per vertical clip passed over between two slots (he used 78% of his pool)
POSITION_WEIGHT = 0.6         # keep the vertical cut spread over the vertical shoot the way his cut covered the horizontal one


def shot_profile(s: dict[str, Any], clip: dict[str, Any]) -> dict[str, Any]:
    m = moment_at(clip, s["source_in"], s["source_out"])
    text = " ".join([clip.get("scene") or "", (m or {}).get("what") or ""])
    return {"tokens": tokens(text), "kind": (m or {}).get("kind"), "people": bool(clip.get("people")), "what": (m or {}).get("what"), "scene": clip.get("scene")}


def clip_profile(clip: dict[str, Any]) -> dict[str, Any]:
    text = " ".join([clip.get("scene") or ""] + [e.get("what") or "" for e in clip.get("events") or []])
    return {"tokens": tokens(text), "kinds": {e.get("kind") for e in clip.get("events") or []}, "people": bool(clip.get("people"))}


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    jac = len(a["tokens"] & b["tokens"]) / max(len(a["tokens"] | b["tokens"]), 1)
    return jac + (0.3 if a["kind"] and a["kind"] in b["kinds"] else 0.0) + (0.2 if a["people"] == b["people"] else 0.0)


AIM_MARGIN = 0.1              # a moment must share clearly more of his shot's words than the one the placement rule lands on before the window moves to it


def moment_words(profile: dict[str, Any], event: dict[str, Any] | None) -> float:
    """Word overlap (Jaccard) between what was in his shot (or its scene) and one described moment."""
    if not event or not event.get("what"):
        return 0.0
    mine, theirs = tokens(profile.get("what") or profile.get("scene") or ""), tokens(event["what"])
    return len(mine & theirs) / max(len(mine | theirs), 1)


def moment_score(profile: dict[str, Any], event: dict[str, Any] | None) -> float:
    """How like his shot one described moment is: word overlap + 0.3 for the same kind of moment."""
    return moment_words(profile, event) + (0.3 if event and profile.get("kind") and event.get("kind") == profile["kind"] else 0.0)


def aim_at_match(profile: dict[str, Any], clip: dict[str, Any], length: float, start: float, taken: list[tuple[float, float]]) -> tuple[float, dict[str, Any] | None]:
    """(start, the moment aimed at): the clip was chosen for being like his shot, so the window goes on ITS moment most like his shot -- centred on it -- when that
    shares clearly more of his shot's words than the moment the placement rule landed on (the same KIND alone -- 'action', 'reaction' -- is too coarse to move
    for; it only ranks moments that do share words) and the window is usable there; otherwise the rule's start stands (None)."""
    floor = moment_words(profile, moment_at(clip, start, start + length)) + AIM_MARGIN
    events = [e for e in clip.get("events") or [] if e.get("t") is not None and e.get("what") and moment_words(profile, e) >= floor]
    best = max(events, key=lambda e: moment_score(profile, e), default=None)
    if best is None:
        return start, None
    aimed = round(min(max(float(best["t"]) - length / 2.0, 0.0), max(clip["duration"] - length - 0.04, 0.0)), 3)
    if not _valid(clip, aimed, length) or any(aimed < b and aimed + length > a for a, b in taken):
        return start, None
    return aimed, best


def align(his_profiles: list[dict[str, Any]], repeats: list[bool], lengths: list[float], vertical: list[dict[str, Any]], extra: list[float]) -> list[int]:
    """The best in-order assignment of his slots to vertical clips (dynamic programming): never backwards in recording order (he never went backwards), a clip
    may fill two slots in a row (cheaply where he did that), clips can be passed over (at a small cost each), each clip long enough for its slot; score = how alike
    the vertical clip is to what he put in that slot + `extra` (clip quality, learned selection) - distance from his relative place in the shoot."""
    import math
    N, M = len(his_profiles), len(vertical)
    profiles = [clip_profile(c) for c in vertical]
    fits = [[vertical[j]["duration"] >= lengths[i] + 0.2 and bool(vertical[j].get("steady")) for j in range(M)] for i in range(N)]
    gain = [[similarity(his_profiles[i], profiles[j]) + extra[j] - POSITION_WEIGHT * abs(i / max(N - 1, 1) - j / max(M - 1, 1)) if fits[i][j] else -math.inf
             for j in range(M)] for i in range(N)]
    best = [[-math.inf] * M for _ in range(N)]
    back = [[-1] * M for _ in range(N)]
    for j in range(M):
        best[0][j] = gain[0][j] - SKIP_PENALTY * j
    for i in range(1, N):
        run_best, run_arg = -math.inf, -1   # best over j' < j of best[i-1][j'] - SKIP_PENALTY * (j - j' - 1)
        for j in range(M):
            stay = best[i - 1][j] - (0.0 if repeats[i] else REPEAT_PENALTY)   # the same clip again
            move = run_best - SKIP_PENALTY * 0   # run_best already carries the skip cost up to j-1
            if stay >= move:
                best[i][j], back[i][j] = stay + gain[i][j], j
            else:
                best[i][j], back[i][j] = move + gain[i][j], run_arg
            cand = best[i - 1][j]
            run_best -= SKIP_PENALTY
            if cand > run_best:
                run_best, run_arg = cand, j
    j = max(range(M), key=lambda k: best[N - 1][k] - SKIP_PENALTY * (M - 1 - k))
    path = [j]
    for i in range(N - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    return path[::-1]


# ================================================================================================ his music, re-used as he set it
NOT_A_MUSIC_BED = ("sfx", "camera_audio")


def pick_music_bed(audio: list[dict[str, Any]], cut_seconds: float) -> dict[str, Any] | None:
    """His song under the cut: of the audio items that aren't sound effects or camera sound, the one covering most of [0, cut_seconds] (ambience beds such as
    crowd chatter cover a few seconds); None when nothing covers at least half the cut."""
    def cover(a: dict[str, Any]) -> float:
        return max(0.0, min(a["end"], cut_seconds) - max(a["start"], 0.0))
    best = max((a for a in audio if a.get("kind") not in NOT_A_MUSIC_BED), key=cover, default=None)
    return best if best is not None and cover(best) >= 0.5 * cut_seconds else None


def his_music(project_path: str, cut_seconds: float) -> dict[str, Any] | None:
    """The song under his cut as he set it, read from the saved project: the file, where in the song it starts, where on his timeline, its level."""
    from app import post_reference
    bed = pick_music_bed(post_reference.extract_reference_edit(project_path, CUT)["audio"], cut_seconds)
    if bed is None:
        return None
    paths = sorted(p for p in prproj.project_media_paths(project_path) if os.path.basename(p) == bed["name"])
    return {"name": bed["name"], "path": paths[0] if paths else None, "timeline_start": bed["start"], "timeline_end": bed["end"],
            "in_seconds": bed["source_in"], "level_db": bed.get("level_db")}


def music_for_plan(project_path: str, folder: Path, frames: int, fps: float) -> tuple[dict[str, Any], str]:
    """(plan["music"], a note): his song cut to the plan's length from where his starts, at his level, ending hard like his -- or {} and why not."""
    from app import post_music
    seconds = frames / fps
    mine = his_music(project_path, seconds)
    if mine is None:
        return {}, "No music: your cut has none."
    if not mine["path"] or not os.path.exists(mine["path"]):
        return {}, f"Music NOT placed: couldn't find the file of \"{mine['name']}\" ({mine['path'] or 'not recorded in the project'}). Drag it in at the start."
    if abs(mine["timeline_start"]) > 1.0 / fps:
        return {}, f"Music NOT placed: your song starts {mine['timeline_start']:.2f} s into your cut, and the build can only place music from the start."
    level = mine["level_db"] or 0.0
    cut_path = folder / f"{Path(mine['path']).stem}_from{mine['in_seconds']:.3f}s_{frames}f{f'_{level:+.1f}dB' if level else ''}.wav"
    asyncio.run(post_music.render_music_cut(mine["path"], str(cut_path), mine["in_seconds"], seconds, fade_out=0.02, gain_db=level))
    analysis = asyncio.run(post_music.analyze_music(mine["path"]))
    music = {"source": mine["path"], "cut_path": str(cut_path), "in_seconds": mine["in_seconds"], "tempo_bpm": analysis["tempo_bpm"],
             "track_seconds": analysis["duration"], "gain_db": level, "fade_out_seconds": 0.02, "from": f"your music under \"{CUT}\""}
    note = (f"Music: your song \"{mine['name']}\" from {mine['in_seconds']:.2f} s into it ({analysis['tempo_bpm']:.0f} BPM), at your level ({level:+.1f} dB), "
            f"ending hard like yours, so every cut sits where yours does against it.")
    if mine["timeline_end"] < seconds - 1.0 / fps:
        note += f" (Yours stops at {mine['timeline_end']:.2f} s; here it plays on to the end.)"
    return music, note


def _study_of(project_path: str, d: dict[str, Any]) -> dict[str, Any]:
    st = json.loads((d["folder"] / "study.json").read_text()) if (d["folder"] / "study.json").exists() else None
    if st is None or st.get("cut_source") != d["cut_source"]:   # the study must be of THIS version of his cut (the rough cut's study says nothing about the final)
        st = study(project_path)
    return st


def _alignment(d: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
    """His slots matched to vertical clips by description, in order (align): where the picture check looks first, and the fallback for a slot it can't decide."""
    his, by_name, fps = d["his"], d["by_name"], d["fps"]
    vclips = [by_name[c["name"]] for c in d["pools"]["vertical"]]
    profiles = [shot_profile(s, by_name[s["name"]]) for s in his]
    repeats = [False] + [his[i]["name"] == his[i - 1]["name"] for i in range(1, len(his))]
    model = None
    if st["selection"]["useful"]:
        pool = d["pools"]["horizontal"]
        model = _logit_fit([clip_features(by_name[c["name"]]) for c in pool], [int(c["name"] in {s["name"] for s in his}) for c in pool])
    extra = []
    for c in vclips:
        f = clip_features(c)
        extra.append(0.3 * f[0] + (0.5 * (float(_logit_predict(model, [f])[0]) - 0.5) if model is not None else 0.0))
    path = align(profiles, repeats, [s["frames"] / fps for s in his], vclips, extra)
    return {"vclips": vclips, "profiles": profiles, "repeats": repeats, "path": path, "model": model}


# ================================================================================================ look: his shot and vertical candidates, compared BY PICTURE
LOOK_FILE = "visual_matches.json"
LOOK_CANDIDATES = 6            # vertical moments shown next to each of his shots
LOOK_NEIGHBOURS = 6            # clips either side of where the slot falls in the vertical shoot (and of the description match) that may be offered
LOOK_LONG_SIDE = 1024          # pixels on a frame's long side
LOOK_MAX_USD = 1.20            # approved 2026-10-23 ("about $1"): no call is made that could take the run past this
REUSE_GAP = 3                  # a clip doesn't come back within 3 slots of its last use, unless he did the same at that spot (picked by picture, it did:
                               # one clip 3 times in 5 slots, 8 others twice within 2-4 -- the vertical footage has fewer distinct looks than his)
LOOK_MAX_TOKENS = 600          # room for a sentence of reasoning before the JSON (at 300, 8 of 35 answers ran out before it)
DARK_FRAME_LUMA = 0.12         # a candidate frame darker than this (0..1) is not offered
SOFT_FRAME_SHARE = 0.35        # nor one under 35% of the median sharpness of all candidate frames
FFMPEG = "/opt/homebrew/bin/ffmpeg"
LOOK_PROMPT = (
    "A hand-cut horizontal behind-the-scenes edit is being re-made as a vertical edit from SEPARATE vertical footage of the same shoot. The first image is one "
    "shot from the editor's horizontal cut (it lasts {length:.2f} s in the edit). The numbered candidates are moments from the vertical footage. Rank ALL "
    "candidates by how well each would stand in for the editor's shot in the vertical edit: first the same subject or person doing the same thing; then the "
    "same kind of shot (wide or close, what is in the foreground, how the camera moves); then a similar look and energy. Ignore that the candidates are "
    "vertical. Rank a candidate lower if it is blurred, badly framed (the subject cut off) or nearly empty. Reply with ONLY this JSON object, nothing "
    'before or after it: {{"ranking": [every candidate number, best first], "why": "at most 12 words on why the first one"}}')


def grab_frame(path: str, t: float, out: Path) -> bool:
    """One frame of a clip at `t` seconds as a JPEG, LOOK_LONG_SIDE on its long side, the right way up (ffmpeg applies the rotation). Kept for re-runs."""
    if out.exists():
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    side = LOOK_LONG_SIDE
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale='if(gt(iw,ih),{side},-2)':'if(gt(iw,ih),-2,{side})'", "-q:v", "3", str(out)], capture_output=True, timeout=120)
    return r.returncode == 0 and out.exists()


def frame_quality(path: Path) -> tuple[float, float]:
    """(mean luma 0..1, sharpness: the variance of the Laplacian of a 512-pixel grey copy)."""
    import numpy as np
    from PIL import Image
    g = Image.open(path).convert("L")
    g.thumbnail((512, 512))
    a = np.asarray(g, dtype=np.float32) / 255.0
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(a.mean()), float(lap.var())


def look_candidates(i: int, n: int, s: dict[str, Any], profile: dict[str, Any], vclips: list[dict[str, Any]], near: int, fps: float) -> list[dict[str, Any]]:
    """Up to LOOK_CANDIDATES + 3 vertical moments for his slot i of n, one per clip, from the clips around where the slot falls in the vertical shoot and around
    the description match `near`: each clip's moment most like his shot (else its steadiest usable stretch); a cut inside or a dark window is left out."""
    from app import post_steady
    L = s["frames"] / fps
    centre = round(i / max(n - 1, 1) * (len(vclips) - 1))
    lo, hi = max(0, min(centre, near) - LOOK_NEIGHBOURS), min(len(vclips) - 1, max(centre, near) + LOOK_NEIGHBOURS)
    out = []
    for j in range(lo, hi + 1):
        c = vclips[j]
        if c["duration"] < L + 0.2 or not c.get("steady"):
            continue
        events = sorted((e for e in c.get("events") or [] if e.get("t") is not None and e.get("what")),
                        key=lambda e: (moment_score(profile, e), float(e.get("punch", 0))), reverse=True)
        start, moment = None, None
        for e in events:
            at = round(min(max(float(e["t"]) - L / 2.0, 0.0), max(c["duration"] - L - 0.04, 0.0)), 3)
            if _valid(c, at, L):
                start, moment = at, e
                break
        if start is None:
            start = round(post_steady.window_for_slot({**c, "events": []}, L, [])["start"], 3)
            moment = moment_at(c, start, start + L)
        sw = post_steady.score_window(c["steady"], start, L)
        if sw["cuts"] or sw["dark"]:
            continue
        out.append({"j": j, "name": c["name"], "start": start, "length": round(L, 4), "what": (moment or {}).get("what") or c.get("scene") or "",
                    "score": round(moment_score(profile, moment) + 0.5 * similarity(profile, clip_profile(c)), 4)})
    out.sort(key=lambda x: -x["score"])
    keep = out[:LOOK_CANDIDATES + 3]
    mine = next((x for x in out if x["j"] == near), None)
    if mine is not None and mine not in keep:   # the description match is always offered
        keep = keep[:-1] + [mine]
    return keep


def parse_ranking(text: str, k: int) -> tuple[list[int] | None, str | None]:
    """Claude's {"ranking": [...], "why": "..."} -> (every candidate number 1..k exactly once, best first; why), or (None, None) when it isn't readable."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("ranking"), list):
        return None, None
    seen: list[int] = []
    for x in data["ranking"]:
        if isinstance(x, (int, float)) and int(x) == x and 1 <= int(x) <= k and int(x) not in seen:
            seen.append(int(x))
    if not seen:
        return None, None
    return seen + [x for x in range(1, k + 1) if x not in seen], str(data.get("why") or "")[:160]


def _image_block(path: str) -> dict[str, Any]:
    import base64
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(Path(path).read_bytes()).decode()}}


def _look_key(s: dict[str, Any], cands: list[dict[str, Any]]) -> str:
    return json.dumps([s["name"], round(s["source_in"], 3), s["frames"], [[c["name"], c["start"]] for c in cands]])


def look(project_path: str) -> dict[str, Any]:
    """Shows Claude a frame of each of his shots beside up to LOOK_CANDIDATES vertical candidates and keeps its ranking (visual_matches.json). Within
    LOOK_MAX_USD: refuses to start if the estimate is over it, and stops making calls before one could take it past. Re-runs reuse every ranking whose
    shot and candidates haven't changed."""
    import statistics
    from dotenv import load_dotenv
    from app import post_moments
    from app.post_edit_plan import DESCRIBE_MODEL_FOR_ESTIMATES as MODEL
    d = load(project_path)
    st = _study_of(project_path, d)
    al = _alignment(d, st)
    his, fps, folder = d["his"], d["fps"], d["folder"]
    frames_dir = folder / "look_frames"
    old = json.loads((folder / LOOK_FILE).read_text()) if (folder / LOOK_FILE).exists() else {}
    slots: dict[int, dict[str, Any]] = {}
    for i, s in enumerate(his):
        cands = look_candidates(i, len(his), s, al["profiles"][i], al["vclips"], al["path"][i], fps)
        mine = frames_dir / f"his_{Path(s['name']).stem}_{s['source_in']:.3f}_{s['frames']}f.jpg"
        ok = grab_frame(d["by_name"][s["name"]]["path"], (s["source_in"] + s["source_out"]) / 2.0, mine)
        for c in cands:
            c["frame"] = str(frames_dir / f"v_{Path(c['name']).stem}_{c['start']:.3f}_{c['length']:.3f}.jpg")
            c["ok"] = grab_frame(d["by_name"][c["name"]]["path"], c["start"] + c["length"] / 2.0, Path(c["frame"]))
        slots[i] = {"his_frame": str(mine) if ok else None, "candidates": cands}
    quality = {c["frame"]: frame_quality(Path(c["frame"])) for sl in slots.values() for c in sl["candidates"] if c["ok"]}
    median = statistics.median(q[1] for q in quality.values()) if quality else 0.0
    dropped = 0
    for i, sl in slots.items():
        kept = []
        for c in sl["candidates"]:
            if not c.pop("ok"):
                continue
            luma, sharp = quality[c["frame"]]
            c.update({"luma": round(luma, 3), "sharpness": round(sharp / median, 3) if median else None})
            if luma < DARK_FRAME_LUMA or (median and sharp < SOFT_FRAME_SHARE * median):
                dropped += 1
                continue
            kept.append(c)
        sl["candidates"] = kept[:LOOK_CANDIDATES]
        sl["key"] = _look_key(his[i], sl["candidates"])
    cached = {int(k): v for k, v in (old.get("slots") or {}).items()}
    tokens_per_image = (LOOK_LONG_SIDE * round(LOOK_LONG_SIDE * 9 / 16)) / 750.0

    def est_in(sl: dict[str, Any]) -> int:
        return int(tokens_per_image * (1 + len(sl["candidates"])) + 600)
    todo = [i for i, sl in slots.items() if sl["his_frame"] and len(sl["candidates"]) >= 2
            and not (cached.get(i, {}).get("key") == sl["key"] and cached[i].get("ranking"))]
    for i, sl in slots.items():
        if i not in todo and cached.get(i, {}).get("key") == sl["key"]:
            sl["ranking"], sl["why"] = cached[i].get("ranking"), cached[i].get("why")
    estimate = sum(post_moments.usd(MODEL, est_in(slots[i]), LOOK_MAX_TOKENS)[0] for i in todo)
    already = sum(float(json.loads(x).get("usd", 0)) for x in ((folder / post_moments.USAGE_FILE).read_text().splitlines() if (folder / post_moments.USAGE_FILE).exists() else [])
                  if x.strip() and json.loads(x).get("operation") == "match_shots_by_picture")   # the cap is for the whole approval, not each run
    budget = LOOK_MAX_USD - already
    print(f"look: {len(his)} shots, {sum(len(sl['candidates']) for sl in slots.values())} candidate frames ({dropped} dark/soft left out); "
          f"{len(todo)} call(s) to make, estimate ${estimate:.2f} (cap ${LOOK_MAX_USD:.2f}, ${already:.2f} already spent)", flush=True)
    if estimate > budget:
        raise RuntimeError(f"the estimate (${estimate:.2f}) is over what's left of the approved ${LOOK_MAX_USD:.2f} (${budget:.2f}); nothing was spent")
    spent, usage = [0.0], {"in": 0, "out": 0, "calls": 0}
    if todo:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        from anthropic import AsyncAnthropic

        async def one(i: int, client: Any, gate: asyncio.Semaphore) -> None:
            sl, s = slots[i], his[i]
            reserve = post_moments.usd(MODEL, est_in(sl), LOOK_MAX_TOKENS)[0]
            async with gate:
                if spent[0] + reserve > budget:
                    sl["skipped"] = "budget"
                    return
                spent[0] += reserve
                content: list[dict[str, Any]] = [{"type": "text", "text": "The editor's shot (horizontal):"}, _image_block(sl["his_frame"])]
                for k, c in enumerate(sl["candidates"], start=1):
                    content += [{"type": "text", "text": f"Candidate {k}:"}, _image_block(c["frame"])]
                content.append({"type": "text", "text": LOOK_PROMPT.format(length=s["frames"] / fps)})
                try:
                    resp = await client.messages.create(model=MODEL, max_tokens=LOOK_MAX_TOKENS, messages=[{"role": "user", "content": content}])
                except Exception as exc:   # noqa: BLE001 -- one failed call leaves that slot to the description match
                    spent[0] -= reserve
                    sl["error"] = str(exc)[:200]
                    return
                spent[0] += post_moments.usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)[0] - reserve
                usage["in"] += resp.usage.input_tokens
                usage["out"] += resp.usage.output_tokens
                usage["calls"] += 1
                text = "".join(b.text for b in resp.content if b.type == "text")
                sl["ranking"], sl["why"] = parse_ranking(text, len(sl["candidates"]))
                if sl["ranking"] is None:
                    sl["error"] = "unreadable answer: " + text[:200]

        async def ask_all() -> None:   # only the calls are async: load() and music rendering run their own event loops
            client, gate = AsyncAnthropic(), asyncio.Semaphore(4)
            await asyncio.gather(*(one(i, client, gate) for i in todo))
        asyncio.run(ask_all())
    if usage["calls"]:
        line = post_moments.record_usage(folder, job_id=d["job"]["id"], operation="match_shots_by_picture", model=MODEL, usage=usage,
                                          extra={"shots": len(his), "project": Path(project_path).name})
        print(f"look: {usage['calls']} call(s), ${line['usd']:.2f} ({line['price_basis']})", flush=True)
    out = {"cut_source": d["cut_source"], "model": MODEL, "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "slots": {str(i): sl for i, sl in slots.items()}}
    (folder / LOOK_FILE).write_text(json.dumps(out, indent=1))
    ranked = sum(1 for sl in slots.values() if sl.get("ranking"))
    return {"shots": len(his), "ranked": ranked, "calls": usage["calls"], "usd": post_moments.usd(MODEL, usage["in"], usage["out"])[0],
            "skipped": [i + 1 for i, sl in slots.items() if not sl.get("ranking")]}


def vertical_frame_size(vclips: list[dict[str, Any]]) -> tuple[int, int]:
    """The vertical footage's picture size as it plays (rotation applied): the frame his logo and end card are drawn for."""
    p = probe(vclips[0]["path"])
    w, h = p["size"]
    return (h, w) if p["rotation"] is not None and abs(int(p["rotation"])) % 180 == 90 else (w, h)


def _picture_pick(look_data: dict[str, Any] | None, i: int, s: dict[str, Any], by_name: dict[str, Any], recent: list[str], his_recent: list[str],
                  taken: dict[int, list[tuple[float, float]]]) -> tuple[dict[str, Any], float, int, str | None] | None:
    """(clip, start, rank, why) of Claude's best-ranked candidate for slot i that is usable here: not a clip used in the last REUSE_GAP slots (`recent`, newest
    last) unless he used his shot's clip at the same distance (`his_recent`), and not overlapping a stretch already used; None when the slot wasn't ranked (or
    the look is of another version of his cut)."""
    sl = (look_data or {}).get("slots", {}).get(str(i))
    if not sl or not sl.get("ranking") or sl.get("key") != _look_key(s, sl["candidates"]):
        return None
    for rank, k in enumerate(sl["ranking"], start=1):
        cand = sl["candidates"][k - 1]
        clip = by_name.get(cand["name"])
        if clip is None:
            continue
        if cand["name"] in recent:
            gap = len(recent) - max(k for k, n in enumerate(recent) if n == cand["name"])   # 1 = the slot before
            if len(his_recent) < gap or his_recent[-gap] != s["name"]:
                continue
        a = cand["start"]
        if any(a < b2 and a + cand["length"] > a2 for a2, b2 in taken.get(clip["file_id"], [])):
            continue
        return clip, a, rank, sl.get("why") if rank == 1 else None
    return None


def plan_vertical(project_path: str) -> dict[str, Any]:
    from app import post_candidate_moments, post_steady
    from app.post_variants import validate_plan
    from learning import transfer_finish
    d = load(project_path)
    st = _study_of(project_path, d)
    al = _alignment(d, st)
    his, by_name, fps = d["his"], d["by_name"], d["fps"]
    vclips, profiles, repeats, path, model = al["vclips"], al["profiles"], al["repeats"], al["path"], al["model"]
    look_file = d["folder"] / LOOK_FILE
    look_data = json.loads(look_file.read_text()) if look_file.exists() else None
    if look_data and look_data.get("cut_source") != d["cut_source"]:
        look_data = None
    rule = "default"
    params = st["placement"]["params_on_all"]
    if st["placement"]["gate_met"]:
        rule = "offset" if st["placement"]["offset (fit on all)"] >= st["placement"]["position (fit on all)"] else "position"
    shots, frame, taken, aimed, by_picture = [], 0, {}, 0, 0
    for i, (s, j) in enumerate(zip(his, path)):
        L = s["frames"] / fps
        pick = _picture_pick(look_data, i, s, by_name, [x["name"] for x in shots[-REUSE_GAP:]], [x["name"] for x in his[max(0, i - REUSE_GAP):i]], taken)
        aimed_at, rank, why = None, None, None
        if pick is not None:
            clip, start, rank, why = pick
            by_picture += 1
        else:
            clip = vclips[j]
            start = rule_start(rule, params, clip, L, taken.get(clip["file_id"], []))
            if any(start < b and start + L > a for a, b in taken.get(clip["file_id"], [])):   # the default can't avoid it either: take the steadiest free stretch
                start = post_steady.window_for_slot({**clip, "events": []}, L, taken.get(clip["file_id"], []))["start"]
            start, aimed_at = aim_at_match(profiles[i], clip, L, start, taken.get(clip["file_id"], []))
            aimed += aimed_at is not None
        taken.setdefault(clip["file_id"], []).append((start, start + L))
        win = {"start": start, "duration": L, "source": f"matched to your horizontal shot {s['order']} ({s['name']})", "steady": post_steady.score_window(clip["steady"], start, L)}
        rec = post_candidate_moments.describe(clip, win, describe_provenance=clip.get("moments_provenance"), length=L)
        yours = profiles[i]["what"] or profiles[i]["scene"] or "no description"
        shots.append({"index": i + 1, "role": "body", "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"], "start_frame": frame,
                      "duration_frames": s["frames"], "source_in": round(start, 3), "source_out": round(start + L, 3),
                      "moment_source": (f"picked by picture for your horizontal shot {s['order']} ({s['name']}: {yours})" + (f" -- {why}" if why else "")
                                        if pick is not None else f"matched to your horizontal shot {s['order']} ({s['name']}: {yours})"),
                      "cut_hit_percentile": None, "cut_on_hit": False, "candidate": post_candidate_moments.compact(rec),
                      "matched_to": {"order": s["order"], "name": s["name"], "source_in": round(s["source_in"], 3), "kind": profiles[i]["kind"],
                                     "similarity": round(similarity(profiles[i], clip_profile(clip)), 3), "aimed_at": (aimed_at or {}).get("what"),
                                     "picked_by": "picture" if pick is not None else "description", "picture_rank": rank, "picture_why": why}})
        frame += s["frames"]
    music, music_note = music_for_plan(project_path, d["folder"], frame, fps)
    swapped = st.get("out_of_recording_order_pairs", 0)
    plan = {"fps": fps, "duration_frames": frame, "duration_seconds": round(frame / fps, 2), "shots": shots, "mode": "learned_transfer",
            "style": f"learned:{CUT}", "shoot_name": Path(project_path).stem + " (vertical, learned)", "music": music, "fit": None, "format_from_sequence": "vertical",
            "checks": {"shot_count": len(shots)}, "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "learned_from": {"cut": CUT, "cut_source": d["cut_source"], "study": st, "placement_rule": rule, "selection_model_used": model is not None},
            "notes": [f"Your rhythm: the {len(his)} shot lengths of {d['cut_source']} in the same order, on your frames ({frame / fps:.2f} s at {fps:g} fps, your sequence's rate).",
                      music_note,
                      (f"Each slot: {by_picture} of {len(his)} picked by Claude looking at a frame of your shot beside up to {LOOK_CANDIDATES} vertical moments "
                       f"(dark or soft ones left out; the best-ranked one that doesn't bring back a clip within {REUSE_GAP} slots, unless you did, or reuse a stretch)"
                       + (f"; the other {len(his) - by_picture} by description." if by_picture < len(his) else ".") if by_picture else
                       "Each slot: the vertical clip most like what you put there (Claude's description of the scene and moment, people or not), in order.")
                      + f" {len({s['file_id'] for s in shots})} different clips of {len(vclips)}.",
                      ("Order: as you cut it, slot for slot." + (f" Your cut puts {swapped} pair(s) of shots out of recording order; the vertical follows the "
                       "best match for each slot, not recording order." if swapped and by_picture else (f" Your cut puts {swapped} pair(s) of shots out of "
                       "recording order; the vertical keeps recording order (it can't tell why you swapped them)." if swapped else ""))),
                      ("Where in each clip: the moment Claude was shown and ranked." if by_picture == len(his) else
                       "Where in each clip" + (" (slots matched by description)" if by_picture else "") + ": "
                       + (f"the rule learned from your cut ({rule})" if rule != "default" else
                          f"the planner's default (Claude's best usable moment, centred), because no learned rule beat it by {GATE_NET_SHOTS} of your {len(his)} shots "
                          "on held-out shots") + f"; except in {aimed} slot(s), where the clip has a moment clearly more like your shot, and the window is centred on that."
                       + (" Slots picked by picture use the moment Claude was shown." if by_picture else "")),
                      "No camera sound. Nothing here was checked against your taste for the vertical; that is what this test is."]}
    fin = transfer_finish.finish_for_plan(project_path, CUT, plan, d["folder"], vertical_frame_size(vclips), Path(music["source"]).name if music else None)
    plan["accents"] = fin["accents"]
    if fin["zooms"]:
        plan["zooms"] = fin["zooms"]
    if fin["graphics"]:
        plan["graphics"] = fin["graphics"]
    plan["finish_counts"] = fin["counts"]
    plan["notes"] += [f"Your finishing, copied slot for slot: {fin['counts']['sounds']} sound(s), {fin['counts']['flashes']} flash(es), {fin['counts']['zoom_hits']} zoom hit(s), "
                      f"zoom blur on {fin['counts']['shot_zoom_blur']} shot(s), black & white on {fin['counts']['black_and_white_shots']}, {fin['counts']['punch_ins']} punch-in(s), "
                      f"{fin['counts']['images']} image piece(s) (logo, end card)."] + fin["notes"]
    problems = validate_plan(plan, vclips)
    if problems:
        raise RuntimeError("the vertical plan came out invalid: " + " ".join(problems[:3]))
    (d["folder"] / "edit_plan_latest.json").write_text(json.dumps(plan, indent=1))
    (d["folder"] / f"edit_plan_learned_vertical_{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps(plan, indent=1))
    return plan


def load_project_plan(project_path: str) -> dict[str, Any] | None:
    """The latest learned plan of a project that isn't a POST shoot, or None (for the plugin's Build My Edit)."""
    from app.post_edit_plan import edit_dir
    f = edit_dir(workspace(project_path)) / "edit_plan_latest.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=["prepare", "study", "look", "plan"])
    ap.add_argument("--project", default=HAUS)
    ap.add_argument("--no-describe", action="store_true")
    ap.add_argument("--no-steady", action="store_true")
    a = ap.parse_args()
    if a.step == "prepare":
        asyncio.run(prepare(a.project, describe=not a.no_describe, steady=not a.no_steady))
    elif a.step == "study":
        print(json.dumps(study(a.project), indent=1))
    elif a.step == "look":
        print(json.dumps(look(a.project), indent=1))
    else:
        plan = plan_vertical(a.project)
        print(f"vertical plan: {len(plan['shots'])} shots, {plan['duration_seconds']} s, music: {plan['music'].get('cut_path') or 'none'}; notes:")
        for n in plan["notes"]:
            print("  -", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
