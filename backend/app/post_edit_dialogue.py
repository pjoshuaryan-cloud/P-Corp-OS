"""
POST (2026-10-13) -- edit plan for a MULTICAM INTERVIEW / TALKING HEAD (Josh's dialogue-led edit type).

Read off Josh's talking-head reference ("THE BEANCOUNTER", see post_reference_video.py; the numbers live in
post_style.DialogueStyle): two camera angles of one man talking, switching angle at EVERY cut (18 of 18), a cut about every
15 s (takes of 9-65 s), each cut inside or beside a quiet gap in the speech and ~70% of the way through it, a quicker run of
3-7 s takes in the last ~6%, then a held closing shot with the logo card. The picture switches angle; the dialogue never cuts.

How the plan is made:
  1. the cameras are lined up by their sound (post_sync.py) -- cameras that heard the same speech get a lag relative to the first;
  2. the stretch of the interview to use is chosen (default: from the first real speech) and kept inside every camera's footage;
  3. cut times are laid out in the style's rhythm and each is moved to the nearest good quiet gap in the dialogue;
  4. cameras alternate shot by shot; each shot plays the SAME moment from its camera (source in = interview time + that camera's lag);
  5. one dialogue track (the dialogue camera's own audio) is rendered for the whole stretch with a fade-out and goes under the picture.

Same plan format as the other planners (video-only shots + one audio file), so the preview render, the review step (which here
swaps ANGLE, never moment) and the Premiere plugin's Assemble Edit work on it unchanged.

NOT done: removing pauses, flubs or fillers (the dialogue runs continuous -- cutting content is an editorial call); the closing
card and fade; a separate microphone track; several files per camera.
"""

from __future__ import annotations

import random
import statistics
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from app import post_music, post_sync
from app.post_edit_plan import EditPlanError, MIN_SHOT_FRAMES, _make_dirs, _save_plan_files, edit_dir, music_dir
from app.post_reference_audio import RMS_HOP, QUIET_DEPTH_DB, _frame_rms_db, quiet_runs
from app.post_style import DialogueStyle, StyleProfile
from app.ssd_guard import on_drive

ANALYSIS_RATE = 16000
MIN_TAKE_SECONDS = 2.0  # no take shorter than this, however the gaps fall
MIN_EDIT_SECONDS = 20.0
SEARCH_SECONDS = 3.0  # how far from its target time a cut may move to find a good gap
MIN_CLEAR_GAP_SECONDS = 0.06  # a gap shorter than this sits at the edge of 'quiet' and different measurements disagree about it
START_MARGIN = 0.5  # stay this far inside the footage of every camera
DRIFT_NOTE_SECONDS = 0.045  # more than about a frame of change in the offset along the take is reported
DRIFT_REFUSE_SECONDS = 0.35


# ------------------------------------------------------------------------------------------------------------ the audio
def decode_range(path: str, start: float, seconds: float, sr: int = ANALYSIS_RATE) -> np.ndarray:
    cmd = [post_sync.FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=600)
    return np.frombuffer(out.stdout, dtype=np.float32) if out.returncode == 0 and out.stdout else np.zeros(0, dtype=np.float32)


def first_speech_seconds(db: np.ndarray, hop: float = RMS_HOP, sustain: float = 1.0) -> float | None:
    """The first moment the level stays within 20 dB of the loud speech for `sustain` seconds (the interview proper starts;
    the chatter and clapper before it are usually quieter or shorter)."""
    loud = db > (np.percentile(db, 95) - 20.0)
    need = int(sustain / hop)
    run = 0
    for i, v in enumerate(loud):
        run = run + 1 if v else 0
        if run >= need:
            return round((i - need + 1) * hop, 2)
    return None


