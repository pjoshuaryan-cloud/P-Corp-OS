"""
POST (2026-09-25, Phase 2) -- media intelligence: real metadata
extraction via `ffprobe` (bundled with Homebrew's `ffmpeg`, installed
separately on this Mac -- not a Python dependency) and deterministic
categorization from that metadata. Deliberately NOT Section 6's visual/
AI content analysis (shot type, movement, subject) -- that needs real
computer-vision capability nothing in this codebase has and isn't named
in Phase 2's own scope.

Two real findings from live testing against actual ffprobe output
(not just documented shape) that shaped this file:
- `-v error`, not `-v quiet` -- quiet swallows the actual failure
  message on stderr, leaving nothing useful for `probe_error`.
- A still image is told apart from real video by `format.format_name`
  (e.g. "image2" for a JPEG/PNG) being a known image-only demuxer name,
  NOT by guessing from `nb_frames` or a near-zero duration -- both of
  those turned out unreliable in a real live test.

Every extractor here follows document_attachments.py's own "never
raise, fail soft on content, fail loud only on the operation itself"
discipline: a missing ffprobe binary, a corrupt file, or unparseable
JSON all degrade to a `probe_error` string, never an exception that
would crash the whole batch over one bad file.
"""

import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.post_db import (
    create_post_job_file_metadata_batch,
    create_post_job_file_proxies_batch,
    get_post_job,
    list_post_job_file_metadata,
    list_post_job_files,
    list_queued_post_job_file_proxies,
    mark_post_job_file_proxy_complete,
    mark_post_job_file_proxy_failed,
    mark_post_job_file_proxy_processing,
    update_post_job_media_analyzed,
    update_post_job_proxies_generated,
)
from app.post_profiles import POST_PROFILES

# Demuxer names ffprobe uses for single-frame raster images -- confirmed
# live (a real JPEG produced format_name "image2"). Kept as a set since
# different image types can report different demuxer names.
_IMAGE_FORMAT_NAMES = {
    "image2", "image2pipe", "png_pipe", "webp_pipe", "gif", "tiff_pipe",
    "bmp_pipe", "heic_pipe", "jpeg_pipe",
}

# Real bug found live: the production LaunchAgent's own PATH is just
# `/usr/bin:/bin:/usr/sbin:/sbin` (confirmed via `launchctl print`) --
# it does NOT include Homebrew's bin directory, so a bare "ffprobe"
# subprocess call raises FileNotFoundError there even though it works
# fine from an interactive shell. Resolving the real, absolute install
# path once here (checking both Apple Silicon's and Intel's default
# Homebrew prefixes) sidesteps relying on PATH at all; falls back to the
# bare name only if neither known location exists, so a non-Homebrew
# ffmpeg install (already on PATH some other way) still works.
def _resolve_ffprobe_path() -> str:
    for candidate in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "ffprobe"


FFPROBE_PATH = _resolve_ffprobe_path()


# Same Homebrew-PATH gap as FFPROBE_PATH above -- ffmpeg is the identical
# binary bundle at the identical install location, so it needs the exact
# same absolute-path resolution to work from the production LaunchAgent.
def _resolve_ffmpeg_path() -> str:
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "ffmpeg"


FFMPEG_PATH = _resolve_ffmpeg_path()

# A stated, easily-adjustable assumption -- above standard 23.976-30fps
# cinema/broadcast rates, not a claim about any specific camera's own
# slow-motion mode.
SLOW_MOTION_FPS_THRESHOLD = 48.0

KNOWN_DRONE_MAKES = ("dji", "autel", "skydio", "parrot")
KNOWN_PHONE_MAKES = ("apple", "iphone", "samsung", "google", "pixel")


