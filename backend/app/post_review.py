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

from app.post_media import COMPOSE_MIN_START, FFMPEG_PATH
from app.post_edit_plan import EVENT_LEAD_SECONDS, _clamp, _scene_key
from app.ssd_guard import on_drive

MIN_PREVIEW_SECONDS = 0.8  # a 0.12 s shot can't be judged by eye: the review clip shows at least this much
NEIGHBOURHOOD = 6  # how many clips either side (in shoot order) count as "the same stretch" for alternatives
SAME_CLIP_ALTERNATIVES = 2
SAME_CLIP_MIN_GAP_SECONDS = 2.0  # another event from the SAME clip must be a clearly different moment, not 1 s along the same action
OTHER_CLIP_ALTERNATIVES = 2
_CLIP_RENDER_LIMIT = asyncio.Semaphore(3)


class ReviewError(RuntimeError):
    pass


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
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals)}


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
    slots = []
    for shot in plan["shots"]:
        length = shot["duration_frames"] / fps
        clip = by_id.get(shot["file_id"])
        current = _describe(clip, shot["file_id"], shot["name"], shot["source_in"], length, "current")
        alts: list[dict] = []
        seen = {current["id"]}

        def add(c: dict, min_gap: float = 0.0) -> None:
            gap = max(length + 0.1, min_gap)
            if c["id"] not in seen and not any(abs(c["source_in"] - a["source_in"]) < gap and c["file_id"] == a["file_id"] for a in [current, *alts]):
                seen.add(c["id"]); alts.append(c)
        orig = originals.get(str(shot["index"]))
        if orig and candidate_id(orig["file_id"], orig["source_in"]) != current["id"]:
            add(_describe(by_id.get(orig["file_id"]), orig["file_id"], orig["name"], orig["source_in"], length, "original"))
        if clip:  # other events in the same clip
            n = 0
            for e in sorted(clip.get("events") or [], key=lambda e: -e["punch"]):
                if n >= SAME_CLIP_ALTERNATIVES:
                    break
                before = len(alts)
                add(_describe(clip, clip["file_id"], clip["name"], _window_start(clip, e["t"], min(length, clip["duration"])), min(length, clip["duration"]), "same_clip"), SAME_CLIP_MIN_GAP_SECONDS)
                n += len(alts) - before
        if shot["role"] == "body" and shot["file_id"] in by_id:  # strong events from neighbouring clips not used elsewhere
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
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals)}


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
    if chosen is None:
        raise ReviewError("That moment isn't one of the options for this shot any more -- reload the page.")
    review = plan.setdefault("review", {"approved": [], "original": {}})
    if action == "swap" and chosen["id"] != slot["current"]["id"]:
        clip = next(c for c in clips if c["file_id"] == chosen["file_id"])
        review["original"].setdefault(str(slot_index), {"file_id": shot["file_id"], "name": shot["name"], "path": shot["path"], "source_in": shot["source_in"], "moment_source": shot["moment_source"]})
        fps = plan["fps"]
        shot.update({
            "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"], "source_in": chosen["source_in"],
            "source_out": round(chosen["source_in"] + shot["duration_frames"] / fps, 3),
            "moment_source": f"picked in review" + (f" -- event ({chosen['kind']}): {chosen['what']}" if chosen["kind"] else ""),
        })
        # A story plan's steadiness / slow zoom were measured on the OLD moment. The new one hasn't been measured, so it gets no zoom
        # (a moving shot with a zoom on top is exactly what the zoom rule exists to prevent).
        shot.pop("steady", None)
        zooms = (plan.get("zooms") or {}).get("items")
        if zooms:
            plan["zooms"]["items"] = [z for z in zooms if z["shot_index"] != slot_index]
        if plan.get("mode") == "multicam":
            shot["moment_source"] = f"angle switched in review -- {clip['name']}"
            shot["angle"] = next(i for i, c in enumerate(plan["cameras"]) if c["file_id"] == clip["file_id"])
    if slot_index not in review["approved"]:
        review["approved"].append(slot_index)  # choosing a moment also counts as having reviewed the slot
    return {"chosen": chosen, "shown": [slot["current"], *slot["alternatives"]], "slot": {k: slot[k] for k in ("index", "role", "seconds", "cut_at_seconds")}}


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


def clip_cache_path(edit_dir: Path, file_id: int, start: float, seconds: float) -> Path:
    return edit_dir / "review_clips" / f"{file_id}_{int(round(start * 1000))}_{int(round(seconds * 1000))}.mp4"


async def render_review_clip(src: str, start: float, seconds: float, out: Path) -> Path:
    """A small silent looping preview of one candidate (at least MIN_PREVIEW_SECONDS long). Cached on disk."""
    if await on_drive(out.exists):
        return out
    await on_drive(_make_parent, out, writing=True)
    tmp = out.with_suffix(".part.mp4")
    async with _CLIP_RENDER_LIMIT:
        if await on_drive(out.exists):
            return out
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-ss", f"{max(start, 0):.3f}", "-i", src, "-t", f"{max(seconds, MIN_PREVIEW_SECONDS):.3f}", "-an",
            "-vf", "scale=-2:360,fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-movflags", "+faststart", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    if proc.returncode != 0 or not await on_drive(tmp.exists):
        raise ReviewError(f"Couldn't render the preview clip: {err.decode(errors='replace')[:160]}")
    await on_drive(tmp.replace, out, writing=True)
    return out


def _make_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