def pick_cut(target: float, runs: list[tuple[float, float]], db: np.ndarray, earliest: float, latest: float, position: float, window: float, min_gap: float = 0.0) -> dict[str, Any]:
    """The cut time nearest `target` (within +-window) that sits in a quiet gap, preferring longer gaps (a sentence end) and
    nearer ones; landing `position` of the way through the gap. With no quiet gap in reach, the quietest instant instead."""
    best, best_score = None, -1e9
    for a, b in runs:
        mid = (a + b) / 2
        if not (target - window <= mid <= target + window) or b - a < min_gap:
            continue
        t = a + position * (b - a)
        if not (earliest <= t <= latest):
            continue
        score = min(b - a, 0.8) - 0.05 * abs(mid - target)
        if score > best_score:
            best, best_score = {"t": t, "in_gap": True, "gap_seconds": round(b - a, 3)}, score
    if best:
        return best
    lo, hi = max(int(max(earliest, target - window) / RMS_HOP), 0), min(int(min(latest, target + window) / RMS_HOP), len(db) - 1)
    if hi <= lo:
        return {"t": min(max(target, earliest), latest), "in_gap": False, "gap_seconds": None}
    i = lo + int(np.argmin(db[lo:hi + 1]))
    return {"t": i * RMS_HOP, "in_gap": False, "gap_seconds": None}


def pick_cut_widening(target: float, runs: list[tuple[float, float]], db: np.ndarray, earliest: float, latest: float, position: float, take_seconds: float) -> dict[str, Any]:
    """pick_cut, looking further from the target when no quiet gap is close: +-3 s (at most 30% of the take), then +-6 s (50%), then
    +-10 s (70%); only after all three is the quietest instant used. The reference puts every cut at a quiet gap."""
    for min_gap in (MIN_CLEAR_GAP_SECONDS, 0.0):  # first only unambiguous gaps, then (if there are none in reach at all) any gap at all
        for reach, share in ((SEARCH_SECONDS, 0.3), (2 * SEARCH_SECONDS, 0.5), (10.0, 0.7)):
            cut = pick_cut(target, runs, db, earliest, latest, position, min(reach, share * take_seconds), min_gap)
            if cut["in_gap"]:
                return cut
    return cut


def target_lengths(style: DialogueStyle, total: float, rng: random.Random) -> list[float]:
    """Shot lengths in the style's rhythm: takes drawn from the body lengths (capped for a short edit), then the quicker run
    the reference has near its end, the last shot at least as long as the closing hold. They sum to `total`."""
    tail_total = style.tail_fraction * total if total >= 120 else 0.0
    cap = max(6.0, 0.4 * total)
    lengths: list[float] = []
    used = 0.0
    while used < total - tail_total - MIN_TAKE_SECONDS:
        L = min(rng.choice(style.body_lengths), cap)
        if used + L > total - tail_total:
            L = total - tail_total - used
        if L < MIN_TAKE_SECONDS and lengths:
            lengths[-1] += L  # a sliver is folded into the take before it
        else:
            lengths.append(L)
        used += L
    left = total - sum(lengths)
    while left > style.closing_hold_seconds + MIN_TAKE_SECONDS and tail_total > 0:
        L = min(rng.choice(style.tail_lengths), left - style.closing_hold_seconds)
        if L < MIN_TAKE_SECONDS:
            break
        lengths.append(L)
        left -= L
    lengths.append(left)
    if len(lengths) > 1 and lengths[-1] < style.closing_hold_seconds:  # the last shot holds at least the closing hold
        lengths[-2] -= style.closing_hold_seconds - lengths[-1]
        lengths[-1] = style.closing_hold_seconds
    return lengths