async def probe_file(path: str) -> dict:
    """Runs ffprobe against one file. Never raises -- every failure mode
    (missing binary, corrupt file, invalid JSON) returns a dict with a
    non-None `probe_error` instead."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE_PATH, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return _empty_metadata(probe_error="ffprobe not found -- install with `brew install ffmpeg`.")
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        message = stderr.decode(errors="replace").strip() or f"ffprobe exited with code {proc.returncode}"
        return _empty_metadata(probe_error=message[:500])
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return _empty_metadata(probe_error="ffprobe returned invalid JSON.")

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    format_tags = fmt.get("tags", {})

    if fmt.get("format_name") in _IMAGE_FORMAT_NAMES:
        media_type = "image"
    elif video_stream:
        media_type = "video"
    elif audio_stream:
        media_type = "audio"
    else:
        media_type = "other"

    frame_rate = None
    if video_stream and video_stream.get("r_frame_rate"):
        num_str, _, denom_str = video_stream["r_frame_rate"].partition("/")
        try:
            num, denom = int(num_str), int(denom_str) if denom_str else 1
            if denom:
                frame_rate = round(num / denom, 3)
        except ValueError:
            frame_rate = None

    duration_seconds = None
    if fmt.get("duration"):
        try:
            duration_seconds = float(fmt["duration"])
        except ValueError:
            duration_seconds = None

    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "media_type": media_type,
        "duration_seconds": duration_seconds,
        "width": _int_or_none(video_stream.get("width")) if video_stream else None,
        "height": _int_or_none(video_stream.get("height")) if video_stream else None,
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "frame_rate": frame_rate,
        "bit_depth": _int_or_none(video_stream.get("bits_per_raw_sample")) if video_stream else None,
        "pixel_format": video_stream.get("pix_fmt") if video_stream else None,
        "color_space": video_stream.get("color_space") if video_stream else None,
        "audio_channels": _int_or_none(audio_stream.get("channels")) if audio_stream else None,
        # Apple's own QuickTime tags first (most of Josh's own footage);
        # generic make/model tags as a fallback for other cameras.
        "camera_make": format_tags.get("com.apple.quicktime.make") or format_tags.get("make"),
        "camera_model": format_tags.get("com.apple.quicktime.model") or format_tags.get("model"),
        "creation_time": format_tags.get("creation_time"),
        "probe_error": None,
        # Container-level bit_rate (bits/sec) -- Phase 4's own
        # "very high bitrate" proxy-recommendation criterion. Never
        # extracted in Phase 2 since nothing needed it yet.
        "bit_rate": _int_or_none(fmt.get("bit_rate")),
    }


def _empty_metadata(probe_error: str) -> dict:
    return {
        "media_type": None, "duration_seconds": None, "width": None, "height": None,
        "video_codec": None, "audio_codec": None, "frame_rate": None, "bit_depth": None,
        "pixel_format": None, "color_space": None, "audio_channels": None,
        "camera_make": None, "camera_model": None, "creation_time": None, "probe_error": probe_error,
        "bit_rate": None,
    }


def guess_device_category(camera_make: str | None, camera_model: str | None) -> str | None:
    """Best-effort ONLY, from make/model string matching against a short
    known list -- returns 'drone'/'phone'/None, never a confident guess
    for anything else. Surfaced in the UI as a guess, not a fact,
    matching this app's 'never assert false precision' discipline."""
    haystack = f"{camera_make or ''} {camera_model or ''}".lower()
    if any(name in haystack for name in KNOWN_DRONE_MAKES):
        return "drone"
    if any(name in haystack for name in KNOWN_PHONE_MAKES):
        return "phone"
    return None


async def run_media_analysis(job_id: int, postgres_conn: Any = None) -> None:
    """Probes every file belonging to this job and stores the results.
    Runs every probe concurrently (asyncio.gather) -- unlike Phase 1's
    ingestion, these are lightweight subprocess calls reading only file
    headers, not multi-GB sequential I/O, so there's no need for the
    chunked-yield discipline the copy phase requires."""
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    if not files:
        await update_post_job_media_analyzed(job_id, postgres_conn=postgres_conn)
        return
    results = await asyncio.gather(*(probe_file(f["destination_path"]) for f in files))
    rows = [{"file_id": f["id"], **result} for f, result in zip(files, results)]
    await create_post_job_file_metadata_batch(rows, postgres_conn=postgres_conn)
    await update_post_job_media_analyzed(job_id, postgres_conn=postgres_conn)


