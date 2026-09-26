"""
POST (2026-09-25, Phase 1) -- autonomous video post-production prep:
drive detection, footage ingestion with checksum verification, and
crash-safe resumability. Own SQLite file (post.db) and own Postgres
schema (post), same "genuinely separate domain" reasoning as every
other *_db.py module in this app.

Uses ventures_db.py's/trade_proposals_db.py's inline-DDL-with-real-
CHECK-constraints pattern, not Joshx's own loose free-text-status
convention -- POST's job/file statuses are real enforced pipeline
stages a UI renders and a background worker transitions through, not
Frank's own free-text notes.

`post_job_files.verified_at IS NULL` is the resume checkpoint, mirroring
trade_proposals_db.py's `command_written_at IS NULL` guard exactly: a
resumed/restarted job re-queries files still needing work and continues
only those -- it never restarts a whole job from zero.

POST_JOB_STATUSES intentionally includes placeholder values for later
phases (media analysis, Premiere integration, proxies, color analysis)
that Phase 1 never reaches -- front-loading the CHECK constraint's full
eventual vocabulary now avoids a real cross-backend migration later
(SQLite: recreate table; Postgres: DROP/ADD CONSTRAINT) for each new
phase. Their exact names may still change once those phases are
actually scoped.

Like every file under backend/data/, gitignored -- nothing written here
ever reaches GitHub.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "data" / "post.db"

POST_PROFILE_NAMES = ("joshx", "alpha_mode")

POST_JOB_STATUSES = (
    "created", "scanning", "ready",                        # Phase 1 setup
    "ingesting", "verifying",                              # Phase 1 active work
    "ingested",                                            # Phase 1 terminal success
    "ingest_failed", "cancelled",                          # Phase 1 off-ramps, both resumable via /start
    "analyzing_media", "premiere_project_created",         # Phase 2/3 placeholders
    "generating_proxies", "analyzing_color",               # Phase 4/5 placeholders
    "complete", "archived",
)
POST_JOB_FILE_STATUSES = ("pending", "copying", "copied", "verified", "failed")
MEDIA_TYPES = ("video", "audio", "image", "other")
PROXY_STATUSES = ("queued", "processing", "complete", "failed")

# Descriptive tags from the spec's own NEW SHOOT flow -- app-level
# validated (see main.py's create-job route), deliberately NOT DB CHECK-
# constrained. Unlike `status`, these never gate pipeline behavior, only
# feed a Premiere sequence-preset choice and a source/delivery mismatch
# warning -- SQLite can't ALTER TABLE to add a CHECK constraint to an
# existing table, and there's no real need to pay that cost for tags
# that don't gate anything.
DELIVERABLE_FORMATS = ("16:9", "9:16", "1:1", "4:5", "custom")
RESOLUTIONS = ("4k_uhd", "4k_dci", "custom")
FRAME_RATES = ("23.976", "24", "25", "29.97", "30", "50", "59.94", "other")

_POST_JOB_COLUMNS = (
    "id", "profile", "shoot_name", "client_name", "source_path", "source_volume_name", "source_volume_uuid",
    "destination_root", "joshx_project_id", "alpha_mode_project_id", "status",
    "total_files", "total_bytes", "files_copied", "files_failed", "bytes_copied",
    "current_file_path", "error_message", "started_at", "completed_at", "created_at", "media_analyzed_at",
    "deliverable_format", "resolution", "frame_rate", "premiere_project_path", "proxies_generated_at",
)
_POST_JOB_FILE_COLUMNS = (
    "id", "job_id", "relative_path", "destination_path", "size_bytes", "status", "bytes_copied",
    "source_checksum", "destination_checksum", "verified_at", "error_message", "attempt_count", "created_at",
)
_POST_JOB_FILE_METADATA_COLUMNS = (
    "id", "file_id", "media_type", "duration_seconds", "width", "height", "video_codec", "audio_codec",
    "frame_rate", "bit_depth", "pixel_format", "color_space", "audio_channels", "camera_make", "camera_model",
    "creation_time", "probe_error", "created_at", "bit_rate",
)
_POST_JOB_FILE_PROXY_COLUMNS = (
    "id", "file_id", "status", "proxy_path", "error_message", "created_at", "completed_at",
)


async def init_post_db(postgres_conn: Any = None) -> None:
    if postgres_conn is not None:
        await _init_postgres(postgres_conn)
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile TEXT NOT NULL CHECK (profile IN {POST_PROFILE_NAMES}),
                shoot_name TEXT NOT NULL,
                client_name TEXT,
                source_path TEXT NOT NULL,
                source_volume_name TEXT,
                source_volume_uuid TEXT,
                destination_root TEXT NOT NULL,
                joshx_project_id INTEGER,
                alpha_mode_project_id INTEGER,
                status TEXT NOT NULL DEFAULT 'created' CHECK (status IN {POST_JOB_STATUSES}),
                total_files INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                files_copied INTEGER NOT NULL DEFAULT 0,
                files_failed INTEGER NOT NULL DEFAULT 0,
                bytes_copied INTEGER NOT NULL DEFAULT 0,
                current_file_path TEXT,
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT,
                media_analyzed_at TEXT,
                deliverable_format TEXT,
                resolution TEXT,
                frame_rate TEXT,
                premiere_project_path TEXT,
                proxies_generated_at TEXT
            )
            """
        )
        cursor = await db.execute("PRAGMA table_info(post_jobs)")
        job_columns = {row[1] async for row in cursor}
        if "media_analyzed_at" not in job_columns:
            await db.execute("ALTER TABLE post_jobs ADD COLUMN media_analyzed_at TEXT")
        for column in ("deliverable_format", "resolution", "frame_rate", "premiere_project_path", "proxies_generated_at"):
            if column not in job_columns:
                await db.execute(f"ALTER TABLE post_jobs ADD COLUMN {column} TEXT")
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post_job_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES post_jobs(id),
                relative_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {POST_JOB_FILE_STATUSES}),
                bytes_copied INTEGER NOT NULL DEFAULT 0,
                source_checksum TEXT,
                destination_checksum TEXT,
                verified_at TEXT,
                error_message TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post_job_file_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL REFERENCES post_job_files(id),
                media_type TEXT CHECK (media_type IN {MEDIA_TYPES}),
                duration_seconds REAL,
                width INTEGER,
                height INTEGER,
                video_codec TEXT,
                audio_codec TEXT,
                frame_rate REAL,
                bit_depth INTEGER,
                pixel_format TEXT,
                color_space TEXT,
                audio_channels INTEGER,
                camera_make TEXT,
                camera_model TEXT,
                creation_time TEXT,
                probe_error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                bit_rate INTEGER
            )
            """
        )
        cursor = await db.execute("PRAGMA table_info(post_job_file_metadata)")
        metadata_columns = {row[1] async for row in cursor}
        if "bit_rate" not in metadata_columns:
            await db.execute("ALTER TABLE post_job_file_metadata ADD COLUMN bit_rate INTEGER")
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post_job_file_proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL REFERENCES post_job_files(id),
                status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN {PROXY_STATUSES}),
                proxy_path TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )
            """
        )
        await db.commit()


