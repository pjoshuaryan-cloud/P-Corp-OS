"""
POST (2026-10-07) -- edit plan: WHEN to cut (on the music's hits, in the rhythm of a chosen style) and
WHICH clip/moment goes in each slot. The Premiere plugin builds the sequence from the plan; a preview
render lets Josh watch and hear it first.

What is solid: cut timing (every cut sits on a detected hit in the song; shot lengths and pacing come
from the style profile built from a reference edit -- see post_style.py) and the structure (an optional
establishing clip that opens the edit and returns as the closing card). What is NOT solid: which
MOMENT of a clip is used. Tests against 41 moments Josh cut by hand showed that composition, motion and
sharpness signals are no better than chance at predicting his picks, so this module places a moment from
an unvalidated source (an earlier composition pick, or a hand-set pick, or the middle of the clip) and
labels it `moment_source`; the expectation is that Josh reviews and swaps moments.

Pure functions (plan_cut_times, choose_music_window, select_clips, choose_window, build_plan) hold the
logic so they can be tested without a database or Premiere; `plan_for_job` is the I/O wrapper.
"""

import asyncio
import json
import math
import random
import hashlib
import re
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

from app.post_media import COMPOSE_MIN_START, FFMPEG_PATH
from app.post_style import StyleProfile
from app.ssd_guard import DriveNotResponding, on_drive, require_connected

MIN_SHOT_FRAMES = 3
HIT_USABLE_PERCENTILE = 55.0  # hits weaker than this are not offered as cut points
MUSIC_FADE_OUT_SECONDS = 1.5
PREVIEW_WIDTH, PREVIEW_HEIGHT = 540, 960


class EditPlanError(RuntimeError):
    pass


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def choose_music_window(hits: list[list[float]], track_seconds: float, duration: float, override_in: float | None = None) -> float:
    """Where in the song the edit starts (seconds): on a strong hit, in the stretch with the most strong
    hits. `override_in` (Josh picking a section) is snapped to the nearest strong hit within 0.3 s."""
    strong = [h for h in hits if h[1] >= 75.0]
    if override_in is not None:
        near = min(strong or hits, key=lambda h: abs(h[0] - override_in), default=None)
        return near[0] if near and abs(near[0] - override_in) <= 0.3 else override_in
    if track_seconds < duration + 0.5:
        raise EditPlanError(f"The track is {track_seconds:.0f}s but this edit needs {duration:.0f}s. Use a longer track or a shorter edit.")
    usable = [h for h in hits if h[1] >= 60.0]
    best_start, best_score = None, -1.0
    for h in strong:
        if h[0] + duration > track_seconds - 0.5:
            continue
        score = sum(u[1] / 100.0 for u in usable if h[0] <= u[0] < h[0] + duration)
        if score > best_score + 1e-9:
            best_start, best_score = h[0], score
    if best_start is None:
        raise EditPlanError("Couldn't find a strong hit to start the edit on in this track.")
    return best_start


def plan_cut_times(hits: list[list[float]], duration: float, profile: StyleProfile, rng: random.Random, opener_seconds: float | None = None) -> list[dict]:
    """Cut points (seconds from the start of the edit) in the style's rhythm, each snapped to a music hit.
    `hits` are [time_from_edit_start, strength_percentile]. Returns [{"t", "hit_pct", "on_hit"}], first at 0,
    last = where the closing card begins (or `duration` if the style has none). With `opener_seconds` the first shot is an opening-card slot:
    it ends on the strongest hit within 0.6 s of that length (off the beat at exactly that length when there is none)."""
    usable = sorted((h for h in hits if h[1] >= HIT_USABLE_PERCENTILE and 0.0 <= h[0] <= duration), key=lambda h: h[0])
    body_end = duration - profile.end_card_seconds if profile.end_card_seconds else duration

    def nearest(t: float, tol: float) -> list[float] | None:
        c = min(usable, key=lambda h: abs(h[0] - t), default=None)
        return c if c is not None and abs(c[0] - t) <= tol else None

    first = nearest(0.0, 0.05)
    cuts = [{"t": 0.0, "hit_pct": first[1] if first else None, "on_hit": first is not None}]
    end_hit = nearest(body_end, 0.3) if profile.end_card_seconds else None
    if end_hit:
        body_end = end_hit[0]
    t = 0.0
    if opener_seconds:
        near = [h for h in usable if abs(h[0] - opener_seconds) <= 0.6 and h[0] > 0.5]
        if near:
            pick = max(near, key=lambda h: (h[1] / 100.0 - 0.4 * abs(h[0] - opener_seconds), -h[0]))
            t, pct, on = pick[0], pick[1], True
        else:
            t, pct, on = opener_seconds, None, False
        cuts.append({"t": round(t, 4), "hit_pct": pct, "on_hit": on})
    mean_len = profile.mean_shot_seconds
    curve = profile.pacing_curve
    while True:
        local = curve[min(len(curve) - 1, int(min(0.999, t / duration) * len(curve)))]
        length = _clamp(rng.choice(profile.shot_lengths) * (local / mean_len), profile.min_shot_seconds, profile.max_shot_seconds)
        if t + length >= body_end - profile.min_shot_seconds:
            break
        lo, hi = t + max(profile.min_shot_seconds, 0.6 * length), t + 1.5 * length
        pool = [h for h in usable if lo <= h[0] <= hi]
        if pool:
            pick = max(pool, key=lambda h: (h[1] / 100.0 - 0.6 * abs(math.log((h[0] - t) / length)), -h[0]))
            t, pct, on = pick[0], pick[1], True
        else:
            # nothing in the window (a short shot can fall between two hits): take the next hit after the
            # minimum shot length if it isn't far past the target, else cut off-hit at the target
            nxt = min((h for h in usable if h[0] >= t + profile.min_shot_seconds), key=lambda h: h[0], default=None)
            if nxt and nxt[0] - t <= max(1.5 * length, length + 0.3):
                t, pct, on = nxt[0], nxt[1], True
            else:
                t, pct, on = t + length, None, False
        cuts.append({"t": round(t, 4), "hit_pct": pct, "on_hit": on})
    cuts.append({"t": round(body_end, 4), "hit_pct": end_hit[1] if end_hit else None, "on_hit": end_hit is not None})
    return cuts