async def compute_media_report(job_id: int, postgres_conn: Any = None) -> dict:
    """Deterministic Python aggregation over already-fetched rows -- same
    'one source of truth, no LLM in the path' discipline as Ventures'
    compute_customer_metrics/compute_health_label. Duplicate detection
    reuses Phase 1's own SHA-256 source_checksum -- no new hashing pass."""
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    metadata_by_file_id = {m["file_id"]: m for m in await list_post_job_file_metadata(job_id, postgres_conn=postgres_conn)}

    media_type_counts: dict[str, int] = defaultdict(int)
    cameras: dict[tuple[str | None, str | None], int] = defaultdict(int)
    resolutions: dict[tuple[int, int], int] = defaultdict(int)
    frame_rates: dict[float, int] = defaultdict(int)
    device_categories: dict[str, int] = defaultdict(int)
    vertical_count = 0
    horizontal_count = 0
    slow_motion_files: list[dict] = []
    corrupt_files: list[dict] = []
    checksum_groups: dict[str, list[str]] = defaultdict(list)

    for f in files:
        if f["source_checksum"]:
            checksum_groups[f["source_checksum"]].append(f["relative_path"])
        meta = metadata_by_file_id.get(f["id"])
        if meta is None:
            continue
        if meta["probe_error"]:
            corrupt_files.append({"path": f["relative_path"], "error": meta["probe_error"]})
            continue
        if meta["media_type"]:
            media_type_counts[meta["media_type"]] += 1
        if meta["camera_make"] or meta["camera_model"]:
            cameras[(meta["camera_make"], meta["camera_model"])] += 1
            category = guess_device_category(meta["camera_make"], meta["camera_model"])
            if category:
                device_categories[category] += 1
        if meta["width"] and meta["height"]:
            resolutions[(meta["width"], meta["height"])] += 1
            if meta["height"] > meta["width"]:
                vertical_count += 1
            else:
                horizontal_count += 1
        # Real bug found live: a still image's frame_rate comes from the
        # image2 muxer's own meaningless default (e.g. 25fps) and is not
        # a real property of a photo -- only aggregate/flag frame rate
        # for actual video.
        if meta["frame_rate"] and meta["media_type"] == "video":
            frame_rates[meta["frame_rate"]] += 1
            if meta["frame_rate"] > SLOW_MOTION_FPS_THRESHOLD:
                slow_motion_files.append({"path": f["relative_path"], "frame_rate": meta["frame_rate"]})

    duplicate_groups = [paths for paths in checksum_groups.values() if len(paths) > 1]

    return {
        "total_files": len(files),
        "media_type_counts": dict(media_type_counts),
        "cameras": [{"make": make, "model": model, "count": count} for (make, model), count in cameras.items()],
        "device_categories": dict(device_categories),
        "resolutions": [{"width": w, "height": h, "count": count} for (w, h), count in resolutions.items()],
        "frame_rates": [{"fps": fps, "count": count} for fps, count in frame_rates.items()],
        "vertical_count": vertical_count,
        "horizontal_count": horizontal_count,
        "slow_motion_files": slow_motion_files,
        "corrupt_files": corrupt_files,
        "duplicate_groups": duplicate_groups,
    }


# ------------------------------------------------------------ proxies (Phase 4)

# Stated, easily-adjustable assumptions -- Section 12's own named
# criteria (very high bitrate, 6K+, RAW/long-GOP-ish codec), not a
# claim about any specific camera or delivery spec being the one
# correct threshold.
PROXY_WIDTH_THRESHOLD = 5760
PROXY_BITRATE_THRESHOLD_BPS = 50_000_000
PROXY_CODEC_HINTS = ("raw", "prores_raw", "braw")


