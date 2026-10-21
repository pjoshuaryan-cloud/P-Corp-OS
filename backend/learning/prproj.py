"""Read the edit decisions out of a Premiere project file (.prproj, auto-saves included).

A project is gzipped XML. Every sequence lists its video tracks; a track lists its clip items; an item has a timeline start/end and a sub-clip that
points to a source file with an in and out point (all in ticks, 254016000000 per second). What this module returns is exactly what an editor decided:
which source file, which part of it, where on the timeline, how long.

Read-only: nothing is written next to the project. Not a Premiere API, so it only needs the file.
"""
from __future__ import annotations

import gzip
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

TICKS_PER_SECOND = 254016000000.0
VIDEO_TRACK_GROUP = "228cda18-3625-4d2d-951e-348879e4ed93"  # the GUID Premiere uses for a sequence's video track group


class ProjectError(RuntimeError):
    pass


@dataclass
class Shot:
    """One video clip item on a timeline."""
    t0: float                 # timeline start, seconds
    t1: float                 # timeline end, seconds
    src_in: float | None      # source in point, seconds
    src_out: float | None     # source out point, seconds
    path: str | None          # the source media file as the project recorded it (None for generated items like adjustment layers)
    name: str | None
    track: int                # 1 = V1
    src_duration: float | None  # the source file's full length, seconds, as the project recorded it
    nested: str | None = None   # set when the source is another sequence, not a file
    src_fps: float | None = None  # the source file's frame rate as the project recorded it (50.0 for 50 fps footage), None when not found

    @property
    def length(self) -> float:
        return self.t1 - self.t0

    @property
    def source_length(self) -> float | None:
        return None if self.src_in is None or self.src_out is None else self.src_out - self.src_in

    @property
    def speed(self) -> float | None:
        """Source seconds per timeline second (1.0 = real time). Not 1.0 means the shot is slowed down or sped up."""
        sl = self.source_length
        return None if sl is None or self.length <= 0 else sl / self.length


@dataclass
class Sequence:
    name: str
    out_mark: float | None    # the sequence's Out point, seconds: where the exported cut ends when the editor set one (it matches the export's length)
    in_mark: float | None
    tracks: list[list[Shot]] = field(default_factory=list)

    @property
    def shots(self) -> list[Shot]:
        return [s for t in self.tracks for s in t]

    def delivered_shots(self, only_files: bool = True) -> list[Shot]:
        """Shots inside the exported range [in, out) -- working timelines also park alternatives beyond the Out point. Generated items
        (adjustment layers, black video) have no real file and are dropped when `only_files`."""
        lo, hi = self.in_mark or 0.0, self.out_mark
        out = []
        for s in self.shots:
            if only_files and (not s.path or s.path.isdigit()):
                continue
            if hi is not None and s.t0 >= hi - 0.01:
                continue
            if s.t1 <= lo:
                continue
            out.append(Shot(**{**s.__dict__, "t1": min(s.t1, hi) if hi is not None else s.t1}))
        return out


def normalise_name(name: str | None) -> str:
    """Sequence names carry odd spacing ('15 sec ( 4x5 )'); lower-case with all whitespace removed is the stable key."""
    return re.sub(r"[\s ]+", "", name or "").lower()


def _read_xml(path: str) -> ET.Element:
    try:
        with gzip.open(path, "rb") as fh:
            return ET.fromstring(fh.read())
    except OSError:
        with open(path, "rb") as fh:  # an uncompressed project
            return ET.fromstring(fh.read())
    except ET.ParseError as exc:
        raise ProjectError(f"{os.path.basename(path)} isn't readable as a Premiere project ({exc}).") from exc


