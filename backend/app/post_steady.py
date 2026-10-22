"""Steady moments and slow zooms for corporate (narrated b-roll) edits (2026-10-14).

Josh's direction for corporate videos: hard cuts only, shots taken from STEADY moments of a clip (no jolts, no blur, no cut inside the
shot), calmer pacing, and a slow zoom -- in OR out -- only on shots whose footage is too static / has little action of its own (a clip
that already moves doesn't need a second movement on top).

This module reads a clip at low resolution (8 frames a second, 160x90 grey) and answers three questions about any window of it:

  * is it steady?   no hard cut inside, smooth motion (low jerk), sharp, not dark;
  * is it static?   the picture barely changes (mean frame-to-frame change below STATIC_MOTION);
  * where is the steadiest window of a given length?

Everything is deterministic and local (ffmpeg + numpy, no Claude credits). The thresholds are stated assumptions calibrated on
Josh's real Diplomat footage (see the constants) -- adjustable, not a claim about the one right value.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import shutil
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_FPS = 8.0
FRAME_W, FRAME_H = 160, 90
MAX_ANALYSED_SECONDS = 300.0  # a longer clip is read for its first five minutes only
READ_TIMEOUT_SECONDS = 240.0
DECODE_THREADS = 2  # decoder threads per ffmpeg. ffmpeg's default (one per core) makes several readers spin against each other: 8 readers x 12 threads took 140 s a clip instead of 20 s (2026-10-15)
READ_CONCURRENCY = 5  # clips read at once: DECODE_THREADS x this ~ the core count. A 4K 4:2:2 10-bit 50p clip costs ~5 CPU-seconds per second of footage whatever the settings (hardware decode can't read it), so 165 clips need ~15 minutes of a 12-core Mac
SAVE_EVERY = 10  # the cache is saved after every this many clips, so a long first read keeps its progress if the request is cut off or the backend restarts

# --- what counts as what (calibrated on the real Diplomat clips, see calibration notes in the plan's `notes`) ---
CUT_SPIKE_MIN = 0.15          # a frame-to-frame change this big (share of full range) is a hard cut. Real cuts in Josh's Diplomat clips change >= 0.19;
CUT_SPIKE_RATIO = 3.0         #   the cut-free footage never exceeds 0.121 even in fast moves. Must also be this many times the clip's usual change.
SOFT_CUT_MIN = 0.07           # a cut between two SIMILAR looking shots changes less -- but it is a lone spike: its neighbours are calm,
SOFT_CUT_ISOLATION = 5.0      #   while fast camera movement raises the samples around it too. This many times the larger neighbour.
STATIC_MOTION = 0.016         # mean frame-to-frame change (0..1) below this = "too static / lacks action": gets a slow zoom. Real Diplomat footage splits cleanly: steadiest windows are 0.005-0.009 (nearly still) or >= 0.031 (moving), nothing between
STATIC_PEAK = 0.03            # ... and no single moment above this (still windows peak <= 0.02; moving ones >= 0.034) -- somebody walking through is action, not a still shot
DARK_LUMA = 0.08              # a window whose picture is nearly black is not a usable moment
UNDER_LUMA = 0.16             # mean brightness below this = underexposed (a soft penalty, not a ban: a moody shot can be dark on purpose)
OVER_LUMA = 0.86              # ... above this = overexposed
BLOWN_SHARE = 0.15            # more than this share of the frame at pure white = blown highlights

# --- picture signature (2026-10-15): so the planner can tell when two shots look alike ---
# One 16x9 grey thumbnail per second of every clip (the 160x90 frame averaged in 10x10 blocks). On Josh's real corporate footage the correlation of two
# thumbnails separated same-scene from different-scene shots with AUC 0.98 (same-scene pairs averaged 0.68, different-scene pairs 0.02), and it ignores
# colour grading, so the same aerial in two colour treatments still counts as the same look.
THUMB_W, THUMB_H = 16, 9
EVENT_BONUS = 0.05            # steadiness-score points a window earns for covering a clip's strongest described event (Claude's judgment; small on purpose)
# 2026-10-19: when Claude has described a clip, the shot is centred on its best described event (first one whose stretch has no cut and isn't black); the steadiest
# stretch is only the fallback. Measured on 168 of Josh's real shots from 21 projects (learning/vision_eval.py): the steadiest stretch lands on the moment he used
# LESS often than a random one (top-3 10% vs 18%), while Claude's picks from the pictures hit 26-27% (top-1 9-12% vs 6.5%). A thin edge, but the only one found.
# False restores the steadiest-with-a-small-bonus behaviour.
EVENT_FIRST = True

# --- slow zoom ---
# Josh's direction (2026-10-14): corporate edits are CALMER than the Diplomat reference (median shot 1.63 s). Shot / phrase lengths are multiplied by
# this. 1.0 = exactly the reference's pace. A stated, adjustable default -- not measured from anything.
CALM_PACE = 1.3
MIN_PACE, MAX_PACE = 0.8, 2.0

ZOOM_MIN_PERCENT = 2.5        # total scale change over a shot; the reference's clean slow zooms were ~3% over the shot
ZOOM_MAX_PERCENT = 5.0
ZOOM_PERCENT_PER_SECOND = 1.8  # in between, longer shots zoom a little more so the move stays slow
ZOOM_PUSH_IN_SHARE = 0.7      # the reference's clean zooms were mostly push-ins; the rest are pull-outs


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


async def read_clip(path: str, limiter: asyncio.Semaphore | None = None) -> np.ndarray | None:
    """The clip as (frames, 90, 160) uint8 grey at SAMPLE_FPS, or None when it can't be read. Never raises."""
    async def run() -> bytes:
        proc = await asyncio.create_subprocess_exec(
            _ffmpeg(), "-nostdin", "-v", "error", "-threads", str(DECODE_THREADS), "-t", str(MAX_ANALYSED_SECONDS), "-i", path,
            "-an", "-vf", f"fps={SAMPLE_FPS},scale={FRAME_W}:{FRAME_H}:flags=area,format=gray", "-f", "rawvideo", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=READ_TIMEOUT_SECONDS)  # a stuck drive must not hang the plan
        except asyncio.TimeoutError:
            proc.kill()
            return b""
        return out
    try:
        if limiter is not None:
            async with limiter:
                raw = await run()
        else:
            raw = await run()
    except OSError:
        return None
    n = len(raw) // (FRAME_W * FRAME_H)
    if n < 3:
        return None
    return np.frombuffer(raw[: n * FRAME_W * FRAME_H], dtype=np.uint8).reshape(n, FRAME_H, FRAME_W)


