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
import zlib
from pathlib import Path
from typing import Any

FEEDBACK_DIR = Path(__file__).resolve().parents[1] / "data" / "learning" / "feedback"
_REAL_FEEDBACK_DIR = FEEDBACK_DIR   # tests point FEEDBACK_DIR elsewhere; see _write_log
SAME_MOMENT_SHARE = 0.5     # his shot counts as "the planned moment" when at least this share of it lies inside the planned stretch of the same clip
EVENT_NEAR_SECONDS = 0.75   # his shot "sits on" a described moment when the moment is inside it (give or take 0.25 s) or within this of its centre
EVENT_MARGIN_SECONDS = 0.25
RETIMED_TOLERANCE = 0.05    # speed within 5% of real time is not a retime
MIN_SHARED_CLIPS = 0.3      # below this share of his clips being in the plan, the plan is probably not the one he built from
PLAN_NEWER_GRACE_SECONDS = 120.0   # a plan saved within this of the sequence's build time counts as the one it was built from


class LearnError(RuntimeError):
    """Something the user can fix (no such sequence, project not saved yet, no plan): the message says what."""


class NotACutYet(LearnError):
    """The sequence is his clips laid end to end (each used whole), not an edit: nothing to learn from yet."""


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
            # The clip's whole candidate set goes in the log (not just the one he sat on): a taste model needs the moments he did NOT pick as much as the one he did.
            row["candidates"] = [{"rank": r, "t": e.get("t"), "kind": e.get("kind"), "punch": e.get("punch")} for r, e in enumerate(sorted(events, key=lambda e: -float(e.get("punch", 0))), start=1)]
            row["clip_seconds"] = dur
            row["people"] = bool((rec or {}).get("people"))
            if near:
                _, rank, e = min(near)
                at_event += 1
                at_best += rank == 1
                row["event"] = {"rank": rank, "kind": e.get("kind"), "punch": e.get("punch"), "what": e.get("what"), "t": e.get("t")}
        final_rows.append(row)

    slot_rows, kept, changed, dropped = [], 0, 0, 0
    plan_slowed, plan_slowed_kept, plan_slowed_you_slowed = 0, 0, 0
    for p in plan["shots"]:
        key = _name(p.get("path") or p.get("name"))
        mine = his_by_clip.get(key, [])
        planned_speed = float(p.get("speed") or 1.0)
        matched = [m for m in mine if _overlap(m.src_in, m.src_out, p["source_in"], p["source_out"]) / max(m.src_out - m.src_in, 1e-6) >= SAME_MOMENT_SHARE]
        if not mine:
            state = "dropped"; dropped += 1
        elif matched:
            state = "kept"; kept += 1
        else:
            state = "different_moment"; changed += 1
        slot = {"index": p.get("index"), "name": p.get("name"), "source_in": p.get("source_in"), "source_out": p.get("source_out"), "state": state, "moment": p.get("moment_source", "")[:60]}
        if planned_speed != 1.0:   # the plan slowed this shot (set in review): did he keep the shot, and did he slow it too?
            slot["speed"] = planned_speed
            plan_slowed += 1
            if state == "kept":
                plan_slowed_kept += 1
                his_speed = next((m.speed for m in matched if m.speed is not None), None)
                slot["he_slowed"] = bool(his_speed is not None and his_speed < 1.0 - RETIMED_TOLERANCE)
                plan_slowed_you_slowed += slot["he_slowed"]
        slot_rows.append(slot)

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
    if plan_slowed:   # only when the plan slowed something, so a plan without slow motion reports exactly what it did before
        summary.update({"plan_slowed_shots": plan_slowed, "plan_slowed_shots_kept": plan_slowed_kept, "plan_slowed_shots_you_slowed": plan_slowed_you_slowed,
                        "you_slowed_shots": sum(1 for v in speeds if v < 1.0 - RETIMED_TOLERANCE)})
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
    if s.get("plan_slowed_shots"):
        out.append(f"Slow motion: the plan slowed {s['plan_slowed_shots']} shots; you kept {s['plan_slowed_shots_kept']} of them and slowed {s['plan_slowed_shots_you_slowed']} of those. "
                   f"You slowed {s['you_slowed_shots']} shots in all.")
    return out[:1] + result["warnings"] + out[1:]   # what to be careful about comes before the numbers


