"""How close was a saved plan to the edit Josh actually made from it?

Reads the finished sequence out of his saved Premiere project and compares it with one or more saved plans (edit_plan_*.json) of the same job:
  - clips: how many of the clips he used were in the plan at all (and how many the plan used that he didn't)
  - moments: for his shots whose clip WAS in the plan, how often the planned stretch of that clip is the moment he used
    ("on his moment" = the plan's window covers at least half of his shot; "near it" = his shot's centre lies inside the window, or within 1 s of it)
Read-only. Run from backend/:
  .venv/bin/python -m learning.plan_vs_final "<project.prproj>" "<sequence name part>" plan_a.json plan_b.json ...
"""
from __future__ import annotations

import json
import os
import sys

from learning import prproj


def his_shots(project: str, name_part: str) -> tuple[str, list[prproj.Shot]]:
    key = prproj.normalise_name(name_part)
    candidates = [s for s in prproj.read_sequences(project) if key in prproj.normalise_name(s.name)]
    if not candidates:
        raise SystemExit(f"No sequence with '{name_part}' in its name. Found: {[s.name for s in prproj.read_sequences(project)]}")
    seq = max(candidates, key=lambda s: len(s.delivered_shots()))
    return seq.name, [s for s in seq.delivered_shots() if s.src_in is not None and s.src_out is not None and s.track == 1]


def compare(shots: list[prproj.Shot], plan: dict) -> dict:
    planned: dict[str, list[tuple[float, float]]] = {}
    for p in plan["shots"]:
        planned.setdefault(os.path.basename(p["path"]).lower(), []).append((p["source_in"], p["source_out"]))
    his_clips = {os.path.basename(s.path).lower() for s in shots}
    in_plan = [s for s in shots if os.path.basename(s.path).lower() in planned]
    on = near = 0
    for s in in_plan:
        length = max(s.src_out - s.src_in, 1e-6)
        centre = (s.src_in + s.src_out) / 2
        windows = planned[os.path.basename(s.path).lower()]
        covered = max(max(0.0, min(w1, s.src_out) - max(w0, s.src_in)) / length for w0, w1 in windows)
        on += covered >= 0.5
        near += covered >= 0.5 or any(w0 - 1.0 <= centre <= w1 + 1.0 for w0, w1 in windows)
    return {"plan_shots": len(plan["shots"]), "plan_clips": len(planned), "his_shots": len(shots), "his_clips": len(his_clips),
            "his_clips_in_plan": len(his_clips & set(planned)), "his_shots_with_clip_in_plan": len(in_plan), "on_his_moment": on, "near_his_moment": near}


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__); return 1
    name, shots = his_shots(sys.argv[1], sys.argv[2])
    total = sum(s.length for s in shots)
    print(f"his sequence '{name.strip()}': {len(shots)} shots on V1, {total:.1f} s, {len({os.path.basename(s.path).lower() for s in shots})} distinct clips")
    for path in sys.argv[3:]:
        r = compare(shots, json.load(open(path)))
        print(f"\n{os.path.basename(path)}: {r['plan_shots']} planned shots from {r['plan_clips']} clips")
        print(f"  clips: {r['his_clips_in_plan']} of his {r['his_clips']} clips were in the plan ({r['his_clips_in_plan'] / r['his_clips']:.0%})")
        n = max(r['his_shots_with_clip_in_plan'], 1)
        print(f"  moments: of his {r['his_shots_with_clip_in_plan']} shots whose clip was in the plan, the plan's stretch was HIS moment for {r['on_his_moment']} ({r['on_his_moment'] / n:.0%}) and within about a second of it for {r['near_his_moment']} ({r['near_his_moment'] / n:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
