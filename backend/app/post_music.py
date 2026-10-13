"""
POST (2026-10-06) -- music analysis for beat-synced edits.

Given a music file, finds the tempo and the beat times so cuts can land on beats, and
renders the stretch of the track the edit will use (trimmed to start on a beat, with a
short fade-out) as a WAV the Premiere plugin can simply drop on the timeline.

Local and free: ffmpeg decodes to mono PCM, numpy does the rest (onset strength ->
tempo by autocorrelation with a mild preference for ~120 BPM -> beat tracking by
dynamic programming, after Ellis 2007). No new dependencies. Assumes 4/4 for the
bar grid; `confidence` says how regular the detected beats are, and a low value means
the tempo is drifting or ambiguous and the cuts will feel loose.
"""

import asyncio
import math
from pathlib import Path
from typing import Any

import numpy as np

from app.post_media import FFMPEG_PATH

SAMPLE_RATE = 22050
N_FFT = 1024
HOP = 256
HOP_SECONDS = HOP / SAMPLE_RATE
MIN_BPM, MAX_BPM = 60.0, 180.0
TEMPO_PRIOR_BPM = 120.0  # mild preference, so a 60 BPM half-time reading loses to its 120 BPM double
TEMPO_PRIOR_OCTAVE_SIGMA = 1.0
BEAT_TIGHTNESS = 100.0  # how strictly beats must follow the tempo (higher = more regular)
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aif", ".aiff", ".flac", ".aac", ".ogg")


class MusicAnalysisError(RuntimeError):
    pass


async def _decode_mono(path: str) -> np.ndarray:
    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-hide_banner", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise MusicAnalysisError("ffmpeg not found -- install with `brew install ffmpeg`.") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not stdout:
        raise MusicAnalysisError(f"Couldn't read audio from {Path(path).name}: {stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(stdout, dtype=np.float32)


N_BANDS = 40
LOW_BAND_HZ = 220.0  # the kick lives below this; the beat grid leans on it so off-beat hi-hats can't pull it away
ONSET_LATENCY_SECONDS = -0.035  # the flux peak lands ~34 ms BEFORE the hit (window centring); measured against synthetic click tracks with known beat times


def _band_edges() -> np.ndarray:
    """Triangular filters on a mel-like scale (as the ear hears: many narrow bands for bass, fewer for treble)."""
    mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    inv = lambda m: 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    centres = inv(np.linspace(mel(30.0), mel(8000.0), N_BANDS + 2))
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SAMPLE_RATE)
    bank = np.zeros((N_BANDS, len(freqs)), dtype=np.float32)
    for i in range(N_BANDS):
        lo, mid, hi = centres[i], centres[i + 1], centres[i + 2]
        up = (freqs - lo) / max(mid - lo, 1e-6)
        down = (hi - freqs) / max(hi - mid, 1e-6)
        bank[i] = np.clip(np.minimum(up, down), 0.0, None)
    return bank, centres[1:-1]


def _onset_strength(samples: np.ndarray) -> np.ndarray:
    """Onset envelope, one value per HOP: half bass-only flux (kick), half all-band flux
    (snares, claps, chords), each de-trended and scaled so neither swamps the other."""
    if len(samples) < N_FFT * 4:
        raise MusicAnalysisError("Audio is too short to analyse.")
    n_frames = 1 + (len(samples) - N_FFT) // HOP
    window = np.hanning(N_FFT).astype(np.float32)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    power = np.abs(np.fft.rfft(samples[idx] * window, axis=1)) ** 2
    bank, centres = _band_edges()
    bands = np.log1p(power @ bank.T * 10.0)
    flux = np.maximum(0.0, np.diff(bands, axis=0))
    flux = np.concatenate([np.zeros((1, flux.shape[1])), flux])
    kernel_len = max(1, int(0.5 / HOP_SECONDS))
    kernel = np.ones(kernel_len) / kernel_len

    def detrend(env: np.ndarray) -> np.ndarray:
        env = np.maximum(0.0, env - np.convolve(env, kernel, mode="same"))
        return env / (env.std() or 1.0)

    low = detrend(flux[:, centres < LOW_BAND_HZ].mean(axis=1))
    everything = detrend(flux.mean(axis=1))
    onset = 0.5 * low + 0.5 * everything
    shift = int(round(ONSET_LATENCY_SECONDS / HOP_SECONDS))
    return np.roll(onset, -shift) if shift else onset


