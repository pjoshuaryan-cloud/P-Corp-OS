"""
POST (2026-09-25, Phase 1) -- drive/source detection. Shells out to
`diskutil info -plist` (stdlib subprocess + plistlib), the same
"control a native macOS thing via a CLI tool, no new Swift/
DiskArbitration code" precedent already established by
system_calendar.py's own _run_osascript() -- matches this app's
existing "backend does the heavy lifting, Swift is thin UI" bias.

Filtering out the boot volume by comparing DeviceIdentifier rather than
trusting diskutil's own Internal/RemovableMedia/Ejectable flags: a live
test against this exact Mac found a real, currently-mounted exFAT
volume (a card-reader-attached volume) that reports Internal=true
despite genuinely being removable camera-card-style media -- exactly
the "exFAT cards report these flags inconsistently across enclosures"
risk flagged during planning. Comparing device identity against the
actual boot volume (from `diskutil info /`) is precise where the
heuristic flags are not.

Copies EVERYTHING under a selected source root, no media-extension
filter -- a camera card's sidecar/XML/audio files matter too, and
extension-filtering risks silently dropping something Josh needed.
"""

import asyncio
import os
import plistlib
from pathlib import Path

_SKIP_ENTRIES = {".DS_Store", ".Trashes", ".fseventsd", ".Spotlight-V100", ".TemporaryItems", ".AppleDouble"}


def _is_junk(name: str) -> bool:
    """OS/filesystem leftovers that are not footage. Includes macOS "AppleDouble" shadow files: on an exFAT/FAT drive macOS keeps a hidden 4 KB `._<name>` next to every
    file that carries Finder metadata, so a card of 165 clips scanned as 330 files (2026-10-15) and every shadow file showed up as a corrupt clip."""
    return name in _SKIP_ENTRIES or name.startswith("._")


def same_drive(first: str, second: str) -> bool:
    """Whether two paths are on one drive, by the device each really lives on, so a folder on the SSD counts as the SSD. If either can't be read, no: a missing drive has its own explanation."""
    try:
        return os.stat(first).st_dev == os.stat(second).st_dev
    except OSError:
        return False


async def _diskutil_info_plist(path: str) -> dict | None:
    proc = await asyncio.create_subprocess_exec(
        "diskutil", "info", "-plist", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        return plistlib.loads(stdout)
    except Exception:
        return None


async def _boot_volume_device_identifier() -> str | None:
    info = await _diskutil_info_plist("/")
    return info.get("DeviceIdentifier") if info else None


async def list_source_volumes() -> list[dict]:
    """Every mounted volume under /Volumes except the boot volume itself.
    Both source AND destination pickers reuse this -- Josh may copy to a
    different SSD than the card came from, no separate route needed."""
    boot_device = await _boot_volume_device_identifier()
    volumes: list[dict] = []
    if not os.path.isdir("/Volumes"):
        return volumes
    for entry in sorted(os.scandir("/Volumes"), key=lambda e: e.name):
        if entry.name in _SKIP_ENTRIES:
            continue
        info = await _diskutil_info_plist(entry.path)
        if info is None:
            continue
        device_id = info.get("DeviceIdentifier")
        if boot_device is not None and device_id == boot_device:
            continue
        volumes.append({
            "name": info.get("VolumeName") or entry.name,
            "path": entry.path,
            "uuid": info.get("VolumeUUID"),
            "filesystem": info.get("FilesystemType"),
            "total_bytes": info.get("TotalSize"),
            "free_bytes": info.get("FreeSpace") or info.get("APFSContainerFree"),
            "writable": info.get("WritableVolume", True),
        })
    return volumes


def scan_source_tree(source_path: str) -> tuple[int, int, list[tuple[str, str, int]]]:
    """Recursively walks source_path, skipping OS/filesystem junk
    entries (.DS_Store, macOS ._ shadow files, ...). Returns (total_files, total_bytes, [(relative_path,
    absolute_source_path, size_bytes), ...]) -- the caller is
    responsible for computing each file's destination path from its
    relative_path. Synchronous (a plain os.walk, no I/O heavy enough to
    need chunked yielding) -- the caller wraps this single call in
    asyncio.to_thread since a very large card could still take a
    non-trivial moment to enumerate."""
    total_files = 0
    total_bytes = 0
    files: list[tuple[str, str, int]] = []
    source_root = Path(source_path)
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [d for d in dirnames if not _is_junk(d)]
        for filename in filenames:
            if _is_junk(filename):
                continue
            absolute_path = Path(dirpath) / filename
            try:
                size = absolute_path.stat().st_size
            except OSError:
                continue
            relative_path = str(absolute_path.relative_to(source_root))
            files.append((relative_path, str(absolute_path), size))
            total_files += 1
            total_bytes += size
    return total_files, total_bytes, files


# ---- what's on a card, by the day it was recorded (2026-11-12) ---------------------------------------------------------------------
# A card often still holds older shoots. Josh asked to copy only the shoot he's editing and to KNOW before anything copies what will
# and won't come across. A file's day is its modification date in this Mac's time zone: on a camera card that's when the clip or
# photo was recorded. Card bookkeeping files (MEDIAPRO.XML and the like) carry whatever day the card last wrote them.

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".insv", ".braw", ".r3d", ".crm", ".mkv"}
PHOTO_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2", ".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff"}


def file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        return "clip"
    # A camera's own thumbnail of each clip (Sony THMBNL/C0001T01.JPG) travels with the clips but isn't a photo he took.
    if ext in PHOTO_EXTENSIONS and "THMBNL" not in path.upper().split(os.sep) and "/THMBNL/" not in path.upper():
        return "photo"
    return "other"


def recording_day(absolute_path: str) -> str | None:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(os.stat(absolute_path).st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return None


def scan_by_day(source_path: str) -> list[tuple[str, str, int, str | None]]:
    """scan_source_tree's files, each with the day it was recorded: (relative_path, absolute_path, size, day)."""
    _files, _bytes, files = scan_source_tree(source_path)
    return [(rel, absolute, size, recording_day(absolute)) for rel, absolute, size in files]


def summarize_days(files: list[tuple[str, str, int, str | None]]) -> list[dict]:
    """Per recording day, newest first: how many clips, photos and other files, how big, and the first and last clip's name."""
    days: dict[str, dict] = {}
    for rel, _absolute, size, day in files:
        key = day or "unknown"
        d = days.setdefault(key, {"day": key, "clips": 0, "photos": 0, "other": 0, "files": 0, "bytes": 0, "clip_names": []})
        kind = file_kind(rel)
        d[{"clip": "clips", "photo": "photos", "other": "other"}[kind]] += 1
        d["files"] += 1
        d["bytes"] += size
        if kind == "clip":
            d["clip_names"].append(os.path.basename(rel))
    out = []
    for d in days.values():
        names = sorted(d.pop("clip_names"))
        d["first_clip"], d["last_clip"] = (names[0], names[-1]) if names else (None, None)
        out.append(d)
    return sorted(out, key=lambda d: d["day"], reverse=True)


def only_days(files: list[tuple[str, str, int, str | None]], days: list[str]) -> list[tuple[str, str, int, str | None]]:
    wanted = set(days)
    return [f for f in files if (f[3] or "unknown") in wanted]