def _scene_key(clip: dict) -> str:
    return " ".join(sorted(re.findall(r"[a-z]+", (clip.get("scene") or "").lower())))


def select_clips_by_moments(ordered: list[dict], n: int, exclude_ids: set[int]) -> list[dict]:
    """`n` clips in shoot order: the shoot is split into `n` stretches and each contributes the clip whose best
    event is strongest, with a penalty for showing the same scene as the clip chosen just before (so a series of
    near-identical clips -- five staff clapping, ten DJ angles -- doesn't fill the edit). Clips with no probed
    moments score 0, so they are still used when a stretch has nothing better."""
    pool = [c for c in ordered if c["file_id"] not in exclude_ids]
    if not pool:
        raise EditPlanError("No usable video clips to cut from.")
    if n >= len(pool):
        return [pool[i % len(pool)] for i in range(n)]
    chosen: list[dict] = []
    for i in range(n):
        a, b = round(i * len(pool) / n), max(round((i + 1) * len(pool) / n), round(i * len(pool) / n) + 1)
        bucket = pool[a:b]
        previous = _scene_key(chosen[-1]) if chosen else None

        def score(c: dict) -> float:
            best = max((e["punch"] for e in c.get("events") or []), default=0.0)
            return best - (SAME_SCENE_PENALTY if previous and _scene_key(c) == previous else 0.0)
        chosen.append(max(bucket, key=lambda c: (score(c), -pool.index(c))))
    return chosen


def select_clips(ordered: list[dict], n: int, exclude_ids: set[int]) -> list[dict]:
    """`n` clips spread evenly through the shoot (keeping shoot order), skipping `exclude_ids`.
    Re-uses clips (in order) only when there are fewer than `n`."""
    pool = [c for c in ordered if c["file_id"] not in exclude_ids]
    if not pool:
        raise EditPlanError("No usable video clips to cut from.")
    if n >= len(pool):
        return [pool[i % len(pool)] for i in range(n)]
    return [pool[round(i * (len(pool) - 1) / max(n - 1, 1))] for i in range(n)]


EVENT_LEAD_SECONDS = 0.12  # a shot starts just before its event so the action begins inside it
SAME_SCENE_PENALTY = 1.5  # punch points knocked off a clip that shows the same scene as the previous shot's clip


def _event_window(clip: dict, length: float, taken: list[tuple[float, float]], lo: float, hi: float) -> dict | None:
    """The clip's strongest event not already used, as a window starting just before it. None if the clip has
    no usable events left."""
    for e in sorted(clip.get("events") or [], key=lambda e: -e["punch"]):
        start = _clamp(e["t"] - EVENT_LEAD_SECONDS, lo, hi)
        if any(start < b and start + length > a for a, b in taken):
            continue
        return {"start": round(start, 3), "duration": round(length, 3), "source": f"event ({e['kind']}): {e['what']} -- Claude's judgment, not checked against your taste"}
    return None


def choose_window(clip: dict, length: float, taken: list[tuple[float, float]]) -> dict:
    """Source window of `length` seconds from `clip`: starting just before its strongest unused EVENT if the
    clip has probed moments; else centred on its hand-set or composition pick; else the middle of the clip.
    Moved clear of windows already used from the same clip. Never validated as Josh's taste -- `source` says
    where the moment came from."""
    dur = clip["duration"]
    length = min(length, dur)
    lo_ = min(COMPOSE_MIN_START, max(dur - length, 0.0))
    hi_ = max(dur - length - 0.04, 0.0)
    if clip.get("events"):
        w = _event_window(clip, length, taken, lo_, hi_)
        if w:
            return w
    picks = [p for p in clip.get("picks", []) if p.get("source") in ("user", "composed")]
    if picks:
        p = min(picks, key=lambda x: x.get("rank") or 99)
        centre, source = p["start"] + p["duration"] / 2.0, ("hand-set pick" if p["source"] == "user" else "composition pick (unvalidated)")
    else:
        centre, source = dur / 2.0, "middle of clip (no pick)"
    lo = min(COMPOSE_MIN_START, max(dur - length, 0.0))
    hi = max(dur - length - 0.04, 0.0)  # one frame clear of the clip's end: a subclip can't run past the last frame
    start = _clamp(centre - length / 2.0, lo, hi)
    for a, b in sorted(taken):
        if start < b and start + length > a:  # overlaps an earlier use of this clip -> try just after, else just before
            after, before = b + 0.1, a - length - 0.1
            start = after if after <= hi else (before if before >= lo else start)
    return {"start": round(start, 3), "duration": round(length, 3), "source": source}


