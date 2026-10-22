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

from app import post_candidate_moments, post_pick
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

# Earlier / later (2026-10-22): the same clip with the stretch moved by half the shot's length (0.2 to 1 s). Measured on 168 of Josh's shots, no placement rule
# (centred, lead-in, by kind of moment) beat the planner's own by enough to adopt (learning/placement.py), so the timing is offered as a one-click choice instead.
NUDGE_SHARE = 0.5
NUDGE_MIN_SECONDS, NUDGE_MAX_SECONDS = 0.2, 1.0
CHANGE_OUTCOMES = ("swapped", "moved", "regenerated")   # the decisions a reason chip can explain


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
            "speed": 1.0, "can_slow": False, "slow_note": None, "locked": False, "why": None,
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals), "slowed": 0, "locked": 0,
            "can_regenerate": False}


def _nudges(plan: dict[str, Any], clips: list[dict], clip: dict | None, shot: dict[str, Any], length: float, steady_plan: bool) -> list[dict[str, Any]]:
    """The current moment moved earlier and later (see NUDGE_SHARE). Not for opening/closing cards or slowed shots, never past either end of the clip, and on a plan
    cut from the steadiness analysis never onto a stretch with a cut in it."""
    if clip is None or shot["role"] != "body" or shot_speed(shot) != 1.0:
        return []
    step = round(_clamp(length * NUDGE_SHARE, NUDGE_MIN_SECONDS, NUDGE_MAX_SECONDS), 2)
    out = []
    for origin, delta in (("earlier", -step), ("later", step)):
        start = round(shot["source_in"] + delta, 3)
        if start < 0 or start + length > clip["duration"] - 0.04:
            continue
        if steady_plan and post_pick.valid_alternative(plan, clips, shot["index"], clip["file_id"], start) is None:
            continue
        c = _describe(clip, clip["file_id"], clip["name"], start, length, origin)
        c.update({"what": f"the same moment, {step:.2f} s {origin}", "tag": "timing"})
        out.append(c)
    return out


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
    locked = set(review.get("locked", []))
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
        prev = (review.get("previous") or {}).get(str(shot["index"]))   # what it showed just before the last Regenerate
        if prev and candidate_id(prev["file_id"], prev["source_in"]) != current["id"]:
            add(_describe(by_id.get(prev["file_id"]), prev["file_id"], prev["name"], prev["source_in"], length, "previous"))
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
        alts.extend(c for c in _nudges(plan, clips, clip, shot, length, steady_plan) if c["id"] not in seen)   # deliberately close to the current one: not through add()'s gap rule
        slots.append({
            "index": shot["index"], "role": shot["role"], "seconds": round(length, 2), "duration_frames": shot["duration_frames"],
            "cut_at_seconds": round(shot["start_frame"] / fps, 2), "approved": shot["index"] in approved,
            "current": current, "alternatives": alts,
            "speed": speed, "can_slow": can_slow or speed != 1.0, "slow_note": slow_note,
            "locked": shot["index"] in locked,
            "why": post_candidate_moments.explain_choice(shot["candidate"]) if shot.get("candidate") else None,
        })
    return {"fps": fps, "style": plan.get("style"), "duration_seconds": plan["duration_seconds"], "slots": slots,
            "approved": len(approved), "total": len(slots), "swapped": sum(1 for s in slots if str(s["index"]) in originals),
            "slowed": sum(1 for s in slots if s["speed"] != 1.0), "locked": len(locked), "can_regenerate": steady_plan}


