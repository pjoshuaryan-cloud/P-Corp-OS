"""
POST (2026-10-13) -- what a finished video's SOUND says about how it was cut.

Companion to post_reference_video.py. For an exported video it answers, from the audio alone, the question a planner
actually needs: WHAT DO THE CUTS FOLLOW?
  * the music -- cuts sit on the music's hits, usually a fixed few frames BEFORE the hit (so the new picture is already
    on screen when the hit lands). Measured with a lead/lag search, and always shown next to the share a random set of
    cut times would get by luck (hit-dense music hands out a lot of luck);
  * the pauses -- a talking-head edit trims at the gaps between sentences;
  * neither -- cuts follow the pictures (a story told in b-roll, with a music bed that doesn't set the rhythm).

What it deliberately does NOT do: decide "this is speech" vs "this is music" from loudness statistics. That was tried
(pause share, syllable-rate modulation, beat peakiness) against synthetic speech, speech over a music bed and six real
tracks and it does not separate them (sparse music reads as speech, speech over a bed reads as music), so no such label
is produced. Loudness, tempo and the beat strength are reported as plain measurements.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

import numpy as np

from app import post_music as pm

FFMPEG = "/opt/homebrew/bin/ffmpeg"
RMS_HOP = 0.02  # seconds per energy frame
OFFSET_SEARCH_MS = (-150, 151, 5)  # lead/lag search range and step
OFFSET_TOLERANCE_MS = 25.0  # a cut "follows" a hit when the hit is within this of (cut + the common offset)
MIN_MUSIC_LIFT = 1.8  # share on the hits must beat chance by at least this factor (random cuts score ~1.45 after the offset search picks its best) ...
MIN_MUSIC_SHARE = 0.5  # ... and be at least this large
MIN_PAUSE_LIFT = 1.6
MIN_PAUSE_SHARE = 0.7


def decode_audio(path: str, sr: int = pm.SAMPLE_RATE) -> np.ndarray:
    out = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, timeout=1800)
    if out.returncode != 0 or not out.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(out.stdout, dtype=np.float32)


def loudness(path: str) -> dict[str, float | None]:
    """Integrated loudness (LUFS), loudness range and true peak, from ffmpeg's EBU R128 meter."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, timeout=1800)
    summary = out.stderr.split("Summary:")[-1]
    grab = lambda label: (lambda m: float(m.group(1)) if m else None)(re.search(label + r":\s+(-?[0-9.]+)", summary))
    return {"integrated_lufs": grab("I"), "range_lu": grab("LRA"), "true_peak_dbfs": grab("Peak")}