def build_plan(
    *, profile: StyleProfile, hits: list[list[float]], music_in: float, duration: float, fps: float,
    clips: list[dict], bookend_file_id: int | None, seed: int = 7,
) -> dict[str, Any]:
    """Cut times + clip assignment, snapped to the frame grid. `hits` are song-time [t, pct]; `clips` are
    ordered [{file_id, name, path, duration, picks}]."""
    rng = random.Random(seed)
    rel_hits = [[h[0] - music_in, h[1]] for h in hits if music_in - 0.05 <= h[0] <= music_in + duration + 0.05]
    cuts = plan_cut_times(rel_hits, duration, profile, rng)
    # frame grid; drop a cut that would leave a shot under MIN_SHOT_FRAMES
    frames: list[int] = []
    kept: list[dict] = []
    for c in cuts:
        f = round(c["t"] * fps)
        if frames and f - frames[-1] < MIN_SHOT_FRAMES:
            continue
        frames.append(f)
        kept.append(c)
    total_frames = round(duration * fps)
    has_card = profile.end_card_seconds > 0 and len(frames) >= 3
    if frames[-1] >= total_frames:
        frames.pop(); kept.pop()
    n_body = len(frames) - (1 if has_card else 0)  # shots before the card; the last cut starts the card
    slots = list(zip(frames, frames[1:] + [total_frames]))
    exclude = {bookend_file_id} if bookend_file_id is not None else set()
    has_moments = any(c.get("events") for c in clips)
    chosen = (select_clips_by_moments if has_moments else select_clips)(clips, max(n_body, 1), exclude)
    by_id = {c["file_id"]: c for c in clips}
    used: dict[int, list[tuple[float, float]]] = {}
    shots: list[dict] = []
    for i, (f0, f1) in enumerate(slots):
        length = (f1 - f0) / fps
        is_card = has_card and i == len(slots) - 1
        is_opener = i == 0 and bookend_file_id is not None and bookend_file_id in by_id
        if is_card and bookend_file_id in by_id:
            clip, role = by_id[bookend_file_id], "end_card"
        elif is_opener:
            clip, role = by_id[bookend_file_id], "opener"
        else:
            clip, role = chosen[min(i, len(chosen) - 1)], ("end_card" if is_card else "body")
        # a clip too short for the slot -> take the next clip in shoot order that fits
        if clip["duration"] < length + 0.2:
            order = [c for c in clips if c["file_id"] not in exclude or role in ("opener", "end_card")]
            clip = next((c for c in order if c["duration"] >= length + 0.2), clip)
        w = choose_window(clip, length, used.get(clip["file_id"], []))
        used.setdefault(clip["file_id"], []).append((w["start"], w["start"] + w["duration"]))
        cut = kept[i]
        shots.append({
            "index": i + 1, "role": role, "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"],
            "start_frame": f0, "duration_frames": f1 - f0,
            "source_in": w["start"], "source_out": round(w["start"] + (f1 - f0) / fps, 3),
            "moment_source": w["source"], "cut_hit_percentile": cut["hit_pct"], "cut_on_hit": cut["on_hit"],
        })
    lengths = [s["duration_frames"] / fps for s in shots]
    plan = {
        "style": profile.name, "style_sources": profile.source_slugs, "fps": fps, "duration_frames": total_frames, "duration_seconds": round(total_frames / fps, 2),
        "music": {"in_seconds": round(music_in, 3), "fade_out_seconds": MUSIC_FADE_OUT_SECONDS},
        "shots": shots,
        "checks": {
            "shot_count": len(shots),
            "shot_length_median": round(statistics.median(lengths), 2), "shot_length_mean": round(statistics.mean(lengths), 2),
            "style_median": round(statistics.median(profile.shot_lengths), 2), "style_mean": round(profile.mean_shot_seconds, 2),
            "cuts_on_hits": round(sum(1 for s in shots if s["cut_on_hit"]) / len(shots), 2),
            "distinct_clips": len({s["file_id"] for s in shots}),
            "moment_sources": {k: sum(1 for s in shots if s["moment_source"].startswith(k)) for k in ("event", "composition", "hand-set", "middle")},
            "consecutive_same_scene": sum(1 for a, b in zip(shots, shots[1:]) if a["file_id"] != b["file_id"] and by_id[a["file_id"]].get("scene") and _scene_key(by_id[a["file_id"]]) == _scene_key(by_id[b["file_id"]])),
            "bookend": bookend_file_id is not None and bookend_file_id in by_id,
        },
        "notes": [
            "Cut timing follows the music's hits and the style's pacing; that part is measured against the reference.",
            "Which moment of each clip is used is NOT validated as your taste (moment_source says where it came from) -- review and swap.",
        ],
    }
    return plan


