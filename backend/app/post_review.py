"""
POST (2026-10-08) -- the review step of an edit plan.

Why: nothing measurable predicts which moment of a clip Josh picks (composition, motion, pixel events and
Claude's idea of a "punchy moment" were all at chance against his hand cuts), so the plan can only be a good
first draft. This lets him fix it quickly: for every slot of the plan he sees the current moment and a few
alternatives (other events of the same clip, strong events from neighbouring clips) and picks one. Cut
timing never changes -- only WHICH clip/moment fills a slot.

Every decision (what he picked, what he passed over, with each candidate's features) is appended to a log,
so his taste accumulates as real labelled data for later jobs instead of being guessed.

Pure functions (build_review, apply_choice, log_record) so they can be tested without a server.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app import post_pick
from app.post_media import COMPOSE_MIN_START, FFMPEG_PATH
from app.post_edit_plan import EVENT_LEAD_SECONDS, _clamp, _scene_key
from app.ssd_guard import on_drive

MIN_PREVIEW_SECONDS = 0.8  # a 0.12 s shot can't be judged by eye: the review clip shows at least this much
NEIGHBOURHOOD = 6  # how many clips either side (in shoot order) count as "the same stretch" for alternatives
SAME_CLIP_ALTERNATIVES = 2
SAME_CLIP_MIN_GAP_SECONDS = 2.0  # another event from the SAME clip must be a clearly different moment, not 1 s along the same action
OTHER_CLIP_ALTERNATIVES = 2
_CLIP_RENDER_LIMIT = asyncio.Semaphore(3)

# Slow motion (2026-10-21). A slowed shot keeps its slot on the timeline (cut timing never changes), so at speed 0.5 it shows HALF as much source: the window
# [source_in, source_out) is duration * speed long, centred where the real-time window was. The real-time window is kept in `speed_original` so the toggle can be undone exactly.
# Only 48+ fps clips qualify (he slows 41% of those and 1.5% of 24-31 fps clips: half-speed footage needs twice the frames to stay smooth).
SLOW_SPEED = 0.5
SLOW_SPEEDS = (1.0, SLOW_SPEED)
SLOW_MIN_CLIP_SLACK_SECONDS = 0.05


class ReviewError(RuntimeError):
    pass


_ALTERNATIVES_CACHE: dict[tuple, dict[int, list[dict[str, Any]]]] = {}  # picker alternatives are the slow part of a review: kept for as long as the plan is unchanged


def _is_steady_plan(plan: dict[str, Any], clips: list[dict]) -> bool:
    """A corporate plan (narrated story or highlight) whose clips have been analysed: swaps come from the picker, not from Claude's event list."""
    return plan.get("mode") in ("highlight", "story") and any(c.get("steady") for c in clips)


def _picker_alternatives(plan: dict[str, Any], clips: list[dict]) -> dict[int, list[dict[str, Any]]]:
    key = (tuple((s["file_id"], round(s["source_in"], 3), s["duration_frames"]) for s in plan["shots"]), tuple(sorted(c["file_id"] for c in clips if c.get("steady"))))
    if key not in _ALTERNATIVES_CACHE:
        if len(_ALTERNATIVES_CACHE) >= 4:
            _ALTERNATIVES_CACHE.pop(next(iter(_ALTERNATIVES_CACHE)))
        _ALTERNATIVES_CACHE[key] = post_pick.alternatives(plan, clips)
    return _ALTERNATIVES_CACHE[key]


def shot_speed(shot: dict[str, Any]) -> float:
    """1.0 = real time. Plans made before this existed have no `speed`."""
    return float(shot.get("speed") or 1.0)


def slow_check(plan: dict[str, Any], clip: dict | None, shot: dict[str, Any]) -> tuple[bool, str | None]:
    """(can this shot be slowed to half speed, why not in plain words -- None when the shot isn't one that is ever offered slow motion)."""
    if plan.get("mode") == "multicam":
        return False, None   # an interview's timing is set by the dialogue
    if shot.get("role") != "body":
        return False, None   # opening and closing cards
    fps = (clip or {}).get("fps")
    if not fps:
        return False, "Slow motion needs the clip's frame rate: run Analyze Media again."
    if fps * SLOW_SPEED < plan["fps"] - 0.5:
        return False, f"This clip is {fps:g} fps; at half speed it would play at {fps * SLOW_SPEED:g} fps in a {plan['fps']:g} fps edit and stutter."
    window = shot["duration_frames"] / plan["fps"]
    if window * SLOW_SPEED > clip["duration"] - SLOW_MIN_CLIP_SLACK_SECONDS:
        return False, "This clip is too short to cut a slow-motion shot from."
    return True, None


