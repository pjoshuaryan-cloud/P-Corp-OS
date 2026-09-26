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

_SKIP_ENTRIES = {".DS_Store", ".Trashes", ".fseventsd", ".Spotlight-V100", ".TemporaryItems"}


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
    entries. Returns (total_files, total_bytes, [(relative_path,
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
        dirnames[:] = [d for d in dirnames if d not in _SKIP_ENTRIES]
        for filename in filenames:
            if filename in _SKIP_ENTRIES:
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
