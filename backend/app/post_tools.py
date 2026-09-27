"""
POST (2026-09-25, Phases 1-2; extended 2026-09-27, Phase 7) -- Frank
chat tools. The first 3 (list_post_jobs, get_post_job_status,
get_post_media_report) are read-only, zero side effects. Phase 7 adds
"Frank, prep this shoot" -- but a real, hard safety constraint from
Phase 1 still holds and is NOT relaxed here: an LLM tool call must
never directly kick off a real multi-hour, multi-GB copy, and job
creation fundamentally needs a live drive listing Frank's chat model
has no way to see without the desktop UI having already scanned
sources first. Confirmed directly with Josh: Phase 7 stays at
"guidance + safe triggers on existing jobs" -- Frank can tell Josh
exactly where a shoot stands (get_post_job_status's own text, extended
below) and can trigger Analyze Media / Generate Proxies on an
already-ingested job when explicitly asked (both bounded,
already-explicit-gate actions with no drive picker involved, sharing
the exact same guarded functions the REST routes use -- see
post_media.py's trigger_media_analysis/trigger_proxy_generation).
Creating a job or starting ingestion remain structurally unreachable
from chat: no tool exists for either, the same "narrow tool surface no
conversation can reach around" pattern Ventures' own agent isolation
uses to satisfy the original spec's "no unrestricted write
permissions" boundary.
"""

from typing import Any

from app.post_db import get_post_job_progress, list_post_jobs
from app.post_media import compute_media_report, compute_proxy_recommendations, trigger_media_analysis, trigger_proxy_generation

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

ANALYZE_POST_JOB_MEDIA_TOOL = {
    "name": "analyze_post_job_media",
    "description": (
        "Runs media analysis (camera detection, resolution/frame-rate categorization, exposure/color flags) "
        "on an already fully-ingested POST job. Safe to re-run. The job must be 'ingested' first -- this cannot "
        "start ingestion itself. The actual analysis runs in the background; check back with get_post_job_status."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "integer", "description": "The POST job's id."},
        },
        "required": ["job_id"],
    },
}

GENERATE_POST_JOB_PROXIES_TOOL = {
    "name": "generate_post_job_proxies",
    "description": (
        "Generates edit proxies for files in a POST job that would benefit from them (very high resolution/"
        "bitrate/RAW footage). Media analysis must have already run (use analyze_post_job_media first if not). "
        "Safe to re-run. The actual transcoding runs in the background; check back with get_post_job_status."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "integer", "description": "The POST job's id."},
        },
        "required": ["job_id"],
    },
}

POST_TOOLS = [
    LIST_POST_JOBS_TOOL, GET_POST_JOB_STATUS_TOOL, GET_POST_MEDIA_REPORT_TOOL,
    ANALYZE_POST_JOB_MEDIA_TOOL, GENERATE_POST_JOB_PROXIES_TOOL,
]
POST_TOOL_NAMES = {tool["name"] for tool in POST_TOOLS}


async def _describe_next_step(job: dict, postgres_conn: Any = None) -> str:
    """Deterministic 'what's next' guidance from the job's own already-
    known state -- no LLM judgment call, same discipline as every other
    POST report in this app. This is what makes 'Frank, prep this shoot'
    actually useful without ever needing Frank to guess."""
    status = job["status"]
    if status == "created":
        return "start ingestion from the desktop POST screen (I can't see live connected drives, so this has to be a manual step)."
    if status in ("scanning", "ingesting", "verifying"):
        return "ingestion is in progress -- check back shortly."
    if status == "analyzing_media":
        return "media analysis is in progress -- check back shortly."
    if status == "generating_proxies":
        return "proxy generation is in progress -- check back shortly."
    if status == "ingest_failed":
        return "ingestion failed -- click Start/Retry in the desktop app, or ask me to check the error."
    if status == "cancelled":
        return "ingestion was cancelled -- click Start/Retry in the desktop app when ready."
    if status == "ingested":
        if not job.get("media_analyzed_at"):
            return "run Analyze Media next (ask me to do this, or click it in the desktop app)."
        # compute_proxy_recommendations is a pure eligibility check (from
        # real width/bitrate/codec) -- it has no idea whether a proxy
        # was already generated, so that has to be checked separately
        # via the job's own completion marker, or this would keep
        # suggesting "generate proxies" forever even after they're done.
        if not job.get("proxies_generated_at"):
            recommendations = await compute_proxy_recommendations(job["id"], postgres_conn=postgres_conn)
            if recommendations:
                return f"{len(recommendations)} file(s) would benefit from proxies (ask me to generate them), or it's already ready to \"Prepare POST Project\" in the Premiere plugin."
        return "ready -- open the Premiere plugin and click \"Prepare POST Project\"."
    if status == "premiere_project_created":
        return f"the Premiere project already exists at {job.get('premiere_project_path') or 'its stored path'} -- if this shoot has dialogue, open the plugin and click \"Transcribe Dialogue\"."
    return "nothing further needed."


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
        next_step = await _describe_next_step(job, postgres_conn)
        return (
            f"#{job['id']} {job['shoot_name']} ({job['profile']}) -- status {job['status']}. "
            f"{job['files_copied']}/{job['total_files']} files copied, {job['files_failed']} failed, "
            f"{job['bytes_copied']}/{job['total_bytes']} bytes{eta_text}."
            + (f" Error: {job['error_message']}" if job.get("error_message") else "")
            + f" Next: {next_step}"
        )
    if name == "analyze_post_job_media":
        _, message = await trigger_media_analysis(tool_input["job_id"], postgres_conn)
        return message
    if name == "generate_post_job_proxies":
        _, message, _ = await trigger_proxy_generation(tool_input["job_id"], postgres_conn)
        return message
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