def apply_choice(plan: dict[str, Any], clips: list[dict], slot_index: int, file_id: int, source_in: float, action: str) -> dict[str, Any]:
    """Puts the chosen candidate into the slot (action "swap") or just marks the slot approved ("approve"). The
    candidate must be one the review currently offers for that slot, so a stale or tampered page can't put an
    arbitrary window into the plan. Returns the chosen candidate. Mutates `plan`."""
    if action not in ("swap", "approve"):
        raise ReviewError(f"Unknown action {action!r}.")
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    if shot is None:
        raise ReviewError(f"The plan has no shot {slot_index}.")
    was_yours = str(shot.get("moment_source", "")).startswith("picked in review")   # keeping (or leaving) his OWN pick says nothing about the planner's kinds
    slot = next(s for s in build_review(plan, clips)["slots"] if s["index"] == slot_index)
    wanted = candidate_id(file_id, source_in)
    options = {c["id"]: c for c in [slot["current"], *slot["alternatives"]]}
    chosen = options.get(wanted)
    if chosen is None and _is_steady_plan(plan, clips) and post_pick.valid_alternative(plan, clips, slot_index, file_id, source_in) is not None:
        # The list of swaps for a shot depends on its neighbours, so it can change after another swap: a page opened earlier still offers the old one.
        # It is still the job's own clip with a clean stretch (no cut inside), so it is accepted.
        clip_ = next(c for c in clips if c["file_id"] == file_id)
        length_ = shot["duration_frames"] / plan["fps"]
        origin_ = "other_clip" if file_id != shot["file_id"] else "same_clip"
        step = round(_clamp(length_ * NUDGE_SHARE, NUDGE_MIN_SECONDS, NUDGE_MAX_SECONDS), 2)
        if origin_ == "same_clip" and abs(abs(source_in - shot["source_in"]) - step) < 0.006:
            origin_ = "earlier" if source_in < shot["source_in"] else "later"   # exactly this shot's nudge: a re-timing, not a different moment
        chosen = _describe(clip_, file_id, clip_["name"], source_in, length_, origin_)
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
        moved = f" -- moved {chosen['origin']}" if chosen["origin"] in ("earlier", "later") else ""
        shot.update({
            "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"], "source_in": new_in,
            "source_out": round(new_in + src_len, 3),
            "moment_source": f"picked in review{moved}" + (f" -- event ({chosen['kind']}): {chosen['what']}" if chosen["kind"] else ""),
        })
        shot.pop("candidate_real_time", None)   # it described the footage that was just swapped out
        shot.pop("event_kind", None)            # the kind of moment a regeneration picked: the new stretch's kind comes from its own event
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
        refresh_candidate(plan, shot, clip)
    if slot_index not in review["approved"]:
        review["approved"].append(slot_index)  # choosing a moment also counts as having reviewed the slot
    if slot_index in review.get("approved_by_lock", []):
        review["approved_by_lock"].remove(slot_index)   # now his own decision: unlocking no longer takes the approval back
    return {"chosen": chosen, "shown": [slot["current"], *slot["alternatives"]], "slot": {k: slot[k] for k in ("index", "role", "seconds", "cut_at_seconds")},
            "current_was_yours": was_yours}


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
            # the real-time candidate record is kept beside it, so going back to normal speed gives back the identical shot
            shot["candidate_real_time"] = shot.get("candidate")
            shot.update({"source_in": new_in, "source_out": round(new_in + src_len, 3), "speed": speed})
            zooms = (plan.get("zooms") or {}).get("items")
            if zooms:
                plan["zooms"]["items"] = [z for z in zooms if z["shot_index"] != slot_index]
            refresh_candidate(plan, shot, clip)
        else:
            original = shot.pop("speed_original", None)
            real_in = original["source_in"] if original else shot["source_in"]
            shot.update({"source_in": real_in, "source_out": round(real_in + window, 3)})
            shot.pop("speed", None)
            if "candidate_real_time" in shot:
                kept = shot.pop("candidate_real_time")
                if kept is None:
                    shot.pop("candidate", None)
                else:
                    shot["candidate"] = kept
            else:   # slowed before candidate records existed: describe the real-time window afresh
                refresh_candidate(plan, shot, clip)
    review = plan.setdefault("review", {"approved": [], "original": {}})
    if slot_index not in review["approved"]:
        review["approved"].append(slot_index)   # deciding about a shot's speed also counts as having reviewed it
    if slot_index in review.get("approved_by_lock", []):
        review["approved_by_lock"].remove(slot_index)
    event = next((e for e in (clip or {}).get("events") or [] if abs((e["t"] - EVENT_LEAD_SECONDS) - shot["source_in"]) <= 0.75), None)
    return {"slot": {"index": slot_index, "role": shot["role"], "seconds": round(window, 3), "cut_at_seconds": round(shot["start_frame"] / plan["fps"], 2)}, "speed": speed, "was": was,
            "clip": {"name": shot["name"], "fps": (clip or {}).get("fps"), "seconds": (clip or {}).get("duration")},
            "moment": {"kind": event["kind"] if event else None, "punch": event["punch"] if event else None, "what": event["what"] if event else None},
            "clip_position": round(shot["source_in"] / clip["duration"], 2) if clip and clip.get("duration") else None}


