"""
POST (2026-10-13) -- builds a saved reference edit from a FINISHED VIDEO (an export), in the same record format the
planner already reads (post_reference.py), plus a `video_analysis` block with everything measured.

    build_video_reference(path, slug, tags, client)   # does the whole job: frames, audio, shot labels, save
    assemble_record(...)                              # the pure part (used when the pieces were measured earlier)

Measured in post_reference_video.py / post_reference_audio.py (validated against footage with known answers) and labelled
in post_reference_vision.py (Claude, a few cents per video). What a reference built this way does NOT carry: exact effect
values, sound-effect files, or which source clip a shot came from -- there is no project file behind it.
"""

from __future__ import annotations

import asyncio
from statistics import median
from typing import Any

import numpy as np

from app import post_reference as pr
from app import post_reference_audio as ra
from app import post_reference_video as rv
from app import post_reference_vision as rvis

_DRIVER_TO_TYPE = {"music": "music_montage", "pauses": "dialogue_led", "pictures": "narrated_broll"}


def pacing_stats(lengths: list[float], shots: list[dict], duration: float) -> dict[str, Any]:
    arr = np.array(lengths)
    by_tenth = []
    for b in range(10):
        inside = [l for s, l in zip(shots, lengths) if min(9, int(s["start"] / duration * 10)) == b]
        by_tenth.append(round(float(np.mean(inside)), 2) if inside else None)
    return {"mean": round(float(arr.mean()), 3), "median": round(float(np.median(arr)), 3), "p10": round(float(np.percentile(arr, 10)), 3), "p90": round(float(np.percentile(arr, 90)), 3),
            "min": round(float(arr.min()), 3), "max": round(float(arr.max()), 3), "share_under_half_second": round(float(np.mean(arr < 0.5)), 3),
            "share_under_one_second": round(float(np.mean(arr < 1.0)), 3), "share_3s_or_more": round(float(np.mean(arr >= 3.0)), 3), "by_tenth": by_tenth}


def rhythm_in_beats(lengths: list[float], tempo_bpm: float | None) -> dict[str, Any] | None:
    """Shot lengths against the music's beat. The tempo estimate can come out at half or double the felt tempo, so this is a
    description of the edit relative to THAT estimate."""
    if not tempo_bpm:
        return None
    beat = 60.0 / tempo_bpm
    units = np.array(lengths) / beat
    edges = [0, 0.5, 1, 2, 4, 1e9]
    names = ["under half a beat", "half to one beat", "one to two beats", "two to four beats", "four beats or more"]
    return {"tempo_bpm": tempo_bpm, "beat_seconds": round(beat, 3), "median_shot_in_beats": round(float(np.median(units)), 2),
            "share": {n: round(float(np.mean((units >= lo) & (units < hi))), 3) for n, lo, hi in zip(names, edges, edges[1:])}}


def _describe_shot(label: dict | None) -> str:
    if not label:
        return "unlabelled"
    subject = str(label.get("subject", "")).replace("_", " ")
    out = f"{subject} ({label.get('size')})"
    if label.get("text") in ("logo", "title") and label.get("text_words"):
        out += f" with the text '{label['text_words']}'"
    return out


def structure_of(vis: dict[str, Any], labels: list[dict], audio: dict[str, Any], duration: float, fps: float) -> dict[str, Any]:
    """How the edit opens and closes, from the shots Claude labelled (the first two and last two are always among them in new builds)."""
    shots = vis["shots"]
    by = {l["shot_index"]: l for l in labels}
    last = len(shots) - 1
    say = lambda idx: [_describe_shot(by[i]) for i in idx if i in by]
    ends_dip = any(d["time"] >= duration - 1.2 for d in vis["dips"])  # a black stretch in the last 1.2 s
    return {"first_shot_seconds": round(shots[0]["end"] - shots[0]["start"], 3), "last_shot_seconds": round(shots[-1]["end"] - shots[-1]["start"], 3),
            "opens_on": " then ".join(say(range(0, min(2, len(shots))))) or "not labelled",
            "closes_on": " then ".join(say(range(max(0, last - 1), last + 1))) or "not labelled", "ends_with_dip_to_black": bool(ends_dip)}


