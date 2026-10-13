"""
POST (2026-10-09) -- accents: the flashes, zoom hits, per-shot zoom blur, black & white closing shots, logo and
(optional) sound effects that dress a cut, placed from a style's measured rules (post_style.AccentStyle).

Draft 01's accents were measured from the edit itself: flashes (2-frame Lumetri Exposure +6.2 adjustment layers)
cluster in flurries of very short shots; zoom hits (4-frame Impact Zoom Blur adjustment layers) land on strong
music hits after a longer shot; both start a frame or two BEFORE a cut; ~22% of shots carry their own zoom blur,
mostly early and on strong hits; the last two shots go black & white under the client logo with a flash.
This module reproduces that pattern for a new edit. It does NOT claim to reproduce his exact placement -- it
applies his rules; he can delete or move any accent in Premiere (they are ordinary adjustment layers/effects).

Everything is deterministic (strongest hits first, then a seeded tie-break), pure (no I/O) except build_sfx_index.
"""

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any

import numpy as np

from app.post_style import FLURRY_SHOT_SECONDS, AccentStyle
from app.ssd_guard import on_drive

# Parameters that equal the effect's default when it is first added: not worth a keyframe action each
_LUMETRI_DEFAULTS = {"Exposure": 0.0, "Contrast": 0.0, "Highlights": 0.0, "Shadows": 0.0, "Whites": 0.0, "Blacks": 0.0, "Saturation": 100.0, "Temperature": 0.0, "Tint": 0.0}
LUMETRI = "AE.ADBE Lumetri"
ZOOM_BLUR = "AE.Impact_Zoom_Blur_FX"
BLACK_WHITE = "AE.ADBE Black & White"
OVERLAY_VIDEO_TRACK = 2  # V2 holds the adjustment layers
LOGO_VIDEO_TRACK = 4  # V4 holds the logo
SFX_HIT_AUDIO_TRACK = 3  # A3
SFX_WHOOSH_AUDIO_TRACK = 4  # A4 (music is on A2)
FLASH_COOLDOWN_FRAMES = 3  # two flashes never overlap
SFX_LIBRARY_ROOT = "/Volumes/Joshx SSD/ALPHA MODE ASSETS/SFX Collection"
SFX_INDEX_PATH = Path(__file__).resolve().parent.parent / "data" / "post_sfx_index.json"
SFX_ROLE_BY_FOLDER = {"Hits": "hit", "Whooshes": "whoosh"}
HIT_MAX_PEAK_SECONDS = 0.6  # a usable hit has its loudest moment right at the start of the file
WHOOSH_PEAK_RANGE_SECONDS = (0.4, 3.0)  # a whoosh's loudest moment is part-way in; that moment is lined up with the cut
MIN_SFX_FRAMES = 2
HIT_MAX_TAIL_SECONDS = 0.5
WHOOSH_MAX_TAIL_SECONDS = 0.8


def _non_default(params: dict[str, float], defaults: dict[str, float]) -> dict[str, float]:
    return {k: v for k, v in params.items() if abs(v - defaults.get(k, float("nan"))) > 1e-9}


def _rng_pick(rng: random.Random, items: list) -> Any:
    return items[rng.randrange(len(items))] if items else None


def _cut_sounds_at_next_on_track(sfx: list[dict]) -> list[dict]:
    """Two sounds can't overlap on one audio track: placing the second overwrites the end of the first (a flurry
    repeats the same hit ~16 frames apart, but a hit rings longer than that). So each sound is shortened to end where
    the next one on its track starts -- what Premiere would do anyway, now written into the plan. A sound left with
    under MIN_SFX_FRAMES is dropped (the next one would swallow it). Order of the list is kept."""
    by_track: dict[int, list[dict]] = {}
    for s in sfx:
        by_track.setdefault(s["track"], []).append(s)
    dropped: set[int] = set()
    for items in by_track.values():
        items.sort(key=lambda s: s["start_frame"])
        for cur, nxt in zip(items, items[1:]):
            room = nxt["start_frame"] - cur["start_frame"]
            if room < MIN_SFX_FRAMES:
                dropped.add(id(cur))
            elif cur["frames"] > room:
                cur["frames"] = room
    return [s for s in sfx if id(s) not in dropped]