def _estimate_tempo(onset: np.ndarray) -> tuple[float, float]:
    """(bpm, peak_strength) from the autocorrelation of the onset envelope."""
    n = len(onset)
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(onset - onset.mean(), size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    acf /= acf[0] or 1.0
    lags = np.arange(1, n)
    bpm = 60.0 / (lags * HOP_SECONDS)
    valid = (bpm >= MIN_BPM) & (bpm <= MAX_BPM)
    prior = np.exp(-0.5 * (np.log2(bpm / TEMPO_PRIOR_BPM) / TEMPO_PRIOR_OCTAVE_SIGMA) ** 2)
    score = np.where(valid, acf[1:] * prior, -np.inf)
    best = int(np.argmax(score))
    lag = float(lags[best])
    if 1 <= best < len(score) - 1:  # parabolic refinement of the peak
        a, b, c = acf[best], acf[best + 1], acf[best + 2]
        denom = a - 2 * b + c
        if denom:
            lag += 0.5 * (a - c) / denom
    return 60.0 / (lag * HOP_SECONDS), float(acf[best + 1])


def _track_beats(onset: np.ndarray, bpm: float) -> np.ndarray:
    """Beat frame indices by dynamic programming: each beat is chosen to sit on a strong
    onset while staying about one beat-period after the previous one."""
    period = 60.0 / bpm / HOP_SECONDS
    smooth = np.convolve(onset, np.exp(-0.5 * (np.arange(-int(period / 4), int(period / 4) + 1) / (period / 32)) ** 2), mode="same")
    n = len(smooth)
    cum = np.zeros(n)
    back = -np.ones(n, dtype=int)
    first = True
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offsets = np.arange(lo, hi + 1)
    penalty = -BEAT_TIGHTNESS * np.log(offsets / period) ** 2
    for t in range(n):
        prev = t - offsets
        ok = prev >= 0
        if not ok.any():
            cum[t] = smooth[t]
            continue
        cand = cum[prev[ok]] + penalty[ok]
        j = int(np.argmax(cand))
        cum[t] = smooth[t] + cand[j]
        back[t] = prev[ok][j]
    # start the backtrace at the best-scoring local maximum in the last two beat periods
    tail = np.arange(max(0, n - int(2 * period)), n)
    t = int(tail[np.argmax(cum[tail])])
    beats = [t]
    while back[t] >= 0:
        t = int(back[t])
        beats.append(t)
    return np.array(beats[::-1])


HIT_MIN_GAP_SECONDS = 0.10
HIT_PERCENTILE_FLOOR = 50.0  # only peaks stronger than this share of all peaks count as hits (at 50, 80% of Josh's draft-01 cuts sit within 40 ms of one, 92% within 80 ms)


def _pick_hits(onset: np.ndarray) -> list[list[float]]:
    """Audible hits (kicks, snares, accents) as [time_seconds, strength_percentile]: local maxima of the
    onset envelope, refined to sub-frame, at least HIT_MIN_GAP_SECONDS apart (the stronger one wins),
    kept if stronger than HIT_PERCENTILE_FLOOR% of all peaks. Percentile 100 = the song's strongest hit.
    Josh's draft-01 cuts land within 40 ms of such a hit 86% of the time."""
    win = 3
    padded = np.pad(onset, win, mode="constant")
    is_peak = np.ones(len(onset), dtype=bool)
    for k in range(1, win + 1):
        is_peak &= onset >= padded[win - k: win - k + len(onset)]
        is_peak &= onset > padded[win + k: win + k + len(onset)]
    idx = np.where(is_peak & (onset > 0))[0]
    if len(idx) == 0:
        return []
    values = onset[idx]
    floor = np.percentile(values, HIT_PERCENTILE_FLOOR)
    keep = idx[values >= floor]
    # enforce the minimum gap, strongest first
    order = keep[np.argsort(-onset[keep])]
    taken: list[int] = []
    gap = int(HIT_MIN_GAP_SECONDS / HOP_SECONDS)
    occupied = np.zeros(len(onset), dtype=bool)
    for i in order:
        if not occupied[max(0, i - gap): i + gap + 1].any():
            taken.append(int(i))
            occupied[i] = True
    taken.sort()
    rank = np.sort(values)
    hits = []
    for i in taken:
        y0, y1, y2 = onset[max(i - 1, 0)], onset[i], onset[min(i + 1, len(onset) - 1)]
        denom = y0 - 2 * y1 + y2
        frac = float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5)) if denom < 0 else 0.0
        pct = float(np.searchsorted(rank, onset[i]) / len(rank) * 100.0)
        hits.append([round((i + frac) * HOP_SECONDS, 4), round(pct, 1)])
    return hits


async def analyze_music(path: str) -> dict[str, Any]:
    """{"duration", "tempo_bpm", "beats":[sec...], "downbeat_phase", "downbeats":[sec...],
    "hits":[[sec, strength_percentile]...], "beat_energy":[...], "confidence", "alignment"}.
    Raises MusicAnalysisError on an unreadable file. The number crunching runs on a worker thread so
    the server (and Frank's chat) stays responsive while a song is analysed."""
    samples = await _decode_mono(path)
    return await asyncio.to_thread(_analyze_samples, samples)


