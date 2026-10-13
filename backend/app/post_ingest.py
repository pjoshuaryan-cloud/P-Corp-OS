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
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from app.post_db import (
    apply_post_job_ingest_batch,
    create_post_job_files_batch,
    get_post_job,
    list_pending_post_job_files,
    list_post_job_files,
    list_post_jobs,
    record_post_job_scan_result,
    update_post_job_status,
)
from app.post_media import run_highlight_detection, run_media_analysis, run_proxy_generation
from app.post_profiles import build_project_structure, compute_destination_root
from app.post_sources import scan_source_tree

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB -- frequent enough event-loop yields without excessive syscall overhead
POST_INGEST_POLL_INTERVAL_SECONDS = 5
PROGRESS_UPDATE_EVERY_BYTES = 32 * 1024 * 1024  # granularity of the in-memory byte counter; DB writes are throttled separately below
FLUSH_INTERVAL_SECONDS = 3.0
MAX_CONSECUTIVE_FLUSH_FAILURES = 5  # ~15s+ of failing DB writes -> stop copying rather than copy for hours with nothing persisted
FINAL_FLUSH_ATTEMPTS = 3
FINAL_FLUSH_RETRY_SECONDS = 1.0

# Free-space pre-flight (2026-10-06): a job that can't fit used to copy until
# the drive filled up and then die halfway, leaving a full drive. Now it fails
# before the first byte is copied.
FREE_SPACE_RESERVE_BYTES = 1_000_000_000  # headroom that must remain free after the job (adjustable)
MIN_ASSUMED_ALLOCATION_UNIT = 4096
# macOS reports a 1MiB "fragment size" for exFAT, which is the preferred I/O size
# rather than the real cluster (typically 128KiB on large drives); using it per
# file would wildly overcount jobs with many small files, so cap it.
MAX_ASSUMED_ALLOCATION_UNIT = 128 * 1024
_SPACE_NEEDING_STATUSES = ("pending", "copying", "failed")  # 'copied' files already occupy the destination


