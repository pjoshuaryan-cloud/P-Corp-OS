"""Turn Premiere projects into a labelled set of editing decisions: for each delivered edit, every shot with the raw clip it came from and where in it.

What counts as an edit's decisions:
  * a SEQUENCE the editor delivered -- it has an Out point (that is where the export ends) and several real footage shots inside the exported range;
  * only FOOTAGE shots -- not stock elements, graphics, music, or the editor's own earlier renders (a hero video re-imported to cut a short version from it);
  * the same cut exported in several aspect ratios counts once (the shot sets overlap almost entirely).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from learning import footage, prproj

NON_FOOTAGE_PATH = re.compile(r"envato|artlist|stock|transition|overlay|sfx|sound effect|film burn|light leak|glitch|mogrt|template|preset|elements|/assets|leader|countdown|logo|titles?/", re.I)
OWN_RENDER_NAME = re.compile(r"hero|final|grade|render|export|cutdown|reel|draft|recap|visuali[sz]er|cover|slide|preview|\bcut\b|revision", re.I)
AUTOSAVE_UUID = re.compile(r"--[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}.*$")   # "--<project id>..." that Premiere appends to an auto-save's name
AUTOSAVE_STAMP = re.compile(r"-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")                                  # "-2026-09-14_14-03-54"
MIN_FOOTAGE_SHOTS = 4
SAME_EDIT_OVERLAP = 0.6   # two sequences whose shot sets overlap this much (Jaccard) are one edit in different shapes


@dataclass
class ProjectFile:
    name: str
    path: str
    mtime: float
    is_autosave: bool


def is_footage(path: str | None) -> bool:
    if not path or path.isdigit():
        return False
    if os.path.splitext(path)[1].lower() not in footage.VIDEO_EXTENSIONS:
        return False
    return not NON_FOOTAGE_PATH.search(path) and not OWN_RENDER_NAME.search(os.path.basename(path))


def project_name(file_name: str) -> str:
    stem = re.sub(r"\.(prproj)$", "", file_name, flags=re.I)
    return AUTOSAVE_STAMP.sub("", AUTOSAVE_UUID.sub("", stem)).strip()


def collect_projects(files: list[str]) -> list[ProjectFile]:
    """One entry per distinct project: its real project file when there is one, else its newest auto-save."""
    best: dict[str, ProjectFile] = {}
    for path in files:
        if not path.lower().endswith(".prproj"):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        pf = ProjectFile(name=project_name(os.path.basename(path)), path=path, mtime=mtime, is_autosave="auto-save" in path.lower())
        key = pf.name.lower()
        old = best.get(key)
        if old is None or (old.is_autosave and not pf.is_autosave) or (old.is_autosave == pf.is_autosave and pf.mtime > old.mtime):
            best[key] = pf
    return sorted(best.values(), key=lambda p: -p.mtime)


def _shot_key(s: prproj.Shot) -> tuple[str, float]:
    return os.path.basename(s.path or "").lower(), round(s.src_in or 0.0, 1)


def delivered_edits(sequences: list[prproj.Sequence]) -> list[dict]:
    """The distinct delivered edits of a project: [{sequence, shots, variants}] with footage shots only."""
    candidates = []
    for seq in sequences:
        if seq.name.lower().startswith("nested sequence") or seq.out_mark is None:
            continue
        shots = [s for s in seq.delivered_shots() if is_footage(s.path) and s.src_in is not None and s.src_out is not None]
        if len(shots) >= MIN_FOOTAGE_SHOTS:
            candidates.append({"sequence": seq, "shots": shots, "keys": {_shot_key(s) for s in shots}})
    edits: list[dict] = []
    for cand in sorted(candidates, key=lambda c: (-len(c["shots"]), -(c["sequence"].out_mark or 0))):
        for edit in edits:
            union = len(edit["keys"] | cand["keys"])
            if union and len(edit["keys"] & cand["keys"]) / union >= SAME_EDIT_OVERLAP:
                edit["variants"].append(cand["sequence"].name)
                break
        else:
            edits.append({**cand, "variants": []})
    return edits


def build_project(pf: ProjectFile, index: footage.DriveIndex, durations: footage.Durations) -> dict:
    """The labelled record for one project: delivered edits with every shot's raw clip resolved (or marked missing / ambiguous)."""
    sequences = prproj.read_sequences(pf.path)
    edits = delivered_edits(sequences)
    paths = sorted({s.path for e in edits for s in e["shots"] if s.path})
    # lengths of every candidate file for the clips we need, in parallel, before resolving
    durations.prefetch([c for p in paths if not os.path.exists(p) for c in index.candidates(os.path.basename(p))] + [p for p in paths if os.path.exists(p)])
    resolved = {p: footage.resolve(p, next((s.src_duration for e in edits for s in e["shots"] if s.path == p and s.src_duration), None), index, durations) for p in paths}
    out_edits = []
    for e in edits:
        seq = e["sequence"]
        shots = []
        for s in e["shots"]:
            r = resolved[s.path]
            shots.append({"t0": round(s.t0, 3), "t1": round(s.t1, 3), "src_in": round(s.src_in, 3), "src_out": round(s.src_out, 3), "recorded_path": s.path, "src_duration": s.src_duration,
                          "real_path": r.path if r.usable else None, "status": r.status, "track": s.track, "speed": round(s.speed, 3) if s.speed else None})
        out_edits.append({"sequence": seq.name, "variants": e["variants"], "length": seq.out_mark, "shots": shots})
    return {"project": pf.name, "file": pf.path, "mtime": pf.mtime, "autosave": pf.is_autosave, "sequences": len(sequences), "edits": out_edits}


def summarise(record: dict) -> dict:
    shots = [s for e in record["edits"] for s in e["shots"]]
    usable = [s for s in shots if s["real_path"]]
    return {"project": record["project"], "edits": len(record["edits"]), "shots": len(shots), "usable": len(usable),
            "share": (len(usable) / len(shots)) if shots else 0.0, "status": {k: sum(1 for s in shots if s["status"] == k) for k in ("exact", "matched", "ambiguous", "unverified", "missing")}}
