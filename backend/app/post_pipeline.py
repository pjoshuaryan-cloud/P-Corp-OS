"""
POST (2026-10-20) -- one plain-language picture of where a shoot is, from the moment it is started to the moment it is ready to edit.

Why: the shoot screen showed a different status line and button for every step (copy, check, analyse...), and "is it done yet?" had no single answer. This turns
a job's own fields into ONE description -- four stages (read the drive, copy, check the copies, analyse), one overall percentage, one sentence -- computed on the
server so the desktop and the phone always show the same thing. It only DESCRIBES: it changes nothing about how a job runs.

Honest by construction: a stage shows a count ("40 of 342") only where the job really has one, a time estimate only for the copy (the one stage whose speed is
measured as it goes), and the percentage counts only finished stages plus real progress inside the active one -- nothing is guessed to make a bar look smooth.
"""
from __future__ import annotations

import subprocess
from typing import Any

# (done, total) files analysed so far, per job id, kept in memory by post_media.run_media_analysis while it runs. A restart forgets it (the analysis simply starts
# again from the job's status), which only costs the live count.
ANALYSIS_PROGRESS: dict[int, tuple[int, int]] = {}

STAGES = (("scan", "Read the drive"), ("copy", "Copy the files"), ("verify", "Check the copies"), ("analyse", "Analyse the clips"))
WEIGHTS = {"scan": 3, "copy": 47, "verify": 35, "analyse": 15}   # roughly where the time goes on a real shoot; only used for the single overall percentage
_STATUS_STAGE = {"scanning": "scan", "ready": "copy", "ingesting": "copy", "verifying": "verify", "analyzing_media": "analyse"}
_AFTER_INGEST = ("ingested", "generating_proxies", "analyzing_color", "premiere_project_created", "complete", "archived")


