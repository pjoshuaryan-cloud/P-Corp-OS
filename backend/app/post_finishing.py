"""POST finishing plan for a sectioned edit (Rabit Haus event recap), reel autopilot phase 3 step 3 (2026-11-17).

Measured on Rabit Haus's three event recaps: over nine in ten joins are hard cuts, with two to four blur moves (a whip or a smear of motion) where the
location changes; few or no whoosh-like sounds, under a blur move when there is one; the music tails off under the last ~4 s. This module decides,
for a plan already built in sections (post_edit_highlight), WHERE those blur moves go and which whoosh sits under each, and sets the music fade.

  * Blur moves only at a join between two sections (a change of section is a change of place in the recap), preferring the joins into the place,
    the main moment and the close; two to four of them, at least MIN_GAP_SECONDS apart, and only where both shots have enough footage beyond the cut
    for Premiere to run the transition (HANDLE_SECONDS each side).
  * The transition is Premiere's own whip ("AE.ADBE Whip"), proven to place and render by step 0 on 2026-11-17.
  * Under each blur move, a whoosh from the catalogued library whose loudest moment lands on the cut (post_accents' rule), on A4. Skipped when the
    library index has no usable whooshes.
  * The music fade is MUSIC_TAIL_SECONDS: the rendered music cut really fades over it.
Pure: no files, no network. Premiere doesn't place the blur moves or whooshes yet (that is phase 4); the plan carries them as `finishing`.
"""
from __future__ import annotations

from typing import Any

BLUR_MOVE = "AE.ADBE Whip"
MOVE_SECONDS = 0.4          # the transition's length, centred on the cut
HANDLE_SECONDS = 0.25       # footage each shot needs beyond the cut for a centred transition of MOVE_SECONDS
MIN_MOVES, MAX_MOVES = 2, 4
MIN_GAP_SECONDS = 5.0       # Rabit Haus: 2-4 blur moves in 35 s, never bunched
MUSIC_TAIL_SECONDS = 4.0    # their music tails off under the last ~4 s
WHOOSH_TRACK = 4            # A4, as the accents use (music is on A2)
# Which section a blur move leads INTO, best first: a new place, the event's peak, the close; then the rest
INTO_PREFERENCE = {"place": 1.0, "main moment": 0.9, "close": 0.8, "details": 0.6, "people": 0.5}


def section_joins(shots: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """(index of the last shot of a section, index of the first shot of the next) for every change of section, in timeline order."""
    out = []
    for i in range(1, len(shots)):
        a, b = shots[i - 1].get("section"), shots[i].get("section")
        if a and b and a != b:
            out.append((i - 1, i))
    return out


def _has_handles(shot_out: dict[str, Any], shot_in: dict[str, Any], clips_by_id: dict[int, dict[str, Any]]) -> bool:
    out_clip = clips_by_id.get(shot_out["file_id"]) or {}
    room_after = float(out_clip.get("duration") or 0.0) - float(shot_out["source_out"])
    room_before = float(shot_in["source_in"])
    return room_after >= HANDLE_SECONDS and room_before >= HANDLE_SECONDS


def choose_moves(shots: list[dict[str, Any]], fps: float, clips_by_id: dict[int, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the blur moves, every section change considered). See the module docstring for the rules."""
    candidates = []
    for a, b in section_joins(shots):
        if shots[a]["file_id"] == shots[b]["file_id"]:
            continue   # the same clip either side isn't a change of place
        into = shots[b].get("section")
        candidates.append({"from_shot": shots[a]["index"], "to_shot": shots[b]["index"], "cut_frame": shots[b]["start_frame"], "into_section": into,
                           "score": INTO_PREFERENCE.get(into, 0.3), "handles": _has_handles(shots[a], shots[b], clips_by_id)})
    chosen: list[dict[str, Any]] = []
    gap = round(MIN_GAP_SECONDS * fps)
    for c in sorted((c for c in candidates if c["handles"]), key=lambda c: (-c["score"], c["cut_frame"])):
        if len(chosen) >= MAX_MOVES:
            break
        if all(abs(c["cut_frame"] - o["cut_frame"]) >= gap for o in chosen):
            chosen.append(c)
    chosen.sort(key=lambda c: c["cut_frame"])
    frames = max(2, round(MOVE_SECONDS * fps))
    moves = [{"cut_frame": c["cut_frame"], "from_shot": c["from_shot"], "to_shot": c["to_shot"], "into_section": c["into_section"],
              "transition": BLUR_MOVE, "frames": frames, "alignment": "centre"} for c in chosen]
    return moves, candidates


def plan_whooshes(moves: list[dict[str, Any]], fps: float, sfx_index: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from app.post_accents import WHOOSH_MAX_TAIL_SECONDS, WHOOSH_PEAK_RANGE_SECONDS, MIN_SFX_FRAMES
    whooshes = sorted((x for x in (sfx_index or []) if x.get("role") == "whoosh" and WHOOSH_PEAK_RANGE_SECONDS[0] <= x.get("peak_seconds", 0) <= WHOOSH_PEAK_RANGE_SECONDS[1]),
                      key=lambda x: x["name"])
    if not whooshes:
        return []
    out = []
    for k, m in enumerate(moves):
        w = whooshes[(k * 7) % len(whooshes)]   # a different whoosh for each move, deterministically
        start = m["cut_frame"] - round(w["peak_seconds"] * fps)   # its loudest moment on the cut
        if start < 0:
            continue
        frames = max(MIN_SFX_FRAMES, min(round((w["peak_seconds"] + min(w["tail_seconds"], WHOOSH_MAX_TAIL_SECONDS)) * fps), round(w["seconds"] * fps)))
        out.append({"role": "whoosh", "file": w["path"], "name": w["name"], "start_frame": start, "frames": frames, "track": WHOOSH_TRACK, "under_move_at": m["cut_frame"]})
    return out


def plan_finishing(plan: dict[str, Any], fps: float, clips_by_id: dict[int, dict[str, Any]], sfx_index: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The finishing for a sectioned plan, and the music fade set on the plan. Returns what goes in plan["finishing"]."""
    moves, candidates = choose_moves(plan["shots"], fps, clips_by_id)
    sfx = plan_whooshes(moves, fps, sfx_index)
    plan["music"]["fade_out_seconds"] = MUSIC_TAIL_SECONDS
    notes = [f"{len(moves)} blur move(s) ({BLUR_MOVE.split('.')[-1].replace('ADBE ', '')}, {MOVE_SECONDS:g} s) where the section changes"
             + (": into " + ", ".join(m["into_section"] for m in moves) if moves else "") + "; every other join is a hard cut."]
    if len(moves) < MIN_MOVES:
        short = sum(1 for c in candidates if not c["handles"])
        notes.append(f"Fewer than {MIN_MOVES} blur moves fit: " + (f"{short} section change(s) had too little footage either side of the cut. " if short else "")
                     + f"They're also kept {MIN_GAP_SECONDS:g} s apart.")
    notes.append(f"{len(sfx)} whoosh(es) under the blur moves, loudest moment on the cut." if sfx else
                 "No whooshes: the sound-effect catalogue has no usable whooshes (plug in the Joshx SSD and catalogue it).")
    notes.append(f"The music tails off over the last {MUSIC_TAIL_SECONDS:g} s.")
    notes.append("Planned, not yet placed: Build My Edit doesn't add the blur moves or their whooshes until phase 4.")
    return {"transitions": moves, "sfx": sfx, "music_fade_seconds": MUSIC_TAIL_SECONDS, "built_by_premiere": False, "notes": notes}
