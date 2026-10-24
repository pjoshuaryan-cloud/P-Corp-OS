"""Copies the FINISHING of a cut he made by hand -- sound effects and ambience, flashes and zoom hits, zoom blur and black & white on shots, punch-ins, logo and
end card -- onto a plan that is matched to his cut slot for slot (learning/transfer_cut.py). Written for the HAUS test (2026-10-23): his finished horizontal
-> the learned vertical. Everything is read from his saved project; only what the plugin can build is copied, in the shapes it already builds (plan.accents,
plan.zooms, plan.graphics), and everything else is named in the notes. Read-only on his project and media: the sounds and images it needs are rendered into
the workspace.

What is approximated, and why (each is said in the plan's notes):
  - a flash: his ramps 0 -> peak -> 0 over its frames; the plugin sets one value, so the peak is held for the 2 frames around it;
  - a punch-in: his is Transform > Scale with eased keyframes; the plugin animates Motion > Scale, linear, over the whole shot (Transform's motion blur
    is not reproduced);
  - an image that fades out (his logo): drawn full, then in FADE_STEPS fainter copies over his fade.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app import post_accents, post_music, post_reference
from learning import prproj

TICKS = 254016000000
FLASH_FRAMES = 2
FADE_STEPS = 3
SKIP_IMAGES = ("4x3 Clean.png",)   # left out at his request (2026-10-23): a 4:3 letterbox frame drawn for a horizontal picture
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd")
GRAPHICS_TRACK = 3                 # V2 holds the flashes and zoom hits; his images go above them


def parse_keyframes(text: str | None) -> list[tuple[float, float]]:
    """Premiere's "ticks,value,...;ticks,value,...;" -> [(seconds, value)] for numeric values (a point or a flag is skipped)."""
    out = []
    for part in (text or "").split(";"):
        bits = part.split(",")
        if len(bits) < 2:
            continue
        try:
            out.append((int(bits[0]) / TICKS, float(bits[1].rstrip("."))))
        except ValueError:
            continue
    return out


def _start_value(param: Any | None) -> float | None:
    if param is None:   # an image placed at its own size by the plugin has no Scale recorded
        return None
    bits = (param.findtext("StartKeyframe") or "").split(",")
    try:
        return float(bits[1].rstrip(".")) if len(bits) > 1 else None
    except ValueError:
        return None


