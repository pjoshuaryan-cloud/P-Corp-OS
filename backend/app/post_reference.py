"""
POST (2026-10-07) -- reference edits: a finished (or hand-cut) Premiere sequence read into a
structured record, so future jobs of the same kind can borrow its style.

Josh's "draft 01" for the JD Sports store opening is the first one: a ~32 s vertical reel,
50 shots, cut to a song, with zoom-blur / flash adjustment layers and sound effects. This module
reads a saved .prproj (gzip XML) and records, for one sequence:
  - every shot (source clip name, source in/out, timeline start/end, effects on it),
  - the overlay layers (adjustment layers carrying a Lumetri flash or a zoom blur, logos),
  - the audio (music, sound effects, camera audio), and
  - summary numbers a planner can use: shot-length distribution, pacing over time, how often
    effects are used, how cuts relate to the music.
Records are saved as JSON under backend/data/post_references/ with tags (genre, client, format)
so a new "streetwear store opening" job can find them.

Read-only with respect to Premiere: it never opens or changes the project.
"""

import gzip
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

TICKS_PER_SECOND = 254016000000
REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "post_references"
_PLAIN_EFFECTS_TO_IGNORE = ("AE.ADBE Motion", "CompoundComponent")
_SFX_NAME = re.compile(r"SFX|whoosh|riser|click|shutter|impact|hit|swoosh|boom|pass", re.IGNORECASE)


class ReferenceError_(RuntimeError):
    pass


def _load(prproj_path: str) -> tuple[ET.Element, dict[str, ET.Element]]:
    try:
        with gzip.open(prproj_path, "rb") as fh:
            root = ET.parse(fh).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ReferenceError_(f"Couldn't read the Premiere project {Path(prproj_path).name}: {exc}") from exc
    ids: dict[str, ET.Element] = {}
    for el in root.iter():
        for key in ("ObjectID", "ObjectUID"):
            if key in el.attrib:
                ids[el.attrib[key]] = el
    return root, ids


def _ticks(el: ET.Element | None, tag: str) -> int:
    child = el.find(tag) if el is not None else None
    return int(child.text) if child is not None and (child.text or "").strip() else 0


def _effects(item: ET.Element, ids: dict[str, ET.Element]) -> list[str]:
    comps = item.find("ClipTrackItem/ComponentOwner/Components")
    names: list[str] = []
    if comps is not None and "ObjectRef" in comps.attrib:
        for ref in ids[comps.attrib["ObjectRef"]].iter("Component"):
            comp = ids.get(ref.attrib.get("ObjectRef", ""))
            match = comp.find("MatchName") if comp is not None else None
            if match is not None and match.text and match.text not in _PLAIN_EFFECTS_TO_IGNORE:
                names.append(match.text)
    return names


# Parameters worth recording per effect (values that define a "look"); everything else stays at the effect's default.
_PARAMS_OF_INTEREST = {
    "AE.ADBE Lumetri": ("Exposure", "Contrast", "Highlights", "Shadows", "Whites", "Blacks", "Saturation", "Temperature", "Tint"),
    "AE.Impact_Zoom_Blur_FX": ("Zoom", "Variation", "Slices", "Feather", "Edge Behavior"),
    "AE.ADBE Motion": ("Scale",),
    "AE.ADBE Opacity": ("Opacity",),
}


def _effect_params(item: ET.Element, ids: dict[str, ET.Element]) -> dict[str, dict[str, float]]:
    """{effect match name: {parameter: value}} for the parameters in _PARAMS_OF_INTEREST that hold a number."""
    comps = item.find("ClipTrackItem/ComponentOwner/Components")
    out: dict[str, dict[str, float]] = {}
    if comps is None or "ObjectRef" not in comps.attrib:
        return out
    for ref in ids[comps.attrib["ObjectRef"]].iter("Component"):
        comp = ids.get(ref.attrib.get("ObjectRef", ""))
        match = comp.find("MatchName") if comp is not None else None
        wanted = _PARAMS_OF_INTEREST.get(match.text) if match is not None else None
        if not wanted:
            continue
        for p in comp.iter("Param"):
            param = ids.get(p.attrib.get("ObjectRef", ""))
            name = param.find("Name") if param is not None else None
            kf = param.find("StartKeyframe") if param is not None else None
            if name is None or name.text not in wanted or kf is None:
                continue
            parts = (kf.text or "").split(",")
            try:
                out.setdefault(match.text, {})[name.text] = float(parts[1].strip("."))
            except (IndexError, ValueError):
                pass
    return out


