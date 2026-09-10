"""Canonical row serialization + hashing for the migration tool.

Used identically against rows fetched from SQLite (via introspect.py) or
from Postgres (via psycopg) -- both return plain Python
int/float/str/None/bytes for these schemas (no BLOB columns exist today),
so one function works for both sides of every comparison this tool makes.

Rows are always sorted here, in Python, by primary-key value -- never via
SQL ORDER BY. Postgres's default en_US.UTF-8 collation and SQLite's
binary-value default can order TEXT differently in edge cases, which
would silently break a checksum comparison even when the underlying data
is identical. Sorting in Python removes that dependency entirely.
"""

import hashlib
import json


def compute_table_checksum(
    columns: list[str],
    rows: list[tuple],
    pk_column: str,
) -> tuple[int, str]:
    """Returns (row_count, sha256_hex) for a table's full row set.

    Correctly produces a deterministic result for a 0-row table (empty
    input list) -- several real tables in this codebase are currently
    empty and must not crash or behave specially here.
    """
    pk_index = columns.index(pk_column)
    sorted_rows = sorted(rows, key=lambda row: row[pk_index])
    serialized = "\n".join(
        json.dumps(list(row), separators=(",", ":"), default=str)
        for row in sorted_rows
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return len(rows), digest
