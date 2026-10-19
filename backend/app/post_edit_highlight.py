"""Corporate highlight cut to music (2026-10-14).

Josh's direction for a 35-45 s corporate highlight with no dialogue or voice-over: hard cuts that land on the music's hits, a calm pace (slower than a
reel), every shot from the steadiest stretch of its clip, a slow zoom (in or out) only on shots whose footage is static, an opening and a closing brand
card, no flashes or other accents.

This is the beat-synced sibling of the narrated story (post_edit_story.py): it takes the SAME shot rhythm from the corporate reference (about 1.6 s a
shot, multiplied by the calm pace), but places the cuts on the music's hits with the same cut-time planner the music reels use (post_edit_plan.plan_cut_times),
and picks clips and windows with the same shared helper as the story (post_edit_story.assign_clips_to_slots). There is no measured corporate highlight to
music: the rhythm is the narrated reference's, adapted. The plan says so.
"""
from __future__ import annotations

import dataclasses
import random
import statistics
from typing import Any

from app import post_steady
from app.post_edit_plan import EditPlanError, MIN_SHOT_FRAMES, _scene_key, plan_cut_times
from app.post_edit_story import assign_clips_to_slots
from app.post_steady import CALM_PACE, MAX_PACE, MIN_PACE
from app.post_style import StyleProfile

MIN_HIGHLIGHT_SECONDS = 12.0   # shorter than this there is no room for a card, a closing hold and a few shots
MIN_SHOT_SECONDS = 1.0         # a calm highlight never flashes a shot by faster than this
MAX_SHOT_SECONDS = 4.5
CLOSING_SHARE = 0.11           # the closing hold (the brand card) is about this much of the edit ...
CLOSING_MIN_SECONDS, CLOSING_MAX_SECONDS = 2.5, 4.5  # ... within these bounds (a 40 s highlight holds its card about 4.4 s)


def cut_profile(profile: StyleProfile, duration: float, pace: float) -> StyleProfile:
    """The profile the cut-time planner uses: the corporate reference's shot lengths times the calm pace, flat across the edit
    (a highlight doesn't build like a reel), a closing hold sized to the edit, and nothing shorter than a second."""
    story = profile.story
    if story is None:
        raise EditPlanError(f"'{profile.name}' has no shot rhythm to build a highlight from.")
    lengths = [max(MIN_SHOT_SECONDS, l * pace) for l in story.body_lengths]
    hold = min(CLOSING_MAX_SECONDS, max(CLOSING_MIN_SECONDS, CLOSING_SHARE * duration), story.closing_hold_seconds)
    return dataclasses.replace(
        profile, shot_lengths=lengths, pacing_curve=[round(statistics.mean(lengths), 3)] * 10, end_card_seconds=round(hold, 2),
        min_shot_seconds=MIN_SHOT_SECONDS, max_shot_seconds=MAX_SHOT_SECONDS, cut_lead_seconds=0.0, accents=None,
    )


