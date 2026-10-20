"""
POST (2026-10-20) -- learn from the edit Josh actually made.

A plan is a first draft; the edit he finishes from it is the answer key. This reads his saved Premiere project (the .prproj is gzipped XML, parsed by
learning.prproj), finds the sequence he cut, and compares it with the job's saved plan:

  - for each PLANNED shot: kept (his shot sits inside the planned stretch of that clip), used at a different moment, or dropped (the clip isn't in his edit)
  - for each of HIS shots: the plan's moment, another moment of a clip the plan used, or a clip the plan never used
  - against Claude's described moments (Describe clips): how many of his shots sit on one, and on the first-choice one, next to the share that sitting at
    random would give -- so "Claude's pictures agree with you" is a measured number, not a feeling
  - his pace: shot lengths and how many shots he retimed

Everything is written to backend/data/learning/feedback/ (one detailed file per click + an index line), so his taste accumulates as real labelled data for
later rankers instead of being guessed. Read-only on the project and the plan: nothing in Premiere or in the plan changes, and nothing is sent anywhere.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any

FEEDBACK_DIR = Path(__file__).resolve().parents[1] / "data" / "learning" / "feedback"
SAME_MOMENT_SHARE = 0.5     # his shot counts as "the planned moment" when at least this share of it lies inside the planned stretch of the same clip
EVENT_NEAR_SECONDS = 0.75   # his shot "sits on" a described moment when the moment is inside it (give or take 0.25 s) or within this of its centre
EVENT_MARGIN_SECONDS = 0.25
RETIMED_TOLERANCE = 0.05    # speed within 5% of real time is not a retime
MIN_SHARED_CLIPS = 0.3      # below this share of his clips being in the plan, the plan is probably not the one he built from
PLAN_NEWER_GRACE_SECONDS = 120.0   # a plan saved within this of the sequence's build time counts as the one it was built from


class LearnError(RuntimeError):
    """Something the user can fix (no such sequence, project not saved yet, no plan): the message says what."""


def _name(path: str | None) -> str:
    return os.path.basename(path or "").lower()


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _union_length(intervals: list[tuple[float, float]], lo: float, hi: float) -> float:
    total, end = 0.0, lo
    for a, b in sorted((max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi):
        a = max(a, end)
        if b > a:
            total += b - a
            end = b
    return total


_BUILT_AT = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")


def built_at(sequence_name: str) -> float | None:
    """When Assemble Edit built this sequence (its name ends in the build time, UTC), as epoch seconds -- None for a sequence named some other way."""
    m = _BUILT_AT.search(sequence_name or "")
    if not m:
        return None
    y, mo, d, h, mi, sec = (int(x) for x in m.groups())
    return float(calendar.timegm((y, mo, d, h, mi, sec, 0, 0, 0)))


def stale_plan_warning(sequence_name: str, plan_saved_at: float) -> str | None:
    """A warning when the saved plan is NEWER than the sequence (planned again after building it): the comparison would be against a plan he never built from."""
    built = built_at(sequence_name)
    if built is None or plan_saved_at <= built + PLAN_NEWER_GRACE_SECONDS:
        return None
    local = lambda t: time.strftime("%d %b %H:%M", time.localtime(t))
    return (f"The saved plan was made at {local(plan_saved_at)}, after this sequence was built ({local(built)}), so it is probably not the plan you built from -- "
            "the numbers that follow compare it with a newer plan. (Plan again and build again, or learn from an edit built from the latest plan, for a true comparison.)")


def read_final_edit(project_path: str, sequence_name: str | None) -> tuple[str, list[Any]]:
    """(the sequence's name, its video-1 footage shots in timeline order) from a saved project. The sequence is the one named `sequence_name` (whitespace and case
    don't matter), else the one with the most footage shots."""
    from learning import prproj
    if not project_path or not project_path.lower().endswith(".prproj") or not os.path.exists(project_path):
        raise LearnError("I can't find the saved Premiere project. Save it in Premiere (File > Save) and try again.")
    try:
        sequences = prproj.read_sequences(project_path)
    except prproj.ProjectError as exc:
        raise LearnError(str(exc)) from exc
    with_footage = [(s, [x for x in s.delivered_shots() if x.track == 1 and x.src_in is not None and x.src_out is not None]) for s in sequences]
    with_footage = [(s, shots) for s, shots in with_footage if shots]
    if not with_footage:
        raise LearnError("The saved project has no sequence with footage on video track 1. Save it after cutting, and try again.")
    chosen = None
    if sequence_name:
        key = prproj.normalise_name(sequence_name)
        exact = [(s, shots) for s, shots in with_footage if prproj.normalise_name(s.name) == key]
        near = [(s, shots) for s, shots in with_footage if key in prproj.normalise_name(s.name)]
        pool = exact or near
        if not pool:
            raise LearnError(f"The saved project has no sequence called \"{sequence_name.strip()}\" with footage on it (it has: {', '.join(s.name.strip() for s, _ in with_footage)}). "
                             "Save the project first -- Premiere only writes the sequence you just cut when you save.")
        chosen = max(pool, key=lambda p: len(p[1]))
    else:
        chosen = max(with_footage, key=lambda p: len(p[1]))
    seq, shots = chosen
    return seq.name.strip(), sorted(shots, key=lambda s: s.t0)


def analyse(plan: dict[str, Any], shots: list[Any], moments_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compares his shots (learning.prproj.Shot) with the plan. `moments_by_name`: lower-case clip name -> {"duration", "events": [{t, kind, punch, what}]}."""
    plan_by_clip: dict[str, list[dict[str, Any]]] = {}
    for p in plan["shots"]:
        plan_by_clip.setdefault(_name(p.get("path") or p.get("name")), []).append(p)
    his_by_clip: dict[str, list[Any]] = {}
    for s in shots:
        his_by_clip.setdefault(_name(s.path), []).append(s)

    final_rows, at_event, at_best, checked = [], 0, 0, 0
    chance_event, chance_best = 0.0, 0.0
    for k, s in enumerate(shots, start=1):
        key = _name(s.path)
        length = max(s.src_out - s.src_in, 1e-6)
        planned = plan_by_clip.get(key, [])
        cover, slot = 0.0, None
        for p in planned:
            c = _overlap(s.src_in, s.src_out, p["source_in"], p["source_out"]) / length
            if c > cover:
                cover, slot = c, p.get("index")
        status = "same_moment" if cover >= SAME_MOMENT_SHARE else ("other_moment" if planned else "not_in_plan")
        row: dict[str, Any] = {"order": k, "name": os.path.basename(s.path or ""), "timeline_start": round(s.t0, 3), "timeline_seconds": round(s.length, 3),
                               "source_in": round(s.src_in, 3), "source_out": round(s.src_out, 3), "speed": None if s.speed is None else round(s.speed, 3),
                               "status": status, "plan_slot": slot if status == "same_moment" else None, "event": None}
        rec = moments_by_name.get(key)
        events = [e for e in (rec or {}).get("events", []) if e.get("t") is not None]
        if events:
            centre, dur = (s.src_in + s.src_out) / 2.0, float((rec or {}).get("duration") or 0.0)
            near = []
            for rank, e in enumerate(sorted(events, key=lambda e: -float(e.get("punch", 0))), start=1):
                t = float(e["t"])
                inside = s.src_in - EVENT_MARGIN_SECONDS <= t <= s.src_out + EVENT_MARGIN_SECONDS
                if inside or abs(t - centre) <= EVENT_NEAR_SECONDS:
                    near.append((abs(t - centre), rank, e))
            checked += 1
            if dur > 0:   # the share of this clip that counts as "at an event" -- what sitting anywhere at random would score
                zones = [(float(e["t"]) - EVENT_NEAR_SECONDS, float(e["t"]) + EVENT_NEAR_SECONDS) for e in events]
                best_zone = max(events, key=lambda e: float(e.get("punch", 0)))
                chance_event += _union_length(zones, 0.0, dur) / dur
                chance_best += _union_length([(float(best_zone["t"]) - EVENT_NEAR_SECONDS, float(best_zone["t"]) + EVENT_NEAR_SECONDS)], 0.0, dur) / dur
            if near:
                _, rank, e = min(near)
                at_event += 1
                at_best += rank == 1
                row["event"] = {"rank": rank, "kind": e.get("kind"), "punch": e.get("punch"), "what": e.get("what"), "t": e.get("t")}
        final_rows.append(row)

    slot_rows, kept, changed, dropped = [], 0, 0, 0
    for p in plan["shots"]:
        key = _name(p.get("path") or p.get("name"))
        mine = his_by_clip.get(key, [])
        if not mine:
            state = "dropped"; dropped += 1
        elif any(_overlap(m.src_in, m.src_out, p["source_in"], p["source_out"]) / max(m.src_out - m.src_in, 1e-6) >= SAME_MOMENT_SHARE for m in mine):
            state = "kept"; kept += 1
        else:
            state = "different_moment"; changed += 1
        slot_rows.append({"index": p.get("index"), "name": p.get("name"), "source_in": p.get("source_in"), "source_out": p.get("source_out"), "state": state,
                          "moment": p.get("moment_source", "")[:60]})

    n = len(shots)
    same = sum(1 for r in final_rows if r["status"] == "same_moment")
    other = sum(1 for r in final_rows if r["status"] == "other_moment")
    new = n - same - other
    speeds = [s.speed for s in shots if s.speed is not None]
    retimed = sum(1 for v in speeds if abs(v - 1.0) > RETIMED_TOLERANCE)
    plan_clips, his_clips = set(plan_by_clip), set(his_by_clip)
    shared = len(plan_clips & his_clips)
    summary = {
        "his_shots": n, "his_seconds": round(sum(s.length for s in shots), 2), "his_clips": len(his_clips), "plan_shots": len(plan["shots"]), "plan_clips": len(plan_clips),
        "his_clips_in_plan": shared,
        "his_shots_same_moment": same, "his_shots_other_moment_of_plan_clip": other, "his_shots_clip_not_in_plan": new,
        "plan_shots_kept": kept, "plan_shots_different_moment": changed, "plan_shots_dropped": dropped,
        "described_shots_checked": checked, "at_a_described_moment": at_event, "at_the_first_choice_moment": at_best,
        "chance_at_a_described_moment": round(chance_event / checked, 3) if checked else None, "chance_at_the_first_choice": round(chance_best / checked, 3) if checked else None,
        "median_shot_seconds": round(statistics.median(s.length for s in shots), 3), "retimed_shots": retimed,
    }
    warnings = []
    if his_clips and shared / len(his_clips) < MIN_SHARED_CLIPS:
        warnings.append("Few of your clips are in the saved plan. If you planned again after building this sequence, the comparison is against the wrong plan.")
    if n < 5:
        warnings.append(f"Only {n} shot(s) on video track 1 -- a very small sample.")
    return {"summary": summary, "his_shots": final_rows, "plan_shots": slot_rows, "warnings": warnings}


def lines(sequence: str, plan_style: str | None, result: dict[str, Any]) -> list[str]:
    """The plain-English report the plugin prints."""
    s = result["summary"]
    out = [f"Read your edit \"{sequence}\": {s['his_shots']} shots, {s['his_seconds']:.1f} s, from {s['his_clips']} clips"
           + (f" -- compared with the saved plan ({s['plan_shots']} shots, style {plan_style})." if plan_style else ".")]
    out.append(f"Of the plan's {s['plan_shots']} shots: {s['plan_shots_kept']} kept (your shot sits inside the planned stretch), {s['plan_shots_different_moment']} used at a different moment, "
               f"{s['plan_shots_dropped']} not used at all.")
    out.append(f"Of your {s['his_shots']} shots: {s['his_shots_same_moment']} are the plan's moment, {s['his_shots_other_moment_of_plan_clip']} are another moment of a clip the plan used, "
               f"{s['his_shots_clip_not_in_plan']} are clips the plan didn't use.")
    if s["described_shots_checked"]:
        out.append(f"Claude's described moments: {s['at_a_described_moment']} of your {s['described_shots_checked']} shots (on clips that were described) sit on one "
                   f"(about {s['chance_at_a_described_moment']:.0%} by chance), {s['at_the_first_choice_moment']} on its first choice (about {s['chance_at_the_first_choice']:.0%} by chance).")
    else:
        out.append("None of the clips in your edit have been described (Describe clips), so there's nothing to compare your moments with yet.")
    out.append(f"Your pace: median shot {s['median_shot_seconds']:.2f} s; {s['retimed_shots']} of {s['his_shots']} shots sped up or slowed down.")
    return out[:1] + result["warnings"] + out[1:]   # what to be careful about comes before the numbers


def _write_log(job: dict[str, Any], sequence: str, plan_style: str | None, result: dict[str, Any]) -> tuple[Path, int]:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job["id"], "shoot": job.get("shoot_name"), "sequence": sequence, "plan_style": plan_style, **result}
    path = FEEDBACK_DIR / f"job{job['id']}_{stamp}.json"
    n = 1
    while path.exists():   # two clicks in the same second must not overwrite each other
        n += 1
        path = FEEDBACK_DIR / f"job{job['id']}_{stamp}_{n}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1))
    os.replace(tmp, path)
    with open(FEEDBACK_DIR / "index.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": record["ts"], "job_id": job["id"], "sequence": sequence, "file": path.name, "stale_plan": bool(result.get("stale_plan")), "summary": result["summary"]}) + "\n")
    return path, aggregate()["edits"]


def aggregate() -> dict[str, Any]:
    """Everything logged so far, one row per (job, sequence) -- the latest click of an edit still being worked on replaces its earlier ones."""
    index = FEEDBACK_DIR / "index.jsonl"
    latest: dict[tuple, dict[str, Any]] = {}
    if index.exists():
        for line in index.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest[(row["job_id"], "".join(row["sequence"].split()).lower())] = row
    rows = [r["summary"] for r in latest.values()]
    plan_rows = [r["summary"] for r in latest.values() if not r.get("stale_plan")]   # edits compared with a plan he did NOT build from say nothing about the plan
    shots = sum(r["his_shots"] for r in rows)
    plan_shots = sum(r["his_shots"] for r in plan_rows)
    checked = sum(r["described_shots_checked"] for r in rows)
    return {"edits": len(rows), "shots": shots, "edits_compared_with_their_own_plan": len(plan_rows),
            "share_same_moment_as_plan": round(sum(r["his_shots_same_moment"] for r in plan_rows) / plan_shots, 3) if plan_shots else None,
            "share_clip_not_in_plan": round(sum(r["his_shots_clip_not_in_plan"] for r in plan_rows) / plan_shots, 3) if plan_shots else None,
            "described_shots_checked": checked,
            "share_at_a_described_moment": round(sum(r["at_a_described_moment"] for r in rows) / checked, 3) if checked else None}


def moments_by_clip_name(moments: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """post_moments' cache ({file_id: {name, duration, events, ...}}) keyed by lower-case clip name."""
    return {str(v.get("name", "")).lower(): v for v in moments.values() if v.get("name")}


async def learn_from_edit(job: dict[str, Any], sequence_name: str | None = None, project_path: str | None = None) -> dict[str, Any]:
    """Reads his saved edit, compares it with the job's saved plan, logs the result, and returns {summary, lines, ...} for the plugin to print."""
    from app.post_edit_plan import edit_dir, load_saved_plan
    from app.post_moments import load_moments
    from app.ssd_guard import on_drive
    path = project_path or job.get("premiere_project_path")
    plan = await on_drive(load_saved_plan, job)
    if plan is None:
        raise LearnError("This job has no saved edit plan to compare against. Plan the edit in P Corp OS first.")
    sequence, shots = await on_drive(read_final_edit, path, sequence_name, timeout=120.0)
    moments = moments_by_clip_name(await on_drive(load_moments, edit_dir(job)))
    result = analyse(plan, shots, moments)
    plan_file = edit_dir(job) / "edit_plan_latest.json"
    plan_saved_at = (await on_drive(plan_file.stat)).st_mtime
    stale = stale_plan_warning(sequence, plan_saved_at)
    if stale:
        result["warnings"].insert(0, stale)
    result["stale_plan"] = bool(stale)
    result["plan_saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(plan_saved_at))
    log_path, edits = _write_log(job, sequence, plan.get("style"), result)
    report = lines(sequence, plan.get("style"), result)
    totals = aggregate()
    report.append(f"Saved to the feedback log ({edits} edit{'s' if edits != 1 else ''} logged so far, {totals['shots']} shots).")
    return {"sequence": sequence, "summary": result["summary"], "warnings": result["warnings"], "lines": report, "logged_to": str(log_path), "all_edits": totals}
