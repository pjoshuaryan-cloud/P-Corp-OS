"""
POST (2026-09-25, Phase 1-2) -- read-only Frank chat tools only, zero
side effects, so no approval-gating machinery is needed for any of them.

Deliberately NOT building "Frank, prep this shoot" (the full spec's own
section 18) yet -- that's real Phase 7 scope for two independent
reasons: an LLM tool call must never directly kick off a real
multi-hour, multi-GB copy, and job creation fundamentally needs a live
drive listing Frank's chat model has no way to reason about without the
desktop UI having already scanned sources first. Same reasoning applies
to Phase 2's media analysis -- Frank can report on a report already
run, never trigger one itself.
"""

from typing import Any

from app.post_db import get_post_job_progress, list_post_jobs
from app.post_media import compute_media_report

LIST_POST_JOBS_TOOL = {
    "name": "list_post_jobs",
    "description": (
        "List POST (video post-production prep) jobs -- footage ingestion/verification jobs Josh has created "
        "on his Mac. Read-only. Optionally filter by status."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Optional status filter, e.g. \"ingesting\", \"ingested\", \"ingest_failed\".",
            },
        },
    },
}

GET_POST_JOB_STATUS_TOOL = {
    "name": "get_post_job_status",
    "description": "Get the current status and progress (files copied/failed, bytes copied, estimated time remaining) for one POST job by id. Read-only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "integer", "description": "The POST job's id."},
        },
        "required": ["job_id"],
    },
}

GET_POST_MEDIA_REPORT_TOOL = {
    "name": "get_post_media_report",
    "description": (
        "Get the media intelligence report (Phase 2) for one POST job -- cameras detected, resolutions, "
        "frame rates, vertical/horizontal split, potential duplicate files, corrupt/unreadable files, slow-motion "
        "candidates. Read-only. Only available once media analysis has actually run for that job."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "integer", "description": "The POST job's id."},
        },
        "required": ["job_id"],
    },
}

POST_TOOLS = [LIST_POST_JOBS_TOOL, GET_POST_JOB_STATUS_TOOL, GET_POST_MEDIA_REPORT_TOOL]
POST_TOOL_NAMES = {tool["name"] for tool in POST_TOOLS}


async def execute_post_tool_call(name: str, tool_input: dict, postgres_conn: Any = None) -> str:
    if name == "list_post_jobs":
        jobs = await list_post_jobs(tool_input.get("status"), postgres_conn)
        if not jobs:
            return "No POST jobs found."
        lines = [
            f"#{j['id']} {j['shoot_name']} ({j['profile']}) -- {j['status']}, "
            f"{j['files_copied']}/{j['total_files']} files copied"
            for j in jobs
        ]
        return "\n".join(lines)
    if name == "get_post_job_status":
        job = await get_post_job_progress(tool_input["job_id"], postgres_conn)
        if job is None:
            return f"No POST job with id {tool_input['job_id']}."
        eta = job.get("estimated_remaining_seconds")
        eta_text = f", ~{int(eta // 60)}m remaining" if eta else ""
        return (
            f"#{job['id']} {job['shoot_name']} ({job['profile']}) -- status {job['status']}. "
            f"{job['files_copied']}/{job['total_files']} files copied, {job['files_failed']} failed, "
            f"{job['bytes_copied']}/{job['total_bytes']} bytes{eta_text}."
            + (f" Error: {job['error_message']}" if job.get("error_message") else "")
        )
    if name == "get_post_media_report":
        job = await get_post_job_progress(tool_input["job_id"], postgres_conn)
        if job is None:
            return f"No POST job with id {tool_input['job_id']}."
        if not job.get("media_analyzed_at"):
            return f"Job #{job['id']} ({job['shoot_name']}) hasn't had media analysis run yet."
        report = await compute_media_report(tool_input["job_id"], postgres_conn)
        lines = [f"Media report for #{job['id']} {job['shoot_name']} -- {report['total_files']} file(s):"]
        if report["media_type_counts"]:
            lines.append("Types: " + ", ".join(f"{k}={v}" for k, v in report["media_type_counts"].items()))
        if report["cameras"]:
            lines.append("Cameras: " + ", ".join(
                f"{c['make'] or 'Unknown'} {c['model'] or ''}".strip() + f" ({c['count']})" for c in report["cameras"]
            ))
        lines.append(f"Vertical: {report['vertical_count']}, Horizontal: {report['horizontal_count']}")
        if report["slow_motion_files"]:
            lines.append(f"Potential slow-motion: {len(report['slow_motion_files'])} file(s)")
        if report["duplicate_groups"]:
            lines.append(f"Potential duplicate groups: {len(report['duplicate_groups'])}")
        if report["corrupt_files"]:
            lines.append(f"Corrupt/unreadable files: {len(report['corrupt_files'])}")
        return "\n".join(lines)
    return f"Unknown POST tool: {name}"
