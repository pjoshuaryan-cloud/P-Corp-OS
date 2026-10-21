"""
POST (2026-10-20) -- the saved plans of a job, listed in plain words, with a one-click way back to an earlier one.

Why: planning again replaces the plan the plugin builds from, and that plan can carry hours of review swaps and the accents. The backend has always kept the old
one as edit_plan_prev_<when>.json (and a plan can be saved under a name), but the only way back was copying a file by hand -- which is what happened twice with
the JD Sports plan. This lists those files as "Reviewed (25 swapped) + accents, 31.8 s, 48 shots", and restores one without deleting anything: the plan being
replaced is kept first, and the one restored stays in the list.

Only ever touches edit_plan_*.json and plan_names.json inside the job's own edit_plans folder; a file name that isn't one of those is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

LATEST = "edit_plan_latest.json"
NAMES_FILE = "plan_names.json"
_PLAN_FILE = re.compile(r"^edit_plan_[A-Za-z0-9][A-Za-z0-9_.\-]*\.json$")
_PREV_STAMP = re.compile(r"^edit_plan_prev_(\d{8}T\d{6})")
MAX_LABEL = 60


class PlanHistoryError(RuntimeError):
    """Something the user can act on: the plan isn't there, or isn't a plan."""


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _plan_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and _PLAN_FILE.match(p.name) and not p.name.startswith("._"))


def _names(folder: Path) -> dict[str, str]:
    f = folder / NAMES_FILE
    try:
        data = json.loads(f.read_text()) if f.exists() else {}
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _made_at(path: Path) -> float:
    """When the plan was made: for an archived copy its name says (it is stamped with the original plan's own time); otherwise the file's own time."""
    m = _PREV_STAMP.match(path.name)
    if m:
        try:
            return time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        except ValueError:
            pass
    return path.stat().st_mtime


def _pretty_name(files: list[Path]) -> str | None:
    """A plan saved under a name (edit_plan_YOURS_reviewed_20261009.json) shows that name in words; the planner's own archives and the current plan have none."""
    for f in files:
        if f.name != LATEST and not f.name.startswith("edit_plan_prev_"):
            return re.sub(r"[_\s]+", " ", f.name[len("edit_plan_"):-len(".json")]).strip() or None
    return None


def describe_plan(plan: dict[str, Any], style_name) -> dict[str, Any]:
    """What a plan is, in words: how far it has been worked on, its size, style and how its moments were chosen. `style_name(slug)` gives a style's plain name."""
    review = plan.get("review") or {}
    reviewed, swapped = len(review.get("approved", [])), len(review.get("original", {}))
    accents = bool(plan.get("accents"))
    if swapped:
        stage = f"Reviewed ({swapped} swapped)"
    elif reviewed:
        stage = "Reviewed"
    else:
        stage = "Fresh plan"
    title = stage + (" + accents" if accents else "")
    sources = (plan.get("checks") or {}).get("moment_sources") or {}
    if sources.get("event"):
        moments = "cut on described moments"
    elif sources.get("steadiest"):
        moments = "steadiest stretches"
    else:
        moments = ""
    slug = plan.get("style")
    seconds = plan.get("duration_seconds")
    parts = [f"{seconds:.1f} s" if isinstance(seconds, (int, float)) else None, f"{len(plan.get('shots', []))} shots", style_name(slug) if slug else None, moments or None]
    return {"title": title, "subtitle": " · ".join(p for p in parts if p), "reviewed": reviewed, "swapped": swapped, "accents": accents,
            "style": slug, "seconds": seconds, "shots": len(plan.get("shots", [])), "music": Path((plan.get("music") or {}).get("source") or "").name}


def list_plans(folder: Path, style_name=lambda slug: slug) -> list[dict[str, Any]]:
    """Every distinct saved plan of the job, current one first then newest first. Copies with identical content are shown once (the current plan, else a plan
    you saved under a name, else the oldest archive), the others listed under `also_saved_as`."""
    if not folder.is_dir():
        return []
    names = _names(folder)
    by_hash: dict[str, list[Path]] = {}
    for p in _plan_files(folder):
        try:
            by_hash.setdefault(_sha(p), []).append(p)
        except OSError:
            continue
    latest_hash = _sha(folder / LATEST) if (folder / LATEST).exists() else None
    entries = []
    for h, files in by_hash.items():
        def rank(p: Path) -> tuple:
            return (p.name != LATEST, p.name.startswith("edit_plan_prev_"), _made_at(p))
        files.sort(key=rank)
        shown = files[0]
        try:
            plan = json.loads(shown.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
            continue
        info = describe_plan(plan, style_name)
        made = min(_made_at(f) for f in files)   # a restored or copied file carries the time it was copied; an archive's name keeps when the plan was really made
        label = next((names[f.name] for f in files if f.name in names), None)   # a name YOU gave it
        entries.append({"file": shown.name, "current": h == latest_hash, "label": label, "title": label or info["title"], "kind_title": info["title"],
                        "saved_as": _pretty_name(files), "saved_at": _iso(made), **{k: v for k, v in info.items() if k not in ("title",)},
                        "also_saved_as": [f.name for f in files[1:]]})
    cur = [e for e in entries if e["current"]]
    rest = sorted((e for e in entries if not e["current"]), key=lambda e: e["saved_at"], reverse=True)
    return cur + rest


def _valid_file(folder: Path, file_name: str) -> Path:
    if not _PLAN_FILE.match(file_name or "") or file_name.startswith("._"):
        raise PlanHistoryError("That isn't one of this job's saved plans.")
    path = folder / file_name
    if not path.is_file():
        raise PlanHistoryError("That saved plan is no longer there.")
    return path


def restore_plan(folder: Path, file_name: str) -> dict[str, Any]:
    """Makes a saved plan the current one. The plan it replaces is kept first (as edit_plan_prev_...) unless an identical copy is already saved; the restored
    plan's own file stays where it is. Returns {restored, kept_as, message}."""
    chosen = _valid_file(folder, file_name)
    try:
        plan = json.loads(chosen.read_text())
    except (OSError, ValueError) as exc:
        raise PlanHistoryError("That file isn't a readable plan.") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise PlanHistoryError("That file isn't a plan (it has no shots).")
    latest = folder / LATEST
    if latest.exists() and _sha(latest) == _sha(chosen):
        return {"restored": False, "kept_as": None, "message": "That plan is already the current one."}
    kept_as = None
    if latest.exists():
        current_hash = _sha(latest)
        if not any(p != latest and _sha(p) == current_hash for p in _plan_files(folder)):
            from app.post_edit_plan import archive_previous_plan   # the one place that names archives, so they sort and read the same as the planner's own
            dest = archive_previous_plan(folder)
            kept_as = dest.name if dest else None
    tmp = folder / (LATEST + ".part")
    shutil.copyfile(chosen, tmp)
    os.replace(tmp, latest)
    return {"restored": True, "kept_as": kept_as, "message": "Restored: the plugin will now build from this plan."
            + (" The plan it replaced is kept in the history." if kept_as else "")}


def rename_plan(folder: Path, file_name: str, label: str) -> dict[str, Any]:
    """Gives a saved plan a name of your own (stored in plan_names.json; the plan file is untouched). An empty name removes it."""
    _valid_file(folder, file_name)
    label = " ".join((label or "").split())[:MAX_LABEL]
    names = _names(folder)
    if label:
        names[file_name] = label
    else:
        names.pop(file_name, None)
    tmp = folder / (NAMES_FILE + ".part")
    tmp.write_text(json.dumps(names, indent=1))
    os.replace(tmp, folder / NAMES_FILE)
    return {"file": file_name, "label": label or None}


BUILD_GRACE_SECONDS = 120.0   # a plan saved this soon after the sequence's build time still counts as the one it was built from (clock and rounding)


def plan_for_build_time(folder: Path, built_at: float | None) -> tuple[dict[str, Any] | None, str | None, str, float | None]:
    """The plan a sequence was built from: the newest plan that already existed when it was built (Assemble Edit puts the build time in the sequence's name).
    Returns (plan, file name, basis, when it was made): basis is "matched" when found that way; "latest" when the sequence has no build time (built by hand), so the current plan is used
    and the comparison is only indicative; "newer" when every saved plan is newer than the sequence (the plan it came from is gone), so the oldest is used. (None, None, "none", None)
    when the job has no saved plan."""
    if not folder.is_dir():
        return None, None, "none", None
    groups: dict[str, list[Path]] = {}
    for p in _plan_files(folder):
        try:
            groups.setdefault(_sha(p), []).append(p)
        except OSError:
            continue
    plans = []
    for files in groups.values():
        try:
            data = json.loads(files[0].read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("shots"), list) and data["shots"]:
            current = any(f.name == LATEST for f in files)
            plans.append((min(_made_at(f) for f in files), current, sorted(files, key=lambda p: (p.name != LATEST, p.name.startswith("edit_plan_prev_")))[0].name, data))
    if not plans:
        return None, None, "none", None
    if built_at is None:
        cur = next((p for p in plans if p[1]), max(plans, key=lambda p: p[0]))
        return cur[3], cur[2], "latest", cur[0]
    before = [p for p in plans if p[0] <= built_at + BUILD_GRACE_SECONDS]
    if before:
        best = max(before, key=lambda p: p[0])
        return best[3], best[2], "matched", best[0]
    oldest = min(plans, key=lambda p: p[0])
    return oldest[3], oldest[2], "newer", oldest[0]
