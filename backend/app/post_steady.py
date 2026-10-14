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

# --- what counts as what (calibrated on the real Diplomat clips, see calibration notes in the plan's `notes`) ---
CUT_SPIKE_MIN = 0.15          # a frame-to-frame change this big (share of full range) is a hard cut. Real cuts in Josh's Diplomat clips change >= 0.19;
CUT_SPIKE_RATIO = 3.0         #   the cut-free footage never exceeds 0.121 even in fast moves. Must also be this many times the clip's usual change.
SOFT_CUT_MIN = 0.07           # a cut between two SIMILAR looking shots changes less -- but it is a lone spike: its neighbours are calm,
SOFT_CUT_ISOLATION = 5.0      #   while fast camera movement raises the samples around it too. This many times the larger neighbour.
STATIC_MOTION = 0.016         # mean frame-to-frame change (0..1) below this = "too static / lacks action": gets a slow zoom. Real Diplomat footage splits cleanly: steadiest windows are 0.005-0.009 (nearly still) or >= 0.031 (moving), nothing between
STATIC_PEAK = 0.03            # ... and no single moment above this (still windows peak <= 0.02; moving ones >= 0.034) -- somebody walking through is action, not a still shot
DARK_LUMA = 0.08              # a window whose picture is nearly black is not a usable moment

# --- slow zoom ---
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
            _ffmpeg(), "-nostdin", "-v", "error", "-t", str(MAX_ANALYSED_SECONDS), "-i", path,
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
    usual = float(np.median(motion)) or 1e-4
    spikes = []
    for i in range(1, len(motion)):
        big = motion[i] >= CUT_SPIKE_MIN and motion[i] >= CUT_SPIKE_RATIO * usual
        neighbours = max(motion[i - 1] if i - 1 >= 1 else 0.0, motion[i + 1] if i + 1 < len(motion) else 0.0)
        lone = motion[i] >= SOFT_CUT_MIN and motion[i] >= CUT_SPIKE_RATIO * usual and motion[i] >= SOFT_CUT_ISOLATION * max(neighbours, 1e-4)
        if big or lone:
            spikes.append(int(i))
    return {"fps": SAMPLE_FPS, "motion": [round(float(x), 5) for x in motion], "sharp": [round(float(x), 6) for x in sharp],
            "luma": [round(float(x), 4) for x in luma], "spikes": spikes, "seconds": round(len(f) / SAMPLE_FPS, 2)}


def _window_indices(m: dict[str, Any], start: float, length: float) -> tuple[int, int]:
    n = len(m["motion"])
    i0 = max(0, min(n - 1, int(round(start * m["fps"]))))
    i1 = max(i0 + 1, min(n, int(round((start + length) * m["fps"]))))
    return i0, i1


def score_window(m: dict[str, Any], start: float, length: float) -> dict[str, Any]:
    """How steady one window [start, start+length] of the clip is. Lower `score` = steadier; `cuts` > 0 means a hard cut inside it."""
    i0, i1 = _window_indices(m, start, length)
    motion = np.array(m["motion"][i0 + 1:i1] or m["motion"][i0:i1 + 1])  # the change INTO each sample after the first one in the window
    sharp = np.array(m["sharp"][i0:i1])
    luma = np.array(m["luma"][i0:i1])
    cuts = sum(1 for s in m["spikes"] if i0 + 1 <= s <= i1)
    typical_sharp = float(np.median(m["sharp"])) or 1e-6
    jerk = float(np.abs(np.diff(motion)).mean()) if len(motion) > 1 else 0.0
    blur = max(0.0, 1.0 - float(sharp.min()) / typical_sharp) if len(sharp) else 0.0
    dark = 1.0 if (len(luma) and float(luma.mean()) < DARK_LUMA) else 0.0
    mean_m, peak = float(motion.mean()), float(motion.max())
    score = 4.0 * jerk + 1.0 * peak + 0.5 * mean_m + 0.8 * blur + 2.0 * dark + (50.0 * cuts)
    return {"score": score, "cuts": cuts, "mean_motion": mean_m, "peak_motion": peak, "jerk": jerk, "blur": blur, "dark": bool(dark),
            "static": bool(cuts == 0 and not dark and mean_m < STATIC_MOTION and peak < STATIC_PEAK)}


def steadiest_window(m: dict[str, Any], duration: float, length: float, taken: list[tuple[float, float]], *, lo: float = 0.0, hi: float | None = None) -> dict[str, Any]:
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
        total = sc["score"] + centre_bias
        if best is None or total < best[0]:
            best = (total, float(s), sc)
    if best is None:  # every start overlaps an earlier use: take the least-bad regardless
        s = lo
        return {"start": round(s, 3), "duration": round(length, 3), "overlaps_earlier_use": True, **score_window(m, s, length)}
    return {"start": round(best[1], 3), "duration": round(length, 3), "overlaps_earlier_use": False, **best[2]}


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


async def analyse_clips(clips: list[dict[str, Any]], job: dict[str, Any], *, concurrency: int = 3) -> dict[str, int]:
    """Attaches `clip["steady"]` (the per-clip series) to each clip, reading from the job's cache when the file hasn't changed.
    A clip that can't be read gets no `steady` and the planner falls back to its old way for it. Returns counts for the plan's notes."""
    from app.ssd_guard import on_drive
    cache = await on_drive(load_cache, job)
    limiter = asyncio.Semaphore(concurrency)
    counts = {"cached": 0, "analysed": 0, "unreadable": 0}
    dirty = False

    async def one(clip: dict[str, Any]) -> None:
        nonlocal dirty
        key = str(clip["file_id"])
        fp = await on_drive(_fingerprint, clip["path"])
        hit = cache.get(key)
        if hit and fp and hit.get("fp") == fp and hit.get("v") == 1:
            clip["steady"] = hit["m"]
            counts["cached"] += 1
            return
        frames = await read_clip(clip["path"], limiter)
        if frames is None:
            counts["unreadable"] += 1
            return
        m = measure(frames)
        clip["steady"] = m
        cache[key] = {"fp": fp, "v": 1, "m": m}
        counts["analysed"] += 1
        dirty = True

    await asyncio.gather(*(one(c) for c in clips))
    if dirty:
        await on_drive(save_cache, job, cache, writing=True)
    return counts