def measure(frames: np.ndarray) -> dict[str, Any]:
    """Per-sample series for a clip: motion (change from the previous sample, 0..1), sharpness, brightness, plus where hard cuts are."""
    f = frames.astype(np.float32) / 255.0
    luma = f.reshape(len(f), -1).mean(axis=1)
    diff = np.abs(f[1:] - f[:-1]).reshape(len(f) - 1, -1).mean(axis=1)
    # global brightness flicker/auto-exposure shifts are not motion: remove each pair's mean level change before measuring
    shift = (f[1:].reshape(len(f) - 1, -1).mean(axis=1) - f[:-1].reshape(len(f) - 1, -1).mean(axis=1))
    flicker_free = np.abs((f[1:] - f[:-1]) - shift[:, None, None]).reshape(len(f) - 1, -1).mean(axis=1)
    motion = np.concatenate([[flicker_free[0]], flicker_free])  # sample i: change from sample i-1 (the first repeats the second)
    lap = (f[:, 1:-1, 1:-1] * 4 - f[:, :-2, 1:-1] - f[:, 2:, 1:-1] - f[:, 1:-1, :-2] - f[:, 1:-1, 2:])
    sharp = lap.reshape(len(f), -1).var(axis=1)
    hi = (f >= 0.97).reshape(len(f), -1).mean(axis=1)
    secs = frames[:: int(SAMPLE_FPS)]
    thumbs = secs.reshape(len(secs), THUMB_H, FRAME_H // THUMB_H, THUMB_W, FRAME_W // THUMB_W).astype(np.float32).mean(axis=(2, 4)).round().astype(np.uint8)
    usual = float(np.median(motion)) or 1e-4
    spikes = []
    for i in range(1, len(motion)):
        big = motion[i] >= CUT_SPIKE_MIN and motion[i] >= CUT_SPIKE_RATIO * usual
        neighbours = max(motion[i - 1] if i - 1 >= 1 else 0.0, motion[i + 1] if i + 1 < len(motion) else 0.0)
        lone = motion[i] >= SOFT_CUT_MIN and motion[i] >= CUT_SPIKE_RATIO * usual and motion[i] >= SOFT_CUT_ISOLATION * max(neighbours, 1e-4)
        if big or lone:
            spikes.append(int(i))
    return {"fps": SAMPLE_FPS, "motion": [round(float(x), 5) for x in motion], "sharp": [round(float(x), 6) for x in sharp],
            "luma": [round(float(x), 4) for x in luma], "hi": [round(float(x), 4) for x in hi], "spikes": spikes, "seconds": round(len(f) / SAMPLE_FPS, 2),
            "thumbs": base64.b64encode(thumbs.tobytes()).decode("ascii"), "thumb_n": int(len(thumbs))}


def _window_indices(m: dict[str, Any], start: float, length: float) -> tuple[int, int]:
    n = len(m["motion"])
    i0 = max(0, min(n - 1, int(round(start * m["fps"]))))
    i1 = max(i0 + 1, min(n, int(round((start + length) * m["fps"]))))
    return i0, i1


# The series are stored as JSON lists; scoring thousands of windows converts them over and over, so each clip's arrays are made once per plan.
_SERIES: dict[int, tuple[dict[str, Any], dict[str, np.ndarray]]] = {}


def clear_series_cache() -> None:
    _SERIES.clear()


def _series(m: dict[str, Any]) -> dict[str, np.ndarray]:
    hit = _SERIES.get(id(m))
    if hit is not None and hit[0] is m:
        return hit[1]
    arrays = {"motion": np.asarray(m["motion"], dtype=np.float64), "sharp": np.asarray(m["sharp"], dtype=np.float64), "luma": np.asarray(m["luma"], dtype=np.float64),
              "hi": np.asarray(m["hi"], dtype=np.float64) if m.get("hi") else np.zeros(len(m["motion"])), "spikes": np.asarray(m["spikes"], dtype=np.int64)}
    arrays["typical_sharp"] = float(np.median(arrays["sharp"])) or 1e-6  # type: ignore[assignment]
    _SERIES[id(m)] = (m, arrays)
    return arrays


def score_window(m: dict[str, Any], start: float, length: float) -> dict[str, Any]:
    """How steady one window [start, start+length] of the clip is. Lower `score` = steadier; `cuts` > 0 means a hard cut inside it.
    Also counts exposure (2026-10-15): a window that is mostly underexposed, overexposed or full of blown highlights is not a good shot."""
    a = _series(m)
    i0, i1 = _window_indices(m, start, length)
    motion = a["motion"][i0 + 1:i1]
    if len(motion) == 0:
        motion = a["motion"][i0:i1 + 1]  # the change INTO each sample after the first one in the window
    sharp = a["sharp"][i0:i1]
    luma = a["luma"][i0:i1]
    cuts = int(np.count_nonzero((a["spikes"] >= i0 + 1) & (a["spikes"] <= i1)))
    jerk = float(np.abs(np.diff(motion)).mean()) if len(motion) > 1 else 0.0
    blur = max(0.0, 1.0 - float(sharp.min()) / a["typical_sharp"]) if len(sharp) else 0.0  # type: ignore[operator]
    mean_luma = float(luma.mean()) if len(luma) else 0.5
    dark = 1.0 if (len(luma) and mean_luma < DARK_LUMA) else 0.0
    under = max(0.0, (UNDER_LUMA - mean_luma) / UNDER_LUMA)
    over = max(0.0, (mean_luma - OVER_LUMA) / (1.0 - OVER_LUMA))
    blown = max(0.0, float(a["hi"][i0:i1].mean()) - BLOWN_SHARE) if i1 > i0 else 0.0
    exposure = 0.6 * under + 0.6 * over + 1.5 * blown
    mean_m, peak = float(motion.mean()), float(motion.max())
    score = 4.0 * jerk + 1.0 * peak + 0.5 * mean_m + 0.8 * blur + 2.0 * dark + exposure + (50.0 * cuts)
    return {"score": score, "cuts": cuts, "mean_motion": mean_m, "peak_motion": peak, "jerk": jerk, "blur": blur, "dark": bool(dark), "exposure": exposure, "luma": mean_luma,
            "static": bool(cuts == 0 and not dark and mean_m < STATIC_MOTION and peak < STATIC_PEAK)}


def steadiest_window(m: dict[str, Any], duration: float, length: float, taken: list[tuple[float, float]], *, lo: float = 0.0, hi: float | None = None,
                     bonus: Any = None) -> dict[str, Any]:
    """The steadiest `length`-second window of the clip that doesn't overlap windows already used from it.
    Starts are tried every quarter second; ties lean towards the middle of the clip (the opening and closing seconds of a take are
    where cameras are still settling or already moving)."""
    length = min(length, duration)
    hi = max(duration - length - 0.04, 0.0) if hi is None else hi
    lo = min(lo, hi)
    best: tuple[float, float, dict[str, Any]] | None = None
    starts = list(np.arange(lo, hi + 1e-9, 0.25)) or [lo]
    mid = duration / 2.0
    for s in starts:
        if any(s < b and s + length > a for a, b in taken):
            continue
        sc = score_window(m, float(s), length)
        centre_bias = 0.002 * abs((s + length / 2.0) - mid) / max(duration, 1.0)
        total = sc["score"] + centre_bias - (bonus(float(s)) if bonus else 0.0)  # `bonus`: steadiness-score points a window earns (a described event inside it)
        if best is None or total < best[0]:
            best = (total, float(s), sc)
    if best is None:  # every start overlaps an earlier use: take the least-bad regardless
        s = lo
        return {"start": round(s, 3), "duration": round(length, 3), "overlaps_earlier_use": True, **score_window(m, s, length)}
    return {"start": round(best[1], 3), "duration": round(length, 3), "overlaps_earlier_use": False, **best[2]}


def _event_windows(clip: dict[str, Any], length: float, taken: list[tuple[float, float]], limit: int) -> list[dict[str, Any]]:
    """Up to `limit` windows of `clip`, each centred on one of Claude's described events, best event first: the stretch has no hard cut, is not black and is clear of
    windows already used from the clip. Same shape as window_for_slot's result. [] when the clip has no described events or none of them gives a usable stretch."""
    from app.post_media import COMPOSE_MIN_START
    m = clip.get("steady")
    events = [e for e in (clip.get("events") or []) if e.get("t") is not None]
    if not m or not events:
        return []
    dur = min(clip["duration"], m["seconds"])
    length = min(length, dur)
    lo = min(COMPOSE_MIN_START, max(dur - length, 0.0))
    hi = max(dur - length - 0.04, 0.0)
    out: list[dict[str, Any]] = []
    used = list(taken)
    for e in sorted(events, key=lambda e: -float(e.get("punch", 0))):
        start = min(max(float(e["t"]) - length / 2.0, lo), hi)
        if any(start < b and start + length > a for a, b in used):
            continue
        rec = score_window(m, start, length)
        if rec["cuts"] or rec["dark"]:
            continue
        out.append({"start": round(start, 3), "duration": round(length, 3), "overlaps_earlier_use": False, "event_punch": e.get("punch"), "event_kind": e.get("kind"),
                    "source": f"event pick ({e.get('kind', 'moment')}): {e.get('what', '')} -- Claude's judgment from the pictures, not checked against your taste",
                    "steady": {"score": round(rec["score"], 4), "cuts": rec["cuts"], "mean_motion": round(rec["mean_motion"], 4), "peak_motion": round(rec["peak_motion"], 4),
                               "jerk": round(rec["jerk"], 4), "blur": round(rec["blur"], 3), "static": rec["static"], "exposure": round(rec["exposure"], 3), "luma": round(rec["luma"], 3)}})
        used.append((start, start + length))   # the next candidate must be a different moment, not a quarter second along the same one
        if len(out) == limit:
            break
    return out


def event_windows(clip: dict[str, Any], length: float, taken: list[tuple[float, float]], limit: int = 3) -> list[dict[str, Any]]:
    """The picker's candidates for a clip: its best `limit` described moments (see _event_windows). Empty when EVENT_FIRST is off."""
    return _event_windows(clip, length, taken, limit) if EVENT_FIRST else []


def window_for_slot(clip: dict[str, Any], length: float, taken: list[tuple[float, float]]) -> dict[str, Any]:
    """The best window of `clip` for a slot of `length` seconds, shaped like the planner's other window choices ({start, duration, source, steady}).
    If Claude has described the clip (`events`, from Describe clips) and EVENT_FIRST is on, the window is centred on its best event whose stretch is usable
    (no hard cut inside, not black, clear of windows already used from the clip). Otherwise -- or when no described event qualifies -- the steadiest stretch:
    no cut inside, smooth, sharp, well exposed, with a small bonus where it covers a described event."""
    from app.post_media import COMPOSE_MIN_START  # same start margin as the planner's other window choices (cameras are still settling in the first moments)
    m = clip["steady"]
    dur = min(clip["duration"], m["seconds"])  # the analysis may cover less than the whole clip (first five minutes)
    length = min(length, dur)
    lo = min(COMPOSE_MIN_START, max(dur - length, 0.0))
    hi = max(dur - length - 0.04, 0.0)
    events = [e for e in (clip.get("events") or []) if e.get("t") is not None]

    def shaped(start: float, duration: float, source: str, event: dict[str, Any] | None, rec: dict[str, Any], overlaps: bool) -> dict[str, Any]:
        return {"start": round(start, 3), "duration": round(duration, 3), "source": source, "overlaps_earlier_use": overlaps,
                "event_punch": (event.get("punch") if event else None),
                "steady": {"score": round(rec["score"], 4), "cuts": rec["cuts"], "mean_motion": round(rec["mean_motion"], 4), "peak_motion": round(rec["peak_motion"], 4),
                           "jerk": round(rec["jerk"], 4), "blur": round(rec["blur"], 3), "static": rec["static"], "exposure": round(rec["exposure"], 3), "luma": round(rec["luma"], 3)}}

    if EVENT_FIRST:
        first = _event_windows(clip, length, taken, 1)
        if first:
            return first[0]

    def covered(start: float) -> dict[str, Any] | None:
        inside = [e for e in events if start + 0.15 <= e["t"] <= start + length - 0.15]
        return max(inside, key=lambda e: e.get("punch", 0)) if inside else None

    bonus = (lambda start: EVENT_BONUS * covered(start)["punch"] / 10.0 if covered(start) else 0.0) if events else None  # type: ignore[index]
    w = steadiest_window(m, dur, length, taken, lo=lo, hi=hi, bonus=bonus)
    event = covered(w["start"]) if events else None
    if w["cuts"]:
        source = "steadiest window -- but every window of this clip has a cut in it (least bad)"
    elif event:
        source = f"steadiest window around an event ({event.get('kind', 'moment')}): {event.get('what', '')} -- Claude's judgment, not checked against your taste"
    elif w["static"]:
        source = "steadiest window (static footage, no cut inside)"
    else:
        source = "steadiest window (no cut inside, smooth, sharp)"
    return shaped(w["start"], w["duration"], source, event, w, w.get("overlaps_earlier_use", False))


def moment_note(shots: list[dict[str, Any]]) -> str:
    """The plan-notes sentence about how each shot's stretch of its clip was chosen -- so a plan never claims 'steadiest' for shots cut on a described event."""
    n = sum(1 for s in shots if str(s.get("moment_source", "")).startswith("event pick"))
    steady = "the STEADIEST window of its clip -- no cut inside, smooth, sharp, not dark"
    if not n:
        return f"Every shot is taken from {steady}."
    rest = len(shots) - n
    return (f"{n} of {len(shots)} shots are centred on a moment Claude picked from the clip's pictures (Describe clips): no cut inside and not black, but not necessarily the steadiest part of the clip."
            + (f" The other {rest} are {steady}." if rest else ""))


# ------------------------------------------------------------------------------------------------------ picture signatures
def decode_thumbs(m: dict[str, Any]) -> np.ndarray | None:
    """The clip's per-second thumbnails as (seconds, 144) unit vectors with the mean removed (so a dot product is a brightness-independent correlation),
    or None for an analysis made before signatures existed."""
    raw, n = m.get("thumbs"), m.get("thumb_n")
    if not raw or not n:
        return None
    a = np.frombuffer(base64.b64decode(raw), dtype=np.uint8).reshape(int(n), THUMB_W * THUMB_H).astype(np.float32)
    a -= a.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(a, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return a / norm


def window_signature(thumbs: np.ndarray | None, start: float, length: float) -> np.ndarray | None:
    """What a window looks like: the thumbnails at its start, middle and end (so a camera move across a scene still matches that scene)."""
    if thumbs is None or not len(thumbs):
        return None
    idx = sorted({min(len(thumbs) - 1, max(0, int(t))) for t in (start + 0.1, start + length / 2.0, start + length - 0.1)})
    return thumbs[idx]


def similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """How alike two windows look, -1..1 (the best match between any of their sampled frames). 0.0 when either has no signature."""
    if a is None or b is None:
        return 0.0
    return float((a @ b.T).max())


def plan_zooms(shots: list[dict[str, Any]], fps: float, *, seed: int = 7) -> list[dict[str, Any]]:
    """A slow zoom for every body shot whose footage is static (`shot["steady"]["static"]`): push-in about 70% of the time, pull-out
    otherwise, never the same direction more than twice in a row. Total change grows a little with the shot's length (2.5% .. 5%)."""
    rng = random.Random(seed)
    zooms: list[dict[str, Any]] = []
    run_dir, run_len = None, 0
    for shot in shots:
        steady = shot.get("steady") or {}
        if shot.get("role") != "body" or not steady.get("static"):
            continue
        seconds = shot["duration_frames"] / fps
        percent = round(min(ZOOM_MAX_PERCENT, max(ZOOM_MIN_PERCENT, ZOOM_PERCENT_PER_SECOND * seconds)), 1)
        direction = "in" if rng.random() < ZOOM_PUSH_IN_SHARE else "out"
        if direction == run_dir and run_len >= 2:
            direction = "out" if direction == "in" else "in"
        run_len = run_len + 1 if direction == run_dir else 1
        run_dir = direction
        zooms.append({"shot_index": shot["index"], "start_frame": shot["start_frame"], "frames": shot["duration_frames"], "direction": direction, "percent": percent,
                      "why": f"the footage is static (mean change {steady['mean_motion']:.3f}, limit {STATIC_MOTION})"})
    return zooms


# --------------------------------------------------------------------------------------------------------------- caching
CACHE_VERSION = 2  # 2 (2026-10-15): adds the picture signature and the blown-highlight series; a version-1 cache is read again once


def cache_path(job: dict[str, Any]) -> Path:
    from app.post_edit_plan import edit_dir  # local import: post_edit_plan imports this module
    return edit_dir(job) / "steadiness.json"


def _fingerprint(path: str) -> list[float] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, round(st.st_mtime, 2)]


def load_cache(job: dict[str, Any]) -> dict[str, Any]:
    p = cache_path(job)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_cache(job: dict[str, Any], cache: dict[str, Any]) -> None:
    p = cache_path(job)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache))