async def _init_postgres(conn: Any) -> None:
    async with conn.cursor() as cur:
        await cur.execute("CREATE SCHEMA IF NOT EXISTS post")
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post.jobs (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                profile TEXT NOT NULL CHECK (profile IN {POST_PROFILE_NAMES}),
                shoot_name TEXT NOT NULL,
                client_name TEXT,
                source_path TEXT NOT NULL,
                source_volume_name TEXT,
                source_volume_uuid TEXT,
                destination_root TEXT NOT NULL,
                joshx_project_id BIGINT,
                alpha_mode_project_id BIGINT,
                status TEXT NOT NULL DEFAULT 'created' CHECK (status IN {POST_JOB_STATUSES}),
                total_files BIGINT NOT NULL DEFAULT 0,
                total_bytes BIGINT NOT NULL DEFAULT 0,
                files_copied BIGINT NOT NULL DEFAULT 0,
                files_failed BIGINT NOT NULL DEFAULT 0,
                bytes_copied BIGINT NOT NULL DEFAULT 0,
                current_file_path TEXT,
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                media_analyzed_at TEXT,
                deliverable_format TEXT,
                resolution TEXT,
                frame_rate TEXT,
                premiere_project_path TEXT,
                proxies_generated_at TEXT
            )
            """
        )
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS media_analyzed_at TEXT")
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS deliverable_format TEXT")
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS resolution TEXT")
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS frame_rate TEXT")
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS premiere_project_path TEXT")
        await cur.execute("ALTER TABLE post.jobs ADD COLUMN IF NOT EXISTS proxies_generated_at TEXT")
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post.job_files (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                job_id BIGINT NOT NULL REFERENCES post.jobs(id),
                relative_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                size_bytes BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {POST_JOB_FILE_STATUSES}),
                bytes_copied BIGINT NOT NULL DEFAULT 0,
                source_checksum TEXT,
                destination_checksum TEXT,
                verified_at TEXT,
                error_message TEXT,
                attempt_count BIGINT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post.job_file_metadata (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                file_id BIGINT NOT NULL REFERENCES post.job_files(id),
                media_type TEXT CHECK (media_type IN {MEDIA_TYPES}),
                duration_seconds DOUBLE PRECISION,
                width BIGINT,
                height BIGINT,
                video_codec TEXT,
                audio_codec TEXT,
                frame_rate DOUBLE PRECISION,
                bit_depth BIGINT,
                pixel_format TEXT,
                color_space TEXT,
                audio_channels BIGINT,
                camera_make TEXT,
                camera_model TEXT,
                creation_time TEXT,
                probe_error TEXT,
                created_at TEXT NOT NULL,
                bit_rate BIGINT
            )
            """
        )
        await cur.execute("ALTER TABLE post.job_file_metadata ADD COLUMN IF NOT EXISTS bit_rate BIGINT")
        await cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS post.job_file_proxies (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                file_id BIGINT NOT NULL REFERENCES post.job_files(id),
                status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN {PROXY_STATUSES}),
                proxy_path TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
    await conn.commit()


