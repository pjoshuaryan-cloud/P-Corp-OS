"""
POST (2026-10-13) -- the brand graphics of a corporate story edit, rendered as images the Premiere plugin lays over the b-roll:

  * an OPENING and a CLOSING brand card: the logo centred on a flat background, tagline / contact lines under it;
  * the LOGO BUG: the logo on a white rounded plate in the top-right corner for the body of the video;
  * one CAPTION image per narration phrase: white text with a soft shadow near the bottom.

Every number (colours, sizes, positions) is read from the measurements stored in the corporate reference
(`video_analysis.brand_graphics`, measured from Josh's exported video) -- nothing here is a guess about his look.

Why images and not Premiere's own captions / text: Premiere's UXP API can NOT create a caption track or a title (documented: the
caption classes only read and rename tracks), so the plugin can't place native captions. A transparent, FULL-FRAME image placed on an
upper track needs no Motion position/scale edits (the logo placement that is already verified in his Premiere works exactly this
way), and reproduces his burned-in look. The cost: caption text is not editable in Premiere -- the .srt is written beside the plan
for editable captions.

Images are rendered at the sequence's exact frame size (they are placed at native size), and named with a hash of their content so a
changed caption can never be mistaken for an older one already in the project.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_FILE = "/System/Library/Fonts/Avenir Next.ttc"
FONT_INDEX = {"medium": 5, "demi": 2, "bold": 0, "bold_italic": 1}
GRAPHICS_SUBFOLDER = "story_graphics"
MAX_CAPTION_WIDTH_SHARE = 0.86  # a longer phrase wraps onto a second line

# What the reference measured (post_reference_build stores it; these are the same numbers, used if the record isn't there)
DEFAULT_STYLE: dict[str, Any] = {
    "card": {"background_rgb": [220, 220, 220], "ink_rgb": [7, 27, 72], "logo_width_share": 0.531, "logo_lockup_height_share": 0.336,
             "opener": {"logo_top_share": 0.307, "text_top_share": 0.706, "text_band_height_share": 0.056},
             "closer": {"logo_top_share": 0.283, "text_top_share": 0.776, "text_line_height_share": 0.05}},
    "logo_bug": {"left_share": 0.796, "right_share": 0.949, "top_share": 0.051, "bottom_share": 0.178, "plate_rgb": [255, 255, 255], "plate_corner_radius_share_of_height": 0.13, "logo_width_share_of_plate": 0.89},
    "caption": {"text_rgb": [255, 255, 255], "centre_y_share": 0.917, "text_block_height_share": 0.0361, "centre_x_share": 0.5},
}


class GraphicsError(RuntimeError):
    pass


def reference_style(slugs: list[str] | None = None) -> dict[str, Any]:
    """The measured style from the first given corporate reference that has it, else the built-in copy of the same numbers."""
    from app import post_reference as pr
    for slug in slugs or ["corporate-distribution-company"]:
        try:
            bg = (pr.load_reference(slug).get("video_analysis") or {}).get("brand_graphics")
        except Exception:
            bg = None
        if bg:
            return {**DEFAULT_STYLE, **{k: v for k, v in bg.items() if k in DEFAULT_STYLE}}
    return DEFAULT_STYLE


def frame_size_for_job(job: dict) -> tuple[int, int] | None:
    """The sequence size the plugin sets from the job's own choices (same table as the plugin's deliverableFrameSize), or None when the
    job's format isn't a standard one (Premiere then keeps its default size and the graphics can't be sized to it)."""
    res, fmt = job.get("resolution"), job.get("deliverable_format")
    if res not in ("4k_uhd", "4k_dci"):
        return None
    long_edge = 4096 if res == "4k_dci" else 3840
    return {"16:9": (long_edge, 2160), "9:16": (2160, long_edge), "1:1": (2160, 2160), "4:5": (2160, 2700)}.get(fmt)


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_FILE, max(8, int(size)), index=FONT_INDEX[kind])
    except OSError as exc:
        raise GraphicsError(f"The font file {FONT_FILE} couldn't be read, so captions and cards can't be drawn.") from exc


def _tag(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8]


def _open_logo(path: str) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
    except Exception as exc:
        raise GraphicsError(f"Couldn't read the logo {Path(path).name} as an image ({type(exc).__name__}). Put a PNG version of it in the job's graphics folder.") from exc
    return im.convert("RGBA")


def _trim_transparent(im: Image.Image) -> Image.Image:
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def _fit(im: Image.Image, max_w: float, max_h: float) -> Image.Image:
    scale = min(max_w / im.width, max_h / im.height)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)


def _fit_font_to_width(text: str, kind: str, target_w: float, max_size: int) -> ImageFont.FreeTypeFont:
    lo, hi = 8, max_size
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _font(kind, mid).getlength(text) <= target_w:
            lo = mid
        else:
            hi = mid - 1
    return _font(kind, lo)