async def build_sfx_index(root: str = SFX_LIBRARY_ROOT, concurrency: int = 8) -> list[dict[str, Any]]:
    """Scans the sound-effect library once: [{"path", "name", "role" (hit|whoosh), "seconds"}]. Only the
    folders in SFX_ROLE_BY_FOLDER are indexed. Cached at SFX_INDEX_PATH (delete it to rescan)."""
    def list_library_files() -> list[tuple[str, str]]:
        found = []
        for folder, role in SFX_ROLE_BY_FOLDER.items():
            for dirpath, _dirs, names in os.walk(os.path.join(root, folder)):
                found += [(os.path.join(dirpath, n), role) for n in names if not n.startswith(".") and n.lower().endswith((".wav", ".mp3", ".aif", ".aiff", ".m4a", ".flac"))]
        return found
    files = await on_drive(list_library_files, timeout=60.0)  # the library lives on the external drive
    from app import post_music
    sem = asyncio.Semaphore(concurrency)

    async def probe(path: str, role: str):
        async with sem:
            try:
                samples = await post_music._decode_mono(path)
            except post_music.MusicAnalysisError:
                return None
        window = int(post_music.SAMPLE_RATE * 0.01)
        usable = len(samples) // window
        if usable < 3:
            return None
        rms = np.sqrt((samples[: usable * window].reshape(usable, window) ** 2).mean(axis=1))
        smooth = np.convolve(rms, np.ones(3) / 3, mode="same")
        peak_i = int(np.argmax(smooth))
        peak = float(smooth[peak_i])
        if peak < 1e-4:
            return None  # silent file
        after = np.where(smooth[peak_i:] < 0.1 * peak)[0]
        tail = (after[0] if len(after) else len(smooth) - peak_i) * 0.01
        return {"path": path, "name": os.path.basename(path), "role": role, "seconds": round(len(samples) / post_music.SAMPLE_RATE, 3),
                "peak_seconds": round(peak_i * 0.01, 2), "tail_seconds": round(float(tail), 2)}

    index = [r for r in await asyncio.gather(*(probe(p, r) for p, r in files)) if r]
    SFX_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    SFX_INDEX_PATH.write_text(json.dumps(index, indent=1))
    return index


def load_sfx_index() -> list[dict[str, Any]] | None:
    return json.loads(SFX_INDEX_PATH.read_text()) if SFX_INDEX_PATH.exists() else None


