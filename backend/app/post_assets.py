"""POST asset library for the Cinematic Reel Autopilot, phase 1 (2026-11-17).

Catalogues what the finishing pass may place, so later steps choose from what Josh really has:
  * motion graphics templates (.mogrt): length, frame size, frame rate, and how many text fields each has. The Premiere
    plugin can place a template but can't change its text (Adobe's UXP API, checked 2026-10-30 and again in step 0 on
    2026-11-17), so a template with text fields is only usable if its default words are wanted -- `needs_text` says so;
  * video transitions installed in Premiere, grouped by what they do (a blur move like Rabit Haus's, a dissolve, a dip...).
Sound effects already have their own index (post_accents.build_sfx_index); overlays (light leaks, film burns) were put
off by Josh on 2026-11-17.

Reading is local and free: a .mogrt is a zip whose definition.json describes it; no Claude call is made.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

TICKS_PER_SECOND = 254016000000
MOGRT_DIRS = [os.path.expanduser("~/Library/Application Support/Adobe/Common/Motion Graphics Templates")]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEMPLATE_INDEX_PATH = DATA_DIR / "post_template_index.json"
TRANSITION_INDEX_PATH = DATA_DIR / "post_transition_index.json"

TEXT_CONTROL = 6   # clientControls "type" for an editable text field

# Transition groups, by words in Premiere's match names. Order matters: first match wins.
TRANSITION_GROUPS = [
    ("blur_move", ("whip", "directional_blur", "directional blur", "radial blur", "radial_blur", "lens_blur", "blur_dissolve", "blur dissolve", "cross zoom", "cross_zoom", "mobius zoom", "blur_to_color")),
    ("light", ("light_leaks", "light_sweep", "chroma_leaks", "flash", "flare", "burn_white", "burn_alpha", "glow")),
    ("dip", ("dip to", "dip_to")),
    ("dissolve", ("dissolve",)),
    ("push_slide", ("push", "slide")),
    ("wipe", ("wipe",)),
]


def _text(value: Any) -> str:
    """A localized Adobe string ({"strDB": [{"localeString", "str"}]}) or plain text, as plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for entry in value.get("strDB") or []:
            if entry.get("str"):
                return str(entry["str"])
        for key in ("textEditValue", "str", "value"):
            if isinstance(value.get(key), str):
                return value[key]
    return ""


def read_mogrt(path: str, root: str | None = None) -> dict[str, Any] | None:
    """One template's facts from its definition.json, or None if it can't be read."""
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.read("definition.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    source = (d.get("sourceInfoLocalized") or {})
    source = source.get("en_US") or next(iter(source.values()), {}) if isinstance(source, dict) else {}
    duration = source.get("duration") or {}
    seconds = round(duration["value"] / duration["scale"], 2) if duration.get("scale") else None
    tpf = (source.get("framerate") or {}).get("ticksperframe")
    fps = round(TICKS_PER_SECOND / tpf, 3) if tpf else None
    size = (source.get("framesize") or {}).get("size") or {}
    controls = d.get("clientControls") or []
    texts = [c for c in controls if c.get("type") == TEXT_CONTROL]
    rel = os.path.relpath(path, root) if root else os.path.basename(path)
    pack = os.path.dirname(rel) or None
    return {
        "path": path,
        "name": _text(d.get("capsuleNameLocalized")) or d.get("capsuleName") or Path(path).stem,
        "pack": pack,
        "made_in": {"aefx": "After Effects", "ppro": "Premiere"}.get(d.get("authorApp"), d.get("authorApp")),
        "seconds": seconds,
        "fps": fps,
        "width": size.get("x"),
        "height": size.get("y"),
        "text_fields": len(texts),
        "default_text": [t for t in (_text(c.get("value")) for c in texts) if t][:6],
        "other_controls": len(controls) - len(texts),
        "needs_text": len(texts) > 0,
        "vertical": bool(size.get("x") and size.get("y") and size["y"] > size["x"]),
    }


def build_template_index(dirs: list[str] | None = None, out_path: Path | None = TEMPLATE_INDEX_PATH) -> list[dict[str, Any]]:
    """Every .mogrt under the given folders (default: Premiere's own templates folder). Saved to out_path unless None."""
    index = []
    for root in dirs or MOGRT_DIRS:
        for dirpath, _dirs, names in os.walk(root):
            for name in sorted(names):
                if name.lower().endswith(".mogrt") and not name.startswith("."):
                    entry = read_mogrt(os.path.join(dirpath, name), root)
                    if entry:
                        index.append(entry)
    index.sort(key=lambda e: ((e["pack"] or ""), e["name"].lower()))
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(index, indent=1))
    return index


def classify_transition(match_name: str) -> str:
    low = match_name.lower()
    for group, words in TRANSITION_GROUPS:
        if any(w in low for w in words):
            return group
    return "other"


def build_transition_index(match_names: list[str], out_path: Path | None = TRANSITION_INDEX_PATH) -> list[dict[str, Any]]:
    """Premiere's installed video transitions (the plugin reads them with TransitionFactory.getVideoTransitionMatchNames()),
    each with its group and whether it ships with Premiere ("AE.ADBE ..." / "ADBE ...") or comes from a third-party pack."""
    index = [{"match_name": n, "group": classify_transition(n), "built_in": n.startswith(("AE.ADBE ", "ADBE "))} for n in sorted(set(match_names))]
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(index, indent=1))
    return index


def load_index(path: Path) -> list[dict[str, Any]] | None:
    return json.loads(path.read_text()) if path.exists() else None


def summary(templates: list[dict[str, Any]] | None, transitions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Counts for Josh: what the finishing pass can actually use."""
    out: dict[str, Any] = {}
    if templates is not None:
        out["templates"] = len(templates)
        out["templates_without_text"] = sum(1 for t in templates if not t["needs_text"])
        out["templates_vertical"] = sum(1 for t in templates if t["vertical"])
        packs: dict[str, int] = {}
        for t in templates:
            packs[t["pack"] or "(top folder)"] = packs.get(t["pack"] or "(top folder)", 0) + 1
        out["template_packs"] = packs
    if transitions is not None:
        groups: dict[str, int] = {}
        for t in transitions:
            groups[t["group"]] = groups.get(t["group"], 0) + 1
        out["transitions"] = len(transitions)
        out["transition_groups"] = groups
        out["blur_moves_built_in"] = [t["match_name"] for t in transitions if t["group"] == "blur_move" and t["built_in"]]
    return out