def refresh_candidate(plan: dict[str, Any], shot: dict[str, Any], clip: dict | None) -> None:
    """Rewrites the shot's candidate record (post_candidate_moments) for the stretch it NOW shows. A swap, a nudge, a speed change or a regeneration moves the
    stretch; without this the plan's "why this shot" would describe footage that is no longer in it. (A plan made before candidate records existed gets one now.)"""
    if clip is None:
        shot.pop("candidate", None)
        return
    window = {"start": shot["source_in"], "duration": shot["source_out"] - shot["source_in"], "source": shot["moment_source"], "steady": shot.get("steady")}
    if shot.get("event_kind"):
        window["event_kind"] = shot["event_kind"]
    record = post_candidate_moments.describe(clip, window, describe_provenance=clip.get("moments_provenance"), length=shot["source_out"] - shot["source_in"])
    shot["candidate"] = post_candidate_moments.compact(record)


def _shot_summary(shot: dict[str, Any]) -> dict[str, Any]:
    return {"file_id": shot["file_id"], "name": shot["name"], "source_in": shot["source_in"], "source_out": shot["source_out"]}


def set_lock(plan: dict[str, Any], slot_index: int, locked: bool) -> dict[str, Any]:
    """Locks a shot (Regenerate leaves it alone, and it counts as reviewed) or unlocks it. A lock never stops Josh swapping the shot himself. Mutates `plan`."""
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    if shot is None:
        raise ReviewError(f"The plan has no shot {slot_index}.")
    review = plan.setdefault("review", {"approved": [], "original": {}})
    locks = review.setdefault("locked", [])
    by_lock = review.setdefault("approved_by_lock", [])   # approvals that exist only because of a lock: unlocking takes them back
    if locked and slot_index not in locks:
        locks.append(slot_index)
    elif not locked and slot_index in locks:
        locks.remove(slot_index)
    if locked and slot_index not in review["approved"]:
        review["approved"].append(slot_index)
        by_lock.append(slot_index)
    elif not locked and slot_index in by_lock:
        by_lock.remove(slot_index)
        if slot_index in review["approved"]:
            review["approved"].remove(slot_index)   # so Regenerate may replace it again, as the Unlock button says
    return {"slot": {"index": slot_index, "role": shot["role"], "seconds": round(shot["duration_frames"] / plan["fps"], 3), "cut_at": round(shot["start_frame"] / plan["fps"], 2)},
            "locked": locked, "shot": _shot_summary(shot)}


def decided(shot: dict[str, Any], review: dict[str, Any]) -> str | None:
    """Why a shot is Josh's own decision, which Regenerate never touches, or None: locked, kept ("Keep this"), a moment he picked, or slowed by him."""
    if shot["index"] in review.get("locked", []):
        return "locked"
    if str(shot.get("moment_source", "")).startswith("picked in review"):
        return "picked by you"
    if shot_speed(shot) != 1.0:
        return "slowed by you"
    if shot["index"] in review.get("approved", []):
        return "kept by you"
    return None