def recommend_proxy(metadata: dict) -> bool:
    """Deterministic, from already-stored Phase 2 (+ Phase 4's own
    bit_rate) metadata -- same 'compute from real data, never fabricate
    confidence' discipline as compute_media_report. Only ever considers
    real video streams; audio/image/other never need an edit proxy."""
    if not metadata or metadata.get("media_type") != "video":
        return False
    width = metadata.get("width")
    if width and width >= PROXY_WIDTH_THRESHOLD:
        return True
    bit_rate = metadata.get("bit_rate")
    if bit_rate and bit_rate >= PROXY_BITRATE_THRESHOLD_BPS:
        return True
    codec = (metadata.get("video_codec") or "").lower()
    if any(hint in codec for hint in PROXY_CODEC_HINTS):
        return True
    return False


async def compute_proxy_recommendations(job_id: int, postgres_conn: Any = None) -> list[dict]:
    """Files where recommend_proxy() is true -- for the UI's own 'N
    files would benefit' display and as the default generation set (no
    per-file picker in v1, matching this app's own YAGNI bias)."""
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    metadata_by_file_id = {m["file_id"]: m for m in await list_post_job_file_metadata(job_id, postgres_conn=postgres_conn)}
    recommendations = []
    for f in files:
        meta = metadata_by_file_id.get(f["id"])
        if meta and recommend_proxy(meta):
            recommendations.append({
                "file_id": f["id"],
                "relative_path": f["relative_path"],
                "width": meta.get("width"),
                "height": meta.get("height"),
                "bit_rate": meta.get("bit_rate"),
                "video_codec": meta.get("video_codec"),
            })
    return recommendations


def _proxies_subfolder(profile: str) -> str:
    """Looks up the profile's own already-existing PROXIES folder from
    post_profiles.py (07_PROXIES Joshx / 09_PROXIES Alpha Mode) rather
    than duplicating that name as a second hardcoded mapping here."""
    for folder in POST_PROFILES.get(profile, {}).get("folders", []):
        if "PROXIES" in folder:
            return folder
    return "PROXIES"


async def _generate_proxy_file(source_path: str, output_path: Path) -> str | None:
    """Runs one ffmpeg transcode. Never raises -- a missing binary or a
    real ffmpeg failure both degrade to a returned error string instead,
    same fail-soft discipline as probe_file(). Returns None on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-y", "-i", source_path,
            "-vf", "scale=trunc(iw/2/2)*2:trunc(ih/2/2)*2",
            "-c:v", "libx264", "-preset", "fast", "-b:v", "3M",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "ffmpeg not found -- install with `brew install ffmpeg`."
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        text = stderr.decode(errors="replace").strip()
        if not text:
            return f"ffmpeg exited with code {proc.returncode}"
        # ffmpeg's own real error is almost always in the last few lines
        # of a long stderr stream (a verbose build-config banner comes
        # first) -- keep whole trailing lines, not a raw character cut
        # that can slice a line in half.
        lines = text.splitlines()
        return "\n".join(lines[-8:])[-1000:]
    return None


async def run_proxy_generation(job_id: int, postgres_conn: Any = None) -> None:
    """One file at a time, matching every other POST phase's own
    'simple, safe, no resource contention' choice. ffmpeg already runs
    as a real separate OS process via asyncio.create_subprocess_exec, so
    -- unlike Phase 1's raw file-copy loop -- this needs no manual
    chunking to stay non-blocking; awaiting the subprocess is already
    safe for the event loop. Resumes via list_queued_post_job_file_proxies:
    a row left 'processing' by a killed/restarted loop is simply
    retried from scratch (file-level resume, matching Phase 1's own
    decision), never assumed already-done."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return
    proxies_folder = Path(job["destination_root"]) / _proxies_subfolder(job["profile"])
    pending = await list_queued_post_job_file_proxies(job_id, postgres_conn=postgres_conn)
    for row in pending:
        await mark_post_job_file_proxy_processing(row["id"], postgres_conn=postgres_conn)
        output_path = proxies_folder / Path(row["relative_path"]).with_suffix(".mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        error = await _generate_proxy_file(row["destination_path"], output_path)
        if error:
            await mark_post_job_file_proxy_failed(row["id"], error, postgres_conn=postgres_conn)
        else:
            await mark_post_job_file_proxy_complete(row["id"], str(output_path), postgres_conn=postgres_conn)
    await update_post_job_proxies_generated(job_id, postgres_conn=postgres_conn)
