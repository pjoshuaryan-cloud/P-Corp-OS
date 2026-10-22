"""
POST (2026-10-13) -- edit plan for a NARRATED B-ROLL STORY (Josh's corporate edit type).

Where post_edit_plan.py cuts a montage on the music's hits, a story is paced by its narration: shots follow the phrases of a
voice-over, not the beat. Read off Josh's corporate reference (see post_reference_video.py; the numbers live in
post_style.StoryStyle, so nothing here is hard-coded to one video):
  * the body is b-roll cut at the reference's own rhythm (median ~1.6 s a shot, no music sync, no accents),
  * narration runs ~2.3 words a second in phrases of ~4 words, one phrase per shot,
  * it closes on a held shot (~6 s) where the brand card goes.

Given a narration script, the script is split into phrases and each phrase becomes a shot whose length is the time that phrase
takes to say (an ESTIMATE -- the real voice-over doesn't exist yet), and a caption (.srt) file with the same phrases and timing is
written. Without a script the shot lengths are drawn from the reference's own distribution.

Same plan format as the music planner (shots with start_frame / duration_frames / source_in...), so the preview render, the review
step and the Premiere plugin's Assemble Edit work on it unchanged. What is NOT placed: the brand cards, the corner logo, burned-in
captions, dissolves -- the plugin can't place them yet, and the plan says so.
"""

from __future__ import annotations

import math
import random
import re
import statistics
from typing import Any

from app import post_candidate_moments, post_pick, post_steady
from app.post_edit_plan import COMPOSE_MIN_START, EditPlanError, MIN_SHOT_FRAMES, MUSIC_FADE_OUT_SECONDS, _scene_key, choose_window, select_clips, select_clips_by_moments
from app.post_style import StoryStyle, StyleProfile

MIN_PHRASE_SECONDS = 0.9  # a two-word phrase ("and trust") still needs a moment on screen; the reference's shortest caption shots are ~0.9-1.0 s
MAX_PHRASE_SECONDS = 3.5
MAX_SCRIPT_CHARS = 20000
from app.post_steady import CALM_PACE, MAX_PACE, MIN_PACE  # noqa: E402,F401  (kept importable from here: the planner's tests and callers use these names)
# words a long clause is happy to be split BEFORE (a natural place to breathe)
_BREAK_BEFORE = {"and", "with", "that", "to", "for", "in", "across", "from", "while", "so", "which", "who", "as", "by", "on", "of", "our", "their", "every"}


# ----------------------------------------------------------------------------------------------------------- the script
def _chunk(words: list[str], max_words: int) -> list[list[str]]:
    """Splits one clause into pieces of at most `max_words`, as even as possible, preferring to break before a joining word."""
    n = len(words)
    if n <= max_words:
        return [words]
    k = math.ceil(n / max_words)
    cuts: list[int] = []
    for i in range(1, k):
        ideal = round(i * n / k)
        window = [j for j in range(max(1, ideal - 1), min(n - 1, ideal + 1) + 1) if words[j].lower().strip(",.;:") in _BREAK_BEFORE]
        cut = min(window, key=lambda j: abs(j - ideal)) if window else ideal
        if cuts and cut <= cuts[-1]:
            cut = cuts[-1] + 1
        cuts.append(min(cut, n - 1))
    pieces, start = [], 0
    for c in cuts + [n]:
        if c > start:
            pieces.append(words[start:c])
        start = c
    return pieces


