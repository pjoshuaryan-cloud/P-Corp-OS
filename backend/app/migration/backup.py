"""Stage 3 prep: online, read-only backup + checksum of all real SQLite
databases in backend/data/.

This is the ONLY module in this migration tool that ever opens a live
backend/data/*.db file -- and even that is always read-only (sqlite3's
online backup API, source connection opened via the `?mode=ro` URI form),
so "never writes to source" is enforced by SQLite itself, not just by
code discipline. These databases use the default rollback-journal mode
(not WAL), so a raw file copy here -- instead of the online backup API --
would risk grabbing a torn, inconsistent snapshot if the live backend is
mid-write.

Everything downstream (replicate.py, verify.py) reads only from the
.bak-<timestamp> file this step produces, never live data again -- so a
write landing after this step finishes can never make the recorded
checksums diverge from what actually gets replicated.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.migration import introspect
from app.migration.checksum import compute_table_checksum
from app.migration.manifest import DOMAINS

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _online_backup(source_path: Path, dest_path: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(dest_path)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()


def run() -> Path:
    """Backs up all 12 domains, computes per-table checksums against the
    fresh backup files, and writes one combined manifest. Returns the
    manifest's path.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    manifest_domains: dict = {}

    for domain in DOMAINS:
        source_path = DATA_DIR / domain.sqlite_filename
        backup_path = DATA_DIR / f"{domain.sqlite_filename}.bak-{timestamp}"
        _online_backup(source_path, backup_path)

        tables_manifest: dict = {}
        for table in domain.tables:
            schema = introspect.read_table_schema(str(backup_path), table.name)
            columns = [c.name for c in schema.columns]
            rows = introspect.read_all_rows(str(backup_path), table.name, columns)
            row_count, digest = compute_table_checksum(columns, rows, table.pk_column)
            tables_manifest[table.name] = {
                "columns": columns,
                "row_count": row_count,
                "sha256": digest,
                "pk_column": table.pk_column,
                "pk_kind": table.pk_kind,
            }
            print(f"  backed up {domain.name}.{table.name}: {row_count} rows")

        manifest_domains[domain.name] = {
            "sqlite_source": str(source_path),
            "backup_path": str(backup_path),
            "tables": tables_manifest,
        }
        print(f"Backed up domain: {domain.name} -> {backup_path.name}")

    manifest = {"created_at": timestamp, "domains": manifest_domains}
    manifest_path = DATA_DIR / f"migration_manifest_{timestamp}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nBackup manifest written: {manifest_path}")
    return manifest_path


if __name__ == "__main__":
    run()
