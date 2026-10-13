"""
POST (2026-10-13) -- reference edits read from a FINISHED VIDEO instead of a Premiere project.

Why this exists: post_reference.py reads a saved .prproj, which gives exact cuts and effect values -- but only for
timelines Josh built from camera clips. His other reference edits are exported videos (one clip on a timeline), where
the project file holds nothing but "one long video". The cuts, dissolves, flashes and pacing are only in the pixels, so
this module decodes every frame (small, grey/colour, a few numbers per frame) and recovers them.

What it can and can NOT recover, stated plainly:
  * cuts (hard), dissolves, dips to black/white, flash frames, black-and-white runs, blur right at a cut: measured,
    and checked against footage with known answers (see the validation in the session notes / tests);
  * NOT exact effect values (a flash's Lumetri exposure, a zoom blur's amount), NOT sound effects as separate files,
    NOT which source clip a shot came from. A reference built here records WHAT happens and WHEN, not how Premiere
    was told to do it.
  * "shot content" (wide/close, people/product, titles) is not measurable from pixels alone; describe_shots() asks
    Claude about sampled frames and returns its labels, which are labels, not measurements.

Everything is deterministic numpy over per-frame features except describe_shots().
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

LONG_SIDE = 160  # frames are analysed at 160 px on the long side
BLOCK = 5  # thumbnails are 5x5 block means (a 32x18 picture) for the gradual-transition search
HIST_BINS = 16

# --- detection settings (all calibrated on footage with known answers; see validate notes) ---
HARD_MIN_DIFF = 0.06  # a cut moves the picture at least this much (mean abs grey change, 0-1)
HARD_RATIO = 4.0  # ... and at least this many times the typical frame-to-frame change around it
HARD_HIST_MIN = 0.08  # ... and the brightness histogram shifts at least this much (rules out fast motion alone)
CUT_LOCAL_RADIUS = 6  # frames either side used to judge "typical change"
FLASH_MIN_RISE = 0.18  # a flash frame is this much brighter than the frames around it ...
FLASH_MAX_FRAMES = 8  # ... for at most this many frames (longer = a bright shot, not a flash)
FLASH_WHITE = 0.80  # (or just plain near-white)
FLASH_FLAT_STD = 0.14  # a washed-out flash frame has little detail left
BLACK_LUMA = 0.05
BW_CHROMA = 0.012  # colour drained (mean chroma of the frame)
BW_MIN_FRAMES = 12
MIN_SHOT_FRAMES = 3


class VideoReferenceError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ probing + features
def probe_video(path: str) -> dict[str, Any]:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                          "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,sample_rate,channels:format=duration",
                          "-of", "json", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise VideoReferenceError(f"ffprobe couldn't read {path}: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise VideoReferenceError(f"{path} has no video stream.")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v["r_frame_rate"].split("/") + ["1"])[:2]
    fps = float(num) / float(den or 1)
    avg_num, avg_den = (v.get("avg_frame_rate", "0/1").split("/") + ["1"])[:2]
    avg_fps = float(avg_num) / float(avg_den or 1) if float(avg_den or 1) else 0.0
    return {"width": int(v["width"]), "height": int(v["height"]), "fps": fps, "avg_fps": avg_fps,
            "duration": float(data["format"]["duration"]), "frames_declared": int(v.get("nb_frames") or 0),
            "vfr": abs(avg_fps - fps) > 0.05 * fps if avg_fps else False,
            "has_audio": a is not None, "audio_codec": (a or {}).get("codec_name")}


def _frame_times(path: str) -> list[float]:
    """Presentation time of every video frame, in order (packet timestamps; correct for variable frame rate too)."""
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
                         capture_output=True, text=True, timeout=600)
    times = sorted(float(x) for x in out.stdout.split() if x.strip() not in ("", "N/A"))
    return times


@dataclass
class VideoFeatures:
    info: dict[str, Any]
    times: np.ndarray  # seconds per frame
    luma: np.ndarray  # mean brightness 0-1
    luma_std: np.ndarray  # spatial spread of brightness (a washed-out frame has almost none)
    sat: np.ndarray  # mean chroma 0-1 (colour strength; ~0 for black & white)
    sharp: np.ndarray  # variance of the Laplacian (blur drops it)
    diff: np.ndarray  # mean abs grey change from the previous frame (diff[0] = 0)
    hist_diff: np.ndarray  # brightness-histogram change from the previous frame (0-1)
    thumbs: np.ndarray  # (n, h/5, w/5) uint8 grey thumbnails

    @property
    def n(self) -> int:
        return len(self.luma)

    @property
    def fps(self) -> float:
        return self.info["fps"]


def extract_features(path: str, progress: Any = None) -> VideoFeatures:
    """Decodes every frame at 160 px and keeps a few numbers per frame (plus a tiny thumbnail). 4K takes a couple of
    minutes per ten minutes of video; the frames themselves are never stored."""
    info = probe_video(path)
    w, h = info["width"], info["height"]
    if w >= h:
        ow, oh = LONG_SIDE, max(2, round(LONG_SIDE * h / w / 2) * 2)
    else:
        oh, ow = LONG_SIDE, max(2, round(LONG_SIDE * w / h / 2) * 2)
    ch, cw = (oh // BLOCK) * BLOCK, (ow // BLOCK) * BLOCK
    cmd = [FFMPEG, "-v", "error", "-i", path, "-an", "-fps_mode", "passthrough", "-vf", f"scale={ow}:{oh}:flags=fast_bilinear",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=oh * ow * 3 * 8)
    frame_bytes = oh * ow * 3
    luma, lstd, sat, sharp, diff, hdiff, thumbs = [], [], [], [], [], [], []
    prev = None
    prev_hist = None
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    count = 0
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            rgb = np.frombuffer(raw, dtype=np.uint8).reshape(oh, ow, 3)[:ch, :cw].astype(np.float32) / 255.0
            grey = rgb @ weights
            mx, mn = rgb.max(axis=2), rgb.min(axis=2)
            s = mx - mn  # chroma: how far apart the colour channels are (0 for grey/B&W whatever the brightness)
            lap = grey[1:-1, 1:-1] * 4 - grey[:-2, 1:-1] - grey[2:, 1:-1] - grey[1:-1, :-2] - grey[1:-1, 2:]
            hist = np.histogram(grey, bins=HIST_BINS, range=(0, 1))[0].astype(np.float32)
            hist /= hist.sum()
            luma.append(float(grey.mean())); lstd.append(float(grey.std())); sat.append(float(s.mean())); sharp.append(float(lap.var()))
            diff.append(float(np.abs(grey - prev).mean()) if prev is not None else 0.0)
            hdiff.append(float(0.5 * np.abs(hist - prev_hist).sum()) if prev_hist is not None else 0.0)
            thumbs.append((grey.reshape(ch // BLOCK, BLOCK, cw // BLOCK, BLOCK).mean(axis=(1, 3)) * 255).astype(np.uint8))
            prev, prev_hist = grey, hist
            count += 1
            if progress and count % 2000 == 0:
                progress(count)
    finally:
        proc.stdout.close()
        proc.wait(timeout=30)
    if count == 0:
        raise VideoReferenceError(f"Decoded no frames from {path}.")
    stamps = _frame_times(path)
    if len(stamps) >= count:
        times = np.array(stamps[:count]) - stamps[0]
    else:  # no usable packet times: fall back to a steady rate
        times = np.arange(count) / info["fps"]
    return VideoFeatures(info=info, times=times, luma=np.array(luma), luma_std=np.array(lstd), sat=np.array(sat), sharp=np.array(sharp),
                         diff=np.array(diff), hist_diff=np.array(hdiff), thumbs=np.stack(thumbs))


# ------------------------------------------------------------------------------------------------ detection
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[(first, last)] of each run of True."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1)); start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def detect_flashes(f: VideoFeatures) -> list[dict[str, Any]]:
    """Short runs of washed-out bright frames (an exposure blow-out placed on a cut). A bright SHOT is not a flash:
    it lasts longer than FLASH_MAX_FRAMES or keeps its detail."""
    n = f.n
    base = np.array([np.median(f.luma[max(0, i - 8): i + 9]) for i in range(n)])
    candidate = ((f.luma - base >= FLASH_MIN_RISE) & ((f.luma >= FLASH_WHITE) | (f.luma_std <= FLASH_FLAT_STD))) | (f.luma >= 0.93)
    out = []
    for a, b in _runs(candidate):
        if b - a + 1 <= FLASH_MAX_FRAMES and a > 0 and b < n - 1:
            out.append({"first": a, "last": b, "frames": b - a + 1, "time": float(f.times[a]), "peak_luma": float(f.luma[a:b + 1].max())})
    return out


def detect_dips(f: VideoFeatures, flash_mask: np.ndarray) -> list[dict[str, Any]]:
    """Runs of (almost) black frames: a dip to black between shots, or the video's own fade in / fade out."""
    black = (f.luma <= BLACK_LUMA) & (f.luma_std <= 0.05)
    return [{"first": a, "last": b, "frames": b - a + 1, "time": float(f.times[a])} for a, b in _runs(black) if b - a + 1 >= 2]