def split_script(script: str, max_words: int = 6, min_words: int = 2) -> list[str]:
    """Narration -> phrases of 2-`max_words` words (a caption per shot): breaks at sentence ends and commas/colons/dashes first,
    then splits any longer clause evenly; a one-word fragment is joined to its neighbour."""
    text = re.sub(r"\s+", " ", script.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')).strip()
    if not text:
        return []
    clauses = re.split(r"(?<=[.!?])\s+|(?<=[,;:])\s+|\s+[-–—]\s+", text)
    pieces: list[list[str]] = []
    for clause in clauses:
        words = clause.split()
        if words:
            pieces.extend(_chunk(words, max_words))
    merged: list[list[str]] = []
    for piece in pieces:
        if merged and len(merged[-1]) < min_words:
            merged[-1] = merged[-1] + piece  # the fragment before it was too short: join forward
        else:
            merged.append(piece)
    if len(merged) > 1 and len(merged[-1]) < min_words:
        merged[-2] = merged[-2] + merged.pop()
    return [" ".join(p) for p in merged]


def phrase_seconds(phrase: str, words_per_second: float, pace: float = 1.0) -> float:
    """How long a phrase takes to say at the style's narration pace (an estimate), kept within what a shot can sensibly hold.
    A calmer `pace` raises both limits (a shot may be held longer, and never flashes by shorter)."""
    return min(MAX_PHRASE_SECONDS * pace, max(MIN_PHRASE_SECONDS * pace, len(phrase.split()) / words_per_second))


# ---------------------------------------------------------------------------------------------------------- the timeline
def story_timeline(story: StoryStyle, *, fps: float, script: str | None = None, target_seconds: float | None = None, seed: int = 7, has_bookend: bool = False, with_opener: bool | None = None, pace: float = 1.0) -> dict[str, Any]:
    """The slots of the edit, in seconds snapped to the frame grid: [opener] + body shots + closing hold.
    With a script the body is one shot per phrase; without, shots are drawn from the style's own lengths until the target length."""
    if not (MIN_PACE <= pace <= MAX_PACE):
        raise EditPlanError(f"The pace has to be between {MIN_PACE} and {MAX_PACE} (1.0 = the reference's own pace, higher = calmer); got {pace}.")
    rng = random.Random(seed)
    opener = story.opener_seconds if (has_bookend if with_opener is None else with_opener) else 0.0  # the opener slot: for the bookend clip or for an opening brand card
    phrases: list[str] | None = None
    if script is not None and script.strip():
        if len(script) > MAX_SCRIPT_CHARS:
            raise EditPlanError(f"The narration script is {len(script):,} characters; the limit is {MAX_SCRIPT_CHARS:,}. Plan it in sections.")
        phrases = split_script(script, max_words=max(2, round(story.max_phrase_words * pace)))  # calmer = a few more words (so a longer shot) per phrase
        if not phrases:
            raise EditPlanError("The narration script has no words in it.")
        body = [phrase_seconds(p, story.words_per_second, pace) for p in phrases]
        hold = story.closing_hold_seconds
    else:
        total = float(target_seconds or 0)
        if total < 20:
            raise EditPlanError("A story edit needs a length of at least 20 seconds (or a narration script to take its length from).")
        hold = min(story.closing_hold_seconds, max(2.0, 0.2 * total))
        remaining = total - hold - opener
        body, used = [], 0.0
        while True:
            length = rng.choice(story.body_lengths) * pace
            if used + length > remaining - 0.4:
                break
            body.append(length)
            used += length
        if not body:
            raise EditPlanError("That length leaves no room for any shots after the opening and closing holds.")
        scale = remaining / used  # spread what is left over the shots so the edit lands on the requested length
        body = [b * scale for b in body]
    slots: list[dict[str, Any]] = []
    if opener:
        slots.append({"role": "opener", "seconds": opener})
    for i, b in enumerate(body):
        slots.append({"role": "body", "seconds": b, **({"phrase": phrases[i]} if phrases else {})})
    slots.append({"role": "end_card", "seconds": hold})
    # frame grid by cumulative rounding (no drift), every shot at least MIN_SHOT_FRAMES
    boundaries, cum = [0], 0.0
    for sl in slots:
        cum += sl["seconds"]
        boundaries.append(max(boundaries[-1] + MIN_SHOT_FRAMES, round(cum * fps)))
    for sl, a, b in zip(slots, boundaries, boundaries[1:]):
        sl["start_frame"], sl["frames"] = a, b - a
    return {"slots": slots, "total_frames": boundaries[-1], "total_seconds": round(boundaries[-1] / fps, 3), "phrases": phrases, "pace": pace}


# -------------------------------------------------------------------------------------------------------------- the plan
def _steady_window(clip: dict, length: float, taken: list[tuple[float, float]]) -> dict[str, Any]:
    """Kept as a name for the tests and callers that already use it: see post_steady.window_for_slot."""
    return post_steady.window_for_slot(clip, length, taken)


def assign_clips_to_slots(slots: list[dict[str, Any]], *, fps: float, clips: list[dict], bookend_file_id: int | None, seed: int = 7, slow_zooms: bool = True,
                          picker_options: dict[str, Any] | None = None, slot_roles: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Clip + best window for every slot ({role, start_frame, frames, phrase?}), shared by the narrated story and the corporate highlight to music.
    When the clips have been analysed (post_steady), every slot is filled by post_pick: the cleanest stretch of the clip that does not look like a shot already in
    the edit, broadly following the shoot's order. Without an analysis the old rule is used (clips spread evenly in the order given). The opener and the closing hold
    use the bookend clip if there is one. `picker_options` (role_weights, diversity, avoid, preferences) and `slot_roles` ({"first": role, "last": role}) are
    optional style / variant settings (post_style_library, post_variants); without them the plan is exactly what it always was. Every shot carries a
    `candidate` record (post_candidate_moments) saying what it is, the evidence and how it scored. Returns {shots, zooms, by_id, bookend, repetition}."""
    n_body = sum(1 for s in slots if s["role"] == "body")
    exclude = {bookend_file_id} if bookend_file_id is not None else set()
    has_moments = any(c.get("events") for c in clips)
    chosen = (select_clips_by_moments if has_moments else select_clips)(clips, max(n_body, 1), exclude)
    by_id = {c["file_id"]: c for c in clips}
    bookend = by_id.get(bookend_file_id) if bookend_file_id is not None else None
    picker = post_pick.Picker(clips, **(picker_options or {})) if any(c.get("steady") for c in clips) else None
    # a style's opening / closing preference goes to the first and last slots the picker fills: the closing hold too when no establishing clip was given
    picked_slots = [k for k, s in enumerate(slots) if s["role"] == "body" or bookend is None]
    first_pick, last_pick = (picked_slots[0], picked_slots[-1]) if picked_slots else (None, None)
    post_steady.clear_series_cache()
    used: dict[int, list[tuple[float, float]]] = {}
    shots: list[dict[str, Any]] = []
    body_i = 0
    for i, sl in enumerate(slots):
        length = sl["frames"] / fps
        picked = None
        if picker is not None and (sl["role"] == "body" or bookend is None):
            target = (body_i + 0.5) / max(n_body, 1) if sl["role"] == "body" else (0.0 if sl["role"] == "opener" else 1.0)
            prefer = (slot_roles or {}).get("first") if i == first_pick else ((slot_roles or {}).get("last") if i == last_pick else None)
            picked = picker.pick(length, target, exclude=exclude if sl["role"] == "body" else None, prefer_role=prefer)
        similar_to_previous = None
        if picked is not None:
            clip, w = picked["clip"], picked["window"]
            similar_to_previous = picker.register(clip, w, picked["sig"])
            if sl["role"] == "body":
                body_i += 1
        else:
            if sl["role"] == "body":
                clip = chosen[min(body_i, len(chosen) - 1)]
                body_i += 1
            elif bookend is not None:
                clip = bookend
            elif sl["role"] == "opener":  # an opening brand card with no establishing clip: the card covers whatever is under it
                clip = clips[0]
            else:  # no establishing clip given: hold the last clip of the shoot that is long enough
                clip = next((c for c in reversed(clips) if c["duration"] >= length + 0.2), clips[-1])
            if clip["duration"] < length + 0.2:  # too short for the slot: the next clip in order that fits
                clip = next((c for c in clips if c["duration"] >= length + 0.2 and (sl["role"] != "body" or c["file_id"] not in exclude)), clip)
            w = _steady_window(clip, length, used.get(clip["file_id"], [])) if clip.get("steady") else choose_window(clip, length, used.get(clip["file_id"], []))
            if sl["role"] != "body" and bookend is None and (w.get("steady") or {}).get("cuts"):
                # The opener / closing hold with no establishing clip given: any clip with a clean stretch long enough (a hold is long: 6 s)
                for alt in (list(reversed(clips)) if sl["role"] == "end_card" else list(clips)):
                    if not alt.get("steady") or alt["duration"] < length + 0.2:
                        continue
                    w_alt = _steady_window(alt, length, used.get(alt["file_id"], []))
                    if not w_alt["steady"]["cuts"]:
                        clip, w = alt, w_alt
                        break
            if sl["role"] == "body" and (w.get("steady") or {}).get("cuts"):
                # No cut-free stretch of this clip is long enough for the slot: take the next clip (shoot order) that can hold it cleanly.
                pos = next((k for k, c in enumerate(clips) if c["file_id"] == clip["file_id"]), 0)
                for alt in clips[pos + 1:] + clips[:pos]:
                    if not alt.get("steady") or alt["file_id"] in exclude or alt["duration"] < length + 0.2:
                        continue
                    w_alt = _steady_window(alt, length, used.get(alt["file_id"], []))
                    if not w_alt["steady"]["cuts"]:
                        clip, w = alt, w_alt
                        break
            if picker is not None:
                similar_to_previous = picker.register(clip, w)
        used.setdefault(clip["file_id"], []).append((w["start"], w["start"] + w["duration"]))
        candidate = post_candidate_moments.describe(clip, w, parts=picked["parts"] if picked is not None else None, score=picked["score"] if picked is not None else None,
                                                    describe_provenance=clip.get("moments_provenance"), length=sl["frames"] / fps)
        shots.append({
            "index": i + 1, "role": sl["role"], "file_id": clip["file_id"], "name": clip["name"], "path": clip["path"],
            "start_frame": sl["start_frame"], "duration_frames": sl["frames"],
            "source_in": w["start"], "source_out": round(w["start"] + sl["frames"] / fps, 3),
            "moment_source": w["source"], "cut_hit_percentile": None, "cut_on_hit": False,
            "candidate": post_candidate_moments.compact(candidate),
            **({"steady": w["steady"]} if w.get("steady") else {}),
            **({"phrase": sl["phrase"]} if sl.get("phrase") else {}),
            **({"alike_previous": round(similar_to_previous, 2)} if similar_to_previous is not None and picker.chosen[-1]["sig"] is not None else {}),
        })
    zooms = post_steady.plan_zooms(shots, fps, seed=seed) if slow_zooms else []
    repetition = picker.report() if picker is not None else None
    post_steady.clear_series_cache()  # the per-clip arrays were only needed while picking
    return {"shots": shots, "zooms": zooms, "by_id": by_id, "bookend": bookend, "repetition": repetition}


def build_story_plan(*, profile: StyleProfile, timeline: dict[str, Any], music_in: float, fps: float, clips: list[dict], bookend_file_id: int | None, seed: int = 7, slow_zooms: bool = True) -> dict[str, Any]:
    """Clip + moment for every slot of the timeline. Clips run in the order given (shoot order unless the caller passed one),
    spread evenly through them; the opener and the closing hold use the bookend clip if there is one."""
    story = profile.story
    if story is None:
        raise EditPlanError(f"'{profile.name}' isn't a narrated b-roll style.")
    slots = timeline["slots"]
    got = assign_clips_to_slots(slots, fps=fps, clips=clips, bookend_file_id=bookend_file_id, seed=seed, slow_zooms=slow_zooms)
    shots, zooms, by_id, bookend, repetition = got["shots"], got["zooms"], got["by_id"], got["bookend"], got["repetition"]
    lengths = [s["duration_frames"] / fps for s in shots if s["role"] == "body"]
    total_frames = timeline["total_frames"]
    hold = next((s["seconds"] for s in slots if s["role"] == "end_card"), 0.0)
    narration = None
    if timeline.get("phrases"):
        narration = {"words_per_second": story.words_per_second, "timing": "estimated from the style's narration pace -- the real voice-over doesn't exist yet",
                     "phrases": [{"shot_index": s["index"], "text": s["phrase"], "start_frame": s["start_frame"], "frames": s["duration_frames"]} for s in shots if s.get("phrase")]}
    plan: dict[str, Any] = {
        "mode": "story", "style": profile.name, "style_sources": profile.source_slugs, "fps": fps, "duration_frames": total_frames, "duration_seconds": round(total_frames / fps, 2),
        "music": {"in_seconds": round(music_in, 3), "fade_out_seconds": round(min(4.0, max(MUSIC_FADE_OUT_SECONDS, 0.6 * hold)), 2)},
        "shots": shots,
        "checks": {
            "shot_count": len(shots), "shot_length_median": round(statistics.median(lengths), 2), "shot_length_mean": round(statistics.mean(lengths), 2),
            "style_median": round(statistics.median(story.body_lengths), 2), "style_mean": round(statistics.mean(story.body_lengths), 2),
            "cuts_on_hits": None,  # a story is not cut to the beat
            "distinct_clips": len({s["file_id"] for s in shots}),
            "moment_sources": {k: sum(1 for s in shots if s["moment_source"].startswith(k)) for k in ("steadiest", "event", "composition", "hand-set", "middle")},
            "steady": {"pace": timeline.get("pace", 1.0), "shots_with_a_steady_window": sum(1 for s in shots if s.get("steady")),
                       "shots_with_a_cut_inside": sum(1 for s in shots if (s.get("steady") or {}).get("cuts")),
                       "static_body_shots": sum(1 for s in shots if s["role"] == "body" and (s.get("steady") or {}).get("static")), "slow_zooms": len(zooms)},
            "consecutive_same_scene": sum(1 for a, b in zip(shots, shots[1:]) if a["file_id"] != b["file_id"] and by_id[a["file_id"]].get("scene") and _scene_key(by_id[a["file_id"]]) == _scene_key(by_id[b["file_id"]])),
            "bookend": bookend is not None, "closing_hold_seconds": round(hold, 2),
            "repetition": repetition,
        },
        "notes": [
            "Shots are cut at the style's own pace and are NOT timed to the music; the song is a bed that fades out over the closing hold.",
            "Every analysed clip is a candidate for every shot: each is the cleanest stretch of its clip that does not look like a shot already in the edit, and the edit broadly follows the shoot's order. The planner does not reorder footage into a story.",
            "Hard cuts only: no dissolves, flashes, dips or other accents -- a cleaner cut, by design (the reference's 6 short dissolves are not reproduced).",
            f"Pace is {timeline.get('pace', 1.0):g}x the reference's (1.0 = its own, higher = calmer); " + post_steady.moment_note(shots),
            "Which moment of each clip is used is NOT validated as your taste (moment_source says where it came from) -- review and swap.",
        ],
    }
    if zooms:
        plan["zooms"] = {"items": zooms, "note": "Slow zooms (push-in or pull-out) only on shots whose footage is static / has little action; shots that already move get none."}
        plan["notes"].append(f"{len(zooms)} of {sum(1 for s in shots if s['role'] == 'body')} body shots are static footage and get a slow zoom ({sum(1 for z in zooms if z['direction'] == 'in')} push-in, {sum(1 for z in zooms if z['direction'] == 'out')} pull-out); the rest already move, so they get none.")
    if narration:
        plan["narration"] = narration
        plan["notes"].insert(1, "Shot lengths come from the narration script: each phrase is one shot, as long as that phrase takes to say at the style's pace. That is an estimate; re-time to the real voice-over.")
    return plan


# ------------------------------------------------------------------------------------------------------------- captions
def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def captions_srt(plan: dict[str, Any]) -> str:
    """A caption file (SubRip) with one caption per narrated shot, timed to the plan's shots. Empty string if the plan has no script."""
    narration = plan.get("narration")
    if not narration:
        return ""
    fps = plan["fps"]
    blocks = []
    for n, ph in enumerate(narration["phrases"], start=1):
        start = ph["start_frame"] / fps
        end = (ph["start_frame"] + ph["frames"]) / fps
        blocks.append(f"{n}\n{_srt_time(start)} --> {_srt_time(end)}\n{ph['text']}\n")
    return "\n".join(blocks)