# --------------------------------------------------------------------------- I/O wrappers

def _make_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text)


async def render_preview(plan: dict[str, Any], music_wav: str, out_path: str, workdir: str) -> None:
    """Small vertical MP4 of the plan with the music, so it can be watched and heard before Premiere.
    Each shot is re-encoded to the same size/rate/length, joined without re-encoding, then the music is laid under."""
    fps = plan["fps"]
    work = Path(workdir)
    await on_drive(_make_dirs, work, writing=True)
    sem = asyncio.Semaphore(4)

    async def one(shot: dict) -> Path:
        out = work / f"shot_{shot['index']:03d}.mp4"
        async with sem:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-ss", f"{shot['source_in']:.3f}", "-i", shot["path"],
                "-frames:v", str(shot["duration_frames"]), "-an",
                "-vf", f"scale={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:force_original_aspect_ratio=decrease,pad={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-g", str(int(fps)), str(out),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
        if proc.returncode != 0 or not await on_drive(out.exists):
            raise EditPlanError(f"Preview: couldn't cut shot {shot['index']} ({shot['name']}): {err.decode(errors='replace')[:160]}")
        return out

    parts = await asyncio.gather(*(one(s) for s in plan["shots"]))
    listing = work / "concat.txt"
    await on_drive(_write_text, listing, "".join(f"file '{p}'\n" for p in parts), writing=True)
    silent = work / "joined.mp4"
    for cmd in (
        [FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)],
        [FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-i", str(silent), "-i", music_wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path],
    ):
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise EditPlanError(f"Preview: ffmpeg failed: {err.decode(errors='replace')[:200]}")
    try:
        await on_drive(shutil.rmtree, work, ignore_errors=True, writing=True)  # the per-shot temp files are no longer needed
    except DriveNotResponding:
        pass  # the preview itself is finished; leftover temp files are harmless


def plan_to_json(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=1)


# --------------------------------------------------------------------------- job-level wrapper

# Where each profile keeps music and Premiere files (see post_profiles.POST_PROFILES)
_MUSIC_FOLDER = {"joshx": "04_MUSIC", "alpha_mode": "07_MUSIC"}
_EDIT_FOLDER = {"joshx": "09_PROJECT FILES", "alpha_mode": "10_PREMIERE"}


def edit_dir(job: dict) -> Path:
    return require_connected(job["destination_root"]) / _EDIT_FOLDER[job["profile"]] / "edit_plans"   # raises DriveNotConnected when the drive isn't plugged in


def music_dir(job: dict) -> Path:
    return require_connected(job["destination_root"]) / _MUSIC_FOLDER[job["profile"]]


def _fps_from_job(job: dict) -> float:
    try:
        return float(job.get("frame_rate") or 25)
    except (TypeError, ValueError):
        return 25.0


async def load_job_clips(job_id: int, postgres_conn: Any = None, order_names: list[str] | None = None) -> list[dict]:
    """Verified video clips of a job as planner input, in shoot order (camera creation time, then name) or in the
    order of `order_names` (basenames, e.g. read off the Premiere timeline -- clips not named are left out)."""
    from app.post_db import list_post_job_file_highlights, list_post_job_file_metadata, list_post_job_files
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    meta = {m["file_id"]: m for m in await list_post_job_file_metadata(job_id, postgres_conn=postgres_conn)}
    highlights = {h["file_id"]: h for h in await list_post_job_file_highlights(job_id, postgres_conn=postgres_conn)}
    clips = []
    for f in files:
        m = meta.get(f["id"]) or {}
        if f["status"] != "verified" or m.get("media_type") != "video" or not m.get("duration_seconds"):
            continue
        h = highlights.get(f["id"])
        picks = json.loads(h["candidates_json"] or "[]") if h and h["status"] == "complete" else []
        clips.append({"file_id": f["id"], "name": f["relative_path"].split("/")[-1], "path": f["destination_path"],
                      "duration": float(m["duration_seconds"]), "created": m.get("creation_time") or "", "picks": picks})
    if order_names:
        rank = {n: i for i, n in enumerate(order_names)}
        clips = sorted((c for c in clips if c["name"] in rank), key=lambda c: rank[c["name"]])
    else:
        clips.sort(key=lambda c: (c["created"], c["name"]))
    return clips


def attach_moments(clips: list[dict], job: dict) -> list[dict]:
    """Adds probed events / scene / people (post_moments cache) to each clip that has them. In place."""
    from app.post_moments import load_moments
    known = load_moments(edit_dir(job))
    for c in clips:
        m = known.get(str(c["file_id"]))
        if m and abs(m.get("duration", 0) - c["duration"]) <= 0.05:
            c["events"], c["scene"], c["people"] = m["events"], m.get("scene", ""), m.get("people", False)
    return clips