def candidate_id(file_id: int, start: float) -> str:
    return f"{file_id}:{int(round(start * 1000))}"


def _window_start(clip: dict, event_t: float, length: float) -> float:
    dur = clip["duration"]
    return round(_clamp(event_t - EVENT_LEAD_SECONDS, min(COMPOSE_MIN_START, max(dur - length, 0.0)), max(dur - length - 0.04, 0.0)), 3)


def _describe(clip: dict | None, file_id: int, name: str, start: float, length: float, origin: str) -> dict[str, Any]:
    """A candidate: which clip, where it starts, and what is known about that moment."""
    event = None
    if clip:
        near = [e for e in clip.get("events") or [] if abs((e["t"] - EVENT_LEAD_SECONDS) - start) <= 0.35]
        event = min(near, key=lambda e: abs((e["t"] - EVENT_LEAD_SECONDS) - start)) if near else None
    return {
        "id": candidate_id(file_id, start), "file_id": file_id, "name": name, "source_in": round(start, 3), "seconds": round(length, 3), "origin": origin,
        "kind": event["kind"] if event else None, "what": event["what"] if event else None, "punch": event["punch"] if event else None,
        "scene": (clip or {}).get("scene") or None, "people": (clip or {}).get("people"),
        "clip_position": round(start / clip["duration"], 2) if clip and clip.get("duration") else None,
    }


def _build_multicam_review(plan: dict[str, Any], clips: list[dict]) -> dict[str, Any]:
    """A multicam interview: the moment of every shot is fixed by the dialogue, so the only alternative to a shot is the OTHER camera
    playing the same moment (an angle swap). Each alternative starts where that camera's footage lines up with this one's."""
    fps = plan["fps"]
    by_id = {c["file_id"]: c for c in clips}
    lag = {c["file_id"]: c["lag_seconds"] for c in plan["cameras"]}
    review = plan.get("review") or {}
    approved = set(review.get("approved", []))
    originals = review.get("original", {})
    slots = []
    for shot in plan["shots"]:
        length = shot["duration_frames"] / fps
        current = _describe(by_id.get(shot["file_id"]), shot["file_id"], shot["name"], shot["source_in"], length, "current")
        current["what"] = f"{shot['name']} -- this angle"
        alts: list[dict] = []
        orig = originals.get(str(shot["index"]))
        if orig and candidate_id(orig["file_id"], orig["source_in"]) != current["id"]:
            alt = _describe(by_id.get(orig["file_id"]), orig["file_id"], orig["name"], orig["source_in"], length, "original")
            alt["what"] = f"{orig['name']} -- the angle the plan chose"
            alts.append(alt)
        for cam in plan["cameras"]:
            if cam["file_id"] == shot["file_id"] or any(a["file_id"] == cam["file_id"] for a in alts):
                continue
            clip = by_id.get(cam["file_id"])
            start = round(shot["source_in"] - lag[shot["file_id"]] + cam["lag_seconds"], 3)
            if clip and start >= 0 and start + length <= clip["duration"] + 0.05:
                alt = _describe(clip, cam["file_id"], cam["name"], start, length, "other_angle")
                alt["what"] = f"{cam['name']} -- the other angle at the same moment"
                alts.append(alt)
        slots.append({
            "index": shot["index"], "role": shot["role"], "seconds": round(length, 2), "duration_frames": shot["duration_frames"],
            "cut_at_seconds": round(shot["start_frame"] / fps, 2), "approved": shot["index"] in approved, "current": current, "alternatives": alts,
            "speed": 1.0, "can_slow": False, "slow_note": None,
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals), "slowed": 0}