def _components(item: Any, ids: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """[(match name, {param name: param element})] of one timeline item."""
    comps = item.find("ClipTrackItem/ComponentOwner/Components")
    if comps is None or "ObjectRef" not in comps.attrib:
        return []
    out = []
    for ref in ids[comps.attrib["ObjectRef"]].iter("Component"):
        comp = ids.get(ref.attrib.get("ObjectRef", ""))
        if comp is None:
            continue
        params = {}
        for p in comp.iter("Param"):
            prm = ids.get(p.attrib.get("ObjectRef", ""))
            if prm is not None and prm.findtext("Name"):
                params.setdefault(prm.findtext("Name"), prm)
        out.append((comp.findtext("MatchName") or comp.tag, params))
    return out


def _animated(param: Any | None) -> list[tuple[float, float]]:
    return parse_keyframes(param.findtext("Keyframes")) if param is not None and (param.findtext("IsTimeVarying") or "").lower() == "true" else []


def _scale_param(params: dict[str, Any]) -> Any | None:
    """An effect's (uniform) scale setting. Premiere has saved it as "Scale" and -- in his HAUS project after a re-save on 2026-10-24 -- as "Scale Height"."""
    return params.get("Scale") if params.get("Scale") is not None else params.get("Scale Height")


def read_finish(project_path: str, sequence: str, out_seconds: float) -> dict[str, Any]:
    """Everything on his sequence up to `out_seconds` that isn't the picture cut itself, in seconds, with keyframe times made relative to each item's start."""
    root, ids = post_reference._load(project_path)
    seq = next((s for s in root.iter("Sequence") if s.findtext("Name") == sequence), None)
    if seq is None:
        raise ValueError(f"no sequence called {sequence!r} in {Path(project_path).name}")
    paths: dict[str, str] = {}
    for p in sorted(prproj.project_media_paths(project_path)):
        paths.setdefault(Path(p).name, p)
    found: dict[str, list[dict[str, Any]]] = {"shots": [], "overlays": [], "images": [], "titles": [], "layered_clips": [], "sounds": []}
    for tg in seq.findall("TrackGroups/TrackGroup"):
        group = ids.get(tg.find("Second").attrib.get("ObjectRef", ""))
        if group is None or group.tag not in ("VideoTrackGroup", "AudioTrackGroup"):
            continue
        video = group.tag == "VideoTrackGroup"
        for number, tr in enumerate(group.findall("TrackGroup/Tracks/Track"), 1):
            track = ids[tr.attrib["ObjectURef"]]
            for ref in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
                item = ids[ref.attrib["ObjectRef"]]
                timing = item.find("ClipTrackItem/TrackItem")
                start, end = post_reference._ticks(timing, "Start") / TICKS, post_reference._ticks(timing, "End") / TICKS
                if start >= out_seconds - 1e-3:
                    continue
                end = min(end, out_seconds)
                sub = ids[item.find("ClipTrackItem/SubClip").attrib["ObjectRef"]]
                clip = ids[sub.find("Clip").attrib["ObjectRef"]]
                name = sub.findtext("Name") or ""
                src_in = post_reference._ticks(clip, "Clip/InPoint") / TICKS
                comps = _components(item, ids)
                base = {"name": name, "path": paths.get(name), "track": number, "start": start, "end": end, "src_in": src_in}
                if not video:
                    found["sounds"].append({**base, "level_db": post_reference._audio_level_db(item, ids)})
                    continue
                matches = [m for m, _ in comps]
                if name == "Adjustment Layer":
                    for match, params in comps:
                        if match == post_accents.LUMETRI:
                            keys = [(t - src_in, v) for t, v in _animated(params.get("Exposure"))]
                            peak = max(keys, key=lambda k: k[1]) if keys else (None, _start_value(params.get("Exposure")) or 0.0)
                            found["overlays"].append({**base, "kind": "flash", "effect": match, "peak_exposure": peak[1], "peak_at": peak[0]})
                        elif match == post_accents.ZOOM_BLUR:
                            found["overlays"].append({**base, "kind": "zoom_hit", "effect": match, "params": post_reference._effect_params(item, ids).get(match, {})})
                elif name.lower().endswith(IMAGE_SUFFIXES):
                    motion = dict(next((p for m, p in comps if m == "AE.ADBE Motion"), {}))
                    pos = (motion.get("Position").findtext("StartKeyframe") or "").split(",") if motion.get("Position") is not None else []
                    try:
                        x, y = (float(v) for v in pos[1].split(":")[:2])
                    except (IndexError, ValueError):
                        x, y = 0.5, 0.5
                    opacity = dict(next((p for m, p in comps if m == "AE.ADBE Opacity"), {})).get("Opacity")
                    found["images"].append({**base, "scale": _start_value(_scale_param(motion)) or 100.0, "position": [x, y],
                                            "opacity_keys": [(t - src_in, v) for t, v in _animated(opacity)]})
                elif "AE.ADBE Text" in matches or (not base["path"] and name == "Graphic"):
                    found["titles"].append(base)
                elif number == 1:
                    geometry = dict(next((p for m, p in comps if m == "AE.ADBE Geometry2"), {}))
                    motion = dict(next((p for m, p in comps if m == "AE.ADBE Motion"), {}))
                    found["shots"].append({**base, "effects": [m for m in matches if m in (post_accents.ZOOM_BLUR, post_accents.BLACK_WHITE)],
                                           "params": post_reference._effect_params(item, ids),
                                           "punch_in": [(t - src_in, v) for t, v in _animated(_scale_param(geometry))],     # his: Transform > Scale
                                           "motion_zoom": [(t - src_in, v) for t, v in _animated(_scale_param(motion))]})  # the plugin's: Motion > Scale
                else:
                    found["layered_clips"].append({**base, "effects": matches})
    return found


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:60]