def regenerate_section(plan: dict[str, Any], clips: list[dict], from_index: int, to_index: int) -> dict[str, Any]:
    """Re-picks the body shots from `from_index` to `to_index` that Josh has NOT decided on (see `decided`: locked, kept, picked or slowed shots are left exactly
    as they are) with the planner's own picker (post_pick.regenerate). Shots outside the range never change, nor does cut timing. A shot never gets back a stretch
    it has already shown (plan["review"]["seen"]), so pressing it twice moves on. Each changed shot offers back the moment it had just before (and the planner's
    original), and has to be reviewed again. Only for plans cut from the steadiness analysis (highlight and story). Mutates `plan`; returns what changed."""
    if not _is_steady_plan(plan, clips):
        raise ReviewError("Regenerate works on plans cut from the footage analysis (Your usual pace, corporate highlight and story plans). "
                          "This plan's moments come from Claude's descriptions: swap its shots one at a time instead.")
    lo, hi = sorted((int(from_index), int(to_index)))
    fps = plan["fps"]
    review = plan.setdefault("review", {"approved": [], "original": {}})
    locked = set(review.get("locked", []))
    in_range = [s for s in plan["shots"] if lo <= s["index"] <= hi and s["role"] == "body"]
    kept_yours = [{"index": s["index"], "why": why} for s in in_range if (why := decided(s, review))]
    targets = [s["index"] for s in in_range if not decided(s, review)]
    if not targets:
        raise ReviewError("Every shot in that range is one you've decided on (locked, kept, picked or slowed) or an opening/closing shot: "
                          "Regenerate only re-picks the others.")
    seen_map = review.setdefault("seen", {})
    seen: dict[int, list[tuple[int, float, float]]] = {}
    by_index = {s["index"]: s for s in plan["shots"]}
    for idx in targets:
        shot = by_index[idx]
        real_in = (shot.get("speed_original") or {}).get("source_in", shot["source_in"])
        here = [shot["file_id"], round(real_in, 3), round(real_in + shot["duration_frames"] / fps, 3)]
        history = seen_map.setdefault(str(idx), [])
        if here not in history:
            history.append(here)
        seen[idx] = [tuple(x) for x in history]
    picks = post_pick.regenerate(plan, clips, targets, seen)
    by_id = {c["file_id"]: c for c in clips}
    changed, unchanged = [], []
    for idx in targets:
        pick, shot = picks.get(idx), by_index[idx]
        if pick is None:
            unchanged.append(idx)
            continue
        before = _shot_summary(shot)
        before["candidate"] = shot.get("candidate")
        here = {"file_id": shot["file_id"], "name": shot["name"], "path": shot["path"], "source_in": shot["source_in"], "moment_source": shot["moment_source"]}
        review["original"].setdefault(str(idx), here)   # the planner's own moment (kept from the first change on)
        review.setdefault("previous", {})[str(idx)] = here   # the moment it had just before THIS regeneration
        window, length = pick["window"], shot["duration_frames"] / fps
        clip = by_id[pick["file_id"]]
        shot.update({"file_id": clip["file_id"], "name": clip["name"], "path": clip["path"], "source_in": window["start"], "source_out": round(window["start"] + length, 3),
                     "moment_source": window["source"], "steady": window["steady"]})
        for key in ("alike_previous", "event_kind"):
            shot.pop(key, None)
        if window.get("event_kind"):
            shot["event_kind"] = window["event_kind"]
        zooms = (plan.get("zooms") or {}).get("items")
        if zooms:
            plan["zooms"]["items"] = [z for z in zooms if z["shot_index"] != idx]
        refresh_candidate(plan, shot, clip)
        seen_map[str(idx)].append([clip["file_id"], round(window["start"], 3), round(window["start"] + length, 3)])
        changed.append({"index": idx, "before": before, "after": _shot_summary(shot), "candidate": shot.get("candidate"),
                        "slot": {"index": idx, "role": shot["role"], "seconds": round(length, 3), "cut_at": round(shot["start_frame"] / fps, 2)}})
    return {"range": [lo, hi], "regenerated": changed, "unchanged": unchanged, "locked_kept": sorted(i for i in locked if lo <= i <= hi), "kept_yours": kept_yours}


def _event_candidate(c: dict[str, Any] | None) -> dict[str, Any] | None:
    """A shot (or a shot summary with its candidate record) in the learning event's candidate shape."""
    if not c:
        return None
    cand = c.get("candidate") or {}
    event = cand.get("event") or {}
    return {"candidate_id": cand.get("id"), "file_id": c.get("file_id"), "name": c.get("name"), "source_in": c.get("source_in"), "source_out": c.get("source_out"),
            "kind": event.get("kind"), "punch": event.get("punch"), "speed": c.get("speed")}


def review_events(job_id: int, plan: dict[str, Any], outcome_name: str, outcome: dict[str, Any]) -> list[dict[str, Any]]:
    """Learning events (post_learning_events) for a lock, an unlock or a regeneration: explicit feedback, confirmed. None of these counts as a vote for or against
    a kind of moment (only kept / approved / swapped / replaced / dropped do), so locking or regenerating can't skew the taste evidence by itself."""
    from app import post_learning_events as le
    context = {"style": plan.get("style"), "variant": (plan.get("variant") or {}).get("style")}
    ts = le.now_precise()   # lock, unlock, lock within one second are three events, not one
    if outcome_name in ("locked", "unlocked"):
        shot = next(s for s in plan["shots"] if s["index"] == outcome["slot"]["index"])
        return [le.make_event(category="explicit_feedback", confidence="confirmed", outcome=outcome_name, source="review_page", job_id=job_id, slot=outcome["slot"],
                              planned=_event_candidate(shot), context=context, ts=ts)]
    if outcome_name == "regenerated":
        return [le.make_event(category="explicit_feedback", confidence="confirmed", outcome="regenerated", source="review_page", job_id=job_id, slot=c["slot"],
                              planned=_event_candidate(c["before"]), replacement=_event_candidate({**c["after"], "candidate": c["candidate"]}),
                              context={**context, "range": outcome["range"]}, ts=ts) for c in outcome["regenerated"]]
    raise ValueError(outcome_name)