def build_review(plan: dict[str, Any], clips: list[dict]) -> dict[str, Any]:
    """Slots with their current moment and alternatives. `clips` carry events/scene (post_moments) and are in
    shoot order."""
    if plan.get("mode") == "multicam":
        return _build_multicam_review(plan, clips)
    fps = plan["fps"]
    by_id = {c["file_id"]: c for c in clips}
    order = [c["file_id"] for c in clips]
    used = {s["file_id"] for s in plan["shots"]}
    review = plan.get("review") or {}
    approved = set(review.get("approved", []))
    originals = review.get("original", {})
    steady_plan = _is_steady_plan(plan, clips)
    picked = _picker_alternatives(plan, clips) if steady_plan else {}
    slots = []
    for shot in plan["shots"]:
        length = shot["duration_frames"] / fps
        clip = by_id.get(shot["file_id"])
        speed = shot_speed(shot)
        current = _describe(clip, shot["file_id"], shot["name"], shot["source_in"], length * speed, "current")   # a slowed shot shows less source: window = slot length * speed
        if speed != 1.0:
            current["speed"] = speed
        can_slow, slow_note = slow_check(plan, clip, shot)
        if steady_plan:
            current["what"] = shot["moment_source"]
            current["tag"] = "picked in review" if shot["moment_source"].startswith("picked in review") else ("static" if (shot.get("steady") or {}).get("static") else "steady")
        alts: list[dict] = []
        seen = {current["id"]}

        def add(c: dict, min_gap: float = 0.0) -> None:
            gap = max(length + 0.1, min_gap)
            if c["id"] not in seen and not any(abs(c["source_in"] - a["source_in"]) < gap and c["file_id"] == a["file_id"] for a in [current, *alts]):
                seen.add(c["id"]); alts.append(c)
        orig = originals.get(str(shot["index"]))
        if orig and candidate_id(orig["file_id"], orig["source_in"]) != current["id"]:
            add(_describe(by_id.get(orig["file_id"]), orig["file_id"], orig["name"], orig["source_in"], length, "original"))
        if steady_plan:  # the picker's ranked swaps: clean stretches that don't look like the shots around this one
            for cand in picked.get(shot["index"], []):
                described = _describe(by_id.get(cand["file_id"]), cand["file_id"], cand["name"], cand["source_in"], length, cand["origin"])
                described.update({"what": cand["note"], "tag": cand["tag"], "kind": None, "punch": None})
                add(described)
        elif clip:  # other events in the same clip
            n = 0
            for e in sorted(clip.get("events") or [], key=lambda e: -e["punch"]):
                if n >= SAME_CLIP_ALTERNATIVES:
                    break
                before = len(alts)
                add(_describe(clip, clip["file_id"], clip["name"], _window_start(clip, e["t"], min(length, clip["duration"])), min(length, clip["duration"]), "same_clip"), SAME_CLIP_MIN_GAP_SECONDS)
                n += len(alts) - before
        if not steady_plan and shot["role"] == "body" and shot["file_id"] in by_id:  # strong events from neighbouring clips not used elsewhere
            pos = order.index(shot["file_id"])
            near = [by_id[i] for i in order[max(0, pos - NEIGHBOURHOOD): pos + NEIGHBOURHOOD + 1] if i != shot["file_id"] and i not in used and by_id[i].get("events")]
            near.sort(key=lambda c: -max(e["punch"] for e in c["events"]))
            scenes = {_scene_key(by_id[shot["file_id"]])}
            n = 0
            for c in near:
                if n >= OTHER_CLIP_ALTERNATIVES:
                    break
                if _scene_key(c) in scenes or c["duration"] < length + 0.2:
                    continue
                e = max(c["events"], key=lambda e: e["punch"])
                scenes.add(_scene_key(c))
                add(_describe(c, c["file_id"], c["name"], _window_start(c, e["t"], length), length, "other_clip"))
                n += 1
        slots.append({
            "index": shot["index"], "role": shot["role"], "seconds": round(length, 2), "duration_frames": shot["duration_frames"],
            "cut_at_seconds": round(shot["start_frame"] / fps, 2), "approved": shot["index"] in approved,
            "current": current, "alternatives": alts,
            "speed": speed, "can_slow": can_slow or speed != 1.0, "slow_note": slow_note,
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals),
            "slowed": sum(1 for s in slots if s["speed"] != 1.0)}