def draw_image(src: str, frame_size: tuple[int, int], scale_pct: float, position: tuple[float, float], alpha: float, out: Path) -> Path:
    """A transparent full-frame PNG with his image at `scale_pct` of its own pixels, centred at `position` (fractions of the frame), at `alpha`.
    (Measured from his previews, 2026-10-23: his logo and end card show at their files' own pixel size times his Scale -- the end card to the pixel.)"""
    w, h = frame_size
    img = Image.open(src).convert("RGBA")
    size = (max(1, round(img.width * scale_pct / 100.0)), max(1, round(img.height * scale_pct / 100.0)))
    img = img.resize(size, Image.LANCZOS)
    if alpha < 1.0:
        a = np.asarray(img).copy()
        a[:, :, 3] = (a[:, :, 3].astype(float) * alpha).round().astype(np.uint8)
        img = Image.fromarray(a, "RGBA")
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(img, (round(position[0] * w - size[0] / 2), round(position[1] * h - size[1] / 2)))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def _fade_out(keys: list[tuple[float, float]], length: float) -> tuple[float, float] | None:
    """(fade start, fade end) in seconds from the image's start when its opacity goes from full to (near) nothing, else None."""
    if len(keys) < 2:
        return None
    keys = sorted(keys)
    (t0, v0), (t1, v1) = keys[0], keys[-1]
    return (max(0.0, t0), min(length, t1)) if v0 >= 90 and v1 <= 10 and t1 > t0 else None