PREMIERE_LEVEL_0DB = 0.177827941   # Premiere stores an audio clip's Volume Level as linear gain with 1.0 = +15 dB, so 0 dB is 10 ** (-15 / 20)


def _audio_level_db(item: ET.Element, ids: dict[str, ET.Element]) -> float | None:
    """An audio clip's Volume > Level in dB (its first keyframe, or its value when it isn't animated); None when the clip has none recorded."""
    comps = item.find("ClipTrackItem/ComponentOwner/Components")
    if comps is None or "ObjectRef" not in comps.attrib:
        return None
    for ref in ids[comps.attrib["ObjectRef"]].iter("Component"):
        comp = ids.get(ref.attrib.get("ObjectRef", ""))
        for p in comp.iter("Param") if comp is not None else ():
            param = ids.get(p.attrib.get("ObjectRef", ""))
            if param is None or param.findtext("Name") != "Level":
                continue
            parts = (param.findtext("StartKeyframe") or "").split(",")
            try:
                value = float(parts[1].strip("."))
            except (IndexError, ValueError):
                return None
            return round(20 * math.log10(value / PREMIERE_LEVEL_0DB), 2) if value > 0 else None
    return None


def sequence_names(prproj_path: str) -> list[str]:
    root, _ = _load(prproj_path)
    return [n.text for s in root.iter("Sequence") if (n := s.find("Name")) is not None and n.text]


def extract_reference_edit(prproj_path: str, sequence_name: str) -> dict[str, Any]:
    """Everything about one sequence, in seconds. Raises ReferenceError_ if the sequence isn't there."""
    root, ids = _load(prproj_path)
    seq = next((s for s in root.iter("Sequence") if (n := s.find("Name")) is not None and n.text == sequence_name), None)
    if seq is None:
        raise ReferenceError_(f"No sequence called {sequence_name!r} in {Path(prproj_path).name}. Found: {sequence_names(prproj_path)}")
    video: list[list[dict]] = []
    audio: list[list[dict]] = []
    for tg in seq.findall("TrackGroups/TrackGroup"):
        group = ids.get(tg.find("Second").attrib.get("ObjectRef", ""))
        if group is None or group.tag not in ("VideoTrackGroup", "AudioTrackGroup"):
            continue
        for tr in group.findall("TrackGroup/Tracks/Track"):
            track = ids[tr.attrib["ObjectURef"]]
            items = []
            for ref in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
                item = ids[ref.attrib["ObjectRef"]]
                timing = item.find("ClipTrackItem/TrackItem")
                sub = ids[item.find("ClipTrackItem/SubClip").attrib["ObjectRef"]]
                clip = ids[sub.find("Clip").attrib["ObjectRef"]]
                items.append({
                    "name": sub.find("Name").text,
                    "start": round(_ticks(timing, "Start") / TICKS_PER_SECOND, 3),
                    "end": round(_ticks(timing, "End") / TICKS_PER_SECOND, 3),
                    "source_in": round(_ticks(clip, "Clip/InPoint") / TICKS_PER_SECOND, 3),
                    "source_out": round(_ticks(clip, "Clip/OutPoint") / TICKS_PER_SECOND, 3),
                    "effects": _effects(item, ids),
                    "params": _effect_params(item, ids),
                    **({"level_db": _audio_level_db(item, ids)} if group.tag == "AudioTrackGroup" else {}),
                })
            (video if group.tag == "VideoTrackGroup" else audio).append(items)
    shots, overlays, graphics = [], [], []
    for index, track in enumerate(video):
        for it in track:
            if it["name"] == "Adjustment Layer":
                overlays.append({**it, "track": index + 1, "kind": "flash" if any("Lumetri" in e for e in it["effects"]) else
                                 "zoom_blur" if any("Zoom_Blur" in e for e in it["effects"]) else "other"})
            elif re.search(r"\.(png|jpg|jpeg|svg|psd|ai)$", it["name"], re.IGNORECASE):
                graphics.append({**it, "track": index + 1})
            elif index <= 1:  # V1 and V2 both carry picture shots (V2 fills gaps on V1)
                shots.append({**it, "track": index + 1})
    shots.sort(key=lambda s: s["start"])
    sounds = []
    for index, track in enumerate(audio):
        for it in track:
            names = it["name"]
            # judge by name first: a sound-effect pack can be an .mp4 (e.g. a ripped video), a camera clip is MNSTR1234.MP4 / C0001.MP4 etc.
            is_camera_file = re.match(r"^(MNSTR|C\d{4}|DJI_|IMG_|MVI_|GX|GH)", names, re.IGNORECASE) is not None
            kind = "sfx" if _SFX_NAME.search(names) and not is_camera_file else (
                "camera_audio" if is_camera_file else "music")
            sounds.append({**it, "track": index + 1, "kind": kind})
    sounds.sort(key=lambda s: s["start"])
    duration = max((s["end"] for s in shots), default=0.0)
    return {
        "source_project": str(prproj_path), "sequence": sequence_name, "duration_seconds": round(duration, 2),
        "shots": shots, "overlays": overlays, "graphics": graphics, "audio": sounds,
    }