def apply_music_lead(plan: dict[str, Any], profile: StyleProfile, music_in: float) -> float:
    """A style whose cuts sit a few frames BEFORE each hit (measured on Josh's fashion, energy-drink and furniture edits: 25-70 ms):
    the cuts stay where they are and the song starts that much earlier, so every hit lands just after its cut. Returns the song
    in-point to render and records it in the plan. Draft 01 cuts exactly on the hit: lead 0, nothing changes."""
    if not profile.cut_lead_seconds:
        return music_in
    music_in = max(0.0, music_in - profile.cut_lead_seconds)
    plan["music"]["in_seconds"] = round(music_in, 3)
    plan["music"]["cut_lead_seconds"] = profile.cut_lead_seconds
    return music_in


async def plan_for_job(
    job_id: int, *, style: list[str], music_path: str | None = None, music_in_seconds: float | None = None,
    target_seconds: float | None = None, bookend_file_id: int | None = None, order_names: list[str] | None = None,
    seed: int = 7, use_moments: bool = True, label: str | None = None, script: str | None = None,
    camera_file_ids: list[int] | None = None, audio_file_id: int | None = None,
    brand_graphics: bool = True, burn_captions: bool = True, card_tagline: str | None = None, card_contact: list[str] | None = None,
    pace: float | None = None, slow_zooms: bool = True, logo_bug: bool | None = None, fill_frame: bool | None = None, quick: bool = False, postgres_conn: Any = None,
) -> dict[str, Any]:
    """The whole thing for one job: style -> clips -> song analysis -> plan -> music cut written next to the
    project, plan saved as edit_plan_latest.json. Raises EditPlanError with a plain message when something's missing."""
    from app import post_music
    from app.post_db import get_post_job
    from app.post_style import profile_from_references
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        raise EditPlanError(f"No POST job with id {job_id}.")
    if not job.get("media_analyzed_at"):
        raise EditPlanError(f"Job #{job_id} needs Analyze Media run first.")
    try:
        profile = profile_from_references(style)
    except Exception as exc:
        raise EditPlanError(f"Couldn't load the style: {exc}") from exc
    duration = float(target_seconds or profile.target_duration_seconds)
    clips = await load_job_clips(job_id, postgres_conn, order_names)
    if not clips:
        raise EditPlanError("This job has no analysed video clips to cut from.")
    if use_moments:
        await on_drive(attach_moments, clips, job)
    if bookend_file_id is not None and bookend_file_id not in {c["file_id"] for c in clips}:
        raise EditPlanError(f"File {bookend_file_id} isn't one of this job's clips, so it can't open and close the edit.")
    if profile.dialogue is not None:  # a multicam interview: cameras lined up by sound, angle switched at quiet gaps over one dialogue track
        from app.post_edit_dialogue import plan_dialogue_for_job
        return await plan_dialogue_for_job(job, profile, clips, camera_file_ids=camera_file_ids, audio_file_id=audio_file_id, start_in_audio_clip=music_in_seconds,
                                           target_seconds=target_seconds, fps=_fps_from_job(job), seed=seed, label=label)
    fps = _fps_from_job(job)
    timeline = None
    graphics_logo = graphics_size = None
    if profile.story is not None and brand_graphics:  # an opening/closing brand card (and for a story: logo bug, caption images) need a logo and a known sequence size
        from app.post_brand_graphics import frame_size_for_job
        graphics_logo, graphics_size = await on_drive(find_logo, job), frame_size_for_job(job)
    if profile.story is not None and not profile.highlight:  # a narrated b-roll story: paced by its narration (or the style's own rhythm), not by the music's hits
        from app.post_edit_story import CALM_PACE, build_story_plan, story_timeline  # noqa: F401  (build_story_plan is used below)
        timeline = story_timeline(profile.story, fps=fps, script=script, target_seconds=duration, seed=seed, has_bookend=bookend_file_id is not None,
                                  with_opener=bookend_file_id is not None or bool(graphics_logo and graphics_size), pace=CALM_PACE if pace is None else pace)
        duration = timeline["total_seconds"]
    mdir = music_dir(job)
    song = music_path or await on_drive(post_music.find_music_file, str(mdir))
    if not song:
        raise EditPlanError(f"No music yet: put a track in {mdir} (or give me its path) and run this again.")
    try:
        analysis = await post_music.analyze_music(song)
    except post_music.MusicAnalysisError as exc:
        raise EditPlanError(str(exc)) from exc
    song = await on_drive(bring_song_into_project, song, mdir, timeout=180.0, writing=True)  # only after it decoded fine
    music_in = choose_music_window(analysis["hits"], analysis["duration"], duration, music_in_seconds)
    steady_counts = None
    if profile.highlight:  # a calm highlight cut to the music's hits: steadiest windows, slow zooms on static shots, hard cuts only
        from app.post_edit_highlight import build_highlight_plan
        from app.post_steady import CALM_PACE as _CALM, analyse_clips, coverage_note
        steady_counts = await analyse_clips(clips, job, only_cached=quick, always={bookend_file_id} if bookend_file_id is not None else None)
        plan = build_highlight_plan(profile=profile, hits=analysis["hits"], music_in=music_in, duration=duration, fps=fps, clips=clips, bookend_file_id=bookend_file_id,
                                    seed=seed, pace=_CALM if pace is None else pace, slow_zooms=slow_zooms, with_opener=bookend_file_id is not None or bool(graphics_logo and graphics_size),
                                    fill_frame=True if fill_frame is None else fill_frame)
        plan["notes"].append(f"Steadiness: {steady_counts['analysed']} clip(s) analysed now, {steady_counts['cached']} from this job's cache" + (f", {steady_counts['unreadable']} unreadable (those were planned the old way, from the middle of the clip)." if steady_counts["unreadable"] else "."))
        plan["notes"].append(coverage_note(clips, quick))
    elif timeline is not None:
        from app.post_steady import analyse_clips, coverage_note  # reads each clip at low resolution to find its steadiest window and whether it's static (cached per job)
        steady_counts = await analyse_clips(clips, job, only_cached=quick, always={bookend_file_id} if bookend_file_id is not None else None)
        plan = build_story_plan(profile=profile, timeline=timeline, music_in=music_in, fps=fps, clips=clips, bookend_file_id=bookend_file_id, seed=seed, slow_zooms=slow_zooms)
        plan["notes"].append(f"Steadiness: {steady_counts['analysed']} clip(s) analysed now, {steady_counts['cached']} from this job's cache" + (f", {steady_counts['unreadable']} unreadable (those were planned the old way, from the middle of the clip)." if steady_counts["unreadable"] else "."))
        plan["notes"].append(coverage_note(clips, quick))
    else:
        plan = build_plan(profile=profile, hits=analysis["hits"], music_in=music_in, duration=duration, fps=fps,
                          clips=clips, bookend_file_id=bookend_file_id, seed=seed)
    music_in = apply_music_lead(plan, profile, music_in)
    out_dir = edit_dir(job)
    await on_drive(_make_dirs, out_dir, mdir, writing=True)
    if (timeline is not None or profile.highlight) and brand_graphics:
        from app.post_brand_graphics import GraphicsError, GRAPHICS_SUBFOLDER, build_graphics
        if plan.get("narration"):
            plan["captions_path"] = str(out_dir / "captions.srt")
        try:
            gfx, gfx_notes = await on_drive(
                lambda: build_graphics(plan, job=job, logo_path=graphics_logo, size=graphics_size, out_dir=require_connected(job["destination_root"]) / _GRAPHICS_FOLDER[job["profile"]] / GRAPHICS_SUBFOLDER,
                                       tagline=card_tagline, contact_lines=card_contact, burn_captions=burn_captions, style_slugs=style,
                                       logo_bug=(not profile.highlight) if logo_bug is None else logo_bug),
                writing=True, timeout=240.0)
        except GraphicsError as exc:
            gfx, gfx_notes = None, [f"Brand graphics skipped: {exc}"]
        if gfx:
            plan["graphics"] = gfx
        plan["notes"].extend(gfx_notes)
    cut_path = mdir / f"{Path(song).stem}_reelcut.wav"
    try:
        await post_music.render_music_cut(song, str(cut_path), music_in, plan["duration_frames"] / fps, plan["music"].get("fade_out_seconds", MUSIC_FADE_OUT_SECONDS))
    except post_music.MusicAnalysisError as exc:
        raise EditPlanError(str(exc)) from exc
    plan["music"].update({"source": song, "cut_path": str(cut_path), "tempo_bpm": analysis["tempo_bpm"], "track_seconds": analysis["duration"]})
    plan["job_id"] = job_id
    plan["shoot_name"] = job["shoot_name"]
    await on_drive(_save_plan_files, plan, out_dir, label, timeout=30.0, writing=True)
    plan["plan_path"] = str(out_dir / "edit_plan_latest.json")
    return plan