def finish_for_plan(project_path: str, sequence: str, plan: dict[str, Any], folder: Path, frame_size: tuple[int, int], music_name: str | None) -> dict[str, Any]:
    """{"accents", "zooms", "graphics", "notes", "counts"} for `plan` (whose shots start on his cut points) from his finishing on `sequence`."""
    fps = plan["fps"]
    frames_at = {s["start_frame"]: s for s in plan["shots"]}
    cut_frames = sorted(frames_at)
    f = read_finish(project_path, sequence, plan["duration_frames"] / fps)
    notes: list[str] = []
    fr = lambda t: round(t * fps)   # noqa: E731

    def nearest_cut(frame: int) -> int:
        return min(range(len(cut_frames)), key=lambda k: abs(cut_frames[k] - frame)) + 1

    # ---- per-shot effects and punch-ins, on the slot that starts where his shot starts
    shot_effects, zooms, unmatched = [], [], 0
    eased = timing_off = 0
    for s in f["shots"]:
        slot = frames_at.get(fr(s["start"]))
        if slot is None:
            unmatched += 1
            continue
        for effect in s["effects"]:
            shot_effects.append({"shot_index": slot["index"], "effect": effect, "params": s["params"].get(effect, {}) if effect == post_accents.ZOOM_BLUR else {}})
        if len(s["punch_in"]) >= 2:
            (t0, v0), (t1, v1) = s["punch_in"][0], s["punch_in"][-1]
            lo, hi = min(v0, v1), max(v0, v1)
            if lo > 0 and hi > lo:
                zooms.append({"shot_index": slot["index"], "start_frame": slot["start_frame"], "frames": slot["duration_frames"],
                              "direction": "in" if v1 > v0 else "out", "percent": round((hi / lo - 1) * 100, 2)})
                eased += 1
                timing_off += abs(t0) > 1.5 / fps or abs(t1 - (s["end"] - s["start"])) > 1.5 / fps
    if unmatched:
        notes.append(f"{unmatched} of your shots didn't line up with a slot, so their effects weren't copied.")

    # ---- flashes and zoom hits (adjustment layers)
    flashes, zoom_hits = [], []
    for o in f["overlays"]:
        start, frames = fr(o["start"]), max(1, fr(o["end"]) - fr(o["start"]))
        if o["kind"] == "flash":
            if o["peak_at"] is not None and frames > FLASH_FRAMES:
                centre = fr(o["start"] + o["peak_at"])
                start, frames = max(start, centre - FLASH_FRAMES // 2), FLASH_FRAMES
            flashes.append({"kind": "flash", "cut_index": nearest_cut(start), "start_frame": start, "frames": frames, "where": "yours",
                            "effect": post_accents.LUMETRI, "params": {"Exposure": round(float(o["peak_exposure"]), 2)}})
        else:
            zoom_hits.append({"kind": "zoom_hit", "cut_index": nearest_cut(start), "start_frame": start, "frames": frames, "effect": post_accents.ZOOM_BLUR,
                              "params": dict(o["params"])})

    # ---- sounds: every one but the song (that is plan["music"]), cut at his in point, length and level; his tracks keep their order from A3 up (music is on A2)
    sounds = [s for s in f["sounds"] if s["name"] != music_name]
    tracks = sorted({s["track"] for s in sounds})
    sfx, missing = [], []
    for s in sounds:
        if not s["path"] or not Path(s["path"]).exists():
            missing.append(s["name"])
            continue
        start, frames = fr(s["start"]), max(2, fr(s["end"]) - fr(s["start"]))
        level = s["level_db"] or 0.0
        out = folder / "sounds" / f"{_safe(Path(s['name']).stem)}_{s['src_in']:.3f}s_{frames}f{f'_{level:+.1f}dB' if level else ''}.wav"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            asyncio.run(post_music.render_music_cut(s["path"], str(out), s["src_in"], frames / fps, fade_out=0.0, gain_db=level, fade_in=0.0))
        sfx.append({"role": "yours", "file": str(out), "name": s["name"], "start_frame": start, "frames": frames, "track": 3 + tracks.index(s["track"])})
    sfx = post_accents._cut_sounds_at_next_on_track(sfx)
    if missing:
        notes.append(f"Not found, so not placed: {', '.join(sorted(set(missing)))}.")

    # ---- images (logo, end card): drawn full-frame at his size and place; a fade-out becomes FADE_STEPS fainter copies
    cards, skipped_images = [], []
    for im in sorted(f["images"], key=lambda x: x["start"]):
        if im["name"] in SKIP_IMAGES:
            skipped_images.append(im["name"])
            continue
        if not im["path"] or not Path(im["path"]).exists():
            missing.append(im["name"])
            continue
        start, end = fr(im["start"]), fr(im["end"])
        if any(start < c["end_frame"] for c in cards):
            notes.append(f"\"{im['name']}\" overlaps another image of yours, so it wasn't placed.")
            continue
        stem = f"{_safe(Path(im['name']).stem)}_{frame_size[0]}x{frame_size[1]}_{im['scale']:g}pct"
        fade = _fade_out(im["opacity_keys"], im["end"] - im["start"])
        solid_end = start + fr(fade[0]) if fade else end
        pieces = [(start, solid_end, 1.0)]
        if fade and end > solid_end:
            edges = [solid_end + round((end - solid_end) * k / FADE_STEPS) for k in range(FADE_STEPS + 1)]
            pieces += [(edges[k], edges[k + 1], 1.0 - (k + 0.5) / FADE_STEPS) for k in range(FADE_STEPS) if edges[k + 1] > edges[k]]
        for a, b, alpha in pieces:
            if b <= a:
                continue
            out = folder / "graphics" / f"{stem}_{round(alpha * 100)}.png"
            if not out.exists():
                draw_image(im["path"], frame_size, im["scale"], tuple(im["position"]), alpha, out)
            cards.append({"file": str(out), "start_frame": a, "frames": b - a, "end_frame": b, "name": im["name"]})
    for c in cards:
        c.pop("end_frame")

    if skipped_images:
        notes.append(f"Left out at your request: {', '.join(sorted(set(skipped_images)))} (and nothing replaces it).")
    if f["titles"]:
        notes.append(f"Your titles ({len(f['titles'])} text item(s)) aren't copied: the plugin can't create text. Copy them from \"{sequence}\" and paste them in.")
    if f["layered_clips"]:
        notes.append(f"Not copied: {len(f['layered_clips'])} extra layer(s) of footage above your cut ("
                     + ", ".join(sorted({f'{c["name"]} on V{c["track"]}' for c in f["layered_clips"]})) + ").")
    if flashes:
        notes.append(f"Flashes: your {len(flashes)} at the same spots and peak (+{max(x['params']['Exposure'] for x in flashes):g} exposure), held for "
                     f"{FLASH_FRAMES} frames (yours ramp up and down over 4).")
    if zooms:
        notes.append(f"Punch-ins: your {len(zooms)}, same direction and size, animated with Motion > Scale over the whole shot (yours: Transform > Scale, eased"
                     + (f"; {timing_off} of yours don't span the whole shot" if timing_off else "") + ").")
    if any(c["name"] for c in cards):
        notes.append("Logo and end card: your files at your size and place, drawn for the vertical frame" + (f"; your logo's fade-out is done in {FADE_STEPS} steps" if any(
            _fade_out(im["opacity_keys"], im["end"] - im["start"]) for im in f["images"] if im["name"] not in SKIP_IMAGES) else "") + ".")
    accents = {"style": f"copied from your finished \"{sequence}\"", "flashes": flashes, "zoom_hits": sorted(zoom_hits, key=lambda z: z["start_frame"]),
               "shot_effects": sorted(shot_effects, key=lambda e: (e["shot_index"], e["effect"])), "logo": None, "sfx": sfx, "notes": [],
               "counts": {"flashes": len(flashes), "zoom_hits": len(zoom_hits), "shot_zoom_blur": sum(e["effect"] == post_accents.ZOOM_BLUR for e in shot_effects),
                          "black_and_white_shots": sum(e["effect"] == post_accents.BLACK_WHITE for e in shot_effects), "logo": 0, "sfx": len(sfx)},
               "overlay_track": post_accents.OVERLAY_VIDEO_TRACK}
    graphics = {"frame_size": list(frame_size), "tracks": {"cards": GRAPHICS_TRACK}, "cards": [{k: c[k] for k in ("file", "start_frame", "frames")} for c in cards]} if cards else None
    return {"accents": accents, "zooms": {"items": zooms} if zooms else None, "graphics": graphics, "notes": notes,
            "counts": {**accents["counts"], "punch_ins": len(zooms), "images": len(cards), "sounds": len(sfx)}}


# ================================================================================================ finishing as Learn From My Edit reads it (2026-10-23)
# What a sequence carries besides its picture cut, as positions (frames) per kind, and -- for a sequence P Corp built from a plan -- how much of the planned
# finishing he kept, removed or added. Read from the saved project like the picture cut; recorded with every Learn click so his finishing choices become data.
FINISH_KINDS = ("flashes", "zoom_hits", "shot_effects", "punch_ins", "sounds", "images")
_EFFECT_SHORT = {post_accents.ZOOM_BLUR: "zoom blur", post_accents.BLACK_WHITE: "black & white"}


def found_finish(f: dict[str, Any], fps: float) -> dict[str, list[tuple]]:
    """read_finish's result as {kind: [(start frame, detail), ...]} on the sequence's frame grid."""
    fr = lambda t: round(t * fps)   # noqa: E731
    punch = []
    for s in f["shots"]:
        keys = s["punch_in"] if len(s["punch_in"]) >= 2 else s.get("motion_zoom") or []
        if len(keys) >= 2:
            punch.append((fr(s["start"]), "in" if keys[-1][1] > keys[0][1] else "out"))
    return {"flashes": sorted((fr(o["start"]),) for o in f["overlays"] if o["kind"] == "flash"),
            "zoom_hits": sorted((fr(o["start"]),) for o in f["overlays"] if o["kind"] == "zoom_hit"),
            "shot_effects": sorted((fr(s["start"]), _EFFECT_SHORT[e]) for s in f["shots"] for e in s["effects"]),
            "punch_ins": sorted(punch),
            "sounds": sorted((fr(s["start"]), s["track"]) for s in f["sounds"]),
            "images": sorted((fr(i["start"]), i["track"]) for i in f["images"])}


def planned_finish(plan: dict[str, Any]) -> dict[str, list[tuple]]:
    """The same shape for what a plan asked the plugin to build (its accents, zooms, music and images)."""
    acc = plan.get("accents") or {}
    starts = {s["index"]: s["start_frame"] for s in plan.get("shots") or []}
    g = plan.get("graphics") or {}
    tracks = g.get("tracks") or {}
    images = [(c["start_frame"], tracks.get("cards") or 2) for c in g.get("cards") or []]
    if g.get("logo_bug"):
        images.append((g["logo_bug"]["start_frame"], tracks.get("logo_bug") or 3))
    images += [(c["start_frame"], tracks.get("captions") or 4) for c in (g.get("captions") or {}).get("burned_in") or []]
    if acc.get("logo"):
        images.append((acc["logo"]["start_frame"], acc["logo"]["track"]))
    return {"flashes": sorted((x["start_frame"],) for x in acc.get("flashes") or []),
            "zoom_hits": sorted((x["start_frame"],) for x in acc.get("zoom_hits") or []),
            "shot_effects": sorted((starts[e["shot_index"]], _EFFECT_SHORT.get(e["effect"], e["effect"])) for e in acc.get("shot_effects") or [] if e["shot_index"] in starts),
            "punch_ins": sorted((z["start_frame"], z["direction"]) for z in (plan.get("zooms") or {}).get("items") or []),
            "sounds": sorted([(x["start_frame"], x["track"]) for x in acc.get("sfx") or []] + ([(0, 2)] if (plan.get("music") or {}).get("cut_path") else [])),
            "images": sorted(images)}


def compare_finish(planned: dict[str, list[tuple]], found: dict[str, list[tuple]], tolerance: int = 1) -> dict[str, dict[str, Any]]:
    """Per kind: how many planned items are still there (same detail, start within `tolerance` frames), and the start frames of those he removed or moved
    away from, and of those he added or moved to (a moved item shows on both sides)."""
    out = {}
    for kind in FINISH_KINDS:
        want, have, used, kept, removed = planned.get(kind, []), found.get(kind, []), set(), 0, []
        for p in want:
            j = next((j for j, h in enumerate(have) if j not in used and h[1:] == p[1:] and abs(h[0] - p[0]) <= tolerance), None)
            if j is None:
                removed.append(p[0])
            else:
                used.add(j)
                kept += 1
        out[kind] = {"planned": len(want), "kept": kept, "removed_or_moved_from": removed, "added_or_moved_to": [h[0] for j, h in enumerate(have) if j not in used]}
    return out


def finish_lines(found: dict[str, list[tuple]], f: dict[str, Any], comparison: dict[str, dict[str, Any]] | None) -> list[str]:
    """What the plugin prints about the finishing."""
    n = {k: len(v) for k, v in found.items()}
    fx = found["shot_effects"]
    have = (f"{n['flashes']} flash(es), {n['zoom_hits']} zoom hit(s), zoom blur on {sum(1 for x in fx if x[1] == 'zoom blur')} shot(s), black & white on "
            f"{sum(1 for x in fx if x[1] == 'black & white')}, {n['punch_ins']} punch-in(s), {n['sounds']} sound(s), {n['images']} image(s), {len(f['titles'])} title(s)")
    if comparison is None:
        return [f"Finishing in your edit (saved for the learning data): {have}."]
    labels = {"flashes": "flashes", "zoom_hits": "zoom hits", "shot_effects": "shot effects", "punch_ins": "punch-ins", "sounds": "sounds", "images": "images"}
    kept = ", ".join(f"{labels[k]} {c['kept']} of {c['planned']}" for k, c in comparison.items() if c["planned"])
    changed = sum(len(c["removed_or_moved_from"]) for c in comparison.values())
    added = sum(len(c["added_or_moved_to"]) for c in comparison.values())
    return [f"Finishing now: {have}.",
            (f"Of the finishing P Corp built, still where it was put: {kept}. You removed or moved {changed} and added or moved to {added} "
             "(each one is in the feedback log)." if kept else "The plan had no finishing to compare with.")]