# ----------------------------------------------------------------------------------------------------------- the analysis
def analyse_cameras(cams: list[dict[str, Any]], audio_idx: int, start_in_audio_clip: float | None, target_seconds: float) -> dict[str, Any]:
    """Blocking: sync the cameras, find the usable stretch, read the dialogue's quiet gaps. Raises EditPlanError."""
    paths = [c["path"] for c in cams]
    try:
        synced = post_sync.sync_cameras(paths)
    except post_sync.SyncError as exc:
        raise EditPlanError(str(exc)) from exc
    lags = [s["lag_seconds"] for s in synced]
    durations = [c["duration"] for c in cams]
    t_lo = max(-L for L in lags)
    t_hi = min(d - L for d, L in zip(durations, lags))
    if t_hi - t_lo < MIN_EDIT_SECONDS + 2 * START_MARGIN:
        raise EditPlanError(f"All {len(cams)} cameras only overlap for {max(0.0, t_hi - t_lo):.0f} seconds once they are lined up, which is too short to cut (need at least {MIN_EDIT_SECONDS:.0f}). "
                            "Check that these are all the same interview.")
    L_a = lags[audio_idx]
    # first real speech, read from the dialogue camera (its first 10 minutes)
    probe_start = max(0.0, t_lo + L_a)
    probe = decode_range(cams[audio_idx]["path"], probe_start, min(600.0, t_hi - t_lo))
    speech = first_speech_seconds(_frame_rms_db(probe, ANALYSIS_RATE)) if len(probe) > ANALYSIS_RATE * 5 else None
    first_speech_t = (probe_start + speech - L_a) if speech is not None else None  # in reference-camera time
    if start_in_audio_clip is not None:
        t0 = start_in_audio_clip - L_a
        if t0 < t_lo + START_MARGIN:
            raise EditPlanError(f"The interview can't start at {start_in_audio_clip:.1f} s in the dialogue camera: not every camera has footage that early (earliest is {t_lo + L_a + START_MARGIN:.1f} s there).")
    else:
        t0 = max(t_lo + START_MARGIN, (first_speech_t - 0.6) if first_speech_t is not None else t_lo + START_MARGIN)
    room = t_hi - START_MARGIN - t0
    if room < MIN_EDIT_SECONDS:
        raise EditPlanError(f"Only {room:.0f} seconds of the interview are left after that start; need at least {MIN_EDIT_SECONDS:.0f}.")
    total = min(target_seconds, room)
    audio = decode_range(cams[audio_idx]["path"], t0 + L_a, total + 1.0)
    if len(audio) < ANALYSIS_RATE * 5:
        raise EditPlanError(f"{cams[audio_idx]['name']} has no usable audio in that stretch, so there is no dialogue to cut to.")
    db = _frame_rms_db(audio, ANALYSIS_RATE)
    runs = quiet_runs(db, RMS_HOP, QUIET_DEPTH_DB)
    # does any camera drift against the first along the stretch?
    drift: list[dict[str, Any]] = []
    for k in range(1, len(cams)):
        pts = [t0 + 10.0, t0 + total / 2, t0 + max(10.0, total - 60.0)]
        meas = post_sync.check_drift(paths[0], paths[k], lags[k], pts)
        good = [m for m in meas if m["confidence"] >= post_sync.MIN_CONFIDENCE]
        if len(good) >= 2:
            drift.append({"camera": cams[k]["name"], "change_seconds": round(max(m["lag_seconds"] for m in good) - min(m["lag_seconds"] for m in good), 3), "points": good})
    return {"synced": synced, "lags": lags, "t_lo": t_lo, "t_hi": t_hi, "t0": t0, "total": total, "first_speech_ref_time": first_speech_t, "db": db, "runs": runs, "drift": drift}


