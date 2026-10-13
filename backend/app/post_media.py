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
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.post_db import (
    create_post_job_file_highlights_batch,
    create_post_job_file_metadata_batch,
    create_post_job_file_proxies_batch,
    get_post_job,
    list_post_job_file_highlights,
    list_post_job_file_metadata,
    list_post_job_file_transcripts,
    list_post_job_files,
    list_queued_post_job_file_highlights,
    list_queued_post_job_file_proxies,
    mark_post_job_file_highlights_complete,
    mark_post_job_file_highlights_failed,
    mark_post_job_file_highlights_processing,
    mark_post_job_file_proxy_complete,
    mark_post_job_file_proxy_failed,
    mark_post_job_file_proxy_processing,
    update_post_job_highlights_generated,
    update_post_job_media_analyzed,
    update_post_job_proxies_generated,
    update_post_job_status,
)
from app.post_profiles import POST_PROFILES
from app.post_shot_composition import rate_frames

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

# Best-effort Log-gamma name fragments -- most cameras do NOT reliably
# tag their own Log curve via ffprobe's standard color_transfer field
# (it commonly reports "unspecified" or even "bt709" for Log-encoded
# footage), so this matches against camera_make/camera_model/video_codec
# strings instead, same "known list, never a confident guess beyond it"
# discipline as KNOWN_DRONE_MAKES/KNOWN_PHONE_MAKES above.
KNOWN_LOG_GAMMA_HINTS = ("s-log", "slog", "v-log", "vlog", "c-log", "clog", "n-log", "nlog", "log-c", "logc")