def _human_bytes(n: float) -> str:
    """Decimal units, matching what Finder shows."""
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def estimate_space_needed(sizes: Iterable[int], allocation_unit: int) -> int:
    """Bytes the destination will actually consume: each file rounds up to a
    whole allocation unit."""
    unit = max(allocation_unit, 1)
    return sum(-(-size // unit) * unit for size in sizes)


def check_destination_space(destination_root: str, pending_files: list[dict]) -> str | None:
    """Returns a user-facing explanation if the destination drive can't hold
    the files still to be copied (plus FREE_SPACE_RESERVE_BYTES of headroom),
    or None if there's room. Synchronous -- callers run it in a thread.

    Fails OPEN if free space can't be measured (an exotic volume, a drive
    that just vanished): this is a safety net, not a gate, and a vanished
    drive makes every file copy fail loudly on its own anyway."""
    anchor = Path(destination_root)
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    try:
        free = shutil.disk_usage(anchor).free
        unit = os.statvfs(anchor).f_frsize or MIN_ASSUMED_ALLOCATION_UNIT
    except OSError as exc:
        print(f"[post_ingest] couldn't read free space for {anchor}: {exc!r} -- skipping the free-space check")
        return None
    unit = min(max(unit, MIN_ASSUMED_ALLOCATION_UNIT), MAX_ASSUMED_ALLOCATION_UNIT)
    needed = estimate_space_needed(
        (f["size_bytes"] for f in pending_files if f["status"] in _SPACE_NEEDING_STATUSES), unit
    )
    if needed + FREE_SPACE_RESERVE_BYTES <= free:
        return None
    return (
        f"Not enough space on the destination drive: this job still needs about {_human_bytes(needed)} "
        f"(plus {_human_bytes(FREE_SPACE_RESERVE_BYTES)} of headroom) but only {_human_bytes(free)} is free. "
        f"Free up space on that drive, or delete this job and create it again with a different destination, "
        f"then press Retry."
    )


class _IngestWriteBehind:
    """Keeps database writes off the copy/verify hot path (2026-10-06).

    The copy loop used to await a DB write for every file's status marks
    and for every 32MB of progress. Against the cloud Postgres each await
    costs 1-2 network round trips (~0.34s each from Josh's Mac), so a 48GB
    job spent ~6s of every ~178MB file waiting on the database vs ~0.4s
    actually copying -- ~16 MB/s on an SSD that reads ~980 MB/s. Now the
    loop only updates this in-memory buffer; one background task flushes
    it to the DB every FLUSH_INTERVAL_SECONDS in a single batched
    transaction (apply_post_job_ingest_batch) and refreshes `cancelled`
    from the job row at the same time, so the loop never touches the
    connection itself.

    Crash safety is unchanged: marks that hadn't been flushed when the
    process died are simply absent from the DB, so on resume those files
    look unfinished and are redone (re-copied / re-verified) -- the same
    "an unfinished file restarts from zero" rule that already applied.
    close() is a barrier: it performs a final flush so the DB is fully up
    to date before a phase hands over to the next one."""

    def __init__(self, job_id: int, expected_status: str, postgres_conn: Any, *, bytes_copied: int, files_copied: int, files_failed: int):
        self.job_id = job_id
        self.expected_status = expected_status
        self.postgres_conn = postgres_conn
        self.bytes_copied = bytes_copied
        self.files_copied = files_copied
        self.files_failed = files_failed
        self.current_file: str | None = None
        self.cancelled = False
        self._progress_dirty = False
        self._copying: list[int] = []
        self._copied: list[tuple[str, int]] = []
        self._failed: list[tuple[str, int]] = []
        self._verified: list[tuple[str, int]] = []
        self._flush_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._consecutive_failures = 0
        self._fatal: Exception | None = None

    # -- in-memory mutators: no awaits, safe to call from the copy loop --

    async def add_bytes(self, delta: int) -> None:
        self.bytes_copied += delta
        self._progress_dirty = True

    def file_started(self, file_id: int, relative_path: str) -> None:
        self._copying.append(file_id)
        self.current_file = relative_path
        self._progress_dirty = True

    def file_copied(self, file_id: int, source_checksum: str) -> None:
        self._copied.append((source_checksum, file_id))
        self.files_copied += 1
        self._progress_dirty = True

    def file_verified(self, file_id: int, destination_checksum: str, relative_path: str) -> None:
        self._verified.append((destination_checksum, file_id))
        self.current_file = relative_path
        self._progress_dirty = True

    def file_failed(self, file_id: int, error_message: str, *, was_copied: bool = False) -> None:
        self._failed.append((error_message, file_id))
        self.files_failed += 1
        if was_copied:
            self.files_copied -= 1  # a file that copied fine but failed verification no longer counts as copied
        self._progress_dirty = True

    def check(self) -> None:
        if self._fatal is not None:
            raise RuntimeError(
                f"Database writes failed {MAX_CONSECUTIVE_FLUSH_FAILURES} times in a row; stopping so work "
                f"isn't done that can't be recorded: {self._fatal!r}"
            ) from self._fatal

    # -- flushing --

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=FLUSH_INTERVAL_SECONDS)
                return  # stop requested; close() performs the final flush
            except asyncio.TimeoutError:
                pass
            try:
                await self.flush()
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                print(f"[post_ingest] progress flush failed ({self._consecutive_failures}/{MAX_CONSECUTIVE_FLUSH_FAILURES}): {exc!r}")
                if self._consecutive_failures >= MAX_CONSECUTIVE_FLUSH_FAILURES:
                    self._fatal = exc
                    return

    async def flush(self) -> None:
        async with self._flush_lock:
            copying, copied, failed, verified = self._copying, self._copied, self._failed, self._verified
            self._copying, self._copied, self._failed, self._verified = [], [], [], []
            progress = None
            if self._progress_dirty:
                progress = (self.bytes_copied, self.files_copied, self.files_failed, self.current_file)
                self._progress_dirty = False
            try:
                await apply_post_job_ingest_batch(
                    self.job_id, copying_ids=copying, copied=copied, failed=failed, verified=verified,
                    progress=progress, postgres_conn=self.postgres_conn,
                )
                job = await get_post_job(self.job_id, self.postgres_conn)
            except BaseException:
                # Put the batch back ahead of anything buffered meanwhile so
                # the next flush retries it in order.
                self._copying = copying + self._copying
                self._copied = copied + self._copied
                self._failed = failed + self._failed
                self._verified = verified + self._verified
                self._progress_dirty = self._progress_dirty or progress is not None
                raise
            self.cancelled = job is None or job["status"] != self.expected_status

    async def _stop_task(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task  # lets an in-flight flush finish rather than cancelling it mid-transaction

    async def close(self) -> None:
        """Normal end of a phase: stop the background task, then flush
        everything still buffered. Retries a few times (a single dropped
        connection right at the end shouldn't throw away a finished
        phase's marks) and raises only if every attempt fails."""
        await self._stop_task()
        for attempt in range(1, FINAL_FLUSH_ATTEMPTS + 1):
            try:
                await self.flush()
                return
            except Exception as exc:
                if attempt == FINAL_FLUSH_ATTEMPTS:
                    raise
                print(f"[post_ingest] final flush failed (attempt {attempt}/{FINAL_FLUSH_ATTEMPTS}), retrying: {exc!r}")
                await asyncio.sleep(FINAL_FLUSH_RETRY_SECONDS)

    async def abort(self) -> None:
        """Error path: stop the background task without attempting a
        final flush (a flush error here would mask the real exception)."""
        await self._stop_task()


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
        pending_files = await list_pending_post_job_files(job_id, postgres_conn=postgres_conn)
        problem = await asyncio.to_thread(check_destination_space, job["destination_root"], pending_files)
        if problem:
            await update_post_job_status(
                job_id, "ingest_failed", from_statuses=("ingesting",), error_message=problem, postgres_conn=postgres_conn
            )
            return
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

    # Phase 9 -- same "explicit manual gate" discipline as every prior
    # phase's own added status. Reuses 'analyzing_color' as the
    # transient marker (see POST_JOB_STATUSES's own comment) -- only
    # ever fires when POST /post/jobs/{id}/detect-highlights has
    # already set this status. Restores 'premiere_project_created'
    # rather than always 'ingested' when the job already had a real
    # Premiere project before detection started (found live: hardcoding
    # 'ingested' here would silently lose that fact for a job detected
    # post-project-creation, since premiere_project_path is a separate
    # column that never gets cleared but nothing else re-derives status
    # from it).
    if job is not None and job["status"] == "analyzing_color":
        await run_highlight_detection(job_id, postgres_conn)
        restore_status = "premiere_project_created" if job.get("premiere_project_path") else "ingested"
        await update_post_job_status(job_id, restore_status, from_statuses=("analyzing_color",), postgres_conn=postgres_conn)


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
    pending = await list_pending_post_job_files(job_id, postgres_conn=postgres_conn)
    writer = _IngestWriteBehind(
        job_id, "ingesting", postgres_conn,
        bytes_copied=job["bytes_copied"], files_copied=job["files_copied"], files_failed=job["files_failed"],
    )
    writer.start()
    try:
        for file_row in pending:
            writer.check()
            if writer.cancelled:
                break  # cancelled/deleted -- noticed at the writer's next flush (within ~FLUSH_INTERVAL_SECONDS)
            if file_row["status"] == "verified":
                continue  # belt-and-suspenders; the query already excludes these
            source_path = source_root / file_row["relative_path"]
            writer.file_started(file_row["id"], file_row["relative_path"])
            try:
                checksum = await _hash_and_copy_file(str(source_path), file_row["destination_path"], writer.add_bytes)
                writer.file_copied(file_row["id"], checksum)
            except OSError as exc:
                writer.file_failed(file_row["id"], str(exc))
    except BaseException:
        await writer.abort()
        raise
    await writer.close()  # barrier: the DB is fully caught up before the caller moves on


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
    pending = await list_pending_post_job_files(job_id, postgres_conn=postgres_conn)
    writer = _IngestWriteBehind(
        job_id, "verifying", postgres_conn,
        bytes_copied=job["bytes_copied"], files_copied=job["files_copied"], files_failed=job["files_failed"],
    )
    writer.start()
    try:
        for file_row in pending:
            writer.check()
            if writer.cancelled:
                break  # cancelled/deleted
            if file_row["status"] != "copied" or not file_row["source_checksum"]:
                continue  # never successfully copied -- stays failed, nothing to verify
            try:
                destination_checksum = await _hash_file(file_row["destination_path"])
            except OSError as exc:
                writer.file_failed(file_row["id"], f"Verify read failed: {exc}", was_copied=True)
                continue
            if destination_checksum != file_row["source_checksum"]:
                writer.file_failed(
                    file_row["id"], "Checksum mismatch after copy -- destination file is corrupted.", was_copied=True
                )
                continue
            writer.file_verified(file_row["id"], destination_checksum, file_row["relative_path"])
    except BaseException:
        await writer.abort()
        raise
    await writer.close()  # barrier: every verified/failed mark is in the DB before the final tally below
    if writer.cancelled:
        return

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
    actually does the work. Phase 9's highlight detection reuses
    'analyzing_color' as its own transient marker (see
    POST_JOB_STATUSES's own comment) and follows the same pattern."""
    for status in (
        "scanning", "ready", "ingesting", "verifying",
        "analyzing_media", "generating_proxies", "analyzing_color",
    ):
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