def summarize_reference(ref: dict[str, Any]) -> dict[str, Any]:
    """Numbers a planner can use. Pure arithmetic over the extracted record."""
    shots = ref["shots"]
    lengths = sorted(s["end"] - s["start"] for s in shots)
    n = len(lengths)
    def pct(p: float) -> float:
        return round(lengths[min(n - 1, int(p * n))], 2) if n else 0.0
    window = 5.0
    pacing = []
    t = 0.0
    while t < ref["duration_seconds"]:
        inside = [s for s in shots if t <= s["start"] < t + window]
        pacing.append({"from": t, "to": t + window, "shots": len(inside),
                       "mean_shot_seconds": round(sum(s["end"] - s["start"] for s in inside) / len(inside), 2) if inside else None})
        t += window
    effect_counts: dict[str, int] = {}
    for s in shots:
        for e in set(s["effects"]):
            effect_counts[e] = effect_counts.get(e, 0) + 1
    cuts = sorted({s["start"] for s in shots})
    overlay_gaps = [min(abs(o["start"] - c) for c in cuts) for o in ref["overlays"] if o["end"] - o["start"] < 1 and cuts]
    clip_uses: dict[str, int] = {}
    for s in shots:
        clip_uses[s["name"]] = clip_uses.get(s["name"], 0) + 1
    return {
        "shot_count": n, "duration_seconds": ref["duration_seconds"],
        "shot_length_seconds": {"mean": round(sum(lengths) / n, 2) if n else 0, "median": pct(0.5), "p10": pct(0.1), "p90": pct(0.9), "min": lengths[0] if n else 0, "max": lengths[-1] if n else 0},
        "shots_under_half_second": sum(1 for x in lengths if x < 0.5),
        "pacing_by_5s": pacing,
        "effects_on_shots": effect_counts,
        "overlay_layers": {k: sum(1 for o in ref["overlays"] if o["kind"] == k) for k in ("flash", "zoom_blur", "other")},
        "overlays_within_80ms_of_a_cut": round(sum(1 for g in overlay_gaps if g < 0.08) / len(overlay_gaps), 2) if overlay_gaps else None,
        "sound_effects": sum(1 for a in ref["audio"] if a["kind"] == "sfx"),
        "distinct_source_clips": len(clip_uses),
        "clips_used_more_than_once": {k: v for k, v in clip_uses.items() if v > 1},
        "end_card": [g["name"] for g in ref["graphics"]],
    }


def save_reference(slug: str, ref: dict[str, Any], tags: dict[str, Any], music_sync: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> Path:
    """Writes REFERENCE_DIR/<slug>.json (record + summary + tags). Overwrites that slug. `extra` adds top-level keys
    (a reference read from a finished video stores its `video_analysis` there)."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"slug": slug, "tags": tags, "summary": summarize_reference(ref), "music_sync": music_sync, "edit": ref, **(extra or {})}
    path = REFERENCE_DIR / f"{slug}.json"
    path.write_text(json.dumps(record, indent=1))
    return path


def list_references(**tag_filters: Any) -> list[dict[str, Any]]:
    """Saved reference records (without the bulky `edit`) whose tags match every given filter."""
    out = []
    for path in sorted(REFERENCE_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        if all(rec["tags"].get(k) == v for k, v in tag_filters.items()):
            out.append({k: rec[k] for k in ("slug", "tags", "summary", "music_sync")})
    return out


def load_reference(slug: str) -> dict[str, Any]:
    path = REFERENCE_DIR / f"{slug}.json"
    if not path.exists():
        raise ReferenceError_(f"No saved reference called {slug!r}.")
    return json.loads(path.read_text())