# ------------------------------------------------------------------------------------------------------------ the card
def render_card(logo_path: str, size: tuple[int, int], out_dir: Path, *, role: str, lines: list[str] | None, style: dict[str, Any]) -> dict[str, Any]:
    """An opening or closing brand card. `role` "opener": the logo with ONE tagline line under it (sized to the logo's width, bold italic);
    "closer": the logo with up to four contact lines under it (demi-bold, centred). With no lines, the logo sits centred."""
    W, H = size
    c = style["card"]
    bg, ink = tuple(c["background_rgb"]), tuple(c["ink_rgb"])
    lines = [l.strip() for l in (lines or []) if l and l.strip()][:4]
    logo = _trim_transparent(_open_logo(logo_path))
    lay = c["opener" if role == "opener" else "closer"]
    logo = _fit(logo, c["logo_width_share"] * W, c["logo_lockup_height_share"] * H)
    im = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(im)
    logo_top = round((lay["logo_top_share"] if lines else 0.5 - (logo.height / H) / 2) * H)
    im.alpha_composite(logo, ((W - logo.width) // 2, logo_top))
    if lines and role == "opener":
        font = _fit_font_to_width(lines[0], "bold_italic", logo.width, int(0.075 * H))
        box = d.textbbox((0, 0), lines[0], font=font)
        d.text(((W - (box[2] - box[0])) / 2 - box[0], lay["text_top_share"] * H - box[1]), lines[0], font=font, fill=ink)
    elif lines:
        size_px = int(lay["text_line_height_share"] * H * 0.95)
        font = _font("demi", size_px)
        y = lay["text_top_share"] * H
        for line in lines:
            box = d.textbbox((0, 0), line, font=font)
            d.text(((W - (box[2] - box[0])) / 2 - box[0], y - box[1]), line, font=font, fill=ink)
            y += lay["text_line_height_share"] * H * 1.18
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = _tag("card", role, W, H, bg, ink, lines, Path(logo_path).stat().st_size, Path(logo_path).stat().st_mtime_ns)
    path = out_dir / f"corp_card_{role}_{tag}.png"
    im.convert("RGB").save(path, optimize=True)
    return {"file": str(path), "name": path.name}


# ------------------------------------------------------------------------------------------------------------- the bug
def render_logo_bug(logo_path: str, size: tuple[int, int], out_dir: Path, style: dict[str, Any]) -> dict[str, Any]:
    """A full-frame transparent image: the logo on a white rounded plate in the top-right corner, where the reference has it."""
    W, H = size
    b = style["logo_bug"]
    x0, x1, y0, y1 = b["left_share"] * W, b["right_share"] * W, b["top_share"] * H, b["bottom_share"] * H
    plate_w, plate_h = round(x1 - x0), round(y1 - y0)
    # a plate keeps the reference's proportions on this frame shape: fit it inside the box measured on a 16:9 frame
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ss = 4  # draw the plate 4x larger and shrink it: smooth rounded corners
    plate = Image.new("RGBA", (plate_w * ss, plate_h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle([0, 0, plate_w * ss - 1, plate_h * ss - 1], radius=b["plate_corner_radius_share_of_height"] * plate_h * ss, fill=tuple(b["plate_rgb"]) + (255,))
    plate = plate.resize((plate_w, plate_h), Image.LANCZOS)
    logo = _fit(_trim_transparent(_open_logo(logo_path)), b["logo_width_share_of_plate"] * plate_w, 0.78 * plate_h)
    plate.alpha_composite(logo, ((plate_w - logo.width) // 2, (plate_h - logo.height) // 2))
    im.alpha_composite(plate, (round(x0), round(y0)))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"corp_logo_bug_{_tag('bug', W, H, b, Path(logo_path).stat().st_size, Path(logo_path).stat().st_mtime_ns)}.png"
    im.save(path, optimize=True)
    return {"file": str(path), "name": path.name, "box": [round(x0), round(y0), round(x1), round(y1)]}


# --------------------------------------------------------------------------------------------------------------- captions
_CAPTION_SAMPLE = "rely on with care,"


def caption_font(H: int, style: dict[str, Any]) -> ImageFont.FreeTypeFont:
    """The size at which a sample phrase's ink is as tall as the reference's caption text block (3.6% of the frame height)."""
    target = style["caption"]["text_block_height_share"] * H
    lo, hi = 8, int(0.2 * H)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        box = _font("medium", mid).getbbox(_CAPTION_SAMPLE)
        if box[3] - box[1] <= target:
            lo = mid
        else:
            hi = mid - 1
    return _font("medium", lo)


def render_caption(text: str, size: tuple[int, int], out_dir: Path, style: dict[str, Any], font: ImageFont.FreeTypeFont | None = None) -> dict[str, Any]:
    """A full-frame transparent image holding one caption: white text, soft dark shadow, centred where the reference's captions sit.
    A phrase wider than 86% of the frame is wrapped onto two lines."""
    W, H = size
    cap = style["caption"]
    font = font or caption_font(H, style)
    words = text.split()
    lines = [" ".join(words)]
    if font.getlength(lines[0]) > MAX_CAPTION_WIDTH_SHARE * W and len(words) > 1:
        best = min(range(1, len(words)), key=lambda k: abs(font.getlength(" ".join(words[:k])) - font.getlength(" ".join(words[k:]))))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    gap = round(0.32 * line_h)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    top = cap["centre_y_share"] * H - block_h / 2
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    ref_box = font.getbbox("Ag")
    for i, line in enumerate(lines):
        x = cap["centre_x_share"] * W - font.getlength(line) / 2
        td.text((x, top + i * (line_h + gap) - ref_box[1]), line, font=font, fill=tuple(cap["text_rgb"]) + (255,))
    # shadow: the text's own shape, darkened, blurred a little and nudged down
    alpha = text_layer.getchannel("A")
    shadow_a = alpha.filter(ImageFilter.GaussianBlur(max(1.0, 0.0025 * H))).point(lambda v: min(255, int(v * 2.2)))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(shadow_a.point(lambda v: int(v * 0.9)))
    shadow = Image.composite(shadow, Image.new("RGBA", (W, H), (0, 0, 0, 0)), shadow_a)
    offset = max(1, round(0.0022 * H))
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(shadow, (0, offset))
    im.alpha_composite(text_layer)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"corp_caption_{_tag('caption', W, H, text, font.size, cap)}.png"
    if not path.exists():
        im.save(path, optimize=True)
    return {"file": str(path), "name": path.name, "text": text}


# --------------------------------------------------------------------------------------------------------------- the plan
def build_graphics(plan: dict[str, Any], *, job: dict, logo_path: str | None, size: tuple[int, int] | None, out_dir: Path, tagline: str | None, contact_lines: list[str] | None,
                   burn_captions: bool = True, style_slugs: list[str] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Renders the cards, logo bug and caption images for a story plan and describes where to place them. Returns (graphics, notes);
    graphics is None when it can't be done (and `notes` says why). Slots: the plan's `opener` and `end_card` shots are the card slots (the
    b-roll underneath stays as the fallback if a card fails to place); the bug spans between them; each caption sits on its narrated shot."""
    notes: list[str] = []
    if not logo_path:
        return None, ["No logo found in the job's graphics folder, so no brand cards, logo bug or caption images were made. Put a PNG logo there and plan again."]
    if size is None:
        return None, [f"The job's format ({job.get('deliverable_format')}, {job.get('resolution')}) isn't a standard size, so the sequence size can't be known when the graphics are drawn. "
                      "Set the deliverable format and 4K resolution on the job, then plan again."]
    style = reference_style(style_slugs)
    shots = plan["shots"]
    opener = next((s for s in shots if s["role"] == "opener"), None)
    closer = next((s for s in shots if s["role"] == "end_card"), None)
    graphics: dict[str, Any] = {"frame_size": [size[0], size[1]], "tracks": {"cards": 2, "logo_bug": 3, "captions": 4}, "cards": [], "logo_bug": None, "captions": None}
    if opener:
        c = render_card(logo_path, size, out_dir, role="opener", lines=[tagline] if tagline else None, style=style)
        graphics["cards"].append({**c, "role": "opener", "start_frame": opener["start_frame"], "frames": opener["duration_frames"]})
    if closer:
        c = render_card(logo_path, size, out_dir, role="closer", lines=contact_lines, style=style)
        graphics["cards"].append({**c, "role": "closer", "start_frame": closer["start_frame"], "frames": closer["duration_frames"]})
    bug_start = (opener["start_frame"] + opener["duration_frames"]) if opener else 0
    bug_end = closer["start_frame"] if closer else plan["duration_frames"]
    if bug_end - bug_start > 24:
        b = render_logo_bug(logo_path, size, out_dir, style)
        graphics["logo_bug"] = {**b, "start_frame": bug_start, "frames": bug_end - bug_start}
    narrated = [s for s in shots if s.get("phrase")]
    if narrated and burn_captions:
        font = caption_font(size[1], style)
        items = []
        for s in narrated:
            r = render_caption(s["phrase"], size, out_dir, style, font)
            items.append({**r, "start_frame": s["start_frame"], "frames": s["duration_frames"], "shot_index": s["index"]})
        graphics["captions"] = {"burned_in": items, "srt_path": plan.get("captions_path")}
    elif narrated:
        graphics["captions"] = {"burned_in": [], "srt_path": plan.get("captions_path")}
    notes.append("Brand cards, logo bug and caption images are laid OVER the b-roll on upper tracks (V2 cards, V3 logo bug, V4 captions), so the b-roll under them is still there. "
                 "Captions are images, not editable text: Premiere's scripting can't create caption tracks. Import captions.srt for editable captions (and turn the burned-in ones off).")
    return graphics, notes