def detect_hard_cuts(f: VideoFeatures, ignore: np.ndarray) -> list[dict[str, Any]]:
    """Frame i is a cut when the picture changes sharply and abruptly compared with the frames around it. Frames in
    `ignore` (flash and black frames) are skipped: the change is measured across them, so a flash on a cut is
    one cut, not three."""
    keep = np.where(~ignore)[0]
    if len(keep) < 3:
        return []
    d = np.zeros(len(keep))
    hd = np.zeros(len(keep))
    for j in range(1, len(keep)):
        i, p = keep[j], keep[j - 1]
        if i - p == 1:
            d[j], hd[j] = f.diff[i], f.hist_diff[i]
        else:  # frames were skipped between them: compare the two frames that bracket the gap
            d[j] = float(np.abs(f.thumbs[i].astype(np.float32) - f.thumbs[p].astype(np.float32)).mean() / 255.0)
            hd[j] = f.hist_diff[i]
    cuts = []
    for j in range(1, len(keep)):
        lo, hi = max(1, j - CUT_LOCAL_RADIUS), min(len(keep), j + CUT_LOCAL_RADIUS + 1)
        around = np.concatenate([d[lo:max(lo, j - 1)], d[j + 2:hi]])
        local = float(np.median(around)) if len(around) else 0.0
        peak = d[j] >= d[max(1, j - 2):j + 3].max() - 1e-9  # the strongest change in its neighbourhood
        if d[j] >= HARD_MIN_DIFF and d[j] >= HARD_RATIO * max(local, 0.004) and hd[j] >= HARD_HIST_MIN and peak:
            cuts.append({"frame": int(keep[j]), "time": float(f.times[keep[j]]), "score": float(d[j] / max(local, 0.004)), "diff": float(d[j]), "gap_frames": int(keep[j] - keep[j - 1] - 1)})
    return cuts