def read_sequences(path: str) -> list[Sequence]:
    root = _read_xml(path)
    by_id: dict[str, ET.Element] = {}
    by_uid: dict[str, ET.Element] = {}
    for el in root:
        if el.get("ObjectID"):
            by_id[el.get("ObjectID")] = el
        if el.get("ObjectUID"):
            by_uid[el.get("ObjectUID")] = el

    def media_of(video_clip: ET.Element) -> dict[str, Any]:
        src = video_clip.find("Clip/Source")
        source = by_id.get(src.get("ObjectRef")) if src is not None else None
        if source is None:
            return {}
        media_ref = source.find("MediaSource/Media")
        if media_ref is None:
            return {"nested": source.tag}
        media = by_uid.get(media_ref.get("ObjectURef"))
        if media is None:
            return {}
        original = source.findtext("OriginalDuration")
        stream_ref = media.find("VideoStream")
        stream = by_id.get(stream_ref.get("ObjectRef")) if stream_ref is not None else None
        rate = stream.findtext("FrameRate") if stream is not None else None
        return {"path": media.findtext("ActualMediaFilePath") or media.findtext("FilePath"),
                "duration": float(original) / TICKS_PER_SECOND if original else None,
                "fps": round(TICKS_PER_SECOND / int(rate), 3) if rate and rate.isdigit() and int(rate) > 0 else None}

    sequences: list[Sequence] = []
    for seq in (el for el in root if el.tag == "Sequence"):
        props = seq.find("Node/Properties")

        def mark(key: str) -> float | None:
            raw = props.findtext(key) if props is not None else None
            return int(raw) / TICKS_PER_SECOND if raw and raw.lstrip("-").isdigit() else None

        result = Sequence(name=seq.findtext("Name") or "", out_mark=mark("MZ.OutPoint"), in_mark=mark("MZ.InPoint"))
        for group in seq.findall("TrackGroups/TrackGroup"):
            if group.findtext("First") != VIDEO_TRACK_GROUP:
                continue
            group_el = by_id.get(group.find("Second").get("ObjectRef"))
            if group_el is None:
                continue
            tracks = sorted((t for t in group_el.iter("Track") if t.get("ObjectURef")), key=lambda t: int(t.get("Index", 0)))
            for index, track_ref in enumerate(tracks, start=1):
                track = by_uid.get(track_ref.get("ObjectURef"))
                shots: list[Shot] = []
                if track is not None:
                    items = sorted(track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"), key=lambda t: int(t.get("Index", 0)))
                    for item_ref in items:
                        item = by_id.get(item_ref.get("ObjectRef"))
                        if item is None or item.tag != "VideoClipTrackItem":
                            continue
                        sub = by_id.get(item.find("ClipTrackItem/SubClip").get("ObjectRef"))
                        clip = by_id.get(sub.find("Clip").get("ObjectRef")) if sub is not None else None
                        if clip is None:
                            continue
                        # Premiere leaves a value out of the file when it is ZERO: no <Start> = the timeline start, no <InPoint> = the first frame of the clip.
                        # Treating "missing" as "unknown" silently drops every shot that begins at the start of its clip -- the very shots an editor takes most.
                        c_in, c_out = clip.findtext("Clip/InPoint"), clip.findtext("Clip/OutPoint")
                        end = item.findtext("ClipTrackItem/TrackItem/End")
                        if end is None:
                            continue
                        media = media_of(clip)
                        shots.append(Shot(
                            t0=int(item.findtext("ClipTrackItem/TrackItem/Start") or 0) / TICKS_PER_SECOND,
                            t1=int(end) / TICKS_PER_SECOND,
                            src_in=int(c_in or 0) / TICKS_PER_SECOND if c_out else None, src_out=int(c_out) / TICKS_PER_SECOND if c_out else None,
                            path=media.get("path"), name=sub.findtext("Name"), track=index, src_duration=media.get("duration"), nested=media.get("nested"), src_fps=media.get("fps")))
                result.tracks.append(shots)
        sequences.append(result)
    return sequences


def project_media_paths(path: str) -> set[str]:
    """Every media file the project points at (footage, graphics, music), as recorded."""
    root = _read_xml(path)
    return {p.text for p in root.iter("ActualMediaFilePath") if p.text and not p.text.isdigit()}
