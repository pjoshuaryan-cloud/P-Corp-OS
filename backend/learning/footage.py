"""Find the raw clips a project points at, wherever they live now.

A project records absolute paths. Drives get renamed, folders reorganised, footage moved from one Mac to another. So a path that no longer exists is
searched for by file name across every mounted drive -- but a name alone is NOT proof: camera numbering repeats from card to card (C1445.MP4 exists on
several cards). A match is accepted only when its length also agrees with the length the project recorded for the clip it used. Ambiguity is reported,
never guessed.

Read-only: it lists folders and asks ffprobe for a length. Lengths are cached so a second run is fast.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mxf", ".avi", ".mkv", ".mts", ".mpg"}
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems", "Media Cache Files", "Media Cache",
             "Adobe Premiere Pro Video Previews", "Adobe Premiere Pro Audio Previews", "node_modules", ".git"}
DURATION_TOLERANCE = 0.2  # seconds: a project records a clip's length to the frame, ffprobe to the millisecond
FFPROBE = "/opt/homebrew/bin/ffprobe"
DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "learning"


def mounted_roots(extra: list[str] | None = None) -> list[str]:
    """Every mounted drive (not the system volume) plus folders on the Mac that may hold footage."""
    roots = [str(p) for p in sorted(Path("/Volumes").iterdir()) if p.is_dir() and not p.is_symlink() and p.name != "Macintosh HD"]
    roots += [p for p in (os.path.expanduser("~/Movies"), os.path.expanduser("~/Downloads")) if os.path.isdir(p)] + (extra or [])
    return roots


class DriveIndex:
    """Every video file under the given roots, looked up by lower-cased file name."""

    def __init__(self) -> None:
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.roots: list[str] = []
        self.count = 0

    def add_root(self, root: str) -> None:
        self.roots.append(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("._")]
            for name in filenames:
                if name.startswith("._") or os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS:
                    continue
                self.by_name[name.lower()].append(os.path.join(dirpath, name))
                self.count += 1

    def candidates(self, file_name: str) -> list[str]:
        return self.by_name.get(file_name.lower(), [])


@dataclass
class Resolution:
    status: str                  # exact | matched | ambiguous | missing | unverified
    path: str | None = None      # where the clip is now
    note: str = ""
    options: list[str] = field(default_factory=list)  # for 'ambiguous': the candidates that all agree on length

    @property
    def usable(self) -> bool:
        return self.status in ("exact", "matched") and self.path is not None


class Durations:
    """ffprobe lengths, cached on disk by (path, size, modified time)."""

    def __init__(self, cache_file: Path | None = None) -> None:
        self.cache_file = cache_file or DEFAULT_DATA / "duration_cache.json"
        self.cache: dict[str, list] = {}
        if self.cache_file.exists():
            try:
                self.cache = json.loads(self.cache_file.read_text())
            except (OSError, ValueError):
                self.cache = {}
        self.dirty = False

    def of(self, path: str) -> float | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        hit = self.cache.get(path)
        if hit and hit[0] == st.st_size and hit[1] == int(st.st_mtime):
            return hit[2]
        try:
            out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                 capture_output=True, text=True, timeout=60).stdout.strip()
            value = float(out) if out else None
        except (ValueError, subprocess.SubprocessError, OSError):
            value = None
        self.cache[path] = [st.st_size, int(st.st_mtime), value]
        self.dirty = True
        return value

    def prefetch(self, paths: list[str], workers: int = 8) -> None:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(self.of, paths))

    def save(self) -> None:
        if self.dirty:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self.cache))
            self.dirty = False


def _agrees(length: float | None, recorded: float | None) -> bool:
    return length is not None and recorded is not None and abs(length - recorded) <= DURATION_TOLERANCE


def resolve(recorded_path: str, recorded_duration: float | None, index: DriveIndex, durations: Durations) -> Resolution:
    """Where is the clip a project used, now? `recorded_duration` is the clip's full length as the project stored it."""
    name = os.path.basename(recorded_path)
    if os.path.exists(recorded_path):
        if recorded_duration is None or _agrees(durations.of(recorded_path), recorded_duration):
            return Resolution("exact", recorded_path)
        # something else now sits at that path (a replaced or re-exported file): fall through and look elsewhere
    candidates = [p for p in index.candidates(name) if p != recorded_path]
    if not candidates:
        return Resolution("missing", None, "no file with that name on the mounted drives")
    if recorded_duration is None:
        return Resolution("unverified", candidates[0] if len(candidates) == 1 else None, "the project didn't record the clip's length, so a name match can't be checked",
                          candidates if len(candidates) > 1 else [])
    agreeing = [p for p in candidates if _agrees(durations.of(p), recorded_duration)]
    if len(agreeing) == 1:
        return Resolution("matched", agreeing[0], "found by name and confirmed by length")
    if not agreeing:
        return Resolution("missing", None, f"{len(candidates)} file(s) with that name, none the right length ({recorded_duration:.2f}s)")
    parent = os.path.basename(os.path.dirname(recorded_path)).lower()
    same = [p for p in agreeing if os.path.basename(os.path.dirname(p)).lower() == parent]
    if len(same) == 1:
        return Resolution("matched", same[0], "found by name and length, tie broken by the folder name")
    return Resolution("ambiguous", None, f"{len(agreeing)} files agree on name and length", agreeing)
