"""
POST (2026-09-25, Phase 1) -- the ingestion worker. One job at a time,
end to end (scan -> copy -> verify), run directly from
_post_ingest_loop's own while loop -- never spawned as a separate
asyncio.Task, matching _trade_proposal_sync_loop's own documented "one
proposal in flight at a time, by construction" discipline and the
physical reality that two simultaneous multi-GB copies just contend
for the same disk/bus bandwidth anyway.

Chunked asyncio.to_thread, not one to_thread call per whole file and
not a separate worker process: a multi-hour, multi-GB copy done as a
single blocking call would freeze the ENTIRE app (Frank's live chat
WebSocket, every other division's routes) for its whole duration, since
this all runs on one shared asyncio event loop. Wrapping only the
per-chunk read()/write() calls in asyncio.to_thread yields control back
to the event loop between every chunk (CHUNK_SIZE below), frequently
enough that everything else stays responsive. A separate OS worker
process would be a genuine first for this codebase (no multiprocessing/
queue infrastructure exists anywhere) and isn't justified for a
single-user, one-job-at-a-time feature.

Two-pass model (confirmed with Josh): copy every file first (status
'ingesting'), then re-read and re-hash every file as a second pass
(status 'verifying') -- matches the mental model of professional
ingest tools (ShotPut Pro, Hedge) rather than interleaving copy+verify
per file.

File-level resume (confirmed with Josh): a file interrupted mid-copy
restarts from zero on resume, via `list_pending_post_job_files`'s own
`verified_at IS NULL` query -- not true byte-range resume.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from app.post_db import (
    create_post_job_files_batch,
    get_post_job,
    list_pending_post_job_files,
    list_post_job_files,
    list_post_jobs,
    mark_post_job_file_copied,
    mark_post_job_file_copying,
    mark_post_job_file_failed,
    mark_post_job_file_verified,
    record_post_job_scan_result,
    update_post_job_progress,
    update_post_job_status,
)
from app.post_media import run_media_analysis, run_proxy_generation
from app.post_profiles import build_project_structure, compute_destination_root
from app.post_sources import scan_source_tree

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB -- frequent enough event-loop yields without excessive syscall overhead
POST_INGEST_POLL_INTERVAL_SECONDS = 5
PROGRESS_UPDATE_EVERY_BYTES = 32 * 1024 * 1024  # avoid a DB write on every single 8MB chunk


async def _hash_and_copy_file(source_path: str, destination_path: str, on_progress) -> str:
    """Copies source_path to destination_path in CHUNK_SIZE pieces,
    hashing as it goes, yielding to the event loop between every chunk.
    Returns the source's SHA-256 hex digest. Raises on any I/O failure
    -- the caller marks the file failed and moves on rather than
    crashing the whole job."""
    hasher = hashlib.sha256()
    Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
    bytes_since_last_update = 0
    with open(source_path, "rb") as fsrc, open(destination_path, "wb") as fdst:
        while True:
            chunk = await asyncio.to_thread(fsrc.read, CHUNK_SIZE)
            if not chunk:
                break
            await asyncio.to_thread(fdst.write, chunk)
            hasher.update(chunk)
            bytes_since_last_update += len(chunk)
            if bytes_since_last_update >= PROGRESS_UPDATE_EVERY_BYTES:
                await on_progress(len(chunk) + (bytes_since_last_update - len(chunk)))
                bytes_since_last_update = 0
        if bytes_since_last_update:
            await on_progress(bytes_since_last_update)
    return hasher.hexdigest()


async def _hash_file(path: str) -> str:
    """Same chunked/yielding discipline as the copy above, used for the
    verify pass's re-read of the destination file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = await asyncio.to_thread(f.read, CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