def _write_log(job: dict[str, Any], sequence: str, plan_style: str | None, result: dict[str, Any], source: str = "button") -> tuple[Path, int]:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job["id"], "shoot": job.get("shoot_name"), "sequence": sequence, "plan_style": plan_style, "source": source, **result}
    path = FEEDBACK_DIR / f"job{job['id']}_{stamp}.json"
    n = 1
    while path.exists():   # two clicks in the same second must not overwrite each other
        n += 1
        path = FEEDBACK_DIR / f"job{job['id']}_{stamp}_{n}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1))
    os.replace(tmp, path)
    with open(FEEDBACK_DIR / "index.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": record["ts"], "job_id": job["id"], "sequence": sequence, "file": path.name, "source": source, "stale_plan": bool(result.get("stale_plan")), "summary": result["summary"]}) + "\n")
    # the same comparison as versioned learning events in the job's own file (observed only when compared with the plan it was built from). The feedback log above
    # is the record of truth: finding the job's folder or writing the copy must never break it, so any failure here is logged and passed over. The copy follows the
    # log: a log sent somewhere else (a test redirects FEEDBACK_DIR to a temp folder while reading his REAL project) must not write into his real job folder --
    # it did on 2026-10-22, four test runs left 324 copies in GWM's learning_events.jsonl before this check existed.
    if FEEDBACK_DIR == _REAL_FEEDBACK_DIR:
        from app import post_learning_events as le
        from app.post_edit_plan import edit_dir
        try:
            le.record_for_job(edit_dir(job), le.from_learn_record(record))
        except Exception as exc:   # noqa: BLE001 -- DriveNotConnected, a job without a folder, ...: none may cost him the log
            le._log.warning("learning events for job %s not recorded: %s", job.get("id"), exc)
    return path, aggregate()["edits"]


# ---------------------------------------------------------------------------------------------- edits made WITHOUT a P Corp plan (2026-10-22)
# A project he started himself (not a POST shoot, no plan) still shows his choices directly: which stretch of which clip, how long, how fast, in what order. It is
# recorded as-is -- every shot "not in plan" -- under a stable NEGATIVE id per project file, so it can never be mistaken for a shoot number and two projects never
# mix. It is real ground truth for where he cuts and his pace; it is not a vote on the planner's choices (there were none).

def project_key(project_path: str) -> int:
    """A stable negative id for a project that is not a POST shoot (the same file always gets the same id)."""
    return -(zlib.crc32(os.path.normpath(project_path).encode("utf-8")) % 900_000_000 + 1)