def build_highlight_plan(
    *, profile: StyleProfile, hits: list[list[float]], music_in: float, duration: float, fps: float, clips: list[dict],
    bookend_file_id: int | None, seed: int = 7, pace: float = CALM_PACE, slow_zooms: bool = True, with_opener: bool = True, fill_frame: bool = True,
) -> dict[str, Any]:
    """Cut times on the music's hits + clip and steadiest window for every slot, snapped to the frame grid. `hits` are song-time [t, strength percentile];
    `clips` are ordered [{file_id, name, path, duration, steady?, ...}]. The first shot is the opening-card slot (`with_opener`), the last is the closing hold."""
    story = profile.story
    if story is None:
        raise EditPlanError(f"'{profile.name}' isn't a corporate highlight style.")
    if not (MIN_PACE <= pace <= MAX_PACE):
        raise EditPlanError(f"The pace has to be between {MIN_PACE} and {MAX_PACE} (1.0 = the reference's own pace, higher = calmer); got {pace}.")
    if duration < MIN_HIGHLIGHT_SECONDS:
        raise EditPlanError(f"A highlight needs at least {MIN_HIGHLIGHT_SECONDS:.0f} seconds (an opening card, a closing hold and a few shots); got {duration:.0f}.")
    rng = random.Random(seed)
    cprof = cut_profile(profile, duration, pace)
    rel_hits = [[h[0] - music_in, h[1]] for h in hits if music_in - 0.05 <= h[0] <= music_in + duration + 0.05]
    cuts = plan_cut_times(rel_hits, duration, cprof, rng, opener_seconds=story.opener_seconds if with_opener else None)
    frames: list[int] = []
    kept: list[dict] = []
    for c in cuts:  # frame grid; drop a cut that would leave a shot under MIN_SHOT_FRAMES
        f = round(c["t"] * fps)
        if frames and f - frames[-1] < MIN_SHOT_FRAMES:
            continue
        frames.append(f)
        kept.append(c)
    total_frames = round(duration * fps)
    if frames[-1] >= total_frames:
        frames.pop()
        kept.pop()
    raw = list(zip(frames, frames[1:] + [total_frames]))
    if len(raw) < 3:
        raise EditPlanError("That length leaves no room for shots between the opening and closing cards. Use a longer edit.")
    slots = [{"role": "opener" if (i == 0 and with_opener) else ("end_card" if i == len(raw) - 1 else "body"), "start_frame": f0, "frames": f1 - f0} for i, (f0, f1) in enumerate(raw)]
    got = assign_clips_to_slots(slots, fps=fps, clips=clips, bookend_file_id=bookend_file_id, seed=seed, slow_zooms=slow_zooms)
    shots, zooms, by_id, bookend, repetition = got["shots"], got["zooms"], got["by_id"], got["bookend"], got["repetition"]
    for shot, cut in zip(shots, kept):
        shot["cut_hit_percentile"], shot["cut_on_hit"] = cut["hit_pct"], cut["on_hit"]
    body = [s for s in shots if s["role"] == "body"]
    lengths = [s["duration_frames"] / fps for s in body] or [s["duration_frames"] / fps for s in shots]
    hold = shots[-1]["duration_frames"] / fps
    plan: dict[str, Any] = {
        "mode": "highlight", "style": profile.name, "style_sources": profile.source_slugs, "fps": fps, "duration_frames": total_frames, "duration_seconds": round(total_frames / fps, 2),
        "music": {"in_seconds": round(music_in, 3), "fade_out_seconds": round(min(4.0, max(1.5, 0.6 * hold)), 2)},
        "shots": shots,
        "checks": {
            "shot_count": len(shots), "shot_length_median": round(statistics.median(lengths), 2), "shot_length_mean": round(statistics.mean(lengths), 2),
            "style_median": round(statistics.median(cprof.shot_lengths), 2), "style_mean": round(statistics.mean(cprof.shot_lengths), 2),
            "cuts_on_hits": round(sum(1 for s in shots if s["cut_on_hit"]) / len(shots), 2),
            "distinct_clips": len({s["file_id"] for s in shots}),
            "moment_sources": {k: sum(1 for s in shots if s["moment_source"].startswith(k)) for k in ("steadiest", "event", "composition", "hand-set", "middle")},
            "steady": {"pace": pace, "shots_with_a_steady_window": sum(1 for s in shots if s.get("steady")), "shots_with_a_cut_inside": sum(1 for s in shots if (s.get("steady") or {}).get("cuts")),
                       "static_body_shots": sum(1 for s in body if (s.get("steady") or {}).get("static")), "slow_zooms": len(zooms)},
            "consecutive_same_scene": sum(1 for a, b in zip(shots, shots[1:]) if a["file_id"] != b["file_id"] and by_id[a["file_id"]].get("scene") and _scene_key(by_id[a["file_id"]]) == _scene_key(by_id[b["file_id"]])),
            "bookend": bookend is not None, "closing_hold_seconds": round(hold, 2), "opener_slot": with_opener,
            "repetition": repetition,
        },
        "notes": [
            "Cuts land on the music's hits (the share on a hit is in the checks) at a calm pace: shot lengths follow the corporate reference's rhythm times the pace. There is no measured corporate highlight to music, so the rhythm is the narrated reference's, adapted.",
            "Hard cuts only: no dissolves, flashes, dips or other accents. " + post_steady.moment_note(shots),
            f"Pace is {pace:g}x the reference's (1.0 = its own, higher = calmer). The song starts on a strong hit and fades out over the closing hold.",
            "Every analysed clip is a candidate for every shot. Each shot is the cleanest stretch of its clip (no cut, smooth, sharp, well exposed) that does not look like a shot already in the edit, and the edit broadly follows the shoot's order. "
            "It does not reorder footage into a story.",
            *(["Repetition: " + (f"{repetition['distinct_looks']} distinct looks in {repetition['shots']} shots; {repetition['alike_neighbours']} neighbouring pair(s) look alike"
                                 + (" -- the footage has too few different scenes to avoid repeating" if repetition["distinct_looks"] * 2 < repetition["shots"] else "") + ".")]
              if repetition and repetition.get("has_signatures") else []),
            "Which moment of each clip is used is NOT validated as your taste (moment_source says where it came from) -- review and swap.",
        ],
    }
    if fill_frame:
        plan["fit"] = "fill"
        plan["notes"].append("Every clip is scaled in Premiere to fill the frame, centred: a horizontal clip in a vertical edit becomes a centred crop with no black bars, a small clip is scaled up. "
                             "Reframe any shot whose subject sits off-centre. Clips already the frame's shape and size are left alone.")
    if zooms:
        plan["zooms"] = {"items": zooms, "note": "Slow zooms (push-in or pull-out) only on shots whose footage is static / has little action; shots that already move get none."}
        plan["notes"].append(f"{len(zooms)} of {len(body)} body shots are static footage and get a slow zoom ({sum(1 for z in zooms if z['direction'] == 'in')} push-in, {sum(1 for z in zooms if z['direction'] == 'out')} pull-out); the rest already move, so they get none.")
    return plan