async def run_ingest_job(job: dict, postgres_conn: Any = None) -> None:
    """One job, start to finish, or resumed from wherever it left off.
    Each stage is gated on the job's OWN current status so a resume
    (e.g. after a crash during the verify pass) re-enters at the right
    phase rather than always redoing copy -- a job already in
    'verifying' has nothing left to copy, only to re-check."""
    job_id = job["id"]

    if job["status"] in ("created", "ready", "scanning"):
        await _run_scan_phase(job, postgres_conn)
        job = await _reload(job_id, postgres_conn)
        if job is None or job["status"] != "ready":
            return  # scan failed or job was deleted/cancelled mid-scan

    if job["status"] in ("ready", "ingest_failed", "cancelled"):
        await update_post_job_status(job_id, "ingesting", from_statuses=("ready", "ingest_failed", "cancelled"), postgres_conn=postgres_conn)
        job = await _reload(job_id, postgres_conn)

    if job is not None and job["status"] == "ingesting":
        await _run_copy_phase(job_id, postgres_conn)
        job = await _reload(job_id, postgres_conn)
        if job is None or job["status"] != "ingesting":
            return  # cancelled mid-copy
        await update_post_job_status(job_id, "verifying", from_statuses=("ingesting",), postgres_conn=postgres_conn)
        job = await _reload(job_id, postgres_conn)

    if job is not None and job["status"] == "verifying":
        await _run_verify_phase(job_id, postgres_conn)

    # Phase 2 -- deliberately NOT chained onto the scan/ingest/verify
    # sequence above (confirmed with Josh: media analysis is its own
    # manual "Analyze Media" step, not an automatic continuation of
    # ingestion) -- this block only ever fires when a job's status is
    # already 'analyzing_media', which only POST /post/jobs/{id}/analyze-media
    # sets, never a side effect of finishing ingestion.
    if job is not None and job["status"] == "analyzing_media":
        await run_media_analysis(job_id, postgres_conn)
        await update_post_job_status(job_id, "ingested", from_statuses=("analyzing_media",), postgres_conn=postgres_conn)

    # Phase 4 -- same "explicit manual gate, never a silent auto-
    # continuation" discipline as Phase 2's analyzing_media block above.
    # Only ever fires when POST /post/jobs/{id}/generate-proxies has
    # already set this status.
    if job is not None and job["status"] == "generating_proxies":
        await run_proxy_generation(job_id, postgres_conn)
        await update_post_job_status(job_id, "ingested", from_statuses=("generating_proxies",), postgres_conn=postgres_conn)


async def _reload(job_id: int, postgres_conn: Any):
    return await get_post_job(job_id, postgres_conn)


async def _run_scan_phase(job: dict, postgres_conn: Any) -> None:
    """Idempotent -- a job resumed after a crash mid-scan (status still
    'scanning') must never re-enumerate and re-insert file rows a prior
    attempt already created, or every file ends up duplicated. Checking
    for existing rows first is the same 'never redo completed work on
    resume' discipline as the copy/verify phases' own verified_at/
    destination_checksum guards."""
    job_id = job["id"]
    await update_post_job_status(job_id, "scanning", from_statuses=("created", "ready", "scanning"), postgres_conn=postgres_conn)
    existing_files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    if existing_files:
        await update_post_job_status(job_id, "ready", from_statuses=("scanning",), postgres_conn=postgres_conn)
        return
    try:
        destination_root = Path(job["destination_root"])
        await asyncio.to_thread(build_project_structure, job["profile"], destination_root)
        total_files, total_bytes, files = await asyncio.to_thread(scan_source_tree, job["source_path"])
        if total_files == 0:
            await update_post_job_status(
                job_id, "ingest_failed", error_message="No files found under the selected source.", postgres_conn=postgres_conn
            )
            return
        # Everything lands under a single OTHER-equivalent staging area within
        # the destination root for Phase 1 -- Phase 2's media analysis is what
        # actually sorts footage into the profile's camera-labeled subfolders
        # by real metadata; guessing from filename alone here would be the
        # kind of "destructive organization based on assumptions" the spec
        # explicitly warns against.
        staging_root = destination_root / "_INGESTED"
        batch = [(rel, str(staging_root / rel), size) for rel, _abs, size in files]
        await create_post_job_files_batch(job_id, batch, postgres_conn=postgres_conn)
        await record_post_job_scan_result(job_id, total_files, total_bytes, postgres_conn=postgres_conn)
        await update_post_job_status(job_id, "ready", from_statuses=("scanning",), postgres_conn=postgres_conn)
    except OSError as exc:
        await update_post_job_status(job_id, "ingest_failed", error_message=f"Scan failed: {exc}", postgres_conn=postgres_conn)


async def _run_copy_phase(job_id: int, postgres_conn: Any) -> None:
    job = await _reload(job_id, postgres_conn)
    source_root = Path(job["source_path"])
    files_copied = job["files_copied"]
    files_failed = job["files_failed"]
    bytes_copied = job["bytes_copied"]

    async def on_progress(delta_bytes: int) -> None:
        nonlocal bytes_copied
        bytes_copied += delta_bytes
        await update_post_job_progress(job_id, bytes_copied, files_copied, files_failed, str(file_row["relative_path"]), postgres_conn=postgres_conn)

    for file_row in await list_pending_post_job_files(job_id, postgres_conn=postgres_conn):
        current = await _reload(job_id, postgres_conn)
        if current is None or current["status"] != "ingesting":
            return  # cancelled
        if file_row["status"] == "verified":
            continue  # belt-and-suspenders; the query already excludes these
        source_path = source_root / file_row["relative_path"]
        await mark_post_job_file_copying(file_row["id"], postgres_conn=postgres_conn)
        try:
            checksum = await _hash_and_copy_file(str(source_path), file_row["destination_path"], on_progress)
            await mark_post_job_file_copied(file_row["id"], checksum, postgres_conn=postgres_conn)
            files_copied += 1
        except OSError as exc:
            await mark_post_job_file_failed(file_row["id"], str(exc), postgres_conn=postgres_conn)
            files_failed += 1
        await update_post_job_progress(job_id, bytes_copied, files_copied, files_failed, file_row["relative_path"], postgres_conn=postgres_conn)