# ------------------------------------------------------------ post_jobs

async def create_post_job(
    profile: str,
    shoot_name: str,
    source_path: str,
    destination_root: str,
    client_name: str | None = None,
    source_volume_name: str | None = None,
    source_volume_uuid: str | None = None,
    joshx_project_id: int | None = None,
    alpha_mode_project_id: int | None = None,
    deliverable_format: str | None = None,
    resolution: str | None = None,
    frame_rate: str | None = None,
    postgres_conn: Any = None,
) -> int:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO post.jobs "
                "(profile, shoot_name, client_name, source_path, source_volume_name, source_volume_uuid, "
                "destination_root, joshx_project_id, alpha_mode_project_id, "
                "deliverable_format, resolution, frame_rate, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (now() AT TIME ZONE 'utc')) "
                "RETURNING id",
                (profile, shoot_name, client_name, source_path, source_volume_name, source_volume_uuid,
                 destination_root, joshx_project_id, alpha_mode_project_id,
                 deliverable_format, resolution, frame_rate),
            )
            (new_id,) = await cur.fetchone()
        await postgres_conn.commit()
        return new_id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO post_jobs "
            "(profile, shoot_name, client_name, source_path, source_volume_name, source_volume_uuid, "
            "destination_root, joshx_project_id, alpha_mode_project_id, "
            "deliverable_format, resolution, frame_rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile, shoot_name, client_name, source_path, source_volume_name, source_volume_uuid,
             destination_root, joshx_project_id, alpha_mode_project_id,
             deliverable_format, resolution, frame_rate),
        )
        await db.commit()
        return cursor.lastrowid