async def analyse_clips(clips: list[dict[str, Any]], job: dict[str, Any], *, concurrency: int = READ_CONCURRENCY, only_cached: bool = False, always: set[int] | None = None) -> dict[str, int]:
    """Attaches `clip["steady"]` (the per-clip series) to each clip, reading from the job's cache when the file hasn't changed.
    A clip that can't be read gets no `steady` and the planner falls back to its old way for it. `only_cached` reads nothing new except the clips in `always` (the
    establishing clip, which opens the edit and holds the closing card): clips not in the cache simply get no analysis (a quick plan from what has been read so far). Returns counts for the plan's notes."""
    from app.ssd_guard import on_drive
    cache = await on_drive(load_cache, job)
    limiter = asyncio.Semaphore(concurrency)
    counts = {"cached": 0, "analysed": 0, "unreadable": 0, "not_read": 0}
    dirty = False
    saving = asyncio.Lock()

    async def one(clip: dict[str, Any]) -> None:
        nonlocal dirty
        key = str(clip["file_id"])
        fp = await on_drive(_fingerprint, clip["path"])
        hit = cache.get(key)
        if hit and fp and hit.get("fp") == fp and hit.get("v") == CACHE_VERSION:
            clip["steady"] = hit["m"]
            clip["thumbs"] = decode_thumbs(hit["m"])
            counts["cached"] += 1
            return
        if only_cached and clip["file_id"] not in (always or set()):
            counts["not_read"] += 1
            return
        frames = await read_clip(clip["path"], limiter)
        if frames is None:
            counts["unreadable"] += 1
            return
        m = measure(frames)
        clip["steady"] = m
        clip["thumbs"] = decode_thumbs(m)
        cache[key] = {"fp": fp, "v": CACHE_VERSION, "m": m}
        counts["analysed"] += 1
        dirty = True
        if counts["analysed"] % SAVE_EVERY == 0 and not saving.locked():
            async with saving:  # a snapshot of what is done so far (a dict copy: other clips keep finishing while it writes)
                await on_drive(save_cache, job, dict(cache), writing=True)

    await asyncio.gather(*(one(c) for c in clips))
    if dirty:
        await on_drive(save_cache, job, cache, writing=True)
    return counts


def coverage_note(clips: list[dict[str, Any]], quick: bool = False) -> str:
    """One plain sentence on how much of the footage the planner actually looked through."""
    total = len(clips)
    read = [c for c in clips if c.get("steady")]
    long_ones = [c for c in read if c["duration"] > MAX_ANALYSED_SECONDS + 0.5]
    text = f"Looked through {len(read)} of {total} clips for the cleanest stretches"
    if quick:
        return text + f" -- a QUICK plan: the other {total - len(read)} clips had not been read yet, so every shot comes from those {len(read)}. Plan again once they have all been read for the full picture."
    if len(read) < total:
        text += f" ({total - len(read)} couldn't be read and were left out of the picks)"
    if long_ones:
        text += f"; {len(long_ones)} clip(s) run past {int(MAX_ANALYSED_SECONDS // 60)} minutes, so only their first {int(MAX_ANALYSED_SECONDS // 60)} minutes were read"
    return text + "."
