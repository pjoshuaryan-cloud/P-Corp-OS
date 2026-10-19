"""Several different candidate moments per clip, with their action phases (2026-10-19).

Why: no single signal predicts which moment an editor picks (measured on Josh's own edits: the stillest window hit his pick less often than random in
one project and more often in another). So instead of one rule choosing one window, a clip is offered as a handful of DISTINCT candidates, each from a
different point of view -- a steady hold, the peak of an action, where an action begins, where it settles, the sharpest stretch, the opening, the middle --
and a later stage (post_rank, Claude looking at the candidates) chooses among them. This module only proposes; it never chooses.

What it reads is the analysis post_steady already makes of every clip (8 frames a second, 160x90 grey): frame-to-frame change, sharpness, brightness and
where hard cuts are. "Action" here means a rise of that change well above the clip's own usual level: it cannot tell a gesture from a camera move, and the
`kind`/`why` text says what was measured, not what is shown. Nothing here knows what the shot is OF.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app import post_steady

STEP = 0.125                 # seconds between candidate starts
ACTION_FACTOR = 1.6          # an action = frame-to-frame change this many times the clip's usual level ...
ACTION_MIN_RISE = 0.01       # ... and at least this far above it (a perfectly still clip has a tiny baseline)
EDGE_FACTOR = 1.25           # onset / settle: change falls back within this factor of the usual level
PEAK_SEPARATION_SECONDS = 0.75
MAX_PHASE_SECONDS = 2.0      # how far back an onset or forward a settle is looked for
ONSET_LEAD_SECONDS = 0.15    # a shot starts just before the action does, so the action begins inside it
OPENING_SECONDS = 0.3        # cameras are still settling in the first moments (same margin as the rest of the planner)
VIEWS = ("steady hold", "action peak", "action onset", "action settles", "sharpest", "opening", "middle")


def _smooth(values: np.ndarray, width: int = 3) -> np.ndarray:
    return np.convolve(values, np.ones(width) / width, mode="same") if len(values) >= width else values


def motion_events(m: dict[str, Any]) -> list[dict[str, float]]:
    """Actions in a clip: [{onset, peak, settle, strength}] in seconds, strongest first. Strength = the peak's change over the clip's usual level."""
    fps = float(m["fps"])
    motion = _smooth(np.asarray(m["motion"], dtype=float))
    if len(motion) < 5:
        return []
    base = float(np.median(motion)) + 1e-6
    threshold = max(base * ACTION_FACTOR, base + ACTION_MIN_RISE)
    spikes = set(int(i) for i in m.get("spikes", []))
    peaks = [i for i in range(2, len(motion) - 2)
             if motion[i] >= threshold and motion[i] == motion[max(0, i - 4): i + 5].max() and not any(abs(i - s) <= 1 for s in spikes)]  # a hard cut is not an action
    peaks.sort(key=lambda i: -motion[i])
    chosen: list[int] = []
    for i in peaks:
        if all(abs(i - c) / fps >= PEAK_SEPARATION_SECONDS for c in chosen):
            chosen.append(i)
    events = []
    limit = int(MAX_PHASE_SECONDS * fps)
    for i in chosen:
        a = i
        while a > 0 and i - a < limit and motion[a - 1] > base * EDGE_FACTOR:
            a -= 1
        b = i
        while b < len(motion) - 1 and b - i < limit and motion[b + 1] > base * EDGE_FACTOR:
            b += 1
        events.append({"onset": a / fps, "peak": i / fps, "settle": b / fps, "strength": float(motion[i] / base)})
    return events


def _fit(start: float, lo: float, hi: float) -> float:
    return float(min(max(start, lo), hi))


def candidates(m: dict[str, Any], duration: float, length: float, k: int = 6) -> list[dict[str, Any]]:
    """Up to `k` distinct windows of `length` seconds, each from a different point of view, none with a hard cut inside.

    Each: {start, length, view, why, steady: <post_steady score record>, event?: {onset, peak, settle, strength}}. Windows closer than half a window to an
    earlier one are dropped, so the list is genuinely different moments. The order is by view, NOT by quality."""
    dur = min(duration, float(m["seconds"]))
    length = min(length, dur)
    lo = min(OPENING_SECONDS, max(dur - length, 0.0))
    hi = max(dur - length - 0.04, 0.0)
    starts = np.arange(lo, hi + 1e-9, STEP) if hi > lo else np.array([lo])
    records = [post_steady.score_window(m, float(s), length) for s in starts]
    clean = np.array([r["cuts"] == 0 for r in records])
    if not clean.any():
        return []
    score = np.array([r["score"] for r in records])
    blur = np.array([r["blur"] for r in records])
    proposals: list[tuple[str, float, str, dict | None]] = []
    clean_idx = np.flatnonzero(clean)
    best = clean_idx[int(np.argmin(score[clean_idx]))]
    proposals.append(("steady hold", float(starts[best]), "the steadiest stretch: smooth, sharp, no cut", None))
    for e in motion_events(m)[:2]:
        span = e["settle"] - e["onset"]
        proposals.append(("action peak", _fit(e["peak"] - 0.6 * length, lo, hi), f"centred on a rise in movement ({e['strength']:.1f}x the clip's usual level)", e))
        proposals.append(("action onset", _fit(e["onset"] - ONSET_LEAD_SECONDS, lo, hi), "starts just before movement picks up, so the action begins inside the shot", e))
        if span > 0.3:
            proposals.append(("action settles", _fit(e["settle"] - length + 0.1, lo, hi), "ends as the movement settles, so the action is completed", e))
    sharp = clean_idx[int(np.argmin(blur[clean_idx]))]
    proposals.append(("sharpest", float(starts[sharp]), "the sharpest stretch of the clip", None))
    proposals.append(("opening", float(starts[0]), "the opening of the clip, after the camera settles", None))
    proposals.append(("middle", _fit(dur / 2 - length / 2, lo, hi), "the middle of the clip", None))
    out: list[dict[str, Any]] = []
    for view, start, why, event in proposals:
        record = post_steady.score_window(m, start, length)
        if record["cuts"] or any(abs(start - c["start"]) < length * 0.5 for c in out):
            continue
        out.append({"start": round(start, 3), "length": round(length, 3), "view": view, "why": why,
                    "steady": {key: round(float(record[key]), 4) for key in ("score", "mean_motion", "peak_motion", "jerk", "blur", "luma", "exposure")} | {"static": bool(record["static"])},
                    **({"event": {key: round(val, 3) for key, val in event.items()}} if event else {})})
        if len(out) == k:
            break
    return out