def plan_accents(
    plan: dict[str, Any], style: AccentStyle, *, seed: int = 11, logo_path: str | None = None,
    sfx_index: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Accents for a plan, in the style's rhythm. Frames are on the plan's frame grid. See the module docstring."""
    rng = random.Random(seed)
    fps = plan["fps"]
    shots = sorted(plan["shots"], key=lambda s: s["start_frame"])
    n = len(shots)
    minutes = plan["duration_frames"] / fps / 60.0
    seconds = [s["duration_frames"] / fps for s in shots]
    pct = [float(s.get("cut_hit_percentile") or 0.0) for s in shots]
    flurry = [sum(1 for j in (k - 1, k, k + 1) if 0 <= j < n and seconds[j] < FLURRY_SHOT_SECONDS) >= 2 for k in range(n)]
    card_k = next((k for k, s in enumerate(shots) if s["role"] == "end_card"), None)
    last_body = (card_k if card_k is not None else n)  # first index that is NOT an ordinary body shot
    notes: list[str] = []

    intervals: list[tuple[int, int]] = []  # frame ranges the overlays already occupy (flashes and zoom hits never overlap)

    def clear(frame: int, frames: int, margin: int = 1) -> bool:
        return all(frame + frames + margin <= a or frame >= b + margin for a, b in intervals)

    def take(frame: int, frames: int) -> None:
        intervals.append((frame, frame + frames))

    def start_of(k: int, lead: int) -> int:
        return max(0, shots[k]["start_frame"] - lead)

    # ---- flashes: flurry cuts on strong hits (strongest first), plus a few standalone ones, plus the closing card
    flashes: list[dict] = []
    flurry_cuts = [k for k in range(1, last_body) if flurry[k] and pct[k] >= style.flash_min_pct - 5]
    n_flurry = round(style.flash_per_flurry_cut * len([k for k in range(1, last_body) if flurry[k]]))
    for k in sorted(flurry_cuts, key=lambda k: (-pct[k], k))[:n_flurry]:
        f = start_of(k, style.flash_lead_frames)
        if clear(f, style.flash_frames):
            take(f, style.flash_frames)
            flashes.append({"kind": "flash", "cut_index": k + 1, "start_frame": f, "frames": style.flash_frames, "where": "flurry"})
    n_standalone = round(style.flash_standalone_per_minute * minutes)
    for k in sorted((k for k in range(1, last_body) if not flurry[k] and pct[k] >= max(style.flash_min_pct, 85)), key=lambda k: (-pct[k], k))[:n_standalone]:
        f = start_of(k, style.flash_lead_frames)
        if clear(f, style.flash_frames, FLASH_COOLDOWN_FRAMES + 8):
            take(f, style.flash_frames)
            flashes.append({"kind": "flash", "cut_index": k + 1, "start_frame": f, "frames": style.flash_frames, "where": "standalone"})
    if card_k is not None:
        f = start_of(card_k, 2)
        take(f, style.end_card_flash_frames)
        flashes.append({"kind": "flash", "cut_index": card_k + 1, "start_frame": f, "frames": style.end_card_flash_frames, "where": "closing card"})
    flash_params = _non_default(style.flash_params, _LUMETRI_DEFAULTS)
    for fl in flashes:
        fl.update({"effect": LUMETRI, "params": flash_params})

    # ---- zoom hits: strong hit, after a longer shot, outside flurries, spaced apart
    zooms: list[dict] = []
    gap_frames = round(style.zoom_hit_min_gap_seconds * fps)
    flash_cuts = {fl["cut_index"] for fl in flashes}
    want = round(style.zoom_hits_per_minute * minutes)
    cand = [k for k in range(1, last_body) if not flurry[k] and (k + 1) not in flash_cuts and seconds[k - 1] >= style.zoom_hit_min_prev_seconds and pct[k] >= style.zoom_hit_min_pct]
    for k in sorted(cand, key=lambda k: (-pct[k], k)):
        if len(zooms) >= want:
            break
        f = start_of(k, style.zoom_hit_lead_frames)
        if all(abs(f - z["start_frame"]) >= gap_frames for z in zooms) and clear(f, style.zoom_hit_frames):
            take(f, style.zoom_hit_frames)
            zooms.append({"kind": "zoom_hit", "cut_index": k + 1, "start_frame": f, "frames": style.zoom_hit_frames, "effect": ZOOM_BLUR, "params": dict(style.zoom_hit_params)})
    zooms.sort(key=lambda z: z["start_frame"])

    # ---- per-shot zoom blur: strong hits, early in the edit more likely
    shot_effects: list[dict] = []
    zoom_cuts = {z["cut_index"] for z in zooms}
    n_zoom = round(style.shot_zoom_rate * n)
    weights = style.shot_zoom_decile_weights or [1.0] * 10

    def zscore(k: int) -> float:
        return pct[k] / 100.0 + 0.3 * weights[min(9, int(k / n * 10))]
    pool = [k for k in range(1, last_body) if pct[k] >= style.shot_zoom_min_pct and (k + 1) not in zoom_cuts]
    for k in sorted(pool, key=lambda k: (-zscore(k), k))[:n_zoom]:
        shot_effects.append({"shot_index": k + 1, "effect": ZOOM_BLUR, "params": dict(style.shot_zoom_params)})
    # ---- closing shots go black & white
    for k in range(max(0, n - style.closing_bw_shots), n):
        shot_effects.append({"shot_index": k + 1, "effect": BLACK_WHITE, "params": {}})
    shot_effects.sort(key=lambda e: e["shot_index"])

    # ---- logo on the closing card
    logo = None
    if style.end_card_logo and card_k is not None:
        if logo_path and os.path.exists(logo_path):
            logo = {"file": logo_path, "start_frame": shots[card_k]["start_frame"], "frames": shots[card_k]["duration_frames"], "track": LOGO_VIDEO_TRACK}
        else:
            notes.append("This style ends on a logo card but no logo file was found: put the client's logo (a PNG) in the job's graphics folder or pass its path.")

    # ---- sound effects (optional; stand-ins from the library, not the files draft 01 used). The file's loudest
    # moment is lined up with the cut and the file is trimmed shortly after it decays.
    sfx: list[dict] = []
    if sfx_index:
        hits = [x for x in sfx_index if x["role"] == "hit" and x["peak_seconds"] <= HIT_MAX_PEAK_SECONDS]
        whooshes = [x for x in sfx_index if x["role"] == "whoosh" and WHOOSH_PEAK_RANGE_SECONDS[0] <= x["peak_seconds"] <= WHOOSH_PEAK_RANGE_SECONDS[1]]

        def place(entry: dict, cut_frame: int, track: int, max_tail: float) -> dict | None:
            lead_frames = round(entry["peak_seconds"] * fps)
            start = cut_frame - lead_frames
            if start < 0:
                return None
            frames = max(MIN_SFX_FRAMES, round((entry["peak_seconds"] + min(entry["tail_seconds"], max_tail)) * fps))
            frames = min(frames, round(entry["seconds"] * fps))
            return {"role": entry["role"], "file": entry["path"], "name": entry["name"], "start_frame": start, "frames": frames, "track": track}
        # one hit sound per flurry (as in draft 01 the same click repeats through a flurry), a new one for the next flurry
        current, previous_start = None, -999
        for fl in sorted((f for f in flashes if f["where"] == "flurry"), key=lambda f: f["start_frame"]):
            if current is None or fl["start_frame"] - previous_start > round(1.2 * fps):
                current = _rng_pick(rng, hits)
            previous_start = fl["start_frame"]
            placed = place(current, fl["start_frame"] + style.flash_lead_frames, SFX_HIT_AUDIO_TRACK, HIT_MAX_TAIL_SECONDS) if current else None
            if placed:
                sfx.append(placed)
        for z in zooms:
            w = _rng_pick(rng, whooshes)
            placed = place(w, z["start_frame"] + style.zoom_hit_lead_frames, SFX_WHOOSH_AUDIO_TRACK, WHOOSH_MAX_TAIL_SECONDS) if w else None
            if placed:
                sfx.append(placed)
        if not hits or not whooshes:
            notes.append("The sound-effect library has no usable hits and/or whooshes (loud moment near the start / part-way in), so some sound effects were skipped.")
        sfx = _cut_sounds_at_next_on_track(sfx)
    return {
        "style": "accents derived from the reference(s)", "flashes": flashes, "zoom_hits": zooms, "shot_effects": shot_effects, "logo": logo, "sfx": sfx, "notes": notes,
        "counts": {"flashes": len(flashes), "zoom_hits": len(zooms), "shot_zoom_blur": sum(1 for e in shot_effects if e["effect"] == ZOOM_BLUR),
                   "black_and_white_shots": sum(1 for e in shot_effects if e["effect"] == BLACK_WHITE), "logo": 1 if logo else 0, "sfx": len(sfx)},
        "overlay_track": OVERLAY_VIDEO_TRACK,
    }