def apply_choice(plan: dict[str, Any], clips: list[dict], slot_index: int, file_id: int, source_in: float, action: str) -> dict[str, Any]:
    """Puts the chosen candidate into the slot (action "swap") or just marks the slot approved ("approve"). The
    candidate must be one the review currently offers for that slot, so a stale or tampered page can't put an
    arbitrary window into the plan. Returns the chosen candidate. Mutates `plan`."""
    if action not in ("swap", "approve"):
        raise ReviewError(f"Unknown action {action!r}.")
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    if shot is None:
        raise ReviewError(f"The plan has no shot {slot_index}.")
    slot = next(s for s in build_review(plan, clips)["slots"] if s["index"] == slot_index)
    wanted = candidate_id(file_id, source_in)
    options = {c["id"]: c for c in [slot["current"], *slot["alternatives"]]}
    chosen = options.get(wanted)
    if chosen is None and _is_steady_plan(plan, clips) and post_pick.valid_alternative(plan, clips, slot_index, file_id, source_in) is not None:
        # The list of swaps for a shot depends on its neighbours, so it can change after another swap: a page opened earlier still offers the old one.
        # It is still the job's own clip with a clean stretch (no cut inside), so it is accepted.
        clip_ = next(c for c in clips if c["file_id"] == file_id)
        chosen = _describe(clip_, file_id, clip_["name"], source_in, shot["duration_frames"] / plan["fps"], "other_clip" if file_id != shot["file_id"] else "same_clip")
        chosen.update({"what": "a clean stretch offered earlier", "tag": "steady", "kind": None, "punch": None})
    if chosen is None:
        raise ReviewError("That moment isn't one of the options for this shot any more -- reload the page.")
    review = plan.setdefault("review", {"approved": [], "original": {}})
    if action == "swap" and chosen["id"] != slot["current"]["id"]:
        clip = next(c for c in clips if c["file_id"] == chosen["file_id"])
        slowed = shot_speed(shot) != 1.0
        real_time_in = (shot.get("speed_original") or {}).get("source_in", shot["source_in"])   # "the original" alternative is the real-time window, not the slowed one
        review["original"].setdefault(str(slot_index), {"file_id": shot["file_id"], "name": shot["name"], "path": shot["path"], "source_in": real_time_in, "moment_source": shot["moment_source"]})
        fps = plan["fps"]
        window = shot["duration_frames"] / fps
        speed = shot_speed(shot)
        if slowed and not slow_check(plan, clip, shot)[0]:   # the new clip can't be slowed (25 fps, too short): the shot goes back to real time
            speed = 1.0
        src_len = window * speed
        new_in = round(min(max(chosen["source_in"] + (window - src_len) / 2.0, 0.0), max(clip["duration"] - src_len - 0.04, 0.0)), 3) if speed != 1.0 else chosen["source_in"]
        shot.update({
            "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"], "source_in": new_in,
            "source_out": round(new_in + src_len, 3),
            "moment_source": f"picked in review" + (f" -- event ({chosen['kind']}): {chosen['what']}" if chosen["kind"] else ""),
        })
        if speed != 1.0:
            shot["speed"] = speed
            shot["speed_original"] = {"source_in": chosen["source_in"], "source_out": round(chosen["source_in"] + window, 3)}
        else:
            shot.pop("speed", None)
            shot.pop("speed_original", None)
        # A story plan's steadiness / slow zoom were measured on the OLD moment. The new one hasn't been measured, so it gets no zoom
        # (a moving shot with a zoom on top is exactly what the zoom rule exists to prevent).
        shot.pop("steady", None)
        shot.pop("alike_previous", None)
        zooms = (plan.get("zooms") or {}).get("items")
        if zooms:
            plan["zooms"]["items"] = [z for z in zooms if z["shot_index"] != slot_index]
        if plan.get("mode") == "multicam":
            shot["moment_source"] = f"angle switched in review -- {clip['name']}"
            shot["angle"] = next(i for i, c in enumerate(plan["cameras"]) if c["file_id"] == clip["file_id"])
    if slot_index not in review["approved"]:
        review["approved"].append(slot_index)  # choosing a moment also counts as having reviewed the slot
    return {"chosen": chosen, "shown": [slot["current"], *slot["alternatives"]], "slot": {k: slot[k] for k in ("index", "role", "seconds", "cut_at_seconds")}}


def set_speed(plan: dict[str, Any], clips: list[dict], slot_index: int, speed: float) -> dict[str, Any]:
    """Slows a shot to half speed (`speed` 0.5) or puts it back to real time (1.0). The shot keeps its slot, so the cut timing is untouched; at half speed it shows half as much
    source, centred where the real-time window was, and the real-time window is remembered so going back is exact. Slow zooms on that shot are dropped (their timing assumed real time).
    Counts as having reviewed the slot. Mutates `plan`; returns what the log wants."""
    if speed not in SLOW_SPEEDS:
        raise ReviewError(f"Speed has to be 1.0 (normal) or {SLOW_SPEED} (half speed); got {speed!r}.")
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    if shot is None:
        raise ReviewError(f"The plan has no shot {slot_index}.")
    clip = next((c for c in clips if c["file_id"] == shot["file_id"]), None)
    was = shot_speed(shot)
    window = shot["duration_frames"] / plan["fps"]
    if speed != was:
        if speed != 1.0:
            ok, why = slow_check(plan, clip, shot)
            if not ok:
                raise ReviewError(why or "That shot can't be slowed down.")
            real_in = shot["source_in"]
            src_len = window * speed
            new_in = round(min(max(real_in + (window - src_len) / 2.0, 0.0), max(clip["duration"] - src_len - 0.04, 0.0)), 3)
            shot["speed_original"] = {"source_in": real_in, "source_out": round(real_in + window, 3)}
            shot.update({"source_in": new_in, "source_out": round(new_in + src_len, 3), "speed": speed})
            zooms = (plan.get("zooms") or {}).get("items")
            if zooms:
                plan["zooms"]["items"] = [z for z in zooms if z["shot_index"] != slot_index]
        else:
            original = shot.pop("speed_original", None)
            real_in = original["source_in"] if original else shot["source_in"]
            shot.update({"source_in": real_in, "source_out": round(real_in + window, 3)})
            shot.pop("speed", None)
    review = plan.setdefault("review", {"approved": [], "original": {}})
    if slot_index not in review["approved"]:
        review["approved"].append(slot_index)   # deciding about a shot's speed also counts as having reviewed it
    event = next((e for e in (clip or {}).get("events") or [] if abs((e["t"] - EVENT_LEAD_SECONDS) - shot["source_in"]) <= 0.75), None)
    return {"slot": {"index": slot_index, "role": shot["role"], "seconds": round(window, 3), "cut_at_seconds": round(shot["start_frame"] / plan["fps"], 2)}, "speed": speed, "was": was,
            "clip": {"name": shot["name"], "fps": (clip or {}).get("fps"), "seconds": (clip or {}).get("duration")},
            "moment": {"kind": event["kind"] if event else None, "punch": event["punch"] if event else None, "what": event["what"] if event else None},
            "clip_position": round(shot["source_in"] / clip["duration"], 2) if clip and clip.get("duration") else None}