def reason_event(edit_dir: Path, job_id: int, plan: dict[str, Any], slot_index: int, reasons: list[str], note: str | None,
                 explains: str | None = None) -> dict[str, Any]:
    """The reason Josh gave for a change to a shot, as a 'reasoned' event that names that change (context["explains"]), so a client's request takes the change out of
    his taste evidence (post_learning_events._explained_away). `explains`: the id of the change's own event (the review page gets it back from the swap); without it,
    the latest change to that shot in this job. Raises ReviewError for an unknown reason code, a shot he hasn't changed, or an id that isn't a change to that shot."""
    from app import post_learning_events as le
    unknown = [r for r in reasons if r not in le.REASON_CODES]
    if not reasons or unknown:
        raise ReviewError("Pick at least one of the listed reasons." if not reasons else f"Unknown reason {unknown[0]!r}.")
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    if shot is None:
        raise ReviewError(f"The plan has no shot {slot_index}.")
    events = le.load_events(Path(edit_dir) / le.EVENTS_FILE)
    changes = [e for e in events if (e.get("slot") or {}).get("index") == slot_index and e.get("outcome") in CHANGE_OUTCOMES and e.get("job_id") == job_id
               and e.get("category") == "explicit_feedback"]   # his own changes on the review page, never a "moved" seen in a finished timeline
    if explains is not None:
        last = next((e for e in changes if e["id"] == explains), None)
        if last is None:
            raise ReviewError("That change wasn't recorded for this shot, so a reason can't be attached to it.")
    else:
        last = changes[-1] if changes else None
    if last is None:
        raise ReviewError("A reason explains a change: swap, nudge or regenerate this shot first.")
    return le.make_event(category="explicit_feedback", confidence="confirmed", outcome="reasoned", source="review_page", job_id=job_id, ts=le.now_precise(), slot=last.get("slot"),
                         planned=last.get("planned"), replacement=last.get("replacement"), reasons=reasons, note=note,
                         context={"style": plan.get("style"), "explains": last["id"], "explains_outcome": last["outcome"]})


def log_speed_record(edit_dir: Path, job_id: int, plan: dict[str, Any], outcome: dict[str, Any]) -> None:
    """One JSON line per slow-motion decision, in its own file (review_speed_log.jsonl): which shot, how long its slot is, the clip's frame rate, and what the moment is.
    Separate from review_log.jsonl on purpose: that one holds moment swaps and the taste tools read it expecting a pick and what it passed over."""
    edit_dir.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "style": plan.get("style"), "action": "slow" if outcome["speed"] != 1.0 else "normal", **outcome}
    with open(edit_dir / "review_speed_log.jsonl", "a") as fh:
        fh.write(json.dumps(record) + "\n")
    from app import post_learning_events as le   # the same decision as a versioned learning event (converted exactly as a bulk import would, so never twice)
    le.record_for_job(edit_dir, le.from_speed_record(record))


def log_record(edit_dir: Path, job_id: int, plan: dict[str, Any], action: str, outcome: dict[str, Any]) -> str | None:
    """One JSON line per decision: what was picked and everything that was offered (so the passed-over
    candidates are as informative as the pick). Returns the id of the learning event written for it (None when it couldn't be written), so a reason
    given afterwards can name exactly this change."""
    edit_dir.mkdir(parents=True, exist_ok=True)
    chosen = outcome["chosen"]
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "style": plan.get("style"), "action": action, "slot": outcome["slot"],
        "chosen": chosen, "passed_over": [c for c in outcome["shown"] if c["id"] != chosen["id"]],
        "kept_current": chosen["origin"] == "current" or chosen["id"] == outcome["shown"][0]["id"],
        "current_was_yours": bool(outcome.get("current_was_yours")),   # the shot already held a moment HE picked: not a vote on the planner's kinds
    }
    with open(edit_dir / "review_log.jsonl", "a") as fh:
        fh.write(json.dumps(record) + "\n")
    from app import post_learning_events as le   # the same decision as a versioned learning event (converted exactly as a bulk import would, so never twice)
    events = le.from_review_record(record)
    return events[0]["id"] if events and le.record_for_job(edit_dir, events) >= 0 else None


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
