"""
POST (2026-10-13) -- lines up several cameras that filmed the same conversation, from their sound.

A multicam interview is cut by switching between cameras, which only works if every camera's clip is lined up on one timeline.
Cameras that weren't jam-synced to timecode don't start at the same moment, but every camera's microphone heard the same
speech, so the offset between two clips is where their audio lines up best (generalised cross-correlation with phase
transform, "GCC-PHAT": it keeps only WHEN things happen, not how loud or how filtered the mic was, so a camera's built-in
mic and a lavalier still line up).

Convention used everywhere: `lag_seconds` of camera K relative to the reference camera = how much LATER the same moment
appears in K. Reference time t is K time t + lag, so a shot taken at reference time t starts at t + lag in K's file.

Limits, stated plainly: it needs speech (or other sound) that both cameras actually recorded; it looks at the first
`MAX_SECONDS` of each clip; a result with low `confidence` is NOT used (the caller refuses rather than guess). It measures one
offset per camera: a camera whose clock drifts over a long take is reported by `check_drift`, not corrected.
"""

from __future__ import annotations

import subprocess
from typing import Any

import numpy as np

FFMPEG = "/opt/homebrew/bin/ffmpeg"
SYNC_RATE = 4000  # Hz: speech lives below 2 kHz, and a low rate keeps the transform small
MAX_SECONDS = 900  # how much of each clip is searched
MAX_LAG_SECONDS = 600.0
BAND_HZ = (200.0, 1800.0)
MIN_CONFIDENCE = 8.0  # peak height in standard deviations of the background; calibrated on real speech (see validation notes): true matches sit far above, unrelated clips far below
MIN_PEAK_RATIO = 1.4  # the best alignment must beat the next-best (somewhere else) by at least this factor


class SyncError(RuntimeError):
    pass


def decode_for_sync(path: str, start: float = 0.0, seconds: float = MAX_SECONDS) -> np.ndarray:
    """Mono audio at SYNC_RATE from `start` for `seconds`. Empty array if the file has no audio."""
    cmd = [FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", str(SYNC_RATE), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=900)
    if out.returncode != 0 or not out.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(out.stdout, dtype=np.float32)


def estimate_lag(ref: np.ndarray, other: np.ndarray, max_lag_seconds: float = MAX_LAG_SECONDS, sr: int = SYNC_RATE) -> dict[str, Any]:
    """Offset of `other` relative to `ref` (positive = the same moment appears LATER in `other`), with a confidence figure."""
    if len(ref) < sr * 2 or len(other) < sr * 2:
        raise SyncError("One of the clips has less than two seconds of audio, so it can't be lined up.")
    if float(np.std(ref)) < 1e-6 or float(np.std(other)) < 1e-6:
        raise SyncError("One of the clips is silent, so it can't be lined up by sound.")
    n = 1 << int(np.ceil(np.log2(len(ref) + len(other))))
    A = np.fft.rfft(ref - ref.mean(), n)
    B = np.fft.rfft(other - other.mean(), n)
    R = A * np.conj(B)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    R[(freqs < BAND_HZ[0]) | (freqs > BAND_HZ[1])] = 0
    R /= np.abs(R) + 1e-12 * np.abs(R).max() + 1e-30  # phase transform: keep timing, drop level and tone
    r = np.fft.irfft(R, n)
    m = min(int(max_lag_seconds * sr), n // 2 - 1, len(ref) + len(other))  # never wider than half the transform: beyond that the correlation wraps and the same peak shows up twice
    # tau = position in r (negative values wrap to the end); lag = -tau
    taus = np.concatenate([np.arange(-m, 0), np.arange(0, m + 1)])
    vals = r[taus % n]
    k = int(np.argmax(vals))
    peak = float(vals[k])
    guard = int(0.05 * sr)
    mask = np.ones(len(vals), dtype=bool)
    mask[max(0, k - guard): k + guard + 1] = False
    background = vals[mask]
    sd = float(np.std(background)) + 1e-12
    second = float(np.max(background))
    # parabolic refinement to a fraction of a sample
    tau = int(taus[k])
    if 0 < k < len(vals) - 1:
        y0, y1, y2 = vals[k - 1], vals[k], vals[k + 1]
        denom = y0 - 2 * y1 + y2
        frac = float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5)) if denom != 0 else 0.0
    else:
        frac = 0.0
    lag = -(tau + frac) / sr
    return {"lag_seconds": round(float(lag), 4), "confidence": round((peak - float(np.mean(background))) / sd, 1), "peak_ratio": round(peak / max(second, 1e-12), 2)}


def sync_cameras(paths: list[str], max_seconds: float = MAX_SECONDS) -> list[dict[str, Any]]:
    """Lag of every camera relative to the first. [{"path", "lag_seconds", "confidence", "peak_ratio"}]; the first has lag 0.
    Raises SyncError (naming the camera) when a camera can't be lined up with confidence."""
    if len(paths) < 2:
        raise SyncError("Syncing needs at least two cameras.")
    sigs = [decode_for_sync(p, 0.0, max_seconds) for p in paths]
    out = [{"path": paths[0], "lag_seconds": 0.0, "confidence": None, "peak_ratio": None}]
    for p, sig in zip(paths[1:], sigs[1:]):
        if len(sigs[0]) == 0 or len(sig) == 0:
            raise SyncError(f"{p.rsplit('/', 1)[-1]} (or the first camera) has no audio, so the cameras can't be lined up by sound. Record a scratch audio track on every camera, or give the clips' timecode.")
        est = estimate_lag(sigs[0], sig)
        if est["confidence"] < MIN_CONFIDENCE or est["peak_ratio"] < MIN_PEAK_RATIO:
            raise SyncError(f"Couldn't line up {p.rsplit('/', 1)[-1]} with {paths[0].rsplit('/', 1)[-1]} by sound (match strength {est['confidence']}, need {MIN_CONFIDENCE}). "
                            f"They need to have heard the same speech in the first {int(max_seconds // 60)} minutes of each clip.")
        out.append({"path": p, **est})
    return out


def check_drift(ref_path: str, other_path: str, lag_seconds: float, at_seconds: list[float], window: float = 45.0) -> list[dict[str, Any]]:
    """Re-measures the offset in short windows at the given reference times, searching only +-2 s around `lag_seconds`.
    A camera whose clock runs a little fast or slow shows up as a lag that changes along the take."""
    out = []
    for t in at_seconds:
        a = decode_for_sync(ref_path, t, window)
        s0 = max(0.0, t + lag_seconds - 1.5)  # the other clip's window starts 1.5 s before where the match should be
        b = decode_for_sync(other_path, s0, window + 3.0)
        if len(a) < SYNC_RATE * 5 or len(b) < SYNC_RATE * 5:
            continue
        est = estimate_lag(a, b, max_lag_seconds=2.0)
        # a moment at a-time u is at b-time u + local; in file times that is ref t+u -> other s0+u+local, so lag = local + (s0 - t)
        out.append({"at_reference_seconds": t, "lag_seconds": round(est["lag_seconds"] + (s0 - t), 4), "confidence": est["confidence"]})
    return out