# -------------------------------------------------------------------------------------------------------------- the plan
def build_dialogue_plan(*, profile: StyleProfile, cams: list[dict[str, Any]], audio_idx: int, info: dict[str, Any], fps: float, seed: int = 7) -> dict[str, Any]:
    style = profile.dialogue
    if style is None:
        raise EditPlanError(f"'{profile.name}' isn't a talking-head style.")
    rng = random.Random(seed)
    total = info["total"]
    lengths = target_lengths(style, total, rng)
    runs, db, lags = info["runs"], info["db"], info["lags"]
    # cut times (seconds from the start of the edit), each moved to a quiet gap near its target
    cuts: list[dict[str, Any]] = [{"t": 0.0, "in_gap": None, "gap_seconds": None}]
    acc = 0.0
    for i, L in enumerate(lengths[:-1]):
        acc += L
        earliest = cuts[-1]["t"] + MIN_TAKE_SECONDS
        latest = total - style.closing_hold_seconds if i == len(lengths) - 2 else total - MIN_TAKE_SECONDS
        if latest <= earliest:
            break
        cuts.append(pick_cut_widening(acc, runs, db, earliest, latest, style.cut_position_in_gap, L))
        acc = cuts[-1]["t"]  # the next take is measured from where this cut really landed
    # frame grid (round, never closer than MIN_SHOT_FRAMES)
    total_frames = round(total * fps)
    frames = [0]
    for c in cuts[1:]:
        f = round(c["t"] * fps)
        if f - frames[-1] >= max(MIN_SHOT_FRAMES, round(MIN_TAKE_SECONDS * fps)) and total_frames - f >= round(MIN_TAKE_SECONDS * fps):
            frames.append(f)
    kept_cuts = [c for c in cuts]  # for the checks below
    bounds = frames + [total_frames]
    t0 = info["t0"]
    n_cam = len(cams)
    shots: list[dict[str, Any]] = []
    previous = -1
    for i, (f0, f1) in enumerate(zip(bounds, bounds[1:])):
        k = (previous + 1) % n_cam  # round robin: with two cameras, strict alternation (never the same angle twice running)
        previous = k
        cam = cams[k]
        start_sec = f0 / fps
        src_in = round(t0 + start_sec + lags[k], 3)
        role = "end_card" if i == len(bounds) - 2 else "body"
        shots.append({
            "index": i + 1, "role": role, "file_id": cam["file_id"], "name": cam["name"], "path": cam["path"],
            "start_frame": f0, "duration_frames": f1 - f0, "source_in": src_in, "source_out": round(src_in + (f1 - f0) / fps, 3),
            "moment_source": f"{cam['name']} at interview time {t0 + start_sec:.1f} s (synced)", "cut_hit_percentile": None, "cut_on_hit": False, "angle": k,
        })
    cut_marks = [c for c in cuts[1:len(bounds) - 1]]
    in_gap = [c for c in cut_marks if c["in_gap"]]
    L = [s["duration_frames"] / fps for s in shots]
    a = cams[audio_idx]
    fade = round(min(3.0, max(1.5, 0.6 * style.closing_hold_seconds)), 2)
    notes = [
        "The picture switches camera angle at quiet gaps in the dialogue; the dialogue itself is one continuous track and is NOT cut. Pauses, flubs and fillers are still in it -- trim those by hand.",
        f"Cameras are lined up by their sound (the first camera is the reference). Dialogue comes from {a['name']}'s own audio.",
        "Not placed: the closing card and fade. The last shot is held long enough to put one on.",
        "In the review step, a shot's alternatives are the OTHER cameras at the same moment (angle swaps), never a different moment.",
    ]
    for d in info["drift"]:
        if d["change_seconds"] >= DRIFT_NOTE_SECONDS:
            notes.append(f"{d['camera']} drifts about {d['change_seconds'] * 1000:.0f} ms against the first camera along this stretch, so later angle cuts may be a frame or two off.")
    return {
        "mode": "multicam", "style": profile.name, "style_sources": profile.source_slugs, "fps": fps, "duration_frames": total_frames, "duration_seconds": round(total_frames / fps, 2),
        "music": {"in_seconds": round(t0 + lags[audio_idx], 3), "fade_out_seconds": fade, "label": "dialogue"},
        "cameras": [{"file_id": c["file_id"], "name": c["name"], "lag_seconds": lags[i], "sync_confidence": info["synced"][i]["confidence"], "dialogue": i == audio_idx} for i, c in enumerate(cams)],
        "dialogue": {"audio_file_id": a["file_id"], "starts_at_interview_seconds": round(t0, 2), "first_speech_interview_seconds": None if info["first_speech_ref_time"] is None else round(info["first_speech_ref_time"], 2),
                     "overlap_seconds": round(info["t_hi"] - info["t_lo"], 1), "drift": info["drift"]},
        "shots": shots,
        "checks": {
            "shot_count": len(shots), "shot_length_median": round(statistics.median(L), 2), "shot_length_mean": round(statistics.mean(L), 2),
            "style_median": round(statistics.median(style.body_lengths), 2), "style_mean": round(statistics.mean(style.body_lengths), 2),
            "cuts_on_hits": None, "distinct_clips": len({s["file_id"] for s in shots}), "bookend": False,
            "cuts_in_quiet_gap": round(len(in_gap) / len(cut_marks), 2) if cut_marks else None,
            "angle_switches": 1.0 if all(a_["angle"] != b_["angle"] for a_, b_ in zip(shots, shots[1:])) else round(sum(1 for a_, b_ in zip(shots, shots[1:]) if a_["angle"] != b_["angle"]) / max(len(shots) - 1, 1), 2),
            "moment_sources": {"event": 0, "composition": 0, "hand-set": 0, "middle": 0}, "consecutive_same_scene": 0,
        },
        "notes": notes,
    }