def _analyze_samples(samples: np.ndarray) -> dict[str, Any]:
    duration = len(samples) / SAMPLE_RATE
    onset = _onset_strength(samples)
    bpm, acf_peak = _estimate_tempo(onset)
    beat_frames = _track_beats(onset, bpm)
    if len(beat_frames) < 8:
        raise MusicAnalysisError("Couldn't find a steady beat in this track.")
    # a beat tracker always fills the whole track with beats; drop weak ones at the edges (no real hit there)
    strength = onset[beat_frames]
    solid = np.where(strength >= 0.25 * np.median(strength))[0]
    if len(solid) >= 8:
        beat_frames = beat_frames[solid[0]: solid[-1] + 1]
    # sub-frame position: parabola through the onset envelope around each beat frame
    refined = beat_frames.astype(float)
    for k, f in enumerate(beat_frames):
        if 0 < f < len(onset) - 1:
            y0, y1, y2 = onset[f - 1], onset[f], onset[f + 1]
            denom = y0 - 2 * y1 + y2
            if denom < 0:
                refined[k] = f + float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
    beats = refined * HOP_SECONDS
    intervals = np.diff(beats)
    median = float(np.median(intervals))
    regularity = float(np.mean(np.abs(intervals - median) < 0.08 * median))  # share of beats within 8% of the median spacing
    # alignment: onset strength on the beats vs halfway between them (>> 1 means the beats sit on real hits)
    half = np.clip(beat_frames[:-1] + np.round(np.diff(beat_frames) / 2).astype(int), 0, len(onset) - 1)
    alignment = float(onset[beat_frames].mean() / max(onset[half].mean(), 1e-6))
    # bar phase: the beat position (0-3) whose hits are strongest is taken as the downbeat
    phase = int(np.argmax([onset[beat_frames[p::4]].sum() for p in range(4)]))
    # loudness per beat, for choosing which stretch of the song to use
    beat_samples = (beats * SAMPLE_RATE).astype(int)
    energy = []
    for i, start in enumerate(beat_samples):
        end = beat_samples[i + 1] if i + 1 < len(beat_samples) else min(len(samples), start + int(median * SAMPLE_RATE))
        seg = samples[start:end]
        energy.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    hits = _pick_hits(onset)
    return {
        "hits": hits,
        "duration": round(duration, 3),
        "tempo_bpm": round(60.0 / (float(np.polyfit(np.arange(len(beats)), beats, 1)[0]) if regularity >= 0.9 else median), 2),
        "beats": [round(float(b), 4) for b in beats],
        "downbeat_phase": phase,
        "downbeats": [round(float(b), 4) for b in beats[phase::4]],
        "beat_energy": [round(e, 5) for e in energy],
        "confidence": round(regularity, 3),
        "alignment": round(alignment, 2),
        "autocorr_peak": round(acf_peak, 3),
    }


def find_music_file(music_folder: str) -> str | None:
    """The newest audio file in a job's music folder (ignoring the reel cuts this module
    writes itself), or None."""
    folder = Path(music_folder)
    if not folder.is_dir():
        return None
    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".") and "_reelcut" not in p.stem
    ]
    return str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None


def choose_music_window(analysis: dict[str, Any], beats_needed: int, bar_beats: int = 4) -> dict[str, Any]:
    """Which beats of the track to use for an edit `beats_needed` beats long: starts on a
    downbeat, picks the loudest stretch, but never the track's quiet intro/outro (the first
    and last 8% of beats are skipped when the track is long enough to afford it)."""
    beats = analysis["beats"]
    energy = analysis["beat_energy"]
    n = len(beats)
    if n < beats_needed + 1:
        raise MusicAnalysisError(
            f"The track has only {n} detectable beats ({analysis['duration']:.0f}s) but this edit needs {beats_needed}. "
            "Use a longer track or a shorter target length."
        )
    phase = analysis["downbeat_phase"]
    margin = int(n * 0.08) if n > beats_needed * 1.5 else 0
    starts = [i for i in range(phase, n - beats_needed, bar_beats) if i >= margin and i + beats_needed <= n - margin]
    if not starts:
        starts = [i for i in range(phase, n - beats_needed, bar_beats)] or [0]
    cum = np.concatenate([[0.0], np.cumsum(energy)])
    best = max(starts, key=lambda i: cum[i + beats_needed] - cum[i])
    return {"start_beat": best, "in_seconds": beats[best], "beat_times": [b - beats[best] for b in beats[best:best + beats_needed + 1]]}


async def render_music_cut(src: str, out_path: str, in_seconds: float, duration: float, fade_out: float = 1.5) -> None:
    """The chosen stretch as 48 kHz 16-bit stereo WAV: begins exactly on the beat (20 ms
    fade-in against a click), fades out over the last `fade_out` seconds."""
    fade_start = max(0.0, duration - fade_out)
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-ss", f"{in_seconds:.4f}", "-t", f"{duration:.4f}", "-i", src,
        "-vn", "-af", f"afade=t=in:st=0:d=0.02,afade=t=out:st={fade_start:.3f}:d={fade_out:.3f}",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", out_path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MusicAnalysisError(f"Couldn't render the music cut: {stderr.decode(errors='replace')[:200]}")