def assemble_record(slug: str, tags: dict[str, Any], path: str, info: dict[str, Any], vis: dict[str, Any], audio: dict[str, Any],
                    labels: list[dict], overlay: dict[str, Any] | None, sequence_name: str, dialogue: dict[str, Any] | None = None) -> tuple[dict, dict, dict | None, dict]:
    """(edit, tags, music_sync, extra) ready for post_reference.save_reference."""
    shots = vis["shots"]
    lengths = [s["end"] - s["start"] for s in shots]
    duration = round(max(s["end"] for s in shots), 2)
    edit_shots = [{"name": f"shot {i + 1:03d}", "start": s["start"], "end": s["end"], "source_in": 0.0, "source_out": round(s["end"] - s["start"], 3), "effects": [], "params": {}, "track": 1,
                   "opens_with": s["opens_with"], "motion": s["motion"], "mean_luma": s["mean_luma"], "mean_chroma": s["mean_chroma"]} for i, s in enumerate(shots)]
    flash_pos = rv.attach_flash_positions(vis, info["fps"])
    flash_notes = None
    if flash_pos["count"]:
        flash_notes = (f"Flashes: {', '.join(str(f['frames']) + ' frame' + ('' if f['frames'] == 1 else 's') for f in vis['flashes'])} long; {_p(flash_pos['on_a_cut_share'])} sit on a cut "
                       f"(their start relative to the nearest cut, in frames: {flash_pos['frames_from_nearest_cut']}).")
    driver = audio.get("cuts_follow") if audio.get("has_audio") else None
    edit_type = tags.get("edit_type") or _DRIVER_TO_TYPE.get(driver or "")
    tags = {**tags, "edit_type": edit_type}
    sync_any = (audio.get("music_sync_any_hit") or {}) if audio.get("has_audio") else {}
    music_sync = None
    if edit_type == "music_montage":
        music_sync = {"cuts_within_40ms_of_a_strong_hit": sync_any.get("share_on_hits_at_that_offset"), "cut_lead_ms": sync_any.get("best_offset_ms"),
                      "chance": sync_any.get("chance_at_that_offset"),
                      "note": "Measured from the export's own audio. 'cuts_within_40ms_of_a_strong_hit' holds the share of cuts on ANY detected hit within 25 ms at the common lead (cut_lead_ms = how many ms before the hit the cut sits); same key as references read from a project so the planner reads both alike."}
    edit = {"source_project": path, "source_kind": "exported_video", "sequence": sequence_name, "duration_seconds": duration, "shots": edit_shots, "overlays": [], "graphics": [], "audio": [],
            "observed": {"flashes": vis["flashes"], "dissolves": vis["dissolves"], "dips": vis["dips"], "fades": vis["fades"], "bw_runs": vis["bw_runs"], "persistent_overlay": overlay}}
    extra = {"video_analysis": {
        "video": {"width": info["width"], "height": info["height"], "fps": info["fps"], "duration": info["duration"], "vfr": info.get("vfr", False), "has_audio": info["has_audio"]},
        "pacing": pacing_stats(lengths, shots, duration),
        "transitions": {"hard_cuts": len(vis["hard_cuts"]), "dissolves": len(vis["dissolves"]), "dips": len(vis["dips"]), "fades": len(vis["fades"]), "flashes": len(vis["flashes"]),
                        "bw_runs": len(vis["bw_runs"]), "blur_at_cuts": vis["blur_at_cuts"], "flash_notes": flash_notes,
                        "dissolve_frames": [d["frames"] for d in vis["dissolves"]], "bw_seconds": [round(b["seconds"], 2) for b in vis["bw_runs"]]},
        "audio": audio, "rhythm": rhythm_in_beats(lengths, audio.get("tempo_bpm")) if edit_type == "music_montage" else None,
        "structure": structure_of(vis, labels, audio, duration, info["fps"]),
        "content": {**rvis.summarize_labels(labels, len(shots)), "labels": labels}, "persistent_overlay": overlay,
        "dialogue": dialogue, "how_measured": "Every frame decoded (160 px) and analysed in post_reference_video.py; audio in post_reference_audio.py; shot labels by Claude from contact sheets (a sample when the edit has many shots). Validated against footage with known cuts/dissolves/flashes/B&W/overlay before use. Exact effect values are not recoverable from a video."}}
    return edit, tags, music_sync, extra


def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def save_assembled(slug: str, edit: dict, tags: dict, music_sync: dict | None, extra: dict) -> str:
    return str(pr.save_reference(slug, edit, tags, music_sync, extra))


async def build_video_reference(path: str, slug: str, tags: dict[str, Any], client: Any = None, sequence_name: str | None = None) -> dict[str, Any]:
    """Frames -> cuts/dissolves/flashes/B&W/overlay, audio -> what the cuts follow, Claude -> shot labels (if `client`), then saves."""
    features = await asyncio.to_thread(rv.extract_features, path)
    vis = await asyncio.to_thread(rv.analyze_visual, features)
    overlay = rv.detect_persistent_overlay(features)
    cuts = [s["start"] for s in vis["shots"][1:]]
    audio = await asyncio.to_thread(ra.analyze_audio, path, cuts, features.fps) if features.info["has_audio"] else {"has_audio": False}
    labels: list[dict] = []
    if client is not None:
        labels = await rvis.describe_shots(client, path, vis["shots"], vertical=features.info["height"] > features.info["width"])
    dialogue = None
    if audio.get("cuts_follow") == "pauses":  # a dialogue-led edit: record how its cuts sit in the speech and how its angles alternate
        dialogue = {**rv.angle_pattern(features, vis["shots"]), "speech": await asyncio.to_thread(ra.pause_cut_stats, path, cuts)}
    edit, tags, music_sync, extra = assemble_record(slug, tags, path, features.info, vis, audio, labels, overlay, sequence_name or slug, dialogue)
    save_assembled(slug, edit, tags, music_sync, extra)
    return {"slug": slug, "edit_type": tags.get("edit_type"), "shots": len(edit["shots"]), "cuts_follow": audio.get("cuts_follow")}