def _save_plan_files(plan: dict[str, Any], out_dir: Path, label: str | None) -> None:
    archive_previous_plan(out_dir)  # a plan holds review decisions and accents: never overwrite one without keeping it
    if plan.get("narration"):  # a story with a narration script: write the captions beside the plan
        from app.post_edit_story import captions_srt
        (out_dir / "captions.srt").write_text(captions_srt(plan))
        plan["captions_path"] = str(out_dir / "captions.srt")
    (out_dir / "edit_plan_latest.json").write_text(plan_to_json(plan))
    if label:  # keep a named copy so two versions can be compared side by side
        (out_dir / f"edit_plan_{label}.json").write_text(plan_to_json(plan))


def archive_previous_plan(out_dir: Path) -> Path | None:
    """Copies the current edit_plan_latest.json to edit_plan_prev_<when it was made>.json. Planning again replaces
    the latest plan, and the latest plan carries the review decisions and accents, which took real time to make."""
    latest = out_dir / "edit_plan_latest.json"
    if not latest.exists():
        return None
    stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(latest.stat().st_mtime))
    dest = out_dir / f"edit_plan_prev_{stamp}.json"
    n = 2
    while dest.exists():
        dest = out_dir / f"edit_plan_prev_{stamp}_{n}.json"
        n += 1
    shutil.copyfile(latest, dest)
    return dest


