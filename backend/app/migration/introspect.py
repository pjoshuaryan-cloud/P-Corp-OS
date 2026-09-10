"""Reads real SQLite schema/row info from a file, always read-only.

Every connection opened here uses the `?mode=ro` URI form -- this makes
"never writes to the source file" an engine-enforced property, not just
code discipline. In practice this module is only ever pointed at the
.bak-<timestamp> files backup.py produces (see backup.py's own docstring
for why replicate.py/verify.py never reopen a live backend/data/*.db
file), but the read-only connection mode would make even a direct call
against a live file harmless.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    sqlite_type: str
    not_null: bool


@dataclass(frozen=True)
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[ColumnInfo, ...]  # in declared column order
    foreign_keys: tuple[ForeignKeyInfo, ...]


def _read_only_connect(sqlite_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)


def read_table_schema(sqlite_path: str, table: str) -> TableSchema:
    conn = _read_only_connect(sqlite_path)
    try:
        column_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = tuple(
            ColumnInfo(name=row[1], sqlite_type=row[2], not_null=bool(row[3]))
            for row in column_rows
        )
        fk_rows = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        # PRAGMA foreign_key_list columns: id, seq, table, from, to, ...
        foreign_keys = tuple(
            ForeignKeyInfo(column=row[3], ref_table=row[2], ref_column=row[4])
            for row in fk_rows
        )
        return TableSchema(name=table, columns=columns, foreign_keys=foreign_keys)
    finally:
        conn.close()


def read_all_rows(sqlite_path: str, table: str, columns: list[str]) -> list[tuple]:
    conn = _read_only_connect(sqlite_path)
    try:
        column_list = ", ".join(f'"{c}"' for c in columns)
        return conn.execute(f'SELECT {column_list} FROM "{table}"').fetchall()
    finally:
        conn.close()