async def _run_verify_phase(job_id: int, postgres_conn: Any) -> None:
    """Re-reads and re-hashes every copied-but-not-yet-verified
    destination file, comparing against the checksum recorded during
    copy. list_pending_post_job_files already excludes verified files,
    so a resumed verify pass only re-checks what's left.

    Keeps the job row's own files_failed/files_copied/bytes_copied
    counters in sync as verification finds problems -- these started as
    copy-phase totals and must stay accurate here too, since the poll
    response the UI reads its progress from comes from this same row,
    not from re-deriving counts off the file table on every request."""
    job = await _reload(job_id, postgres_conn)
    files_copied, bytes_copied, files_failed = job["files_copied"], job["bytes_copied"], job["files_failed"]
    for file_row in await list_pending_post_job_files(job_id, postgres_conn=postgres_conn):
        current = await _reload(job_id, postgres_conn)
        if current is None or current["status"] != "verifying":
            return  # cancelled
        if file_row["status"] != "copied" or not file_row["source_checksum"]:
            continue  # never successfully copied -- stays failed, nothing to verify
        try:
            destination_checksum = await _hash_file(file_row["destination_path"])
        except OSError as exc:
            await mark_post_job_file_failed(file_row["id"], f"Verify read failed: {exc}", postgres_conn=postgres_conn)
            files_failed += 1
            files_copied -= 1
            await update_post_job_progress(job_id, bytes_copied, files_copied, files_failed, file_row["relative_path"], postgres_conn=postgres_conn)
            continue
        if destination_checksum != file_row["source_checksum"]:
            await mark_post_job_file_failed(
                file_row["id"], "Checksum mismatch after copy -- destination file is corrupted.", postgres_conn=postgres_conn
            )
            files_failed += 1
            files_copied -= 1
            await update_post_job_progress(job_id, bytes_copied, files_copied, files_failed, file_row["relative_path"], postgres_conn=postgres_conn)
            continue
        await mark_post_job_file_verified(file_row["id"], destination_checksum, postgres_conn=postgres_conn)

    all_files = await list_post_job_files(job_id, postgres_conn=postgres_conn)
    total_failed = sum(1 for f in all_files if f["status"] == "failed")
    if total_failed:
        await update_post_job_status(
            job_id, "ingest_failed", from_statuses=("verifying",),
            error_message=f"{total_failed} file(s) failed to copy or verify.", postgres_conn=postgres_conn,
        )
    else:
        await update_post_job_status(job_id, "ingested", from_statuses=("verifying",), postgres_conn=postgres_conn)


async def _next_post_job_to_process(postgres_conn: Any) -> dict | None:
    """Deliberately excludes 'created' -- a freshly-created job sits
    inert until the user explicitly calls POST /post/jobs/{id}/start
    (matching the spec's own NEW SHOOT -> review -> PREPARE SHOOT flow,
    not an auto-start on creation). 'ready' IS included so a job that
    just finished scanning gets picked back up on the very next poll
    with no separate manual step -- Phase 1's "PREPARE SHOOT" is meant
    to feel like one continuous action once started, not a
    scan-then-wait-then-copy multi-click flow. 'analyzing_media'
    (Phase 2) and 'generating_proxies' (Phase 4) are included the same
    way -- their own POST routes set them, and this loop is what
    actually does the work."""
    for status in ("scanning", "ready", "ingesting", "verifying", "analyzing_media", "generating_proxies"):
        jobs = await list_post_jobs(status=status, postgres_conn=postgres_conn)
        if jobs:
            return jobs[-1]  # oldest first (list_post_jobs orders DESC by created_at)
    return None


async def _post_ingest_loop(app) -> None:
    from app.main import _pooled_postgres_conn  # local import -- avoids a circular import at module load time

    while True:
        try:
            async with _pooled_postgres_conn() as postgres_conn:
                job = await _next_post_job_to_process(postgres_conn)
                if job is not None:
                    await run_ingest_job(job, postgres_conn)
        except Exception as exc:
            print(f"[post_ingest] loop iteration failed: {exc!r}")
        await asyncio.sleep(POST_INGEST_POLL_INTERVAL_SECONDS)