def log_speed_record(edit_dir: Path, job_id: int, plan: dict[str, Any], outcome: dict[str, Any]) -> None:
    """One JSON line per slow-motion decision, in its own file (review_speed_log.jsonl): which shot, how long its slot is, the clip's frame rate, and what the moment is.
    Separate from review_log.jsonl on purpose: that one holds moment swaps and the taste tools read it expecting a pick and what it passed over."""
    edit_dir.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "style": plan.get("style"), "action": "slow" if outcome["speed"] != 1.0 else "normal", **outcome}
    with open(edit_dir / "review_speed_log.jsonl", "a") as fh:
        fh.write(json.dumps(record) + "\n")


def log_record(edit_dir: Path, job_id: int, plan: dict[str, Any], action: str, outcome: dict[str, Any]) -> None:
    """One JSON line per decision: what was picked and everything that was offered (so the passed-over
    candidates are as informative as the pick)."""
    edit_dir.mkdir(parents=True, exist_ok=True)
    chosen = outcome["chosen"]
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "style": plan.get("style"), "action": action, "slot": outcome["slot"],
        "chosen": chosen, "passed_over": [c for c in outcome["shown"] if c["id"] != chosen["id"]],
        "kept_current": chosen["origin"] == "current" or chosen["id"] == outcome["shown"][0]["id"],
    }
    with open(edit_dir / "review_log.jsonl", "a") as fh:
        fh.write(json.dumps(record) + "\n")


def clip_cache_path(edit_dir: Path, file_id: int, start: float, seconds: float, speed: float = 1.0) -> Path:
    tag = "" if speed == 1.0 else f"_s{int(round(speed * 100))}"
    return edit_dir / "review_clips" / f"{file_id}_{int(round(start * 1000))}_{int(round(seconds * 1000))}{tag}.mp4"


async def render_review_clip(src: str, start: float, seconds: float, out: Path, speed: float = 1.0) -> Path:
    """A small silent looping preview of one candidate (at least MIN_PREVIEW_SECONDS long). Cached on disk. `seconds` is SOURCE time; at speed 0.5 it plays twice as long."""
    if await on_drive(out.exists):
        return out
    await on_drive(_make_parent, out, writing=True)
    tmp = out.with_suffix(".part.mp4")
    async with _CLIP_RENDER_LIMIT:
        if await on_drive(out.exists):
            return out
        slow = f"setpts={1.0 / speed:.4f}*PTS," if speed != 1.0 else ""   # stretch the timestamps first, then resample to 25 fps: a 50 fps source keeps every frame
        # -t here is an OUTPUT limit (it comes after -i), i.e. measured AFTER the slowdown: `seconds` of source is seconds / speed long on screen
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-ss", f"{max(start, 0):.3f}", "-i", src, "-t", f"{max(seconds / speed, MIN_PREVIEW_SECONDS):.3f}", "-an",
            "-vf", f"{slow}scale=-2:360,fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-movflags", "+faststart", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    if proc.returncode != 0 or not await on_drive(tmp.exists):
        raise ReviewError(f"Couldn't render the preview clip: {err.decode(errors='replace')[:160]}")
    await on_drive(tmp.replace, out, writing=True)
    return out


def _make_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
