"""Checks a sequence the plugin built against the plan it was built from, frame by frame, from the SAVED Premiere project (no Premiere API, nothing written).

For the real-Premiere checklist (premiere-plugin/REAL_PREMIERE_CHECKLIST.md): after Build My Edit, save the project, then

  cd backend && .venv/bin/python -m learning.verify_build --project "<the .prproj>" --plan "<edit_plans>/edit_plan_latest.json" [--sequence "<name>"] [--before "<a copy of the .prproj saved before the build>"]

What it checks, per planned shot in timeline order (V1 = footage, V2 = brand cards):
  * the clip: the V1 item's file is the planned clip;
  * the source in point: within one frame of the SOURCE, or half a frame of the SEQUENCE when that is more (the plugin snaps every in point to the
    sequence's frame grid, so 59.94 fps footage in a 25 fps edit can land up to 1.2 source frames away);
  * the timeline start and length: within half a frame of the plan's start_frame / duration_frames;
  * the edit's total length;
  * brand cards: one V2 item per planned card, on its slot;
  * with --before: every OTHER sequence of the project is exactly as it was (nothing existing was changed).
Not checked (the project file's video tracks are all it reads): music, zooms and scaling, accents, captions. Those are checked by eye, as the checklist says.
Slow motion: the plugin can't set a speed (no Premiere API). It builds every shot from its source_in for duration_frames at real time, so a slowed plan
shot comes out at real time, a full slot of footage starting at the slowed window's start (a quarter slot later than the un-slowed moment); reported, not failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from learning import prproj


def _base(p: str | None) -> str:
    return os.path.basename((p or "").replace("\\", "/")).lower()


def _signature(seq: prproj.Sequence) -> list[tuple]:
    return [(s.track, round(s.t0, 4), round(s.t1, 4), None if s.src_in is None else round(s.src_in, 4), _base(s.path)) for s in seq.shots]


def compare_build(plan: dict[str, Any], seq: prproj.Sequence, before: list[prproj.Sequence] | None = None, after: list[prproj.Sequence] | None = None) -> dict[str, Any]:
    """Pure: {"ok": bool, "checks": [(name, passed, detail)], "worst": {...}} for `seq` against `plan`."""
    fps = float(plan["fps"])
    checks: list[tuple[str, bool, str]] = []
    v1 = sorted((s for s in seq.shots if s.track == 1 and s.path and not s.path.isdigit()), key=lambda s: s.t0)
    planned = sorted(plan["shots"], key=lambda s: s["start_frame"])
    checks.append(("every planned shot is on V1 (and nothing else is)", len(v1) == len(planned), f"{len(v1)} on V1, {len(planned)} planned"))
    worst = {"source_frames": 0.0, "start_frames": 0.0, "length_frames": 0.0}
    clip_bad, in_bad, start_bad, len_bad, slowed = [], [], [], [], []
    for k, (p, s) in enumerate(zip(planned, v1), start=1):
        if _base(s.path) != _base(p.get("path") or p["name"]):
            clip_bad.append(f"shot {p['index']}: {s.name or _base(s.path)} instead of {p['name']}")
            continue
        src_fps = s.src_fps or fps
        if float(p.get("speed") or 1.0) != 1.0:
            slowed.append(p["index"])
        want_in = p["source_in"]   # what the plugin builds from, slowed or not (index.js assembleEdit: source_in, snapped to the sequence frame grid)
        if s.src_in is not None:
            d = abs(s.src_in - want_in) * src_fps
            worst["source_frames"] = max(worst["source_frames"], d)
            if abs(s.src_in - want_in) > max(1.0 / src_fps, 0.5 / fps) + 1e-6:
                in_bad.append(f"shot {p['index']}: source in {s.src_in:.3f} s vs planned {want_in:.3f} s ({d:.1f} source frames)")
        d0 = abs(s.t0 * fps - p["start_frame"])
        dl = abs((s.t1 - s.t0) * fps - p["duration_frames"])
        worst["start_frames"], worst["length_frames"] = max(worst["start_frames"], d0), max(worst["length_frames"], dl)
        if d0 > 0.5:
            start_bad.append(f"shot {p['index']}: starts at frame {s.t0 * fps:.1f}, planned {p['start_frame']}")
        if dl > 0.5:
            len_bad.append(f"shot {p['index']}: {(s.t1 - s.t0) * fps:.1f} frames long, planned {p['duration_frames']}")
    checks.append(("every shot uses the planned clip", not clip_bad, "; ".join(clip_bad[:4])))
    checks.append(("every source in point is within one source frame (or half a sequence frame) of the plan", not in_bad, "; ".join(in_bad[:4]) or f"worst {worst['source_frames']:.2f} frames"))
    checks.append(("every shot starts on its planned frame", not start_bad, "; ".join(start_bad[:4])))
    checks.append(("every shot is its planned length", not len_bad, "; ".join(len_bad[:4])))
    end = max((s.t1 for s in v1), default=0.0) * fps
    checks.append(("the edit is the planned length", abs(end - plan["duration_frames"]) <= 0.5, f"{end:.1f} frames vs {plan['duration_frames']}"))
    cards = (plan.get("graphics") or {}).get("cards") or []
    if cards:
        v2 = sorted((s for s in seq.shots if s.track == 2), key=lambda s: s.t0)
        placed = [c for c in cards if any(abs(s.t0 * fps - c["start_frame"]) <= 0.5 and abs((s.t1 - s.t0) * fps - c["frames"]) <= 1.5 and _base(s.path) == _base(c["file"]) for s in v2)]
        checks.append(("every brand card is on V2 over its slot", len(placed) == len(cards), f"{len(placed)} of {len(cards)} placed"))
    if before is not None and after is not None:
        old = {prproj.normalise_name(s.name): _signature(s) for s in before}
        changed = [s.name for s in after if prproj.normalise_name(s.name) in old and prproj.normalise_name(s.name) != prproj.normalise_name(seq.name)
                   and _signature(s) != old[prproj.normalise_name(s.name)]]
        gone = [n for n in old if n not in {prproj.normalise_name(s.name) for s in after}]
        checks.append(("no existing sequence was changed or removed", not changed and not gone, f"changed {changed[:3]}, removed {gone[:3]}"))
    notes = [f"{len(slowed)} shot(s) are slowed in the plan; Premiere has no speed API, so they are built at real time from the slowed window's start (expected)."] if slowed else []
    return {"ok": all(c[1] for c in checks), "checks": checks, "worst": {k: round(v, 2) for k, v in worst.items()}, "notes": notes}


def pick_sequence(seqs: list[prproj.Sequence], name: str | None) -> prproj.Sequence:
    """The named sequence, else the newest one Assemble Edit / Build My Edit made ('<shoot> - Edit <ISO time>')."""
    if name:
        for s in seqs:
            if prproj.normalise_name(s.name) == prproj.normalise_name(name):
                return s
        raise SystemExit(f"No sequence called {name!r} in the project.")
    from app.post_learn import built_at
    built = [(built_at(s.name), s) for s in seqs if built_at(s.name)]
    if not built:
        raise SystemExit("No sequence made by Build My Edit in the project; pass --sequence.")
    return max(built, key=lambda b: b[0])[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--sequence")
    ap.add_argument("--before", help="a copy of the project saved before the build")
    a = ap.parse_args()
    plan = json.loads(Path(a.plan).read_text())
    after = prproj.read_sequences(a.project)
    seq = pick_sequence(after, a.sequence)
    before = prproj.read_sequences(a.before) if a.before else None
    r = compare_build(plan, seq, before, after if before is not None else None)
    print(f"sequence: {seq.name}  |  plan: {plan.get('style')} {len(plan['shots'])} shots at {plan['fps']} fps")
    for name, ok, detail in r["checks"]:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else (f"   ({detail})" if detail else "")))
    for n in r["notes"]:
        print("note:", n)
    print("NOT checked here (video tracks only): music, zooms/scaling, accents, captions -- check those by eye.")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
