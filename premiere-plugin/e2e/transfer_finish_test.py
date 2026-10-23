"""Tests for learning/transfer_finish.py (his finishing -- sounds, flashes, zoom hits, shot effects, punch-ins, logo, end card -- copied onto a plan matched to his
cut slot for slot) and the picture-matching pieces of learning/transfer_cut.py (2026-10-23). Synthetic files in a temp folder; with the Lexar drive mounted it
also reads his real HAUS project READ-ONLY and renders into the temp folder (never into the workspace or next to his project). Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python transfer_finish_test.py"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from learning import transfer_cut as tc, transfer_finish as tf  # noqa: E402

fails = 0
FFMPEG, FFPROBE = "/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


TMP = Path(tempfile.mkdtemp(prefix="tf_"))

# ---- small pieces ---------------------------------------------------------------------------------------------------------------------------------------------
keys = tf.parse_keyframes("699242544000,110.,0,0,0,0.1666,-17.1,0.1666;847566720000,100.,0,0,-17.1,0.1666,0,0.1666;")
check("Premiere keyframes read as (seconds, value)", [round(t, 4) for t, _ in keys] == [2.7527, 3.3367] and [v for _, v in keys] == [110.0, 100.0], keys)
check("...a flag or a point value is skipped, not misread", tf.parse_keyframes("0,true,0;5,0.5:0.5,0;") == [])
check("a full-to-nothing opacity ramp is a fade-out (his logo: 1.125 -> 1.502 s)", tf._fade_out([(1.125, 100.0), (1.502, 0.0)], 1.502) == (1.125, 1.502))
check("...a fade-in or a dip is not", tf._fade_out([(0.0, 0.0), (0.4, 100.0)], 1.5) is None and tf._fade_out([(0.2, 100.0)], 1.5) is None)

src = TMP / "logo.png"   # 200 x 100, opaque white
Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(src)
out = tf.draw_image(str(src), (400, 800), 50.0, (0.5, 0.25), 0.5, TMP / "drawn.png")
a = np.asarray(Image.open(out))
ys, xs = np.nonzero(a[:, :, 3])
check("an image is drawn full-frame at his Scale of its own pixels (50% of 200x100 -> 100x50)", Image.open(out).size == (400, 800) and xs.max() - xs.min() + 1 == 100
      and ys.max() - ys.min() + 1 == 50, (xs.min(), xs.max(), ys.min(), ys.max()))
check("...centred where his Position puts it (0.5, 0.25 of a 400x800 frame -> centre 200, 200)", abs((xs.min() + xs.max()) / 2 - 199.5) <= 1 and abs((ys.min() + ys.max()) / 2 - 199.5) <= 1)
check("...and at the alpha asked for (half: a fade step)", 126 <= int(a[200, 200, 3]) <= 129, a[200, 200, 3])

# ---- picture matching pieces (transfer_cut) ------------------------------------------------------------------------------------------------------------------
plain, clip = TMP / "plain.mp4", TMP / "clip.mp4"   # 4 s of a 1920x1080 test pattern, then flagged as rotated 90 (as his vertical clips are: a display matrix)
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plain)], check=True)
subprocess.run([FFMPEG, "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", str(plain), "-c", "copy", str(clip)], check=True)
frame = TMP / "f.jpg"
ok = tc.grab_frame(str(clip), 2.0, frame)
w, h = Image.open(frame).size if ok else (0, 0)
check("a frame is grabbed the right way up (rotation applied: tall) with its long side at LOOK_LONG_SIDE", ok and h == tc.LOOK_LONG_SIDE and w < h, (w, h))
sharp = TMP / "sharp.png"
Image.fromarray(((np.indices((256, 256)).sum(axis=0) // 8) % 2 * 255).astype(np.uint8)).save(sharp)
soft = TMP / "soft.png"
Image.open(sharp).filter(ImageFilter.GaussianBlur(6)).save(soft)
dark = TMP / "dark.png"
Image.new("L", (256, 256), 10).save(dark)
qs, qb, qd = tc.frame_quality(sharp), tc.frame_quality(soft), tc.frame_quality(dark)
check("sharpness ranks a crisp frame far above a blurred copy of it", qs[1] > 5 * qb[1], (qs, qb))
check("...and luma flags a dark frame (below DARK_FRAME_LUMA)", qd[0] < tc.DARK_FRAME_LUMA <= qs[0], (qd, qs))
check("Claude's ranking is read even after a sentence of reasoning, completed and de-duplicated",
      tc.parse_ranking('The closest is 3.\n{"ranking": [3, 1, 3, 9], "why": "same boom operator"}', 4) == ([3, 1, 2, 4], "same boom operator"))
check("...and an answer cut off before its JSON is unreadable (that slot falls back to the description match)",
      tc.parse_ranking("The editor's shot shows a man in a cap holding", 4) == (None, None))
s = {"name": "C2990.MP4", "source_in": 1.0, "frames": 14, "source_out": 1.584}
cands = [{"name": "A.MP4", "start": 1.0, "length": 0.584}, {"name": "B.MP4", "start": 2.0, "length": 0.584}]
look = {"slots": {"0": {"key": tc._look_key(s, cands), "candidates": cands, "ranking": [1, 2], "why": "same light"}}}
by = {"A.MP4": {"file_id": 1}, "B.MP4": {"file_id": 2}}
check("the best-ranked candidate is used", tc._picture_pick(look, 0, s, by, [], [], {})[2] == 1)
check("...but not a clip used in the last 3 slots: the next-ranked one is used", tc._picture_pick(look, 0, s, by, ["A.MP4", "X.MP4"], ["P.MP4", "Q.MP4"], {})[2] == 2)
check("...unless he used his shot's clip at the same distance (he repeated C2990 two slots back)",
      tc._picture_pick(look, 0, s, by, ["A.MP4", "X.MP4"], ["C2990.MP4", "Q.MP4"], {})[2] == 1)
check("...a clip last used 4 slots back is fine again", tc._picture_pick(look, 0, s, by, ["A.MP4", "X.MP4", "Y.MP4", "Z.MP4"][-3:], [], {})[2] == 1)
check("...never a stretch of a clip already used", tc._picture_pick(look, 0, s, by, [], [], {1: [(0.9, 1.3)]})[2] == 2)
check("...and a ranking made for a different version of his shot is ignored", tc._picture_pick(look, 0, {**s, "frames": 15}, by, [], [], {}) is None)

# ---- his real HAUS project, read-only (skipped when the drive isn't mounted) -----------------------------------------------------------------------------------
if Path(tc.HAUS).exists():
    fps = 24000 / 1001
    cut = [0, 36, 50, 57, 71, 92, 107, 114, 128, 149, 163, 170, 184, 205, 220, 226, 241, 262, 276, 283, 297, 318, 332, 341, 353, 367, 375, 389, 410, 431, 445, 452,
           466, 487, 496, 535]
    plan = {"fps": 23.976, "duration_frames": 535, "shots": [{"index": k + 1, "start_frame": a, "duration_frames": b - a} for k, (a, b) in enumerate(zip(cut, cut[1:]))]}
    before = Path(tc.HAUS).stat().st_mtime
    r = tf.finish_for_plan(tc.HAUS, tc.CUT, plan, TMP / "ws", (2160, 3840), "(Instrumental) Lamb Truck Keys - AZ Chike [Prod. Pharrell Williams].mp3")
    c, acc = r["counts"], r["accents"]
    check("his finishing is all found: 2 flashes, 3 zoom hits, zoom blur on 3 shots, B&W on 4, 12 punch-ins, 11 sounds",
          (c["flashes"], c["zoom_hits"], c["shot_zoom_blur"], c["black_and_white_shots"], c["punch_ins"], c["sounds"]) == (2, 3, 3, 4, 12, 11), c)
    check("a flash: his peak (+6.2) held for the 2 frames around it (his 4.671 s flash peaks at frame 114 -> frames 113-114)",
          acc["flashes"][0]["start_frame"] == 113 and acc["flashes"][0]["frames"] == 2 and acc["flashes"][0]["params"] == {"Exposure": 6.2}, acc["flashes"][0])
    check("zoom hits keep his own values (Zoom 46, 46, 34)", [z["params"]["Zoom"] for z in acc["zoom_hits"]] == [46.0, 46.0, 34.0])
    check("punch-ins keep direction and size (shot 4 pulls out 110 -> 100, shot 5 pushes in)", [(z["shot_index"], z["direction"], z["percent"]) for z in r["zooms"]["items"]][:2]
          == [(4, "out", 10.0), (5, "in", 10.0)], r["zooms"]["items"][:2])
    tracks = {s["name"][:12]: s["track"] for s in acc["sfx"]}
    check("sounds keep his track order above the music (his A2 -> A3, A3 -> A4)", tracks["Crowd Chatte"] == 3 and tracks["Wind Up Gear"] == 4 and tracks["SFX - Riser "] == 4, tracks)
    shutter = next(s for s in acc["sfx"] if s["name"].startswith("Noisy Buttons"))
    dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", shutter["file"]], capture_output=True, text=True).stdout)
    check("...each cut from his in point to the exact length (the shutter: 8 frames)", abs(dur - shutter["frames"] / fps) < 0.003, dur)
    cards = r["graphics"]["cards"]
    alphas = [Path(x["file"]).stem.rsplit("_", 1)[-1] for x in cards]
    check("the logo: full for 27 frames, then his fade in 3 fainter steps; the end card at 523 for 12 frames", [(x["start_frame"], x["frames"]) for x in cards]
          == [(0, 27), (27, 3), (30, 3), (33, 3), (523, 12)] and alphas == ["100", "83", "50", "17", "100"], [(x["start_frame"], x["frames"], a) for x, a in zip(cards, alphas)])
    end = np.asarray(Image.open(cards[-1]["file"]))
    ys, xs = np.nonzero(end[:, :, 3] > 128)
    check("the end card is drawn at his 9% of its own pixels (visible 496 px wide, as measured in his preview render) and placed as his: its artwork sits 16.5 px "
          "left of the frame's centre in his preview too (the PNG's own margins)", abs((xs.max() - xs.min() + 1) - 496) <= 2
          and abs((xs.min() + xs.max()) / 2 - (1080 - 16.5)) <= 2, (xs.min(), xs.max()))
    notes = " ".join(r["notes"])
    check("the letterbox is left out (his request), the titles are named for him to paste, the extra layer is named", "4x3 Clean.png" in notes and "titles (9 text item(s))" in notes
          and "C2969.MP4 on V2" in notes, notes)
    check("his project file was only read", Path(tc.HAUS).stat().st_mtime == before)
else:
    print("SKIP  his HAUS project (Lexar - A not mounted)")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
