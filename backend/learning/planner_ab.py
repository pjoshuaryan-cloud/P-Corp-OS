"""Plan the same job several ways, offline, and compare the plans with each other and with the edit Josh actually made.

Uses only files already on disk: the job's steadiness.json and moments.json (edit_plans/), a saved plan for the slot layout (cut times and lengths), and his saved
Premiere project. Nothing is written and no API calls are made. Clips are put in shoot order by file name (the real planner uses camera creation time, which is not
saved next to the plan), so absolute numbers can differ a little from a real Plan Edit; the variants are compared on identical input, which is what matters.

  .venv/bin/python -m learning.planner_ab <edit_plans folder> <plan.json for the slot layout> "<project.prproj>" "<sequence name part>"
"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

from app import post_edit_story, post_pick, post_steady
from learning import plan_vs_final

VARIANTS = (
    ("old: steadiest stretch of each clip", {"EVENT_FIRST": False, "EVENT_CANDIDATES": 1}),
    ("event first, one moment per clip", {"EVENT_FIRST": True, "EVENT_CANDIDATES": 1}),
    ("event first, best of 3 moments per clip", {"EVENT_FIRST": True, "EVENT_CANDIDATES": 3}),
    ("event first, best of 5 moments per clip", {"EVENT_FIRST": True, "EVENT_CANDIDATES": 5}),
)


def load_clips(folder: Path) -> list[dict]:
    steady = json.loads((folder / "steadiness.json").read_text())
    moments = json.loads((folder / "moments.json").read_text())
    clips = []
    for key, rec in moments.items():
        hit = steady.get(key)
        if not hit:
            continue
        m = hit["m"]
        clips.append({"file_id": int(key), "name": rec["name"], "path": rec["name"], "duration": float(rec["duration"]), "steady": m, "thumbs": post_steady.decode_thumbs(m),
                      "scene": rec.get("scene", ""), "people": rec.get("people", False), "events": rec.get("events", [])})
    clips.sort(key=lambda c: c["name"])
    return clips


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__); return 1
    folder, layout_path, project, seq_part = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    layout = json.load(open(layout_path))
    slots = [{"role": s["role"], "start_frame": s["start_frame"], "frames": s["duration_frames"]} for s in layout["shots"]]
    fps = float(layout["fps"])
    clips = load_clips(folder)
    seq_name, his = plan_vs_final.his_shots(project, seq_part)
    print(f"{len(clips)} clips, {len(slots)} slots of the saved layout, his edit: {len(his)} shots on V1, {len({os.path.basename(s.path).lower() for s in his})} distinct clips\n")
    saved = (post_steady.EVENT_FIRST, post_pick.EVENT_CANDIDATES)
    try:
        for label, flags in VARIANTS:
            post_steady.EVENT_FIRST, post_pick.EVENT_CANDIDATES = flags["EVENT_FIRST"], flags["EVENT_CANDIDATES"]
            res = post_edit_story.assign_clips_to_slots(slots, fps=fps, clips=clips, bookend_file_id=None)
            shots = res["shots"]
            post_steady.clear_series_cache()
            ids = collections.Counter(s["file_id"] for s in shots)
            scenes = {(next(c for c in clips if c["file_id"] == s["file_id"]).get("scene") or "").lower() for s in shots}
            rep = res.get("repetition") or {}
            cmp = plan_vs_final.compare(his, {"shots": [{"path": s["name"], "source_in": s["source_in"], "source_out": s["source_out"]} for s in shots]})
            n = max(cmp["his_shots_with_clip_in_plan"], 1)
            print(f"{label}")
            print(f"   {len(shots)} shots from {len(ids)} clips ({sum(1 for v in ids.values() if v > 1)} clip(s) used more than once); {len(scenes)} distinct scene labels; "
                  f"{rep.get('distinct_looks')} distinct looks, {rep.get('alike_pairs')} look-alike pairs, {rep.get('alike_neighbours')} look-alike neighbours")
            print(f"   vs his edit: {cmp['his_clips_in_plan']}/{cmp['his_clips']} of his clips in the plan; on his moment for {cmp['on_his_moment']}/{cmp['his_shots_with_clip_in_plan']} "
                  f"({cmp['on_his_moment'] / n:.0%}), within ~1 s for {cmp['near_his_moment']}/{cmp['his_shots_with_clip_in_plan']} ({cmp['near_his_moment'] / n:.0%})\n")
    finally:
        post_steady.EVENT_FIRST, post_pick.EVENT_CANDIDATES = saved
    return 0


if __name__ == "__main__":
    sys.exit(main())