async def list_post_jobs(status: str | None = None, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            if status is not None:
                await cur.execute(
                    f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post.jobs "
                    "WHERE deleted_at IS NULL AND status = %s ORDER BY created_at DESC",
                    (status,),
                )
            else:
                await cur.execute(
                    f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post.jobs "
                    "WHERE deleted_at IS NULL ORDER BY created_at DESC"
                )
            rows = await cur.fetchall()
            return [dict(zip(_POST_JOB_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status is not None:
            cursor = await db.execute(
                f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post_jobs "
                "WHERE deleted_at IS NULL AND status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post_jobs WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        return [dict(r) for r in await cursor.fetchall()]


async def get_post_job(job_id: int, postgres_conn: Any = None) -> dict | None:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post.jobs WHERE id = %s AND deleted_at IS NULL",
                (job_id,),
            )
            row = await cur.fetchone()
            return dict(zip(_POST_JOB_COLUMNS, row)) if row else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_POST_JOB_COLUMNS)} FROM post_jobs WHERE id = ? AND deleted_at IS NULL", (job_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_post_job_progress(job_id: int, postgres_conn: Any = None) -> dict | None:
    """get_post_job() plus a server-computed estimated_remaining_seconds
    (simple linear extrapolation from elapsed time and bytes copied so
    far) -- computed once, server-side, so desktop and iOS polling the
    same job simultaneously always see the identical number rather than
    each deriving a slightly different one from possibly-stale local
    state."""
    job = await get_post_job(job_id, postgres_conn)
    if job is None:
        return None
    job["estimated_remaining_seconds"] = _estimate_remaining_seconds(job)
    return job


def _estimate_remaining_seconds(job: dict) -> float | None:
    if job["status"] not in ("ingesting", "verifying") or not job["started_at"] or job["bytes_copied"] <= 0:
        return None
    started_at = datetime.fromisoformat(job["started_at"])
    now = datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.utcnow()
    elapsed = (now - started_at).total_seconds()
    if elapsed <= 0:
        return None
    remaining_bytes = max(job["total_bytes"] - job["bytes_copied"], 0)
    return elapsed * remaining_bytes / job["bytes_copied"]


async def update_post_job_status(
    job_id: int, status: str, *, from_statuses: tuple[str, ...] | None = None,
    error_message: str | None = None, postgres_conn: Any = None,
) -> bool:
    """Guarded status transition -- when from_statuses is given, the
    UPDATE only applies if the row's current status is one of them
    (WHERE status IN (...)), the same 'guard the transition, not just
    the id' discipline trade_proposals_db.py's resolve_proposal() uses
    to prevent double-resolution from a racing caller."""
    stamps_started = status in ("scanning", "ingesting")
    stamps_completed = status in ("ingested", "ingest_failed", "cancelled")
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            clauses = ["status = %s"]
            params: list[Any] = [status]
            if stamps_started:
                clauses.append("started_at = COALESCE(started_at, (now() AT TIME ZONE 'utc')::text)")
            if stamps_completed:
                clauses.append("completed_at = (now() AT TIME ZONE 'utc')")
            if error_message is not None:
                clauses.append("error_message = %s")
                params.append(error_message)
            sql = f"UPDATE post.jobs SET {', '.join(clauses)} WHERE id = %s AND deleted_at IS NULL"
            params.append(job_id)
            if from_statuses is not None:
                # A naive f"IN {tuple(from_statuses)}" breaks for a
                # single-element tuple -- Python's own repr for one,
                # e.g. ('scanning',), carries a trailing comma that is
                # valid Python but a SQL syntax error. Real parameterized
                # placeholders, same as the SQLite branch below, avoid
                # this entirely.
                placeholders = ", ".join("%s" for _ in from_statuses)
                sql += f" AND status IN ({placeholders})"
                params.extend(from_statuses)
            await cur.execute(sql, params)
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        clauses = ["status = ?"]
        params = [status]
        if stamps_started:
            clauses.append("started_at = COALESCE(started_at, datetime('now'))")
        if stamps_completed:
            clauses.append("completed_at = datetime('now')")
        if error_message is not None:
            clauses.append("error_message = ?")
            params.append(error_message)
        sql = f"UPDATE post_jobs SET {', '.join(clauses)} WHERE id = ? AND deleted_at IS NULL"
        params.append(job_id)
        if from_statuses is not None:
            placeholders = ", ".join("?" for _ in from_statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(from_statuses)
        cursor = await db.execute(sql, params)
        await db.commit()
        return cursor.rowcount > 0


async def record_post_job_scan_result(job_id: int, total_files: int, total_bytes: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET total_files = %s, total_bytes = %s WHERE id = %s AND deleted_at IS NULL",
                (total_files, total_bytes, job_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET total_files = ?, total_bytes = ? WHERE id = ? AND deleted_at IS NULL",
            (total_files, total_bytes, job_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_post_job_progress(
    job_id: int, bytes_copied: int, files_copied: int, files_failed: int,
    current_file_path: str | None, postgres_conn: Any = None,
) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET bytes_copied = %s, files_copied = %s, files_failed = %s, "
                "current_file_path = %s WHERE id = %s AND deleted_at IS NULL",
                (bytes_copied, files_copied, files_failed, current_file_path, job_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET bytes_copied = ?, files_copied = ?, files_failed = ?, "
            "current_file_path = ? WHERE id = ? AND deleted_at IS NULL",
            (bytes_copied, files_copied, files_failed, current_file_path, job_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_post_job(job_id: int, postgres_conn: Any = None) -> bool:
    """Soft delete of the JOB RECORD only -- never touches any copied
    file on disk, matching POST's own file-safety principle that
    original AND copied footage are never auto-deleted."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET deleted_at = (now() AT TIME ZONE 'utc') WHERE id = %s AND deleted_at IS NULL",
                (job_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL", (job_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# ------------------------------------------------------------ post_job_files

async def create_post_job_files_batch(
    job_id: int, files: list[tuple[str, str, int]], postgres_conn: Any = None
) -> None:
    """files: list of (relative_path, destination_path, size_bytes)."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO post.job_files (job_id, relative_path, destination_path, size_bytes, created_at) "
                "VALUES (%s, %s, %s, %s, (now() AT TIME ZONE 'utc'))",
                [(job_id, rel, dest, size) for rel, dest, size in files],
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO post_job_files (job_id, relative_path, destination_path, size_bytes) VALUES (?, ?, ?, ?)",
            [(job_id, rel, dest, size) for rel, dest, size in files],
        )
        await db.commit()


async def list_pending_post_job_files(job_id: int, postgres_conn: Any = None) -> list[dict]:
    """The resume query -- files not yet fully verified. A resumed job
    calls this and continues only these rows; files already verified in
    a prior run are never touched again."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_POST_JOB_FILE_COLUMNS)} FROM post.job_files "
                "WHERE job_id = %s AND deleted_at IS NULL AND verified_at IS NULL ORDER BY id",
                (job_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_POST_JOB_FILE_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_POST_JOB_FILE_COLUMNS)} FROM post_job_files "
            "WHERE job_id = ? AND deleted_at IS NULL AND verified_at IS NULL ORDER BY id",
            (job_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def list_post_job_files(job_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT {', '.join(_POST_JOB_FILE_COLUMNS)} FROM post.job_files "
                "WHERE job_id = %s AND deleted_at IS NULL ORDER BY id",
                (job_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_POST_JOB_FILE_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT {', '.join(_POST_JOB_FILE_COLUMNS)} FROM post_job_files "
            "WHERE job_id = ? AND deleted_at IS NULL ORDER BY id",
            (job_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def mark_post_job_file_copying(file_id: int, postgres_conn: Any = None) -> bool:
    return await _update_post_job_file(
        file_id, "status = {p}", ("copying",),
        extra_sql="attempt_count = attempt_count + 1", postgres_conn=postgres_conn,
    )


async def mark_post_job_file_copied(file_id: int, source_checksum: str, postgres_conn: Any = None) -> bool:
    return await _update_post_job_file(
        file_id, "status = {p}, source_checksum = {p}", ("copied", source_checksum), postgres_conn=postgres_conn
    )


async def mark_post_job_file_verified(file_id: int, destination_checksum: str, postgres_conn: Any = None) -> bool:
    """WHERE verified_at IS NULL guard -- the resume checkpoint itself.
    Mirrors trade_proposals_db.py's mark_command_written() NULL-guard
    exactly: safe to call again on a row that's already verified (it
    simply won't match and returns False), so a retried/duplicated
    verify step can never double-process a file."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.job_files SET status = 'verified', destination_checksum = %s, "
                "verified_at = (now() AT TIME ZONE 'utc') WHERE id = %s AND verified_at IS NULL",
                (destination_checksum, file_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_job_files SET status = 'verified', destination_checksum = ?, "
            "verified_at = datetime('now') WHERE id = ? AND verified_at IS NULL",
            (destination_checksum, file_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_post_job_file_failed(file_id: int, error_message: str, postgres_conn: Any = None) -> bool:
    return await _update_post_job_file(
        file_id, "status = {p}, error_message = {p}", ("failed", error_message), postgres_conn=postgres_conn
    )


async def _update_post_job_file(
    file_id: int, set_clause_template: str, values: tuple, *, extra_sql: str | None = None, postgres_conn: Any = None
) -> bool:
    """Small shared helper for the simple single-purpose per-file status
    setters above -- set_clause_template uses '{p}' as a placeholder
    marker so the same template works for both backends' own param
    styles."""
    if postgres_conn is not None:
        set_clause = set_clause_template.format(p="%s")
        if extra_sql:
            set_clause = f"{set_clause}, {extra_sql}"
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"UPDATE post.job_files SET {set_clause} WHERE id = %s AND deleted_at IS NULL",
                (*values, file_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    set_clause = set_clause_template.format(p="?")
    if extra_sql:
        set_clause = f"{set_clause}, {extra_sql}"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"UPDATE post_job_files SET {set_clause} WHERE id = ? AND deleted_at IS NULL",
            (*values, file_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# ------------------------------------------------------------ post_job_file_metadata (Phase 2)

async def update_post_job_media_analyzed(job_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET media_analyzed_at = (now() AT TIME ZONE 'utc')::text "
                "WHERE id = %s AND deleted_at IS NULL",
                (job_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET media_analyzed_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (job_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_post_job_premiere_project(job_id: int, project_path: str, postgres_conn: Any = None) -> bool:
    """Phase 3 -- the UXP plugin's own success callback. Guarded exactly
    like every other status transition in this file (WHERE status =
    'ingested'), atomic with storing the real .prproj path -- a plugin
    retry after a network hiccup can't double-resolve an already-
    resolved job."""
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET status = 'premiere_project_created', premiere_project_path = %s "
                "WHERE id = %s AND status = 'ingested' AND deleted_at IS NULL",
                (project_path, job_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET status = 'premiere_project_created', premiere_project_path = ? "
            "WHERE id = ? AND status = 'ingested' AND deleted_at IS NULL",
            (project_path, job_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def create_post_job_file_metadata_batch(rows: list[dict], postgres_conn: Any = None) -> None:
    """One row per probed file. Deletes any prior metadata for the same
    file_ids first -- re-analyzing a job (e.g. after Josh reconnects a
    drive with a fixed file) replaces stale metadata rather than
    accumulating duplicate rows, same 'never blindly append on retry'
    discipline as the ingestion phases' own idempotency guards."""
    if not rows:
        return
    file_ids = [row["file_id"] for row in rows]
    columns = (
        "file_id", "media_type", "duration_seconds", "width", "height", "video_codec", "audio_codec",
        "frame_rate", "bit_depth", "pixel_format", "color_space", "audio_channels", "camera_make",
        "camera_model", "creation_time", "probe_error", "bit_rate",
    )
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM post.job_file_metadata WHERE file_id = ANY(%s)", (file_ids,)
            )
            placeholders = ", ".join(["%s"] * len(columns))
            await cur.executemany(
                f"INSERT INTO post.job_file_metadata ({', '.join(columns)}, created_at) "
                f"VALUES ({placeholders}, (now() AT TIME ZONE 'utc'))",
                [tuple(row.get(col) for col in columns) for row in rows],
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders_del = ", ".join("?" for _ in file_ids)
        await db.execute(f"DELETE FROM post_job_file_metadata WHERE file_id IN ({placeholders_del})", file_ids)
        placeholders = ", ".join(["?"] * len(columns))
        await db.executemany(
            f"INSERT INTO post_job_file_metadata ({', '.join(columns)}) VALUES ({placeholders})",
            [tuple(row.get(col) for col in columns) for row in rows],
        )
        await db.commit()


async def list_post_job_file_metadata(job_id: int, postgres_conn: Any = None) -> list[dict]:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT m.{', m.'.join(_POST_JOB_FILE_METADATA_COLUMNS)} "
                "FROM post.job_file_metadata m JOIN post.job_files f ON m.file_id = f.id "
                "WHERE f.job_id = %s",
                (job_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip(_POST_JOB_FILE_METADATA_COLUMNS, row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT m.{', m.'.join(_POST_JOB_FILE_METADATA_COLUMNS)} "
            "FROM post_job_file_metadata m JOIN post_job_files f ON m.file_id = f.id "
            "WHERE f.job_id = ?",
            (job_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ------------------------------------------------------------ post_job_file_proxies (Phase 4)

async def update_post_job_proxies_generated(job_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.jobs SET proxies_generated_at = (now() AT TIME ZONE 'utc')::text "
                "WHERE id = %s AND deleted_at IS NULL",
                (job_id,),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_jobs SET proxies_generated_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (job_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def create_post_job_file_proxies_batch(file_ids: list[int], postgres_conn: Any = None) -> None:
    """One 'queued' row per file recommended for a proxy. Deletes any
    prior proxy rows for the same file_ids first -- re-running Generate
    Proxies on a job replaces stale attempts rather than accumulating
    duplicate rows, same 'never blindly append on retry' discipline as
    create_post_job_file_metadata_batch."""
    if not file_ids:
        return
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("DELETE FROM post.job_file_proxies WHERE file_id = ANY(%s)", (file_ids,))
            await cur.executemany(
                "INSERT INTO post.job_file_proxies (file_id, created_at) VALUES (%s, (now() AT TIME ZONE 'utc'))",
                [(fid,) for fid in file_ids],
            )
        await postgres_conn.commit()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders_del = ", ".join("?" for _ in file_ids)
        await db.execute(f"DELETE FROM post_job_file_proxies WHERE file_id IN ({placeholders_del})", file_ids)
        await db.executemany(
            "INSERT INTO post_job_file_proxies (file_id) VALUES (?)", [(fid,) for fid in file_ids]
        )
        await db.commit()


async def list_post_job_file_proxies(job_id: int, postgres_conn: Any = None) -> list[dict]:
    """Joined against post_job_files for this job -- includes each
    proxy row's own destination_path/relative_path via the join so
    callers (the proxies status route, /premiere-prep) don't need a
    second lookup."""
    columns = _POST_JOB_FILE_PROXY_COLUMNS
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT p.{', p.'.join(columns)}, f.relative_path, f.destination_path "
                "FROM post.job_file_proxies p JOIN post.job_files f ON p.file_id = f.id "
                "WHERE f.job_id = %s ORDER BY p.id",
                (job_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip((*columns, "relative_path", "destination_path"), row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT p.{', p.'.join(columns)}, f.relative_path, f.destination_path "
            "FROM post_job_file_proxies p JOIN post_job_files f ON p.file_id = f.id "
            "WHERE f.job_id = ? ORDER BY p.id",
            (job_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def list_queued_post_job_file_proxies(job_id: int, postgres_conn: Any = None) -> list[dict]:
    """The resume/work query -- rows still needing a real transcode
    (queued, or left 'processing' by a killed/restarted loop -- picked
    back up from scratch, matching Phase 1's own file-level, not byte-
    level, resume decision). Joined against post_job_files for the real
    source destination_path to feed ffmpeg."""
    columns = _POST_JOB_FILE_PROXY_COLUMNS
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                f"SELECT p.{', p.'.join(columns)}, f.relative_path, f.destination_path "
                "FROM post.job_file_proxies p JOIN post.job_files f ON p.file_id = f.id "
                "WHERE f.job_id = %s AND p.status IN ('queued', 'processing') ORDER BY p.id",
                (job_id,),
            )
            rows = await cur.fetchall()
            return [dict(zip((*columns, "relative_path", "destination_path"), row)) for row in rows]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT p.{', p.'.join(columns)}, f.relative_path, f.destination_path "
            "FROM post_job_file_proxies p JOIN post_job_files f ON p.file_id = f.id "
            "WHERE f.job_id = ? AND p.status IN ('queued', 'processing') ORDER BY p.id",
            (job_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def mark_post_job_file_proxy_processing(proxy_id: int, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute("UPDATE post.job_file_proxies SET status = 'processing' WHERE id = %s", (proxy_id,))
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("UPDATE post_job_file_proxies SET status = 'processing' WHERE id = ?", (proxy_id,))
        await db.commit()
        return cursor.rowcount > 0


async def mark_post_job_file_proxy_complete(proxy_id: int, proxy_path: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.job_file_proxies SET status = 'complete', proxy_path = %s, "
                "completed_at = (now() AT TIME ZONE 'utc') WHERE id = %s",
                (proxy_path, proxy_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_job_file_proxies SET status = 'complete', proxy_path = ?, "
            "completed_at = datetime('now') WHERE id = ?",
            (proxy_path, proxy_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_post_job_file_proxy_failed(proxy_id: int, error_message: str, postgres_conn: Any = None) -> bool:
    if postgres_conn is not None:
        async with postgres_conn.cursor() as cur:
            await cur.execute(
                "UPDATE post.job_file_proxies SET status = 'failed', error_message = %s, "
                "completed_at = (now() AT TIME ZONE 'utc') WHERE id = %s",
                (error_message, proxy_id),
            )
            updated = cur.rowcount > 0
        await postgres_conn.commit()
        return updated
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE post_job_file_proxies SET status = 'failed', error_message = ?, "
            "completed_at = datetime('now') WHERE id = ?",
            (error_message, proxy_id),
        )
        await db.commit()
        return cursor.rowcount > 0
