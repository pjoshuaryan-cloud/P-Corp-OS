"""
POST (2026-10-13) -- what is IN the shots of a reference video (the part pixels-as-numbers can't say).

post_reference_video.py measures WHEN things change; this asks Claude to label sampled frames from contact sheets:
how close the shot is, who/what it shows, whether there is on-screen text. The answers are LABELS from a model looking
at one still frame each -- a fair summary of an edit's mix, not a measurement and not a statement about camera movement.

Costs real API credit (a few cents per video); callers check the balance first (post_moments.check_credit).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
from collections import Counter
from typing import Any

from PIL import Image, ImageDraw

FFMPEG = "/opt/homebrew/bin/ffmpeg"
MODEL = "claude-sonnet-5"
TILES_PER_SHEET = 12
MAX_SHOTS_LABELLED = 60

SYSTEM_PROMPT = """You label single frames taken from a finished video edit so a video editor's style can be summarised.
Each image is a contact sheet: every tile has a white number in a black box at its top-left corner. The tiles are in time
order. Return ONLY a JSON array with one object per tile, in number order, with these fields:
  "n": the tile number
  "size": "wide" | "medium" | "close" | "detail" (an extreme close-up of an object or texture) | "graphic" (a full-screen title card, logo or graphic with no live footage)
  "subject": "person_speaking_to_camera" | "person" | "people_group" | "crowd" | "product" | "food_drink" | "venue_interior" | "venue_exterior" | "vehicle_or_equipment" | "screen_or_ui" | "text_or_graphic" | "other"
  "people": how many people are clearly visible: 0, 1, 2, or 3 (3 = three or more)
  "text": "none" | "title" | "lower_third" | "caption_subtitle" | "logo" | "other_text"
  "text_words": the words on screen if text is not "none" (at most 8 words), else ""
  "note": at most 10 words saying what the frame shows
Rules: describe only what is visible in the tile. Use "other" or "none" instead of guessing. Do not comment on image quality. Output the JSON array and nothing else."""


def extract_frame(path: str, t: float, long_side: int, vertical: bool) -> Image.Image | None:
    scale = f"scale=-2:{long_side}" if vertical else f"scale={long_side}:-2"
    out = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1", "-vf", scale, "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                         capture_output=True, timeout=120)
    if out.returncode != 0 or not out.stdout:
        return None
    return Image.open(io.BytesIO(out.stdout)).convert("RGB")


def make_sheet(tiles: list[tuple[int, Image.Image]], vertical: bool) -> bytes:
    """A grid of numbered tiles: 4 x 3 for landscape video, 6 x 2 for vertical."""
    cols = 6 if vertical else 4
    w, h = tiles[0][1].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for k, (number, im) in enumerate(tiles):
        x, y = (k % cols) * w, (k // cols) * h
        sheet.paste(im.resize((w, h)), (x, y))
        draw.rectangle([x, y, x + 34, y + 22], fill=(0, 0, 0))
        draw.text((x + 6, y + 4), str(number), fill=(255, 255, 255))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def pick_shots(shots: list[dict], limit: int = MAX_SHOTS_LABELLED) -> list[int]:
    """Indices of the shots to label: all of them when few, otherwise the first two, the last two and an even spread between."""
    n = len(shots)
    if n <= limit:
        return list(range(n))
    inner = [round(i * (n - 1) / (limit - 1)) for i in range(limit)]
    return sorted(set(inner) | {0, 1, n - 2, n - 1})


def parse_labels(text: str) -> list[dict]:
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b <= a:
        return []
    try:
        data = json.loads(text[a:b + 1])
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("n"), int)]


async def describe_shots(client: Any, path: str, shots: list[dict], vertical: bool, model: str = MODEL, usage: dict | None = None) -> list[dict]:
    """Labels for sampled shots: [{shot_index, start, end, size, subject, people, text, text_words, note}]. A sheet that
    comes back unreadable is skipped (its shots just have no label), never invented."""
    picks = pick_shots(shots)
    long_side = 360 if vertical else 384
    loop = asyncio.get_running_loop()
    frames: list[tuple[int, Image.Image | None]] = []
    for i in picks:
        s = shots[i]
        t = min(max(s["mid_time"], s["start"] + 0.05), max(s["start"] + 0.05, s["end"] - 0.05))
        frames.append((i, await loop.run_in_executor(None, extract_frame, path, t, long_side, vertical)))
    frames = [(i, im) for i, im in frames if im is not None]
    sheets = [frames[k:k + TILES_PER_SHEET] for k in range(0, len(frames), TILES_PER_SHEET)]
    limiter = asyncio.Semaphore(3)
    results: list[dict] = []

    async def label(sheet: list[tuple[int, Image.Image]]) -> None:
        tiles = [(k + 1, im) for k, (_, im) in enumerate(sheet)]
        jpeg = await loop.run_in_executor(None, make_sheet, tiles, vertical)
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}},
                   {"type": "text", "text": f"This sheet has {len(tiles)} numbered tiles (1 to {len(tiles)}). Label every tile."}]
        async with limiter:
            response = await client.messages.create(model=model, max_tokens=2600, system=SYSTEM_PROMPT, output_config={"effort": "low"}, messages=[{"role": "user", "content": content}])
        if usage is not None:
            usage["in"] = usage.get("in", 0) + response.usage.input_tokens
            usage["out"] = usage.get("out", 0) + response.usage.output_tokens
            usage["calls"] = usage.get("calls", 0) + 1
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        for d in parse_labels(text):
            n = d["n"]
            if 1 <= n <= len(sheet):
                shot_index = sheet[n - 1][0]
                s = shots[shot_index]
                results.append({"shot_index": shot_index, "start": s["start"], "end": s["end"], **{k: d.get(k) for k in ("size", "subject", "people", "text", "text_words", "note")}})

    await asyncio.gather(*(label(sh) for sh in sheets))
    results.sort(key=lambda r: r["shot_index"])
    return results


def summarize_labels(labels: list[dict], total_shots: int) -> dict[str, Any]:
    """Shares of each label among the labelled shots (a sample of the edit when it has many shots)."""
    n = len(labels)
    if n == 0:
        return {"labelled": 0}
    share = lambda key: {k: round(v / n, 3) for k, v in Counter(str(l.get(key)) for l in labels).most_common()}
    people_counts = Counter(l.get("people") for l in labels if isinstance(l.get("people"), int))
    texts = [{"start": l["start"], "kind": l["text"], "words": l.get("text_words") or ""} for l in labels if l.get("text") not in (None, "none")]
    return {"labelled": n, "of_shots": total_shots, "size": share("size"), "subject": share("subject"), "text_overlay": share("text"),
            "people_in_frame": {str(k): round(v / sum(people_counts.values()), 3) for k, v in sorted(people_counts.items())} if people_counts else {},
            "on_screen_text": texts[:25]}