def bring_song_into_project(song: str, music_folder: Path) -> str:
    """The path of the song inside the job's music folder, copying it there if it lives elsewhere (Downloads, a
    sample pack...), so the project owns it. Same name and size already there -> reuse it; same name, different
    file -> the copy gets ' (2)'."""
    src = Path(song)
    music_folder.mkdir(parents=True, exist_ok=True)
    try:
        if src.resolve().parent == music_folder.resolve():
            return str(src)
    except OSError:
        pass
    dest = music_folder / src.name
    if dest.exists():
        if dest.stat().st_size == src.stat().st_size:
            return str(dest)
        n = 2
        while dest.exists():
            dest = music_folder / f"{src.stem} ({n}){src.suffix}"
            n += 1
    shutil.copyfile(src, dest)
    return str(dest)


def _shots_fingerprint(plan: dict[str, Any]) -> str:
    """Identifies what a preview shows (which moments, where, with which music). Accents don't change it: the preview
    doesn't render them."""
    key = [[s["file_id"], s["source_in"], s["start_frame"], s["duration_frames"]] for s in plan["shots"]] + [plan["music"].get("cut_path"), plan["music"].get("in_seconds")]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:16]


def write_preview_fingerprint(job: dict, plan: dict[str, Any]) -> None:
    (edit_dir(job) / "edit_preview.json").write_text(json.dumps({"fingerprint": _shots_fingerprint(plan)}))


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def saved_plan_summary(job: dict) -> dict[str, Any] | None:
    """What the job's saved plan is, for the planning screen: size, music, opening clip, how much of it has been
    reviewed, accents, and whether the preview file still matches it. None if there is no plan."""
    folder = edit_dir(job)
    latest = folder / "edit_plan_latest.json"
    if not latest.exists():
        return None
    plan = json.loads(latest.read_text())
    review = plan.get("review") or {}
    accents = plan.get("accents")
    opener = next((s for s in plan["shots"] if s.get("role") == "opener"), None)
    checks = plan.get("checks") or {}
    preview_file, sidecar = folder / "edit_preview.mp4", folder / "edit_preview.json"
    preview = None
    if preview_file.exists():
        try:
            same = json.loads(sidecar.read_text()).get("fingerprint") == _shots_fingerprint(plan)
        except (OSError, ValueError):
            same = False  # rendered before fingerprints existed: can't tell
        preview = {"path": str(preview_file), "rendered_at": _iso(preview_file.stat().st_mtime), "up_to_date": same}
    music = plan.get("music") or {}
    return {
        "planned_at": _iso(latest.stat().st_mtime), "style": plan.get("style"), "shots": len(plan["shots"]), "seconds": plan["duration_seconds"],
        "music_name": Path(music.get("source") or "").name, "music_in_seconds": music.get("in_seconds"), "tempo_bpm": music.get("tempo_bpm"),
        "opening_clip": {"file_id": opener["file_id"], "name": opener["name"]} if opener else None,
        "checks": {k: checks.get(k) for k in ("shot_count", "shot_length_median", "style_median", "cuts_on_hits", "distinct_clips")},
        "notes": plan.get("notes") or [],
        "reviewed": len(review.get("approved", [])), "swapped": len(review.get("original", {})),
        "accents": accents.get("counts") if accents else None, "accent_notes": (accents or {}).get("notes") or [],
        "preview": preview,
    }


def list_music_files(job: dict) -> list[dict[str, Any]]:
    """Songs in the job's music folder, newest first (the reel cuts this system writes itself are left out)."""
    from app.post_music import AUDIO_EXTENSIONS
    folder = music_dir(job)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".") and "_reelcut" not in p.stem]
    files.sort(key=lambda p: -p.stat().st_mtime)
    return [{"path": str(p), "name": p.name, "megabytes": round(p.stat().st_size / 1_000_000, 1)} for p in files]


def _style_card(record: dict[str, Any]) -> dict[str, Any]:
    tags, summary = record.get("tags") or {}, record.get("summary") or {}
    title = " -- ".join(x for x in (tags.get("client"), tags.get("event")) if x) or record["slug"]
    lengths = summary.get("shot_length_seconds") or {}
    from app.post_style import friendly_style
    friendly_title, blurb = friendly_style(record["slug"], title, tags.get("style") or tags.get("genre") or "")
    return {
        "slug": record["slug"], "title": title, "friendly_title": friendly_title, "blurb": blurb,
        "description": tags.get("style") or tags.get("genre") or "", "format": tags.get("format") or "",
        "seconds": summary.get("duration_seconds"), "median_shot_seconds": lengths.get("median"), "shots": summary.get("shot_count"),
        # overlay_layers is always a dict ({"flash": 0, ...}), so test its COUNTS, not the dict itself
        "has_accents": any((summary.get("overlay_layers") or {}).values()) or bool(summary.get("effects_on_shots")),
        "edit_type": tags.get("edit_type") or "music_montage", "inferred": bool(tags.get("inferred")),
        "cut_lead_ms": (record.get("music_sync") or {}).get("cut_lead_ms"),
    }