# -------------------------------------------------------------------------------------------------------------- the job
async def plan_dialogue_for_job(job: dict, profile: StyleProfile, clips: list[dict], *, camera_file_ids: list[int] | None, audio_file_id: int | None,
                                start_in_audio_clip: float | None, target_seconds: float | None, fps: float, seed: int, label: str | None) -> dict[str, Any]:
    if not camera_file_ids or len(set(camera_file_ids)) < profile.dialogue.min_cameras:
        raise EditPlanError("A talking-head edit switches between camera angles: pick at least two clips that filmed the same interview.")
    ids = list(dict.fromkeys(camera_file_ids))
    by_id = {c["file_id"]: c for c in clips}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise EditPlanError(f"File(s) {missing} aren't verified video clips of this job, so they can't be used as cameras.")
    cams = [dict(by_id[i]) for i in ids]
    if audio_file_id is not None and audio_file_id not in ids:
        raise EditPlanError("The dialogue has to come from one of the cameras you picked.")
    audio_idx = ids.index(audio_file_id) if audio_file_id is not None else 0
    target = float(target_seconds or profile.target_duration_seconds)
    info = await on_drive(analyse_cameras, cams, audio_idx, start_in_audio_clip, target, timeout=420.0)
    worst = max((d["change_seconds"] for d in info["drift"]), default=0.0)
    if worst >= DRIFT_REFUSE_SECONDS:
        raise EditPlanError(f"One camera drifts {worst:.2f} s against the first over this stretch (different clocks), which is too much to cut between without re-syncing. Use a shorter stretch or sync the clips in Premiere first.")
    plan = build_dialogue_plan(profile=profile, cams=cams, audio_idx=audio_idx, info=info, fps=fps, seed=seed)
    out_dir, mdir = edit_dir(job), music_dir(job)
    await on_drive(_make_dirs, out_dir, mdir, writing=True)
    audio_clip = cams[audio_idx]
    cut_path = mdir / f"{Path(audio_clip['name']).stem}_dialogue.wav"
    try:
        await post_music.render_music_cut(audio_clip["path"], str(cut_path), plan["music"]["in_seconds"], plan["duration_frames"] / fps, plan["music"]["fade_out_seconds"])
    except post_music.MusicAnalysisError as exc:
        raise EditPlanError(str(exc)) from exc
    plan["music"].update({"source": audio_clip["path"], "cut_path": str(cut_path), "tempo_bpm": None, "track_seconds": audio_clip["duration"]})
    plan["job_id"] = job["id"]
    plan["shoot_name"] = job["shoot_name"]
    await on_drive(_save_plan_files, plan, out_dir, label, timeout=30.0, writing=True)
    plan["plan_path"] = str(out_dir / "edit_plan_latest.json")
    return plan