def analyse_unplanned(shots: list[Any], moments: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """His cut on its own: the same rows and summary as `analyse`, with no plan to compare against (every shot 'not_in_plan'), plus each shot's media path so its
    footage can be found again for later study. With his project's clip descriptions (`moments`, made by learning/transfer_cut prepare) it also says whether his
    shots sit on Claude's described moments."""
    result = analyse({"shots": []}, shots, moments or {})
    result["warnings"] = [w for w in result["warnings"] if "saved plan" not in w]   # there is no plan, so "few of your clips are in the plan" means nothing
    for row, s in zip(result["his_shots"], shots):
        row["path"] = s.path
        if getattr(s, "src_fps", None):
            row["source_fps"] = s.src_fps
    result["summary"]["no_plan"] = True
    result["plan_basis"], result["plan_made_at"], result["stale_plan"], result["no_plan"] = "none", None, False, True
    return result


def lines_unplanned(project_path: str, sequence: str, result: dict[str, Any]) -> list[str]:
    s = result["summary"]
    out = [f"Read your edit \"{sequence}\" from {os.path.basename(project_path)}: {s['his_shots']} shots, {s['his_seconds']:.1f} s, from {s['his_clips']} clips.",
           "This project isn't one of P Corp OS's shoots, so there's no plan to compare with: your cut is saved as-is (which part of each clip you used, how long, "
           "how fast, in what order) for the learning data.",
           f"Your pace: median shot {s['median_shot_seconds']:.2f} s; {s['retimed_shots']} of {s['his_shots']} shots sped up or slowed down."]
    if s["described_shots_checked"]:
        out.append(f"Claude's described moments: {s['at_a_described_moment']} of your {s['described_shots_checked']} shots (on clips that were described) sit on one "
                   f"(about {s['chance_at_a_described_moment']:.0%} by chance), {s['at_the_first_choice_moment']} on its first choice (about {s['chance_at_the_first_choice']:.0%} by chance).")
    return out[:1] + result["warnings"] + out[1:]


def write_unplanned_log(project_path: str, sequence: str, result: dict[str, Any], source: str = "button") -> tuple[Path, int]:
    """The feedback record of an edit with no plan, plus its learning events in the central store (there is no job folder). The events are 'added' shots, never
    votes. Like _write_log, the event copy only goes to the real store when the log itself does."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    pid = project_key(project_path)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": pid, "shoot": Path(project_path).stem, "project_path": project_path, "sequence": sequence,
              "plan_style": None, "source": source, **result}
    path = FEEDBACK_DIR / f"project{-pid}_{stamp}.json"
    n = 1
    while path.exists():
        n += 1
        path = FEEDBACK_DIR / f"project{-pid}_{stamp}_{n}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1))
    os.replace(tmp, path)
    with open(FEEDBACK_DIR / "index.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": record["ts"], "job_id": pid, "sequence": sequence, "file": path.name, "source": source, "stale_plan": bool(result.get("stale_plan")),
                             "no_plan": bool(result.get("no_plan", True)), "learned_plan": bool(result.get("learned_plan")),
                             "project": os.path.basename(project_path), "summary": result["summary"]}) + "\n")
    if FEEDBACK_DIR == _REAL_FEEDBACK_DIR:
        from app import post_learning_events as le
        try:
            le.append_events(le.CENTRAL_EVENTS, le.from_learn_record(record))
        except Exception as exc:   # noqa: BLE001 -- the feedback log above is the record of truth
            le._log.warning("learning events for %s not recorded: %s", os.path.basename(project_path), exc)
    return path, aggregate()["edits"]


def read_finishing(project_path: str, sequence: str, plan: dict[str, Any] | None, fps: float, end_seconds: float) -> tuple[dict[str, Any] | None, list[str]]:
    """(record, report lines) of the finishing on his sequence -- flashes, zoom hits, shot effects, punch-ins, sounds, images, titles -- and, when the plan asked
    for finishing, how much of it is still where it was put (learning/transfer_finish). Never fails the Learn click: a problem becomes one line."""
    from learning import transfer_finish as tf
    try:
        f = tf.read_finish(project_path, sequence, end_seconds)
        found = tf.found_finish(f, fps)
        planned = tf.planned_finish(plan) if plan else None
        comparison = tf.compare_finish(planned, found) if planned and any(planned.values()) else None
        record = {"fps": fps, "found": {k: [list(x) for x in v] for k, v in found.items()}, "titles": len(f["titles"]), "layered_clips": len(f["layered_clips"]),
                  "vs_plan": comparison}
        return record, tf.finish_lines(found, f, comparison)
    except Exception as exc:   # noqa: BLE001 -- the picture cut is the record of truth; the finishing is extra
        return None, [f"Couldn't read the finishing ({exc}); the cut itself was read and saved."]


def _cut_end(shots: list[Any]) -> float:
    return max((s.t1 for s in shots), default=0.0) + 1e-3


def is_clip_list(shots: list[Any]) -> bool:
    """Mostly whole clips laid end to end (a stringout or selects reel), the same rule the auto-save watch uses: not a cut, and never logged as one."""
    from app.post_autosave import WHOLE_CLIP_SHARE
    shares = [(s.src_out - s.src_in) / s.src_duration for s in shots if s.src_duration]
    return bool(shares) and statistics.median(shares) >= WHOLE_CLIP_SHARE


async def learn_from_project(project_path: str, sequence_name: str | None = None) -> dict[str, Any]:
    """Learn From My Edit for a project that is not a POST shoot: reads the saved sequence, records his cut as-is, returns what the plugin prints.
    Raises NotACutYet (nothing written) when the sequence is his clips laid end to end."""
    from app.ssd_guard import on_drive
    sequence, shots = await on_drive(read_final_edit, project_path, sequence_name, timeout=120.0)
    if built_at(sequence) is not None:   # a sequence P Corp built ("... - Edit <time>"), never his own cut: compare it with the plan it was built from
        return await _learn_from_learned_build(project_path, sequence, shots)
    if is_clip_list(shots):
        raise NotACutYet(f"\"{sequence}\" is your clips laid end to end ({len(shots)} clips, each used whole), not a cut yet, so nothing was saved: a stringout would "
                         "teach the system the wrong thing.")
    from learning.transfer_cut import detect_fps, project_moments
    result = analyse_unplanned(shots, moments_by_clip_name(await on_drive(project_moments, project_path, timeout=30.0)))
    finishing, finish_report = await on_drive(read_finishing, project_path, sequence, None, detect_fps([s.t1 for s in shots]), _cut_end(shots), timeout=120.0)
    result["finishing"] = finishing
    log_path, edits = await on_drive(write_unplanned_log, project_path, sequence, result, timeout=30.0)
    report = lines_unplanned(project_path, sequence, result) + finish_report
    report.append(f"Saved to the feedback log ({edits} edit{'s' if edits != 1 else ''} logged so far).")
    return {"sequence": sequence, "summary": result["summary"], "warnings": result["warnings"], "lines": report, "logged_to": str(log_path), "project_id": project_key(project_path)}


async def _learn_from_learned_build(project_path: str, sequence: str, shots: list[Any]) -> dict[str, Any]:
    """His version of a sequence P Corp built in his own project from a LEARNED plan (learning/transfer_cut.py): what he kept, changed and dropped of it -- the
    score of the transfer test. Refused when there is no learned plan to compare with (a P Corp build is never logged as his cut)."""
    from app.ssd_guard import on_drive
    from learning.transfer_cut import load_project_plan, project_moments
    plan = await on_drive(load_project_plan, project_path)
    if plan is None:
        raise LearnError(f"\"{sequence}\" was built by P Corp OS, not cut by you, and there's no learned plan to compare it with, so nothing was saved.")
    made = time.mktime(time.strptime(plan["made_at"], "%Y-%m-%dT%H:%M:%S")) if plan.get("made_at") else None
    built = built_at(sequence)
    basis = "matched" if made is not None and built is not None and made <= built + PLAN_NEWER_GRACE_SECONDS else "newer"
    # 2026-10-23: this passed {} here, so his click on the HAUS build said none of his clips were described (all 117 are, in the project's workspace)
    result = compare_with_plan(sequence, shots, plan, basis, made, moments_by_clip_name(await on_drive(project_moments, project_path, timeout=30.0)))
    result["learned_plan"], result["no_plan"] = True, False
    finishing, finish_report = await on_drive(read_finishing, project_path, sequence, plan, plan["fps"], _cut_end(shots), timeout=120.0)
    result["finishing"] = finishing
    log_path, edits = await on_drive(write_unplanned_log, project_path, sequence, result, timeout=30.0)
    report = lines(sequence, plan.get("style"), result) + finish_report
    report.append(f"This sequence was built by P Corp OS from what it learned from \"{(plan.get('learned_from') or {}).get('cut', 'your cut')}\": the numbers above are how much "
                  "of it you kept. Saved to the feedback log.")
    return {"sequence": sequence, "summary": result["summary"], "warnings": result["warnings"], "lines": report, "logged_to": str(log_path),
            "project_id": project_key(project_path), "learned_plan": True}


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
    plan_rows = [r["summary"] for r in latest.values() if not r.get("stale_plan") and not r.get("no_plan") and not r.get("learned_plan")]   # learned transfers report themselves   # only edits compared with the plan they were built from say anything about the plan
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


def compare_with_plan(sequence: str, shots: list[Any], plan: dict[str, Any], basis: str, made_at: float | None, moments: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """analyse() plus what the plan basis means for how far to trust the comparison. `basis` is plan_history.plan_for_build_time's: "matched" = the plan the sequence was
    built from; anything else is only indicative, is flagged (stale_plan) and left out of the plan-agreement totals."""
    result = analyse(plan, shots, moments)
    result["plan_basis"] = basis
    result["plan_made_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(made_at)) if made_at else None
    if basis == "matched":
        result["stale_plan"] = False
    elif basis == "latest":
        result["stale_plan"] = True
        result["warnings"].insert(0, "This sequence has no build time in its name (it wasn't made by Assemble Edit), so it is compared with the current plan: indicative only.")
    else:
        warning = stale_plan_warning(sequence, made_at) if made_at else None
        result["stale_plan"] = True
        result["warnings"].insert(0, warning or "Every saved plan is newer than this sequence, so the plan it was built from is gone: indicative only.")
    return result


async def learn_from_edit(job: dict[str, Any], sequence_name: str | None = None, project_path: str | None = None) -> dict[str, Any]:
    """Reads his saved edit, compares it with the plan it was built from, logs the result, and returns {summary, lines, ...} for the plugin to print."""
    from app.post_edit_plan import edit_dir
    from app.post_moments import load_moments
    from app.post_plan_history import plan_for_build_time
    from app.ssd_guard import on_drive
    path = project_path or job.get("premiere_project_path")
    sequence, shots = await on_drive(read_final_edit, path, sequence_name, timeout=120.0)
    plan, _file, basis, made_at = await on_drive(plan_for_build_time, edit_dir(job), built_at(sequence))
    if plan is None:
        raise LearnError("This job has no saved edit plan to compare against. Plan the edit in P Corp OS first.")
    moments = moments_by_clip_name(await on_drive(load_moments, edit_dir(job)))
    result = compare_with_plan(sequence, shots, plan, basis, made_at, moments)
    finishing, finish_report = await on_drive(read_finishing, path, sequence, plan, plan["fps"], _cut_end(shots), timeout=120.0)
    result["finishing"] = finishing
    log_path, edits = await on_drive(_write_log, job, sequence, plan.get("style"), result, writing=True)   # also appends to the job's learning events, on the drive
    report = lines(sequence, plan.get("style"), result) + finish_report
    totals = aggregate()
    report.append(f"Saved to the feedback log ({edits} edit{'s' if edits != 1 else ''} logged so far, {totals['shots']} shots).")
    return {"sequence": sequence, "summary": result["summary"], "warnings": result["warnings"], "lines": report, "logged_to": str(log_path), "all_edits": totals}