DISSOLVE_LENGTHS = tuple(range(5, 42, 2))  # frames; 0.2-1.7 s at 24 fps
DISSOLVE_MIN_SPAN = 0.10  # the picture at the end differs from the start at least this much (mean abs grey change); dissolves between near-identical views are below this and can't be told from slow motion
DISSOLVE_MAX_BLEND_ERR = 0.28  # a mid-dissolve frame is the average of the two ends, to within this share of the span (measured: real dissolves 0.09-0.26, slow motion 0.30+)


def detect_dissolves(f: VideoFeatures, hard_frames: set[int], ignore: np.ndarray) -> list[dict[str, Any]]:
    """Cross-dissolves and fades between two shots. A dissolve is an alpha blend, so a frame partway through is the
    AVERAGE of the picture before and the picture after (a pan or a handheld move is not: its middle frame is a shifted
    picture), the blend grows steadily, and the picture is steady on both sides. Tested on every start frame at several
    lengths; overlapping hits keep the cleanest blend."""
    n = f.n
    th = f.thumbs.astype(np.float32) / 255.0
    d = f.diff
    cands: list[tuple[float, int, int, float]] = []
    for length in DISSOLVE_LENGTHS:
        for s in range(8, n - length - 8):
            e = s + length
            if any(s + 1 <= h <= e for h in hard_frames) or ignore[s:e + 1].any():  # a cut INSIDE the stretch rules it out; one right before/after is fine
                continue
            span = float(np.abs(th[e] - th[s]).mean())
            if span < DISSOLVE_MIN_SPAN:
                continue
            worst = 0.0
            for a in (0.25, 0.5, 0.75):
                m = s + int(round(a * length))
                err = float(np.abs(th[m] - ((1 - a) * th[s] + a * th[e])).mean())
                worst = max(worst, err / span)
            if worst > DISSOLVE_MAX_BLEND_ERR:
                continue
            if any(d[s + 1:e + 1] >= HARD_MIN_DIFF * 1.5):
                continue  # a hard change inside the stretch
            cands.append((worst, s, e, span))
    cands.sort()
    out: list[dict[str, Any]] = []
    taken = np.zeros(n, dtype=bool)
    for worst, s, e, span in cands:
        if taken[max(0, s - 3):e + 4].any():
            continue
        taken[s:e + 1] = True
        out.append({"first": s, "last": e, "frames": e - s, "time": float(f.times[s]), "mid_time": float(f.times[(s + e) // 2]), "span": round(span, 3), "blend_error": round(worst, 3)})
    out.sort(key=lambda x: x["first"])
    return out


def detect_bw_runs(f: VideoFeatures) -> list[dict[str, Any]]:
    """Stretches where the colour is drained (black & white), if the video as a whole is in colour."""
    if float(np.percentile(f.sat, 75)) < 0.03:
        return []  # the whole video is (near) monochrome: nothing to flag
    return [{"first": a, "last": b, "frames": b - a + 1, "time": float(f.times[a]), "seconds": float(f.times[b] - f.times[a])}
            for a, b in _runs(f.sat < BW_CHROMA) if b - a + 1 >= BW_MIN_FRAMES]


def blur_at_cuts(f: VideoFeatures, cut_frames: list[int]) -> dict[str, Any]:
    """Share of cuts with a blurred frame within 3 frames (a zoom/whip transition), against how often a random frame
    looks that blurred. Sharpness has to fall below half its local typical value."""
    n = f.n
    base = np.array([np.median(f.sharp[max(0, i - 12): i + 13]) for i in range(n)])
    soft = f.sharp < 0.5 * np.maximum(base, 1e-9)
    near = [bool(soft[max(0, c - 3): c + 4].any()) for c in cut_frames]
    chance = float(np.mean([soft[max(0, i - 3): i + 4].any() for i in range(3, n - 3)])) if n > 8 else 0.0
    return {"cuts_with_blur": round(float(np.mean(near)), 3) if near else None, "chance": round(chance, 3), "cuts": len(cut_frames)}


def analyze_visual(f: VideoFeatures) -> dict[str, Any]:
    """Cuts, dissolves, dips, flashes, B&W runs and shots for a whole video."""
    flashes = detect_flashes(f)
    flash_mask = np.zeros(f.n, dtype=bool)
    for fl in flashes:
        flash_mask[fl["first"]: fl["last"] + 1] = True
    dips = detect_dips(f, flash_mask)
    dip_mask = np.zeros(f.n, dtype=bool)
    for dp in dips:
        dip_mask[dp["first"]: dp["last"] + 1] = True
    ignore = flash_mask | dip_mask
    hard = detect_hard_cuts(f, ignore)
    hard_frames = {c["frame"] for c in hard}
    all_soft = detect_dissolves(f, hard_frames, ignore)
    # a gradual change that ends/starts on a black run is the fade into/out of that dip (or the video's own fade in/out)
    dissolves, fades = [], []
    for d_ in all_soft:
        touches = [dp for dp in dips if abs(d_["last"] - dp["first"]) <= 2 or abs(d_["first"] - dp["last"]) <= 2]
        (fades if touches else dissolves).append({**d_, "kind": ("fade_out" if abs(d_["last"] - touches[0]["first"]) <= 2 else "fade_in") if touches else "dissolve"})
    bw = detect_bw_runs(f)

    # shot boundaries: hard cuts, dissolve midpoints, and the middle of a dip between two shots (not the video's own fade in/out)
    boundaries: list[dict[str, Any]] = [{"frame": c["frame"], "time": c["time"], "kind": "cut"} for c in hard]
    for d_ in dissolves:
        boundaries.append({"frame": (d_["first"] + d_["last"]) // 2, "time": d_["mid_time"], "kind": "dissolve"})
    inner_dips = [dp for dp in dips if dp["first"] > 2 and dp["last"] < f.n - 3]
    for dp in inner_dips:
        boundaries.append({"frame": (dp["first"] + dp["last"]) // 2, "time": float(f.times[(dp["first"] + dp["last"]) // 2]), "kind": "dip"})
    boundaries.sort(key=lambda b: b["frame"])
    kept: list[dict[str, Any]] = []
    for b in boundaries:
        if kept and b["frame"] - kept[-1]["frame"] < MIN_SHOT_FRAMES:
            continue  # two boundaries within a couple of frames are one event
        kept.append(b)
    starts = [0] + [b["frame"] for b in kept]
    ends = [b["frame"] for b in kept] + [f.n]
    shots = []
    last_time = float(f.times[-1] + (f.times[-1] - f.times[-2] if f.n > 1 else 1.0 / f.fps))
    for k, (a, e) in enumerate(zip(starts, ends)):
        a_t = 0.0 if k == 0 else float(f.times[a])
        e_t = last_time if e >= f.n else float(f.times[e])
        seg = slice(a, e)
        motion = f.diff[a + 1:e] if e - a > 2 else f.diff[a:e]
        shots.append({"start": round(a_t, 3), "end": round(e_t, 3), "frames": e - a, "opens_with": "start" if k == 0 else kept[k - 1]["kind"],
                      "mean_luma": round(float(f.luma[seg].mean()), 3), "mean_chroma": round(float(f.sat[seg].mean()), 3),
                      "motion": round(float(np.median(motion)) if len(motion) else 0.0, 4), "mid_time": round((a_t + e_t) / 2, 3)})
    return {"flashes": flashes, "dips": dips, "fades": fades, "hard_cuts": hard, "dissolves": dissolves, "bw_runs": bw, "shots": shots,
            "blur_at_cuts": blur_at_cuts(f, [c["frame"] for c in hard])}


def attach_flash_positions(visual: dict[str, Any], fps: float) -> dict[str, Any]:
    """For every flash, how far it sits from the nearest shot boundary (in frames; negative = it starts BEFORE the cut,
    as Josh's flashes do), and how many flashes sit on a cut at all."""
    bounds = [s["start"] for s in visual["shots"][1:]]
    rel = []
    for fl in visual["flashes"]:
        if bounds:
            b = min(bounds, key=lambda t: abs(t - fl["time"]))
            rel.append(round((fl["time"] - b) * fps, 1))
    return {"count": len(visual["flashes"]), "frames_from_nearest_cut": rel,
            "on_a_cut_share": round(sum(1 for r in rel if -3 <= r <= 6) / len(rel), 2) if rel else None}


# ------------------------------------------------------------------------------------------------ persistent overlays
def detect_persistent_overlay(f: VideoFeatures) -> dict[str, Any] | None:
    """A logo bug / watermark: a small compact patch near a corner that barely changes for the whole body of the video
    while the picture around it does. A locked-off camera also has still cells, but they cover much of the frame
    (not a small corner patch) and the picture elsewhere is still too, so that is not reported. Returns the corner,
    its size as a share of the frame, and the stretch of video it was tested over; None if there isn't one."""
    n = f.n
    if n < 60:
        return None
    th = f.thumbs.astype(np.float32) / 255.0
    a, b = int(n * 0.12), int(n * 0.95)  # skip the opening/closing cards
    body = th[a:b]
    std, mean = body.std(axis=0), body.mean(axis=0)
    h, w = std.shape
    still = std < 0.035
    if float(np.median(std)) < 0.07 or still.mean() > 0.08:  # the whole picture is calm (locked-off camera), or too much of it is still to be one patch
        return None
    best = None
    for corner, (rs, cs) in {"top-left": (slice(0, max(2, h // 4)), slice(0, max(2, w // 3))), "top-right": (slice(0, max(2, h // 4)), slice(w - max(2, w // 3), w)),
                              "bottom-left": (slice(h - max(2, h // 4), h), slice(0, max(2, w // 3))), "bottom-right": (slice(h - max(2, h // 4), h), slice(w - max(2, w // 3), w))}.items():
        patch = still[rs, cs]
        if patch.sum() >= 2 and (best is None or patch.sum() > best[1]):
            best = (corner, int(patch.sum()), rs, cs)
    if best is None:
        return None
    corner, count, rs, cs = best
    outside = still.copy(); outside[rs, cs] = False
    if outside.sum() > count:  # still cells elsewhere too: not an isolated patch
        return None
    # how much of the video is it up for? a cell that is still across the body and differs from the picture before/after
    return {"corner": corner, "share_of_frame": round(count / (h * w), 3), "cells": count,
            "still_throughout_seconds": [round(float(f.times[a]), 1), round(float(f.times[b - 1]), 1)]}  # the stretch it was tested over, not a measured on-screen time


# ------------------------------------------------------------------------------------------------ camera angles
def angle_pattern(f: VideoFeatures, shots: list[dict]) -> dict[str, Any]:
    """Groups the shots into two looks (camera angles) by how the picture is laid out, and reports whether the cuts switch
    between them. A two-camera interview alternates A B A B; a one-camera jump-cut edit does not (consecutive shots look
    alike). Only meaningful when the video really has two distinct angles: `separation` says how far apart the two groups are
    compared with how much shots within a group differ (below ~1.3 the 'angles' are not distinct)."""
    if len(shots) < 6:
        return {"angles": None}
    th = f.thumbs.astype(np.float32) / 255.0
    feats = []
    for s in shots:
        i = min(int(np.searchsorted(f.times, s["mid_time"])), f.n - 1)
        v = th[i].ravel()
        feats.append(v - v.mean())
    X = np.array(feats)
    rng = np.random.default_rng(1)
    best = None
    for _ in range(20):
        cen = X[rng.choice(len(X), 2, replace=False)].copy()
        for _ in range(30):
            lab = np.argmin(((X[:, None, :] - cen[None]) ** 2).sum(-1), axis=1)
            for k in (0, 1):
                if (lab == k).any():
                    cen[k] = X[lab == k].mean(0)
        sse = float(((X - cen[lab]) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, lab.copy(), cen.copy())
    sse, lab, cen = best
    between = float(np.linalg.norm(cen[0] - cen[1]))
    within = float(np.sqrt(sse / len(X)))
    lengths = np.array([s["end"] - s["start"] for s in shots])
    # the last few shots of an edit may be fades or cards; judge alternation on the cuts between the first 90% of shots
    body = lab[: max(4, int(len(lab) * 0.9))]
    switches = float(np.mean(body[1:] != body[:-1]))
    return {"angles": 2, "labels": "".join(str(int(x)) for x in lab), "share_of_cuts_that_switch_angle": round(switches, 3),
            "separation": round(between / max(within, 1e-9), 2),
            "median_shot_seconds_by_angle": {str(k): round(float(np.median(lengths[lab == k])), 2) for k in (0, 1) if (lab == k).any()}}