def _frame_rms_db(samples: np.ndarray, sr: int) -> np.ndarray:
    hop = int(sr * RMS_HOP)
    n = len(samples) // hop
    if n == 0:
        return np.full(1, -90.0)
    return 20 * np.log10(np.sqrt((samples[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12) + 1e-9)


def _share_near(times: np.ndarray, ref: np.ndarray, shift: float, tol: float) -> float | None:
    """Share of `times` that have an element of `ref` within tol of (time + shift)."""
    if len(times) == 0 or len(ref) == 0:
        return None
    t = times + shift
    idx = np.searchsorted(ref, t)
    lo = ref[np.clip(idx - 1, 0, len(ref) - 1)]
    hi = ref[np.clip(idx, 0, len(ref) - 1)]
    return float(np.mean(np.minimum(np.abs(t - lo), np.abs(hi - t)) <= tol))


def music_sync(cuts: np.ndarray, hit_t: np.ndarray, duration: float, fps: float) -> dict[str, Any]:
    """Do the cuts sit on the hits, and at what lead/lag? Searches the common offset that puts the most cuts on a hit,
    and reports that share beside the share a random set of times gets at the SAME offset."""
    rng = np.random.default_rng(7)
    rand = rng.uniform(0.5, max(0.6, duration - 0.5), 6000)
    lo, hi, step = OFFSET_SEARCH_MS
    shares = {}
    for ms in range(lo, hi, step):
        value = _share_near(cuts, hit_t, ms / 1000.0, OFFSET_TOLERANCE_MS / 1000.0)
        if value is not None:
            shares[ms] = value
    if not shares:
        return {"hits_per_second": round(len(hit_t) / duration, 2), "best_offset_ms": 0, "best_offset_frames": 0.0, "share_on_hits_at_that_offset": 0.0, "chance_at_that_offset": None, "lift": None,
                "within_tolerance_ms": OFFSET_TOLERANCE_MS, "share_at_zero_offset": 0.0}
    top = max(shares.values())
    plateau = [ms for ms, v in shares.items() if v >= top - 1e-9]  # a +-tolerance window gives a flat top: report its CENTRE, not its first edge
    ms = int(round(float(np.mean(plateau)) / step) * step)
    share = shares.get(ms, top)
    chance = _share_near(rand, hit_t, ms / 1000.0, OFFSET_TOLERANCE_MS / 1000.0)
    lift = (share / chance) if chance else None
    return {"hits_per_second": round(len(hit_t) / duration, 2),
            "best_offset_ms": ms, "best_offset_frames": round(ms / 1000.0 * fps, 2),  # + = the hit lands AFTER the cut
            "share_on_hits_at_that_offset": round(share, 3), "chance_at_that_offset": round(chance, 3) if chance is not None else None,
            "lift": round(lift, 2) if lift else None,
            "within_tolerance_ms": OFFSET_TOLERANCE_MS,
            "share_at_zero_offset": round(_share_near(cuts, hit_t, 0.0, OFFSET_TOLERANCE_MS / 1000.0) or 0.0, 3)}


def pause_sync(cuts: np.ndarray, db: np.ndarray, duration: float) -> dict[str, Any]:
    """Share of cuts that fall in (or within 0.15 s of) a quiet gap, against the share of random times that do."""
    quiet = db < (np.percentile(db, 95) - 24.0)
    k = int(0.15 / RMS_HOP)
    near = lambda t: bool(quiet[max(0, int(t / RMS_HOP) - k): int(t / RMS_HOP) + k + 1].any())
    rand = np.random.default_rng(7).uniform(0.5, max(0.6, duration - 0.5), 4000)
    real = float(np.mean([near(t) for t in cuts])) if len(cuts) else None
    chance = float(np.mean([near(t) for t in rand]))
    return {"share_in_quiet_gap": None if real is None else round(real, 3), "chance": round(chance, 3),
            "lift": round(real / chance, 2) if real is not None and chance else None, "quiet_share_of_time": round(float(quiet.mean()), 3)}


def decide_driver(sync: dict[str, Any], pause: dict[str, Any], cut_count: int) -> dict[str, Any]:
    """What the cuts follow, with the numbers that decided it. Few cuts (< 12) = 'not enough cuts to tell'."""
    if cut_count < 12:
        return {"cuts_follow": "unclear", "why": f"only {cut_count} cuts -- not enough to tell what they follow"}
    music = sync.get("lift") and sync["lift"] >= MIN_MUSIC_LIFT and sync["share_on_hits_at_that_offset"] >= MIN_MUSIC_SHARE
    pauses = pause.get("lift") and pause["lift"] >= MIN_PAUSE_LIFT and (pause["share_in_quiet_gap"] or 0) >= MIN_PAUSE_SHARE
    if music and not (pauses and pause["lift"] > sync["lift"]):
        return {"cuts_follow": "music", "why": f"{sync['share_on_hits_at_that_offset']:.0%} of cuts sit on a hit at a {sync['best_offset_ms']:+d} ms offset vs {sync['chance_at_that_offset']:.0%} by chance ({sync['lift']}x)"}
    if pauses:
        return {"cuts_follow": "pauses", "why": f"{pause['share_in_quiet_gap']:.0%} of cuts fall in or within 0.15 s of a quiet gap vs {pause['chance']:.0%} by chance ({pause['lift']}x)"}
    return {"cuts_follow": "pictures", "why": f"cuts line up with neither the music ({sync.get('lift')}x chance) nor the pauses ({pause.get('lift')}x chance)"}


def analyze_audio(path: str, cut_times: list[float], fps: float) -> dict[str, Any]:
    """Loudness, tempo, what the cuts follow, how the sound opens and closes."""
    samples = decode_audio(path)
    sr = pm.SAMPLE_RATE
    if len(samples) < sr * 2:
        return {"has_audio": False}
    duration = len(samples) / sr
    db = _frame_rms_db(samples, sr)
    onset = pm._onset_strength(samples)
    try:
        bpm, beat_strength = pm._estimate_tempo(onset)
    except Exception:
        bpm, beat_strength = None, 0.0
    hits = pm._pick_hits(onset)
    hit_t = np.array(sorted(h[0] for h in hits))
    strong_t = np.array(sorted(h[0] for h in hits if h[1] >= 90.0))
    cuts = np.array([c for c in cut_times if 0.3 < c < duration - 0.3])
    sync_any = music_sync(cuts, hit_t, duration, fps)
    sync_strong = music_sync(cuts, strong_t, duration, fps) if len(strong_t) else None
    pause = pause_sync(cuts, db, duration)
    driver = decide_driver(sync_any, pause, len(cuts))
    edge = int(2.0 / RMS_HOP)
    body = float(np.mean(db))
    return {
        "has_audio": True, "duration": round(duration, 2), "tempo_bpm": round(float(bpm), 1) if bpm else None, "beat_strength": round(float(beat_strength), 3),
        "music_sync_any_hit": sync_any, "music_sync_strong_hit": sync_strong, "pause_sync": pause, **driver,
        "opens_db_vs_body": round(float(np.mean(db[:edge])) - body, 1), "closes_db_vs_body": round(float(np.mean(db[-edge:])) - body, 1),
        "loudness": loudness(path),
    }


# ------------------------------------------------------------------------------------------------ where cuts sit in the speech
QUIET_DEPTH_DB = 24.0  # a gap is "quiet" when the level is this far below the loud speech (95th percentile)


def quiet_runs(db: np.ndarray, hop: float, depth_db: float = QUIET_DEPTH_DB) -> list[tuple[float, float]]:
    """[(start_seconds, end_seconds)] of every stretch where the level sits `depth_db` below the loud speech."""
    quiet = db < (np.percentile(db, 95) - depth_db)
    runs, a = [], None
    for i, v in enumerate(quiet):
        if v and a is None:
            a = i
        if (not v) and a is not None:
            runs.append((a * hop, i * hop)); a = None
    if a is not None:
        runs.append((a * hop, len(quiet) * hop))
    return runs


def pause_cut_stats(path: str, cut_times: list[float]) -> dict[str, Any]:
    """How cuts sit relative to the quiet gaps in the speech: the share inside (or within 0.15 s of) one, how far along the
    gap they land, how long the gaps are, how often a quiet gap occurs at all. Read from the export's own audio."""
    samples = decode_audio(path)
    if len(samples) < pm.SAMPLE_RATE * 5:
        return {}
    db = _frame_rms_db(samples, pm.SAMPLE_RATE)
    runs = quiet_runs(db, RMS_HOP)
    duration = len(samples) / pm.SAMPLE_RATE
    cuts = [c for c in cut_times if 0.3 < c < duration - 0.3]
    inside, positions, lengths, near = 0, [], [], 0
    for c in cuts:
        hit = next((r for r in runs if r[0] <= c <= r[1]), None)
        if hit:
            inside += 1; positions.append((c - hit[0]) / max(hit[1] - hit[0], 1e-6)); lengths.append(hit[1] - hit[0])
        if any(r[0] - 0.15 <= c <= r[1] + 0.15 for r in runs):
            near += 1
    gl = np.array([b - a for a, b in runs]) if runs else np.array([0.0])
    return {"quiet_depth_db": QUIET_DEPTH_DB, "cuts": len(cuts), "cuts_inside_a_quiet_gap": round(inside / max(len(cuts), 1), 3), "cuts_within_0_15s_of_a_quiet_gap": round(near / max(len(cuts), 1), 3),
            "position_in_gap_median": round(float(np.median(positions)), 2) if positions else None, "gap_seconds_at_cuts_median": round(float(np.median(lengths)), 3) if lengths else None,
            "quiet_gaps_per_second": round(len(runs) / duration, 2), "quiet_gap_seconds_median": round(float(np.median(gl)), 3), "quiet_gap_seconds_p90": round(float(np.percentile(gl, 90)), 3)}