def describe_status(job: dict, clips: list[dict]) -> dict[str, Any]:
    """How many of the clips have a description (what they show + their best moments), what describing the rest would
    cost at most, and the state of a describe run in this process. No Claude call, no database."""
    import os
    from app.post_moments import estimate_cost, load_moments, missing_clips, run_state
    missing = missing_clips(clips, load_moments(edit_dir(job)))
    return {"total": len(clips), "described": len(clips) - len(missing), "missing": len(missing), "estimate": estimate_cost(len(missing)),
            "run": run_state(job["id"]), "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}


async def edit_options(job: dict, postgres_conn: Any = None) -> dict[str, Any]:
    """Everything the planning screen offers for a job: styles, songs, clips (with what each shows, if probed),
    the logo that would be used, and the saved plan if there is one. The database part runs first; everything that reads
    the drive then happens in ONE guarded call, so a stuck drive gives a plain 503 instead of freezing the backend."""
    clips = await load_job_clips(job["id"], postgres_conn)
    return await on_drive(_options_from_drive, job, clips)


def _options_from_drive(job: dict, clips: list[dict]) -> dict[str, Any]:
    from app import post_music
    from app.post_style import available_styles
    attach_moments(clips, job)
    mdir = music_dir(job)
    return {
        "job": {"id": job["id"], "shoot_name": job["shoot_name"], "profile": job["profile"], "fps": _fps_from_job(job), "media_analyzed": bool(job.get("media_analyzed_at"))},
        "styles": [_style_card(r) for r in available_styles()],
        "music": {"folder": str(mdir), "files": list_music_files(job), "default": post_music.find_music_file(str(mdir))},
        "clips": [{"file_id": c["file_id"], "name": c["name"], "duration": round(c["duration"], 2), "scene": c.get("scene") or "", "people": c.get("people"), "has_moments": bool(c.get("events"))} for c in clips],
        "moments": {"probed": sum(1 for c in clips if c.get("events")), "total": len(clips)},
        "describe": describe_status(job, clips),
        "logo": find_logo(job),
        "saved_plan": saved_plan_summary(job),
    }


_GRAPHICS_FOLDER = {"joshx": "05_GRAPHICS", "alpha_mode": "06_GRAPHICS"}
_LOGO_EXTENSIONS = (".png", ".svg", ".webp", ".jpg", ".jpeg")


def find_logo(job: dict) -> str | None:
    """The newest logo-like image in the job's graphics folder (PNGs first, since they can be transparent), or None."""
    folder = require_connected(job["destination_root"]) / _GRAPHICS_FOLDER[job["profile"]]
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _LOGO_EXTENSIONS]
    files.sort(key=lambda p: (p.suffix.lower() != ".png", -p.stat().st_mtime))
    return str(files[0]) if files else None


async def add_accents_to_saved_plan(
    job: dict, *, style: list[str] | None = None, logo_path: str | None = None, sfx: bool = False, enabled: bool = True, seed: int = 11,
) -> dict[str, Any]:
    """Adds (or, with enabled=False, removes) accents on the job's SAVED plan, keeping its shots and any review
    decisions untouched -- accents depend only on the cut timing, so they stay valid when moments are swapped."""
    from app import post_accents
    from app.post_style import profile_from_references
    plan = await on_drive(load_saved_plan, job)
    if plan is None:
        raise EditPlanError("This job has no edit plan yet -- plan one first.")
    out = edit_dir(job) / "edit_plan_latest.json"
    if not enabled:
        plan.pop("accents", None)
        await on_drive(_write_text, out, plan_to_json(plan), writing=True)
        return {"removed": True}
    slugs = style or plan.get("style_sources") or []
    try:
        accent_style = profile_from_references(slugs).accents
    except Exception as exc:
        raise EditPlanError(f"Couldn't load the style: {exc}") from exc
    if accent_style is None:
        raise EditPlanError("This style has no accents to apply (its reference edit is hard cuts only).")
    index = None
    if sfx:
        index = post_accents.load_sfx_index() or await post_accents.build_sfx_index()
    logo = logo_path or await on_drive(find_logo, job)
    accents = post_accents.plan_accents(plan, accent_style, seed=seed, logo_path=logo, sfx_index=index)
    plan["accents"] = accents
    await on_drive(_write_text, out, plan_to_json(plan), writing=True)
    return accents


def load_saved_plan(job: dict) -> dict[str, Any] | None:
    path = edit_dir(job) / "edit_plan_latest.json"
    return json.loads(path.read_text()) if path.exists() else None
