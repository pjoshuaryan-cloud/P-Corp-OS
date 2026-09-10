"""Standalone verification: re-fetches every table from Postgres and
recomputes its checksum via the exact same function backup.py used
against the SQLite side, comparing against the recorded manifest.

Runnable on its own (without re-running backup/replicate) so idempotency
can be re-checked after another replicate.py run without needing a fresh
backup snapshot.
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from app.migration.checksum import compute_table_checksum
from app.migration.manifest import DOMAINS
from app.migration.replicate import DATA_DIR, resolve_dsn


def _latest_manifest() -> Path:
    candidates = sorted(DATA_DIR.glob("migration_manifest_*.json"))
    if not candidates:
        raise SystemExit("No migration manifest found -- run backup.py first.")
    return candidates[-1]


def run(dsn: str, manifest_path: Path | None = None) -> bool:
    manifest_path = manifest_path or _latest_manifest()
    manifest = json.loads(manifest_path.read_text())
    all_passed = True

    with psycopg.connect(dsn) as conn:
        for domain in DOMAINS:
            domain_manifest = manifest["domains"][domain.name]
            for table in domain.tables:
                table_manifest = domain_manifest["tables"][table.name]
                columns = table_manifest["columns"]
                expected_count = table_manifest["row_count"]
                expected_hash = table_manifest["sha256"]

                query = sql.SQL("SELECT {} FROM {}.{}").format(
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.Identifier(domain.name),
                    sql.Identifier(table.name),
                )
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()

                actual_count, actual_hash = compute_table_checksum(columns, rows, table.pk_column)
                passed = actual_count == expected_count and actual_hash == expected_hash
                all_passed = all_passed and passed
                status = "PASS" if passed else "FAIL"
                print(f"{domain.name}.{table.name}: {status} ({actual_count} rows)")

    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the Postgres replica against the migration manifest")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()

    dsn = resolve_dsn(args.dsn)
    manifest_path = Path(args.manifest) if args.manifest else None
    passed = run(dsn, manifest_path)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
