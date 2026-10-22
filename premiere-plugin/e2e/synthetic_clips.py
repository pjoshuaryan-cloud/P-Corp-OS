"""Deterministic synthetic clips WITH real steadiness measurements (post_steady.measure on generated frames) and described moments, plus a synthetic beat grid,
shared by the planner tests that need footage without a drive. Same generator as candidate_engine_test.py, so its golden plans and these agree."""
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_steady as sd  # noqa: E402

H, W, F = sd.FRAME_H, sd.FRAME_W, int(sd.SAMPLE_FPS)
KINDS = ("action", "reaction", "camera_move", "reveal", "hero")
SCENES = ("kitchen", "street", "stage", "beach", "office", "crowd")


def _blur(img, sigma):
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    o = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 1, img)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 0, o)


def _scene(seed):
    img = _blur(np.random.default_rng(seed).random((H + 40, W + 200)).astype(np.float32), 1.4)
    return (img - img.min()) / (img.max() - img.min()) * 255


def _frames(kind, seed, seconds):
    rng = np.random.default_rng(1000 + seed)
    base = _scene(seed)
    n = int(seconds * F)
    out = []
    for i in range(n):
        dx = i if kind == "moving" else (int(6 * abs(np.sin(i / 3.0))) if kind == "burst" and n // 3 <= i <= n // 2 else 0)
        out.append(np.clip(base[20:20 + H, 20 + dx:20 + dx + W] + rng.normal(0, 0.8, (H, W)), 0, 255))
    return out


def make_clips(n_groups: int = 3):
    """24 clips by default (8 x 3): static / moving / bursts of motion, 6-9 s long, 50 fps, two in three described with three moments each."""
    kinds = ["static", "moving", "burst", "static", "moving", "burst", "moving", "static"] * n_groups
    clips = []
    for i, kind in enumerate(kinds):
        seconds = 6 + (i % 4)
        m = sd.measure(np.stack(_frames(kind, i + 1, seconds)).astype(np.uint8))
        clip = {"file_id": i + 1, "name": f"C{i + 1:04d}.MP4", "path": f"/x/C{i + 1:04d}.MP4", "duration": m["seconds"], "created": "", "picks": [], "steady": m,
                "thumbs": sd.decode_thumbs(m), "scene": SCENES[i % 6], "people": i % 2 == 0, "fps": 50.0}
        if i % 3 != 2:
            r = random.Random(i)
            clip["events"] = sorted([{"t": round(r.uniform(0.8, m["seconds"] - 0.8), 2), "kind": KINDS[(i + j) % 5], "punch": r.randint(4, 9), "what": f"moment {j} of clip {i + 1}"}
                                     for j in range(3)], key=lambda e: -e["punch"])
        clips.append(clip)
    return clips


def beat_hits(seconds, bpm=128, seed=3):
    r = random.Random(seed)
    beat, out, t, i = 60.0 / bpm, [], 0.0, 0
    while t < seconds:
        out.append([round(t, 3), (96 if i % 4 == 0 else 80) + r.random() * 2])
        out.append([round(t + beat / 2, 3), 56 + r.random() * 6])
        t += beat
        i += 1
    return out