def _minutes(seconds: float) -> str:
    m = seconds / 60.0
    if m < 1.5:
        return "about a minute"
    if m < 90:
        return f"about {round(m)} min"
    hours, minutes = int(m // 60), int(round((m % 60) / 5.0) * 5)
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return f"about {hours} h" + (f" {minutes:02d} min" if minutes else "")


def describe_pipeline(job: dict[str, Any], files_verified: int | None = None, analysis: tuple[int, int] | None = None) -> dict[str, Any]:
    """{"stages": [{key, label, state: done|active|pending|failed, detail}], "percent": 0-100, "headline": str, "eta_seconds": float|None, "needs_attention": bool}."""
    status = job["status"]
    total_files = int(job.get("total_files") or 0)
    total_bytes = int(job.get("total_bytes") or 0)
    copied_files = int(job.get("files_copied") or 0)
    copied_bytes = int(job.get("bytes_copied") or 0)
    analysed_done = bool(job.get("media_analyzed_at"))
    keys = [k for k, _ in STAGES]
    detail = {k: "" for k in keys}
    eta = None
    failed_stage = None

    if status in _STATUS_STAGE:
        active = _STATUS_STAGE[status]
    elif status in _AFTER_INGEST:
        active = None            # copy and check are finished; analysis is finished or waiting for a click
    else:
        active = None            # created / cancelled / ingest_failed: nothing is running
    stopped = status in ("ingest_failed", "cancelled")
    if status == "ingest_failed":
        if total_files == 0:
            failed_stage = "scan"
        elif copied_bytes < total_bytes or copied_files < total_files:
            failed_stage = "copy"
        else:
            failed_stage = "verify"

    done_stages: set[str] = set()
    if status in _AFTER_INGEST:
        done_stages |= {"scan", "copy", "verify"} | ({"analyse"} if analysed_done else set())
    elif active:
        done_stages |= set(keys[: keys.index(active)])
    elif stopped and failed_stage:
        done_stages |= set(keys[: keys.index(failed_stage)])

    fraction = 0.0
    if active == "copy":
        fraction = (copied_bytes / total_bytes) if total_bytes else 0.0
        detail["copy"] = f"{copied_files} of {total_files} files" if total_files else "starting"
        eta = job.get("estimated_remaining_seconds")
    elif active == "verify":
        if files_verified is not None and total_files:
            fraction = files_verified / total_files
            detail["verify"] = f"{files_verified} of {total_files} files"
    elif active == "analyse":
        if analysis and analysis[1]:
            fraction = analysis[0] / analysis[1]
            detail["analyse"] = f"{analysis[0]} of {analysis[1]} clips"
    elif active == "scan":
        detail["scan"] = "setting up the project folders"
    for k in done_stages:
        detail[k] = detail[k] or "done"

    stages = []
    for k, label in STAGES:
        if k == failed_stage:
            state = "failed"
        elif k in done_stages:
            state = "done"
        elif k == active:
            state = "active"
        else:
            state = "pending"
        stages.append({"key": k, "label": label, "state": state, "detail": detail[k]})

    all_done = status in _AFTER_INGEST and analysed_done
    percent = 100 if all_done else int(sum(WEIGHTS[k] for k in done_stages) + (WEIGHTS[active] * fraction if active else 0))
    percent = min(percent, 99) if not all_done else 100

    needs_attention = status == "ingest_failed"
    if status == "created":
        headline = "Not started yet. Press Start."
    elif status == "scanning":
        headline = "Reading the drive and setting up the project folders…"
    elif status in ("ready", "ingesting"):
        headline = f"Copying the files: {copied_files} of {total_files}" + (f", {_minutes(eta)} left" if eta else "")
    elif status == "verifying":
        headline = "Checking every copy against the original" + (f": {files_verified} of {total_files}" if files_verified is not None and total_files else "…")
    elif status == "analyzing_media":
        headline = "Analysing the clips" + (f": {analysis[0]} of {analysis[1]}" if analysis and analysis[1] else "…")
    elif all_done:
        headline = f"Ready: {total_files} files copied, checked and analysed."
    elif status in _AFTER_INGEST:
        headline = f"Copied and checked ({total_files} files). The clips haven't been analysed yet: press Analyze Media."
    elif status == "cancelled":
        headline = "Cancelled."
    elif status == "ingest_failed":
        headline = "Stopped: " + (job.get("error_message") or "something went wrong. Press Retry.")
    else:
        headline = status.replace("_", " ").capitalize()
    return {"stages": stages, "percent": percent, "headline": headline, "eta_seconds": eta, "needs_attention": needs_attention,
            "plan_edit_blocker": plan_edit_blocker(status, analysed_done)}


def plan_edit_blocker(status: str, analysed: bool) -> str | None:
    """Why Plan Edit can't be pressed yet, in a sentence that says what to do (None = it can). The shoot card greys the button and shows this under it instead of
    hiding the button and leaving you to guess."""
    if status in _AFTER_INGEST and analysed:
        if status == "generating_proxies":
            return "Plan Edit unlocks when the proxies finish."
        if status == "analyzing_color":
            return "Plan Edit unlocks when highlight detection finishes."
        return None
    if status == "created":
        return "Press Start first. Plan Edit unlocks once the shoot is copied, checked and analysed."
    if status in ("scanning", "ready", "ingesting", "verifying", "analyzing_media"):
        return "Plan Edit unlocks once the shoot has been copied, checked and analysed."
    if status == "ingest_failed":
        return "The copy stopped (see above). Press Retry; Plan Edit unlocks once the shoot is copied and analysed."
    if status == "cancelled":
        return "This shoot was cancelled. Press Retry to carry on with it."
    if status in _AFTER_INGEST:   # copied and checked, never analysed
        return "Press Analyze Media first: the plan needs to know what each clip is."
    return "Plan Edit isn't available for this shoot yet."


def notify(title: str, body: str) -> None:
    """A macOS notification (same channel as the daily digest: osascript from the backend's own GUI-session launchd job). Never raises: a missed pop-up must not
    fail a job that otherwise succeeded."""
    try:
        from app.digest_notification import send_digest_notification
        send_digest_notification(title, body)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[post_pipeline] couldn't show the notification {title!r}: {exc!r}")