async def probe_file(path: str, limiter: "asyncio.Semaphore | None" = None) -> dict:
    """Runs ffprobe against one file. Never raises -- every failure mode
    (missing binary, corrupt file, invalid JSON) returns a dict with a
    non-None `probe_error` instead."""
    async with _limited(limiter):
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

    metadata = {
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
        # Phase 5 -- real ffprobe fields never captured in Phase 2 since
        # nothing needed them yet: the transfer/gamma curve and color
        # primaries (together, the real signal for HLG/PQ HDR detection)
        # and whether levels are studio-range ("tv") or full-range ("pc").
        "color_transfer": video_stream.get("color_transfer") if video_stream else None,
        "color_primaries": video_stream.get("color_primaries") if video_stream else None,
        "color_range": video_stream.get("color_range") if video_stream else None,
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
    metadata["color_profile_guess"] = guess_color_profile(metadata)
    return metadata


def _empty_metadata(probe_error: str) -> dict:
    return {
        "media_type": None, "duration_seconds": None, "width": None, "height": None,
        "video_codec": None, "audio_codec": None, "frame_rate": None, "bit_depth": None,
        "pixel_format": None, "color_space": None, "audio_channels": None,
        "camera_make": None, "camera_model": None, "creation_time": None, "probe_error": probe_error,
        "bit_rate": None,
        "color_transfer": None, "color_primaries": None, "color_range": None, "color_profile_guess": None,
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


def guess_color_profile(metadata: dict) -> str | None:
    """Best-effort ONLY -- 'hdr_hlg'/'hdr_pq' come from real, standard
    ffprobe transfer-characteristic tags (a genuine signal, not a
    guess); 'log' is a real guess from camera make/model/codec string
    matching since most cameras do NOT reliably tag their own Log curve
    via color_transfer (it commonly reports 'unspecified' or even
    'bt709' for Log-encoded footage -- confirmed real-world ffprobe
    behavior, not assumed). 'sdr' only when there's a real, standard,
    non-HDR transfer tag actually present -- otherwise None (unknown),
    never a false-confidence default. Surfaced in the UI as a guess for
    the 'log' case specifically, matching guess_device_category's own
    'never assert false precision' discipline."""
    if metadata.get("media_type") != "video":
        return None
    transfer = (metadata.get("color_transfer") or "").lower()
    if transfer == "arib-std-b67":
        return "hdr_hlg"
    if transfer == "smpte2084":
        return "hdr_pq"
    haystack = f"{metadata.get('camera_make') or ''} {metadata.get('camera_model') or ''} {metadata.get('video_codec') or ''}".lower()
    if any(hint in haystack for hint in KNOWN_LOG_GAMMA_HINTS):
        return "log"
    if transfer in ("bt709", "bt470bg", "smpte170m", "srgb"):
        return "sdr"
    return None


# Stated, adjustable assumptions -- a cost/coverage tradeoff (sampling,
# not every frame, keeps a per-file scan cheap on long clips, same
# performance bias as proxy generation's own '-preset fast') and
# thresholds that are a starting point, not a lighting-expert judgment.
# Thresholds below are on the 8-bit luma/chroma scale (0-255). NOTE
# (corrected 2026-10-06): signalstats reports on the source's OWN bit-depth
# scale -- 0-1023 for 10-bit footage -- NOT 0-255 as this comment used to
# claim. Found when real 10-bit 4:2:2 clips read luma ~311 and were flagged
# "overexposed"/"warm" though they're normal (the same frames read 77.8 once
# converted to 8-bit). Every signalstats chain below therefore converts with
# format=yuv420p first. (The earlier synthetic test clips were all 8-bit,
# which is why this slipped through.)
EXPOSURE_SAMPLE_INTERVAL_FRAMES = 60  # legacy full-decode fallback only
UNDEREXPOSED_LUMA_THRESHOLD = 40.0
OVEREXPOSED_LUMA_THRESHOLD = 215.0
NEUTRAL_CHROMA_MIDPOINT = 128.0
COLOR_CAST_DEVIATION_THRESHOLD = 8.0


# Sampling cost model (measured 2026-10-06 on Josh's real 4K 50p 10-bit 4:2:2
# long-GOP clips, M3 Pro): decoding every frame to sample 1 in 60 ran ~78 fps
# (24.6s for a 38s clip, ~10 cores saturated) -- the decode, not the sampling,
# is the cost. Instead each clip is sampled by seeking to a handful of
# evenly spaced points and decoding only the nearest KEYFRAME there
# (-skip_frame nokey): a few seconds per clip regardless of its length.
EXPOSURE_SEEK_SPACING_SECONDS = 3.0
EXPOSURE_SEEK_MIN_SAMPLES = 6
EXPOSURE_SEEK_MAX_SAMPLES = 16
# Cap on ffprobe/ffmpeg processes running at once during media analysis --
# it used to launch one per file simultaneously (hundreds for a big job).
# Each sample process is short and mostly startup/IO, so throughput kept
# improving up to the core count and then plateaued (measured on 14 real
# clips, M3 Pro 12 cores, warm cache: 6 -> 12.8s, 8 -> 10.7s, 12 -> 8.9s,
# 16/24 -> 8.8s).
ANALYSIS_MAX_CONCURRENT_PROCESSES = max(4, min(12, os.cpu_count() or 8))
_SIGNALSTATS_8BIT = "format=yuv420p,signalstats,metadata=print"


class _NoLimit:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> bool:
        return False


_NO_LIMIT = _NoLimit()


def _limited(limiter: "asyncio.Semaphore | None"):
    return limiter if limiter is not None else _NO_LIMIT


def _parse_signalstats(text: str) -> tuple[list[float], list[float], list[float]]:
    return (
        [float(v) for v in re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", text)],
        [float(v) for v in re.findall(r"lavfi\.signalstats\.UAVG=([\d.]+)", text)],
        [float(v) for v in re.findall(r"lavfi\.signalstats\.VAVG=([\d.]+)", text)],
    )


def _summarize_exposure(y_values: list[float], u_values: list[float], v_values: list[float]) -> dict:
    if not y_values:
        return _empty_exposure()
    avg_luma = sum(y_values) / len(y_values)
    avg_chroma_u = sum(u_values) / len(u_values) if u_values else None
    avg_chroma_v = sum(v_values) / len(v_values) if v_values else None
    return {
        "avg_luma": avg_luma,
        "avg_chroma_u": avg_chroma_u,
        "avg_chroma_v": avg_chroma_v,
        "exposure_flag": classify_exposure(avg_luma),
        "color_cast_flag": classify_color_cast(avg_chroma_u, avg_chroma_v),
    }


async def _signalstats_sample(path: str, seek_seconds: float, limiter: "asyncio.Semaphore | None") -> tuple[float, float, float] | None:
    """One sample: seek to ~seek_seconds, decode only the keyframe there,
    return its (luma, chroma_u, chroma_v) on the 8-bit scale, or None."""
    async with _limited(limiter):
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_PATH, "-hide_banner", "-v", "error", "-skip_frame", "nokey", "-ss", f"{seek_seconds:.3f}",
                "-i", path, "-frames:v", "1", "-vf", f"{_SIGNALSTATS_8BIT}:file=-", "-f", "null", "-",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return None
        stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    y, u, v = _parse_signalstats(stdout.decode(errors="replace"))
    if not y or not u or not v:
        return None
    return sum(y) / len(y), sum(u) / len(u), sum(v) / len(v)


async def _probe_exposure_full_pass(path: str, limiter: "asyncio.Semaphore | None") -> dict:
    """The original approach, kept as a fallback for files that can't be
    sampled by seeking (no usable index, unusual containers): decode the
    whole file and sample every EXPOSURE_SAMPLE_INTERVAL_FRAMES-th frame.
    Slow on heavy footage but format-agnostic."""
    fd, metadata_path = tempfile.mkstemp(prefix="post_signalstats_", suffix=".txt")
    os.close(fd)
    try:
        # The comma inside select's own expression must be backslash-
        # escaped or ffmpeg's filtergraph parser reads it as the next
        # filter's own separator, not part of the expression.
        filter_chain = f"select='not(mod(n\\,{EXPOSURE_SAMPLE_INTERVAL_FRAMES}))',{_SIGNALSTATS_8BIT}:file={metadata_path}"
        async with _limited(limiter):
            try:
                proc = await asyncio.create_subprocess_exec(
                    FFMPEG_PATH, "-y", "-i", path, "-vf", filter_chain, "-f", "null", "-",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                return _empty_exposure()
            await proc.communicate()
        if proc.returncode != 0:
            return _empty_exposure()
        try:
            text = Path(metadata_path).read_text(errors="replace")
        except OSError:
            return _empty_exposure()
        return _summarize_exposure(*_parse_signalstats(text))
    finally:
        try:
            os.unlink(metadata_path)
        except OSError:
            pass


async def probe_exposure(
    path: str, media_type: str | None, duration_seconds: float | None = None,
    limiter: "asyncio.Semaphore | None" = None,
) -> dict:
    """Averages ffmpeg's real `signalstats` YAVG/UAVG/VAVG (8-bit scale)
    over a handful of sampled keyframes in plain Python -- same 'one
    source of truth, aggregate real per-sample data ourselves' discipline
    as compute_media_report, not a second computation path. Never raises
    -- a missing binary, an unreadable video, or a parse failure all
    degrade to a dict of Nones, same discipline as probe_file(). Skipped
    entirely for non-video media -- there's no exposure concept for
    audio/stills/other.

    With a known duration it samples by seeking (cheap, length-independent);
    if too few samples come back, or the duration is unknown, it falls back
    to the slower whole-file decode so odd formats still get an answer."""
    if media_type != "video":
        return _empty_exposure()
    if duration_seconds and duration_seconds > 0:
        count = min(EXPOSURE_SEEK_MAX_SAMPLES, max(EXPOSURE_SEEK_MIN_SAMPLES, round(duration_seconds / EXPOSURE_SEEK_SPACING_SECONDS)))
        samples = await asyncio.gather(*(
            _signalstats_sample(path, duration_seconds * (i + 0.5) / count, limiter) for i in range(count)
        ))
        good = [s for s in samples if s is not None]
        if len(good) >= max(2, count // 2):
            return _summarize_exposure([s[0] for s in good], [s[1] for s in good], [s[2] for s in good])
    return await _probe_exposure_full_pass(path, limiter)


def _empty_exposure() -> dict:
    return {"avg_luma": None, "avg_chroma_u": None, "avg_chroma_v": None, "exposure_flag": None, "color_cast_flag": None}


def classify_exposure(avg_luma: float | None) -> str | None:
    """'underexposed' / 'overexposed' / 'normal' / None (no data) --
    deterministic, no LLM, matching compute_media_report's own
    discipline. Thresholds are a stated assumption, not a lighting-
    expert judgment -- flagged for Josh's own adjustment once he's seen
    it run against real footage, same disclosed-assumption pattern as
    Phase 2's SLOW_MOTION_FPS_THRESHOLD."""
    if avg_luma is None:
        return None
    if avg_luma < UNDEREXPOSED_LUMA_THRESHOLD:
        return "underexposed"
    if avg_luma > OVEREXPOSED_LUMA_THRESHOLD:
        return "overexposed"
    return "normal"


# A rough, disclosed heuristic for a Premiere Lumetri "Exposure" starting
# nudge (real stops parameter, confirmed via a live spike against Josh's
# installed Premiere -- see project_pcorp_post_division.md). NOT a
# calibrated gamma-to-linear-light conversion -- this app has no real
# color-managed pixel processing to do that correctly, so the scaling
# below is deliberately simple and stated as an adjustable assumption,
# same posture as UNDEREXPOSED_LUMA_THRESHOLD/SLOW_MOTION_FPS_THRESHOLD.
# Scales from 0 stops right at the classification threshold up to
# EXPOSURE_NUDGE_MAX_STOPS at the extreme (pure black / pure white) --
# always a mild starting point for Josh's own eye, never a claimed fix.
EXPOSURE_NUDGE_MAX_STOPS = 1.0


def compute_exposure_nudge_stops(avg_luma: float | None) -> float | None:
    """None when there's no real luma data at all (audio/stills/corrupt
    files). 0.0 when the clip already classifies 'normal' -- no
    correction needed. A signed stops value, scaled by how far PAST the
    underexposed/overexposed threshold the real avg_luma sits, clamped
    to +/-EXPOSURE_NUDGE_MAX_STOPS -- positive brightens, negative
    darkens, matching Lumetri's own real Exposure parameter sign."""
    if avg_luma is None:
        return None
    if avg_luma < UNDEREXPOSED_LUMA_THRESHOLD:
        overshoot = UNDEREXPOSED_LUMA_THRESHOLD - avg_luma
        return round(min(1.0, overshoot / UNDEREXPOSED_LUMA_THRESHOLD) * EXPOSURE_NUDGE_MAX_STOPS, 2)
    if avg_luma > OVEREXPOSED_LUMA_THRESHOLD:
        max_overshoot = 255.0 - OVEREXPOSED_LUMA_THRESHOLD
        overshoot = avg_luma - OVEREXPOSED_LUMA_THRESHOLD
        return round(-min(1.0, overshoot / max_overshoot) * EXPOSURE_NUDGE_MAX_STOPS, 2)
    return 0.0


def classify_color_cast(avg_chroma_u: float | None, avg_chroma_v: float | None) -> str | None:
    """'warm' / 'cool' / 'neutral' / None -- an explicitly ROUGH
    directional signal from real YUV chroma averages (U leans blue/
    yellow, V leans red/green around a neutral 128 midpoint for 8-bit),
    never a color-temperature (Kelvin) claim -- that needs real color-
    managed processing this app doesn't have. Labeled as a rough signal
    everywhere it surfaces, matching this app's own 'never assert false
    precision' discipline."""
    if avg_chroma_u is None or avg_chroma_v is None:
        return None
    u_deviation = avg_chroma_u - NEUTRAL_CHROMA_MIDPOINT
    v_deviation = avg_chroma_v - NEUTRAL_CHROMA_MIDPOINT
    if abs(u_deviation) < COLOR_CAST_DEVIATION_THRESHOLD and abs(v_deviation) < COLOR_CAST_DEVIATION_THRESHOLD:
        return "neutral"
    return "cool" if u_deviation > v_deviation else "warm"


# ------------------------------------------------------------ best-moment selection (was Phase 9's motion/audio "highlight" detection)
# REDESIGNED 2026-10-06. Phase 9 defined a "highlight" as the MOST ACTIVE part of
# a clip (frame-difference motion + loud audio). Josh's footage is handheld store
# b-roll, where "most active" means camera shake, whips and focus hunting, and the
# first rough cut was built from exactly those. Measured on his real clips: the
# picked windows had MORE motion than the rest of the clip in 8/8 clips and were
# BLURRIER in 6/8 (ffmpeg blurdetect). He said it "took the worst parts" -- right.
# A usable b-roll moment is the opposite: STEADY and SHARP. So each clip is now
# scored in sliding windows on those two signals (standardised per clip, so it
# works on any footage) and the best few non-overlapping windows are kept.
# This is a mechanical quality heuristic, not taste: it cannot judge composition,
# subject or story -- that stays Josh's call in the edit.
BEST_WINDOW_SECONDS = 2.0  # steady-only fallback window (Josh's own cuts of the first two clips were 1.4s and 2.2s, not 3s)
BEST_WINDOW_STEP_SECONDS = 0.5
BEST_EDGE_SECONDS = 0.7  # handheld clips wobble as the operator starts/stops recording
BEST_MIN_SEPARATION_SECONDS = 3.0  # clear gap between two picks from one clip, so they are different shots, not one shot cut in half
BEST_KEYFRAME_GAP_SECONDS = 0.3
BEST_MIN_SAMPLES = 4
BEST_MAX_AVG_SAMPLE_GAP_SECONDS = 2.0
HIGHLIGHT_SAMPLE_INTERVAL_FRAMES = 15  # full-decode fallback only
HIGHLIGHT_MIN_DURATION_SECONDS = 1.0  # floor used only when a pick has to be shifted to stay inside the clip
# A keyframe-only pass uses ~1.3 cores (unlike the old full decode, which
# saturated every core), so several files can run at once (measured: throughput
# plateaus around 6-8 files at once on a 12-core M3 Pro).
HIGHLIGHT_MAX_CONCURRENT_FILES = max(2, min(8, (os.cpu_count() or 8) // 2))


def _parse_metadata_series(text: str, key: str) -> list[tuple[float, float]]:
    """ffmpeg's metadata=print writes one block per sampled frame ("pts_time:5.14"
    then "<key>=32.85" on a later line) -- each value must be paired with the SAME
    frame's own timestamp."""
    results: list[tuple[float, float]] = []
    current_time: float | None = None
    value_re = re.compile(re.escape(key) + r"=(-?[\d.]+)")
    for line in text.splitlines():
        time_match = re.search(r"pts_time:([\d.]+)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        value_match = value_re.search(line)
        if value_match and current_time is not None:
            results.append((current_time, float(value_match.group(1))))
    return results


async def _run_quality_pass(path: str, keyframes_only: bool) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """ONE ffmpeg decode producing two time series: (timestamp, blur) from
    blurdetect (higher = softer) and (timestamp, motion) from the frame-to-frame
    luma difference (higher = more camera/subject movement), both on 8-bit data.
    Never raises -- degrades to ([], []) on any failure."""
    fd1, blur_path = tempfile.mkstemp(prefix="post_blur_", suffix=".txt")
    fd2, motion_path = tempfile.mkstemp(prefix="post_motion_", suffix=".txt")
    os.close(fd1)
    os.close(fd2)
    try:
        if keyframes_only:
            pre_args = ["-skip_frame", "nokey"]
            sampler = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{BEST_KEYFRAME_GAP_SECONDS})'"
        else:
            pre_args = []
            sampler = f"select='not(mod(n\\,{HIGHLIGHT_SAMPLE_INTERVAL_FRAMES}))'"
        graph = (
            f"[0:v]{sampler},format=yuv420p,split=2[a][b];"
            f"[a]blurdetect,metadata=print:key=lavfi.blur:file={blur_path}[oa];"
            f"[b]tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={motion_path}[ob]"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_PATH, "-y", *pre_args, "-i", path, "-an", "-filter_complex", graph,
                "-map", "[oa]", "-f", "null", "-", "-map", "[ob]", "-f", "null", "-",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return [], []
        await proc.communicate()
        if proc.returncode != 0:
            return [], []
        try:
            blur = _parse_metadata_series(Path(blur_path).read_text(errors="replace"), "lavfi.blur")
            motion = _parse_metadata_series(Path(motion_path).read_text(errors="replace"), "lavfi.signalstats.YAVG")
        except OSError:
            return [], []
        return blur, motion
    finally:
        for tmp in (blur_path, motion_path):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _series_too_sparse(series: list[tuple[float, float]]) -> bool:
    if len(series) < BEST_MIN_SAMPLES:
        return True
    return (series[-1][0] - series[0][0]) / (len(series) - 1) > BEST_MAX_AVG_SAMPLE_GAP_SECONDS


def _picks_for_duration(duration_seconds: float) -> int:
    """How many moments to take from one clip: one from a short clip, up to
    three from a long one, so a long take contributes more without dominating."""
    if duration_seconds < 12:
        return 1
    if duration_seconds < 30:
        return 2
    return 3


BEST_CANDIDATE_POOL = 4  # steady-only fallback: how many ranked windows to consider
STILL_MAX_HEIGHT = 384

# ---- composition-driven shots (the main path; see post_shot_composition.py for why)
# Tuned against Josh's own hand-corrected cuts of the first two clips: 1.36s and
# 2.18s long, both starting in the first 1.4s of the clip, the subject complete in
# frame. Two examples can't define taste -- they set the starting point and the
# picks should be reviewed and corrected, which feeds back in.
COMPOSE_STEP_SECONDS = 0.5
COMPOSE_MAX_STILLS = 40
COMPOSE_RATING_PASSES = 3  # Claude's per-frame scores wobble about a notch between identical calls (no temperature control); averaging passes steadies the shots
COMPOSE_MIN_SEGMENT = 1.2
COMPOSE_MAX_SEGMENT = 2.0  # his two cuts were 1.4s and 2.2s
COMPOSE_QUALITY_FLOOR = 7.0  # a frame rated below this never starts a shot if the clip has anything better (an early frame may only win a NEAR-tie when it is genuinely good)
COMPOSE_MIN_START = 0.3  # first moments of a recording are autofocus hunting and the operator settling (Josh's cuts started at 0.34s and 1.32s, never at 0)
COMPOSE_MIN_PEAK = 5.0  # the best frame of a clip must rate at least this to be used at all
COMPOSE_EXTRA_MIN_PEAK = 7.0  # a 2nd/3rd shot from the same clip must be clearly good
COMPOSE_RUN_FLOOR = 6.0  # frames below this are never part of a shot
COMPOSE_RUN_TOLERANCE = 1.0  # "good enough" = within this of the clip's best frame; the shot starts at the EARLIEST such frame
COMPOSE_SEPARATION_SECONDS = 1.0  # clear gap kept between two shots from one clip
EARLY_BONUS_POINTS = 1.0  # mild preference for the opening of a clip: full bonus up to ...
EARLY_BONUS_FULL_UNTIL = 2.0
EARLY_BONUS_ZERO_AT = 10.0
STEADY_PENALTY_WEIGHT = 0.8  # per unit of z(blur)+z(motion) worse than the clip's own average


def _rank_windows(
    blur: list[tuple[float, float]], motion: list[tuple[float, float]], duration_seconds: float, pool: int
) -> list[dict]:
    """STEADY-ONLY fallback (used when no vision client is available or its call
    fails). Slides a BEST_WINDOW_SECONDS window across the clip (skipping the first
    and last BEST_EDGE_SECONDS), scores each as z(blur)+z(motion) over THIS clip's
    own windows (lower = steadier and sharper) and returns up to `pool`
    non-overlapping candidates, best first, each {"start", "duration", "z"}. A clip
    too short to score yields one centred candidate with z=None."""
    window = min(BEST_WINDOW_SECONDS, max(duration_seconds - 0.2, 0.5))
    usable = duration_seconds - 2 * BEST_EDGE_SECONDS

    def centred() -> list[dict]:
        start = max(0.0, (duration_seconds - window) / 2)
        return [{"start": round(start, 3), "duration": round(window, 3), "z": None}]

    if usable < window or not blur or not motion:
        return centred()

    def window_mean(series: list[tuple[float, float]], start: float) -> float | None:
        values = [v for t, v in series if start <= t <= start + window]
        return sum(values) / len(values) if values else None

    starts = [BEST_EDGE_SECONDS + i * BEST_WINDOW_STEP_SECONDS for i in range(int((usable - window) / BEST_WINDOW_STEP_SECONDS) + 1)]
    rows = [(s, window_mean(blur, s), window_mean(motion, s)) for s in starts]
    rows = [r for r in rows if r[1] is not None and r[2] is not None]
    if len(rows) < 2:
        return centred()
    z_blur = _zscores([r[1] for r in rows])
    z_motion = _zscores([r[2] for r in rows])
    ranked = sorted((z_blur[i] + z_motion[i], rows[i][0]) for i in range(len(rows)))
    chosen: list[dict] = []
    for z, start in ranked:
        if all(abs(start - c["start"]) >= window + 0.5 for c in chosen):
            chosen.append({"start": round(start, 3), "duration": round(window, 3), "z": round(z, 3)})
        if len(chosen) >= pool:
            break
    return chosen


def _zscores(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    spread = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5 or 1.0
    return [(v - mean) / spread for v in values]


def _select_steady_picks(candidates: list[dict], duration_seconds: float) -> list[dict]:
    """Steady-only fallback selection: best first, extras must beat the clip's own
    average steadiness, quota 1/2/3 by clip length. Labelled source "steady"."""
    window = candidates[0]["duration"] if candidates else BEST_WINDOW_SECONDS
    quota = _picks_for_duration(duration_seconds)
    chosen: list[dict] = []
    for c in candidates:
        if chosen and c["z"] is not None and c["z"] > 0:
            continue
        if all(abs(c["start"] - o["start"]) >= window + BEST_MIN_SEPARATION_SECONDS for o in chosen):
            chosen.append(c)
        if len(chosen) >= quota:
            break
    return [
        {"start": c["start"], "duration": c["duration"], "source": "fallback" if c["z"] is None else "steady", "score": c["z"], "rank": rank}
        for rank, c in enumerate(sorted(chosen, key=lambda c: (c["z"] is None, c["z"] or 0)), start=1)
    ]


def _composition_times(duration_seconds: float) -> list[float]:
    """Times to sample a still at: every COMPOSE_STEP_SECONDS (wider for long clips
    so there are at most COMPOSE_MAX_STILLS), starting just inside the clip."""
    step = COMPOSE_STEP_SECONDS if duration_seconds <= COMPOSE_STEP_SECONDS * COMPOSE_MAX_STILLS else duration_seconds / COMPOSE_MAX_STILLS
    times: list[float] = []
    t = 0.2
    while t < duration_seconds - 0.2 and len(times) < COMPOSE_MAX_STILLS:
        times.append(round(t, 2))
        t += step
    return times


def _early_bonus(t: float) -> float:
    if t <= EARLY_BONUS_FULL_UNTIL:
        return EARLY_BONUS_POINTS
    if t >= EARLY_BONUS_ZERO_AT:
        return 0.0
    return EARLY_BONUS_POINTS * (EARLY_BONUS_ZERO_AT - t) / (EARLY_BONUS_ZERO_AT - EARLY_BONUS_FULL_UNTIL)


def _nearest_value(series: list[tuple[float, float]], t: float) -> float | None:
    return min(series, key=lambda p: abs(p[0] - t))[1] if series else None


def _pick_segments(times: list[float], scores: list[float], step: float, duration_seconds: float, quota: int) -> list[dict]:
    """Turns per-frame scores into short shots. A frame is "good" when it is within
    COMPOSE_RUN_TOLERANCE of the best remaining frame (and >= COMPOSE_RUN_FLOOR).
    The shot starts at the EARLIEST good frame -- among stretches that are about
    equally good the first one wins, which is where an operator has just framed the
    shot (Josh's hand-corrected cuts of the first two clips both began in the
    opening seconds) -- and runs while frames stay good, at most COMPOSE_MAX_SEGMENT
    and at least COMPOSE_MIN_SEGMENT. A 2nd/3rd shot must be clearly good (peak >=
    COMPOSE_EXTRA_MIN_PEAK) and clear of the shots already taken.
    Returns [{"start", "duration", "peak", "anchor"}], best first."""
    n = len(times)
    taken = [False] * n
    shots: list[dict] = []
    while len(shots) < quota:
        free = [i for i in range(n) if not taken[i]]
        if not free:
            break
        peak = max(scores[i] for i in free)
        if peak < (COMPOSE_MIN_PEAK if not shots else COMPOSE_EXTRA_MIN_PEAK):
            break
        threshold = max(min(COMPOSE_RUN_FLOOR, peak), peak - COMPOSE_RUN_TOLERANCE)
        a = next(i for i in free if scores[i] >= threshold)
        b = a
        while b < n - 1 and not taken[b + 1] and scores[b + 1] >= threshold:
            b += 1
        start = max(0.0, times[a] - step / 2)
        end = min(duration_seconds, times[b] + step / 2)
        if end - start > COMPOSE_MAX_SEGMENT:
            end = start + COMPOSE_MAX_SEGMENT
        if start < COMPOSE_MIN_START and duration_seconds - COMPOSE_MIN_START >= COMPOSE_MIN_SEGMENT:
            length = end - start
            start = COMPOSE_MIN_START
            end = min(duration_seconds, start + length)
        if end - start < COMPOSE_MIN_SEGMENT:
            centre = (start + end) / 2
            start = centre - COMPOSE_MIN_SEGMENT / 2
            end = centre + COMPOSE_MIN_SEGMENT / 2
            if start < 0:
                start, end = 0.0, COMPOSE_MIN_SEGMENT
            if end > duration_seconds:
                start, end = max(0.0, duration_seconds - COMPOSE_MIN_SEGMENT), duration_seconds
        shots.append({"start": round(start, 3), "duration": round(end - start, 3), "peak": peak, "anchor": times[a]})
        for i in range(n):
            if start - COMPOSE_SEPARATION_SECONDS <= times[i] <= end + COMPOSE_SEPARATION_SECONDS:
                taken[i] = True
    return shots


def _compose_candidates(
    ratings: dict[float, dict], times: list[float], blur: list[tuple[float, float]], motion: list[tuple[float, float]],
    duration_seconds: float,
) -> list[dict]:
    """Per-frame final score = Claude's composition rating + a mild opening-of-clip
    bonus - a mild penalty for being less steady/sharp than the clip's own average;
    then _pick_segments. Frames Claude didn't rate are left out."""
    step = (times[1] - times[0]) if len(times) > 1 else COMPOSE_STEP_SECONDS
    z_series: list[tuple[float, float]] = []
    if blur and motion and len(blur) >= 2 and len(motion) >= 2:
        zb = _zscores([v for _, v in blur])
        zm = _zscores([v for _, v in motion])
        z_blur = [(t, z) for (t, _), z in zip(blur, zb)]
        z_motion = [(t, z) for (t, _), z in zip(motion, zm)]
        z_series = [(t, (_nearest_value(z_blur, t) or 0.0) + (_nearest_value(z_motion, t) or 0.0)) for t, _ in blur]
    rated_times = [t for t in times if t in ratings]
    if not rated_times:
        return []
    # A shot lasts a second or two but frames are rated every half second one by one,
    # so a single odd rating shouldn't decide anything: weight each frame 1-2-1 with its neighbours.
    raw = [ratings[t]["score"] for t in rated_times]
    smoothed = [
        sum(w * raw[j] for j, w in ((i - 1, 1), (i, 2), (i + 1, 1)) if 0 <= j < len(raw))
        / sum(w for j, w in ((i - 1, 1), (i, 2), (i + 1, 1)) if 0 <= j < len(raw))
        for i in range(len(raw))
    ]
    floor = min(COMPOSE_QUALITY_FLOOR, max(smoothed) - 1.0)
    scores = []
    for t, base in zip(rated_times, smoothed):
        penalty = STEADY_PENALTY_WEIGHT * max(0.0, _nearest_value(z_series, t) or 0.0) if z_series else 0.0
        scores.append(base + _early_bonus(t) - penalty if base >= floor else -1.0)
    shots = _pick_segments(rated_times, scores, step, duration_seconds, _picks_for_duration(duration_seconds))
    candidates = []
    for rank, shot in enumerate(shots, start=1):
        anchor = ratings[shot["anchor"]]
        candidates.append({
            "start": shot["start"], "duration": shot["duration"], "source": "composed", "score": round(shot["peak"], 2), "rank": rank,
            "composition": {"score": anchor["score"], "subject": anchor["subject"], "issue": anchor["issue"]},
        })
    if candidates:
        # kept with the best pick so the selection rules can be re-tuned offline, without new Claude calls
        candidates[0]["ratings"] = {str(t): round(ratings[t]["score"], 2) for t in rated_times}
    return sorted(candidates, key=lambda c: c["start"])


def _average_ratings(passes: list) -> dict[float, dict] | None:
    """Mean score per frame over the passes that produced one (a failed pass is
    simply left out). The subject/issue text comes from the lowest-scoring pass for
    that frame, so a flaw one pass noticed isn't averaged away. None if no pass
    produced anything."""
    usable = [p for p in passes if p]
    if not usable:
        return None
    merged: dict[float, dict] = {}
    for t in sorted({t for p in usable for t in p}):
        seen = [p[t] for p in usable if t in p]
        worst = min(seen, key=lambda r: r["score"])
        merged[t] = {"score": round(sum(r["score"] for r in seen) / len(seen), 2), "subject": worst["subject"], "issue": worst["issue"]}
    return merged


async def _extract_still(path: str, at_seconds: float, limiter: "asyncio.Semaphore | None" = None) -> bytes | None:
    """One JPEG still (upright, STILL_MAX_HEIGHT px tall) from the nearest frame to
    at_seconds, or None. Never raises."""
    async with _limited(limiter):
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_PATH, "-hide_banner", "-v", "error", "-ss", f"{at_seconds:.3f}", "-i", path,
                "-frames:v", "1", "-vf", f"scale=-2:{STILL_MAX_HEIGHT}", "-q:v", "4", "-f", "mjpeg", "-",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return None
        stdout, _ = await proc.communicate()
    return stdout if proc.returncode == 0 and stdout else None


async def detect_highlight_candidates(
    path: str, media_type: str | None, duration_seconds: float | None,
    *, vision: tuple[Any, str] | None = None, context: str = "", limiter: "asyncio.Semaphore | None" = None,
) -> list[dict]:
    """Best shot(s) from a clip for footage with no dialogue to anchor on -- the
    non-dialogue counterpart to post_transcripts.py's find_smart_select_candidates().
    (Name kept for its callers.) Video only. Never raises -- degrades to [] on any
    ffmpeg failure.

    With `vision` = (anthropic_client, model): stills are sampled across the clip,
    Claude rates each frame's composition (post_shot_composition.py), and shots are
    the short runs of well-composed frames (_compose_candidates), source "composed".
    Without it, or if the call fails, the steadiest/sharpest windows are used and
    labelled "steady" so the caller can tell they weren't composition-checked.
    Returns [{"start", "duration", "source", "score", "rank", "composition"?}, ...]
    chronologically, clamped to the clip's length; rank 1 = best."""
    if media_type != "video":
        return []
    blur, motion = await _run_quality_pass(path, keyframes_only=True)
    if _series_too_sparse(blur) or _series_too_sparse(motion):
        blur, motion = await _run_quality_pass(path, keyframes_only=False)
    duration = duration_seconds or max([t for t, _ in blur] + [t for t, _ in motion] + [0.0]) + BEST_EDGE_SECONDS
    if duration <= 0.3:
        return []

    if vision is not None:
        times = _composition_times(duration)
        stills = await asyncio.gather(*(_extract_still(path, t, limiter) for t in times))
        frames = [(t, jpeg) for t, jpeg in zip(times, stills) if jpeg]
        if frames:
            client, model = vision
            ratings = _average_ratings(
                await asyncio.gather(*(rate_frames(client, model, frames, context) for _ in range(COMPOSE_RATING_PASSES)))
            )
            if ratings:
                return _clamp_candidates_to_clip(_compose_candidates(ratings, [t for t, _ in frames], blur, motion, duration), duration_seconds)

    steady = _rank_windows(blur, motion, duration, BEST_CANDIDATE_POOL)
    return _clamp_candidates_to_clip(sorted(_select_steady_picks(steady, duration), key=lambda c: c["start"]), duration_seconds)


def _clamp_candidates_to_clip(candidates: list[dict], clip_duration: float | None) -> list[dict]:
    """Keeps every span inside the clip: Assemble Rough Cut cuts its subclips from
    start to start+duration, so a span running past the last frame would fail.
    Shifts such a span earlier (keeping its length where it can) rather than
    shrinking it to nothing. A no-op when the clip's duration isn't known."""
    if not clip_duration or clip_duration <= 0:
        return candidates
    clamped = []
    for c in candidates:
        end = min(c["start"] + c["duration"], clip_duration)
        start = c["start"]
        if end - start < min(HIGHLIGHT_MIN_DURATION_SECONDS, clip_duration):
            start = max(0.0, end - min(HIGHLIGHT_MIN_DURATION_SECONDS, clip_duration))
        if end - start <= 0:
            continue
        clamped.append({**c, "start": round(start, 3), "duration": round(end - start, 3)})
    return clamped


async def run_media_analysis(job_id: int, postgres_conn: Any = None) -> None:
    """Probes every file belonging to this job and stores the results.
    Runs every probe concurrently (asyncio.gather) -- unlike Phase 1's
    ingestion, these are lightweight subprocess calls reading only file
    headers (plus, for probe_exposure, a handful of sampled frames), not
    multi-GB sequential I/O, so there's no need for the chunked-yield
    discipline the copy phase requires. Phase 5's probe_exposure runs
    only after probe_file resolves each file's real media_type -- it's
    a real decode pass, so it's skipped outright for non-video files."""
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    if not files:
        await update_post_job_media_analyzed(job_id, postgres_conn=postgres_conn)
        return
    # One pipeline per file (probe, then exposure from that probe's real
    # media_type/duration), all files in flight together so the CPU stays
    # busy, with a shared cap on how many ffprobe/ffmpeg processes run at
    # once (it used to launch one per file simultaneously).
    limiter = asyncio.Semaphore(ANALYSIS_MAX_CONCURRENT_PROCESSES)

    async def analyze(f: dict) -> dict:
        probe = await probe_file(f["destination_path"], limiter=limiter)
        exposure = await probe_exposure(
            f["destination_path"], probe["media_type"], probe.get("duration_seconds"), limiter=limiter
        )
        return {"file_id": f["id"], **probe, **exposure}

    rows = await asyncio.gather(*(analyze(f) for f in files))
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
    color_profile_counts: dict[str, int] = defaultdict(int)
    flagged_exposure_files: list[dict] = []
    flagged_color_cast_files: list[dict] = []

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
        # Phase 5 -- color profile only means anything for real video;
        # exposure/color-cast flags only exist when probe_exposure
        # actually ran (also video-only, see run_media_analysis).
        if meta["media_type"] == "video":
            color_profile_counts[meta.get("color_profile_guess") or "unknown"] += 1
            if meta.get("exposure_flag") in ("underexposed", "overexposed"):
                flagged_exposure_files.append({"path": f["relative_path"], "flag": meta.get("exposure_flag")})
            if meta.get("color_cast_flag") in ("warm", "cool"):
                flagged_color_cast_files.append({"path": f["relative_path"], "flag": meta.get("color_cast_flag")})

    duplicate_groups = [paths for paths in checksum_groups.values() if len(paths) > 1]
    # A real, useful signal: a shoot combining Log/HDR footage with
    # standard SDR footage won't grade the same way straight out of the
    # box -- worth flagging even though nothing here decides what to do
    # about it.
    mixed_color_spaces = len([k for k in color_profile_counts if k in ("log", "hdr_hlg", "hdr_pq", "sdr")]) > 1

    # Phase 6 -- dialogue transcription is done entirely by Premiere's
    # own native engine (see post_transcripts.py); this only counts what
    # was already stored. "Pending" means a video file with a real audio
    # track that hasn't been transcribed yet -- files with no audio at
    # all (audio_codec is None) are never counted as pending anything.
    transcripts = await list_post_job_file_transcripts(job_id, postgres_conn=postgres_conn)
    transcribed_file_ids = {t["file_id"] for t in transcripts}
    files_with_audio = sum(1 for f in files if (metadata_by_file_id.get(f["id"]) or {}).get("audio_codec"))
    dialogue_summary = {
        "files_with_transcripts": len(transcripts),
        "files_flagged_profanity": sum(1 for t in transcripts if t["has_profanity"]),
        "files_flagged_filler_words": sum(1 for t in transcripts if t["has_filler_words"]),
        "files_pending_transcription": max(files_with_audio - len(transcripts), 0),
    }

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
        "color_profile_counts": dict(color_profile_counts),
        "mixed_color_spaces": mixed_color_spaces,
        "flagged_exposure_files": flagged_exposure_files,
        "flagged_color_cast_files": flagged_color_cast_files,
        "dialogue_summary": dialogue_summary,
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


# ------------------------------------------------------------ shared triggers (Phase 7)
# One source of truth for the guarded status-flip logic behind both the
# REST routes (/analyze-media, /generate-proxies) and Frank's own new
# analyze_post_job_media/generate_post_job_proxies chat tools -- the two
# entry points must never be allowed to drift on their own guards.

async def trigger_media_analysis(job_id: int, postgres_conn: Any = None) -> tuple[bool, str]:
    """Guarded 'ingested' -> 'analyzing_media' status flip. The actual
    ffprobe work happens in the background loop's own phase, never here
    -- this only starts it. Returns (started, message)."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return False, f"No POST job with id {job_id}."
    started = await update_post_job_status(
        job_id, "analyzing_media", from_statuses=("ingested",), postgres_conn=postgres_conn,
    )
    if not started:
        return False, f"Job #{job_id} must be 'ingested' to analyze media (currently {job['status']!r})."
    return True, f"Started media analysis for job #{job_id} \"{job['shoot_name']}\"."


async def trigger_proxy_generation(job_id: int, postgres_conn: Any = None) -> tuple[bool, str, int]:
    """Guarded 'ingested' -> 'generating_proxies' status flip + creates
    the real 'queued' proxy rows for every currently-recommended file.
    Returns (started, message, file_count)."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return False, f"No POST job with id {job_id}.", 0
    if not job.get("media_analyzed_at"):
        return False, f"Job #{job_id} needs Analyze Media run first.", 0
    recommendations = await compute_proxy_recommendations(job_id, postgres_conn=postgres_conn)
    if not recommendations:
        return False, f"No files in job #{job_id} currently need a proxy.", 0
    started = await update_post_job_status(
        job_id, "generating_proxies", from_statuses=("ingested",), postgres_conn=postgres_conn,
    )
    if not started:
        return False, f"Job #{job_id} must be 'ingested' to generate proxies (currently {job['status']!r}).", 0
    await create_post_job_file_proxies_batch([r["file_id"] for r in recommendations], postgres_conn=postgres_conn)
    return True, f"Started proxy generation for {len(recommendations)} file(s) in job #{job_id} \"{job['shoot_name']}\".", len(recommendations)


def _proxies_subfolder(profile: str) -> str:
    """Looks up the profile's own already-existing PROXIES folder from
    post_profiles.py (07_PROXIES Joshx / 09_PROXIES Alpha Mode) rather
    than duplicating that name as a second hardcoded mapping here."""
    for folder in POST_PROFILES.get(profile, {}).get("folders", []):
        if "PROXIES" in folder:
            return folder
    return "PROXIES"


# Proxy encode settings (changed 2026-10-06; measured on Josh's real 4K 50p
# 10-bit 4:2:2 clips, M3 Pro). The old command had no pixel-format
# constraint, so libx264 emitted 10-bit 4:4:4 "High 4:4:4 Predictive" H.264
# -- heavier to play back than many sources, defeating the point of a proxy
# -- and ran ~40 fps. 8-bit 4:2:0 is the standard, hardware-decodable proxy
# format, and Apple's VideoToolbox encoder (falling back to software if it
# ever errors) took the same 10s test from 12.6s to 8.2s. Mean colour of the
# same frame was identical to the original in every variant. The ceiling is
# decoding the 4K 10-bit source (~76 fps, all cores), which no encoder fixes.
PROXY_VIDEO_FILTER = "scale=trunc(iw/2/2)*2:trunc(ih/2/2)*2,format=yuv420p"
_PROXY_ENCODERS: tuple[tuple[str, list[str]], ...] = (
    ("h264_videotoolbox", ["-c:v", "h264_videotoolbox", "-b:v", "3M"]),
    ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "3M"]),
)
# Two transcodes at once finished the same work ~20% sooner than one at a
# time (measured); more than that just fights over the same cores.
PROXY_MAX_CONCURRENT_TRANSCODES = 2


async def _run_proxy_ffmpeg(source_path: str, output_path: Path, video_args: list[str]) -> str | None:
    """One ffmpeg transcode attempt. Never raises -- a missing binary or a
    real ffmpeg failure both degrade to a returned error string instead,
    same fail-soft discipline as probe_file(). Returns None on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-y", "-i", source_path,
            "-vf", PROXY_VIDEO_FILTER,
            *video_args,
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


async def _generate_proxy_file(source_path: str, output_path: Path) -> str | None:
    """Tries the hardware encoder first, then software; returns None on
    success or the LAST attempt's error text. A failed attempt can leave a
    partial file behind, so it's removed before the next try."""
    error: str | None = None
    for _name, video_args in _PROXY_ENCODERS:
        error = await _run_proxy_ffmpeg(source_path, output_path, video_args)
        if error is None:
            return None
        if error.startswith("ffmpeg not found"):
            return error  # a second encoder can't help
        output_path.unlink(missing_ok=True)
    return error


async def run_proxy_generation(job_id: int, postgres_conn: Any = None) -> None:
    """Up to PROXY_MAX_CONCURRENT_TRANSCODES files at a time (was strictly
    one). ffmpeg already runs as a real separate OS process via
    asyncio.create_subprocess_exec, so -- unlike Phase 1's raw file-copy
    loop -- this needs no manual chunking to stay non-blocking. Resumes via
    list_queued_post_job_file_proxies: a row left 'processing' by a
    killed/restarted loop is simply retried from scratch (file-level
    resume, matching Phase 1's own decision), never assumed already-done.
    The shared DB connection serializes its own writes, so the concurrent
    workers can safely mark their rows on it."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return
    proxies_folder = Path(job["destination_root"]) / _proxies_subfolder(job["profile"])
    pending = await list_queued_post_job_file_proxies(job_id, postgres_conn=postgres_conn)
    limiter = asyncio.Semaphore(PROXY_MAX_CONCURRENT_TRANSCODES)

    async def transcode(row: dict) -> None:
        async with limiter:
            await mark_post_job_file_proxy_processing(row["id"], postgres_conn=postgres_conn)
            output_path = proxies_folder / Path(row["relative_path"]).with_suffix(".mp4")
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                error = await _generate_proxy_file(row["destination_path"], output_path)
            except Exception as exc:  # one odd file must not strand the other worker mid-run
                error = f"{type(exc).__name__}: {exc}"
            if error:
                await mark_post_job_file_proxy_failed(row["id"], error, postgres_conn=postgres_conn)
            else:
                await mark_post_job_file_proxy_complete(row["id"], str(output_path), postgres_conn=postgres_conn)

    await asyncio.gather(*(transcode(row) for row in pending))
    await update_post_job_proxies_generated(job_id, postgres_conn=postgres_conn)


# ------------------------------------------------------------ highlight detection trigger (Phase 9)
# Mirrors trigger_proxy_generation's own real/queued/processing/failed
# shape rather than Analyze Media's simpler one-shot gather -- highlight
# detection runs two real ffmpeg decode passes per file (closer in cost
# profile to a proxy transcode than to a metadata probe), so it gets the
# same crash-resumable per-file lifecycle.

async def trigger_highlight_detection(
    job_id: int, postgres_conn: Any = None, *, keep_composed: bool = False,
) -> tuple[bool, str, int]:
    """Guarded ('ingested'|'premiere_project_created') -> 'analyzing_color'
    status flip (see POST_JOB_STATUSES's own comment for why this
    reuses that value rather than a genuine 'detecting_highlights' name
    -- a real, disclosed naming mismatch, not an oversight) + creates
    the real 'queued' highlight rows for every real video file (video-
    only, matching detect_highlight_candidates' own gate -- there's no
    motion/audio-energy concept for audio-only/still/other files).
    Allowed from 'premiere_project_created' too (found live: Generate
    Proxies' own original 'ingested'-only restriction was copied here
    unexamined, but unlike proxies, highlight detection is just as
    useful for a job that's already had its Premiere project created --
    matching /premiere-prep's own precedent for allowing that status).
    The loop's own completion step (post_ingest.py) restores whichever
    of those two statuses the job actually started from, keyed off
    premiere_project_path so a job with a project doesn't silently lose
    that fact. Returns (started, message, file_count)."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return False, f"No POST job with id {job_id}.", 0
    if not job.get("media_analyzed_at"):
        return False, f"Job #{job_id} needs Analyze Media run first.", 0
    files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    metadata_by_file_id = {m["file_id"]: m for m in await list_post_job_file_metadata(job_id, postgres_conn=postgres_conn)}
    video_file_ids = [
        f["id"] for f in files
        if f["status"] == "verified" and (metadata_by_file_id.get(f["id"]) or {}).get("media_type") == "video"
    ]
    if not video_file_ids:
        return False, f"No video files in job #{job_id} to analyze for highlights.", 0
    # A clip whose pick was set by hand (source "user", see lock_user_highlight) is
    # never re-detected: re-running must not overwrite an edit Josh made himself.
    # keep_composed: a re-run after a failure (credits ran out, API down) redoes only the
    # clips that never got a proper composition rating, instead of paying for all of them again.
    locked_file_ids = await _kept_file_ids(job_id, ("user", "composed") if keep_composed else ("user",), postgres_conn)
    video_file_ids = [fid for fid in video_file_ids if fid not in locked_file_ids]
    if not video_file_ids:
        return False, f"Every video file in job #{job_id} already has a hand-set or composition-rated pick; nothing to detect.", 0
    started = await update_post_job_status(
        job_id, "analyzing_color", from_statuses=("ingested", "premiere_project_created"), postgres_conn=postgres_conn,
    )
    if not started:
        return False, f"Job #{job_id} must be 'ingested' or have an existing Premiere project to detect highlights (currently {job['status']!r}).", 0
    await create_post_job_file_highlights_batch(video_file_ids, postgres_conn=postgres_conn)
    kept = f" ({len(locked_file_ids)} existing pick(s) left as they are)" if locked_file_ids else ""
    return True, f"Started highlight detection for {len(video_file_ids)} video file(s) in job #{job_id} \"{job['shoot_name']}\"{kept}.", len(video_file_ids)


async def _kept_file_ids(job_id: int, sources: tuple[str, ...], postgres_conn: Any = None) -> set[int]:
    """File ids whose stored highlight row has a rank-1 pick from one of `sources`
    ("user" = set by hand, "composed" = rated by Claude; "steady"/"fallback" mean
    no vision rating happened)."""
    kept: set[int] = set()
    for row in await list_post_job_file_highlights(job_id, postgres_conn=postgres_conn):
        if row.get("status") != "complete" or not row.get("candidates_json"):
            continue
        try:
            picks = json.loads(row["candidates_json"])
        except ValueError:
            continue
        if any(isinstance(c, dict) and c.get("source") in sources for c in picks):
            kept.add(row["file_id"])
    return kept


async def lock_user_highlight(job_id: int, file_id: int, start: float, duration: float, postgres_conn: Any = None) -> None:
    """Stores Josh's own choice of moment for a clip as its single pick (source
    "user", rank 1) and protects it from re-detection. Replaces whatever the
    detector had stored for that clip."""
    await create_post_job_file_highlights_batch([file_id], postgres_conn=postgres_conn)
    row = next(
        r for r in await list_post_job_file_highlights(job_id, postgres_conn=postgres_conn) if r["file_id"] == file_id
    )
    pick = [{"start": round(start, 3), "duration": round(duration, 3), "source": "user", "score": None, "rank": 1}]
    await mark_post_job_file_highlights_complete(row["id"], json.dumps(pick), 1, postgres_conn=postgres_conn)


async def run_highlight_detection(job_id: int, postgres_conn: Any = None) -> None:
    """Up to HIGHLIGHT_MAX_CONCURRENT_FILES files at a time (was one at a
    time -- necessary when each pass decoded every frame and saturated all
    cores, wasteful now that a keyframe pass uses ~1.3 cores). Resumes via
    list_queued_post_job_file_highlights: a row left 'processing' by a
    killed/restarted loop is retried from scratch (file-level resume,
    matching Phase 1's own decision). The shared DB connection serializes
    its own writes, so the workers can safely mark their rows on it."""
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        return
    pending = await list_queued_post_job_file_highlights(job_id, postgres_conn=postgres_conn)
    durations = {
        m["file_id"]: m.get("duration_seconds")
        for m in await list_post_job_file_metadata(job_id, postgres_conn=postgres_conn)
    }
    limiter = asyncio.Semaphore(HIGHLIGHT_MAX_CONCURRENT_FILES)
    still_limiter = asyncio.Semaphore(8)
    # Claude checks that each candidate moment shows something intended. If no API
    # key/client is available the picks fall back to steadiness+sharpness alone and
    # are labelled source="steady" so that is visible in the results, never silent.
    vision = None
    try:
        from anthropic import AsyncAnthropic
        from app.main import MODEL, _require_api_key
        vision = (AsyncAnthropic(api_key=_require_api_key()), MODEL)
    except Exception as exc:
        print(f"[post_media] highlight detection running WITHOUT the intent check: {type(exc).__name__}: {str(exc)[:120]}")
    context = f'Shoot: "{job["shoot_name"]}"' + (f' (client: {job["client_name"]})' if job.get("client_name") else "")

    async def detect(row: dict) -> None:
        async with limiter:
            await mark_post_job_file_highlights_processing(row["id"], postgres_conn=postgres_conn)
            try:
                candidates = await detect_highlight_candidates(
                    row["destination_path"], "video", durations.get(row["file_id"]),
                    vision=vision, context=context, limiter=still_limiter,
                )
                await mark_post_job_file_highlights_complete(
                    row["id"], json.dumps(candidates), len(candidates), postgres_conn=postgres_conn,
                )
            except Exception as exc:
                # Real failure (ffmpeg crash, disk issue) -- surfaced honestly,
                # same discipline as run_proxy_generation's own error path,
                # rather than silently leaving the row stuck 'processing'.
                await mark_post_job_file_highlights_failed(row["id"], str(exc), postgres_conn=postgres_conn)

    await asyncio.gather(*(detect(row) for row in pending))
    await update_post_job_highlights_generated(job_id, postgres_conn=postgres_conn)


# ------------------------------------------------------------ visual analysis (Phase 8b)

async def extract_representative_frames(source_path: str, duration_seconds: float | None, count: int = 4) -> list[str]:
    """Real ffmpeg `-vframes 1` calls at N evenly-spaced timestamps
    across the clip's own real duration (inset slightly from the very
    start/end, which are often black or incomplete frames) -- a stated,
    adjustable sampling density, not a claim about which frames are
    most representative. Writes real temp JPEG files and returns their
    paths; the caller is responsible for reading and deleting them.
    Never raises -- a failed extraction at one timestamp is skipped,
    matching probe_file's own fail-soft discipline, so this returns
    whatever frames DID extract successfully (possibly fewer than
    `count`, possibly empty)."""
    if duration_seconds and duration_seconds > 0:
        inset = min(duration_seconds * 0.05, 1.0)
        usable = max(duration_seconds - 2 * inset, 0.1)
        timestamps = (
            [inset + usable * i / (count - 1) for i in range(count)] if count > 1 else [duration_seconds / 2]
        )
    else:
        timestamps = [0.0]

    frame_paths: list[str] = []
    for ts in timestamps:
        fd, out_path = tempfile.mkstemp(prefix="post_frame_", suffix=".jpg")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_PATH, "-y", "-ss", str(ts), "-i", source_path, "-vframes", "1", "-q:v", "3", out_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            try:
                os.unlink(out_path)
            except OSError:
                pass
            continue
        await proc.communicate()
        if proc.returncode == 0 and Path(out_path).stat().st_size > 0:
            frame_paths.append(out_path)
        else:
            try:
                os.unlink(out_path)
            except OSError:
                pass
    return frame_paths
