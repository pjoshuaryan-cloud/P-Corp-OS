"""Central inventory for the SQLite -> Postgres migration tool (Stage 3 prep).

This is this tool's own manifest, not a shared app resource -- every
backend/app/*_db.py module inlines its own DB_PATH independently (e.g.
joshx_db.py:33) and none of them are touched by this migration tool.

pk_kind determines the Postgres PK column's DDL, not the INSERT shape
(one INSERT shape covers all three kinds -- see replicate.py):
  - "identity":  SQLite INTEGER PRIMARY KEY AUTOINCREMENT
  - "plain":     SQLite TEXT PRIMARY KEY (no autoincrement concept applies)
  - "singleton": SQLite INTEGER PRIMARY KEY CHECK (id = 1) config-row tables

Table order within each domain is FK-safe (parents before children),
confirmed by direct schema inspection rather than derived at runtime.
Only 5 of the 12 domains (alpha_mode, finance, pcorp, joshx, people) have
any real intra-file foreign key at all -- the rest are unordered.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    name: str
    pk_column: str
    pk_kind: str  # "identity" | "plain" | "singleton"


@dataclass(frozen=True)
class DomainSpec:
    name: str  # also the Postgres schema name
    sqlite_filename: str
    tables: tuple[TableSpec, ...]  # FK-safe insertion order


DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec("pcorp", "pcorp.db", (
        TableSpec("conversations", "id", "identity"),
        TableSpec("app_state", "id", "singleton"),
        TableSpec("messages", "id", "identity"),
        TableSpec("decisions", "id", "identity"),
        TableSpec("memory_records", "id", "identity"),
        TableSpec("memory_links", "id", "identity"),
        TableSpec("activity_log", "id", "identity"),
        TableSpec("legacy_vault", "id", "identity"),
    )),
    DomainSpec("alpha_mode", "alpha_mode.db", (
        TableSpec("clients", "id", "identity"),
        TableSpec("projects", "id", "identity"),
        TableSpec("invoices", "id", "identity"),
        TableSpec("deliverables", "id", "identity"),
        TableSpec("crew", "id", "identity"),
        TableSpec("equipment", "id", "identity"),
    )),
    DomainSpec("audit", "audit.db", (
        TableSpec("tool_calls", "id", "identity"),
    )),
    # Added 2026-09-11 as a 13th domain, after the original 12 -- Stage 7's
    # per-device auth sessions (auth_db.py) were never part of the
    # original migration inventory. Folding it in makes a device session
    # minted through either the Mac or a cloud instance valid against
    # both (they'd share the same real Postgres), and survives Render's
    # otherwise-ephemeral disk.
    DomainSpec("auth", "auth.db", (
        TableSpec("device_sessions", "id", "identity"),
    )),
    DomainSpec("automations", "automations.db", (
        TableSpec("automation_rules", "id", "plain"),
        TableSpec("automation_runs", "id", "identity"),
    )),
    DomainSpec("calendar", "calendar.db", (
        TableSpec("calendar_events", "id", "plain"),
    )),
    DomainSpec("email", "email.db", (
        TableSpec("emails", "id", "plain"),
    )),
    DomainSpec("finance", "finance.db", (
        TableSpec("accounts", "id", "identity"),
        TableSpec("balance_snapshots", "id", "identity"),
        TableSpec("luno_snapshot_schedule", "id", "singleton"),
        TableSpec("hf_markets_snapshot_schedule", "id", "singleton"),
    )),
    DomainSpec("joshx", "joshx.db", (
        TableSpec("clients", "id", "identity"),
        TableSpec("leads", "id", "identity"),
        TableSpec("projects", "id", "identity"),
        TableSpec("invoices", "id", "identity"),
        TableSpec("expenses", "id", "identity"),
    )),
    DomainSpec("operations", "operations.db", (
        TableSpec("tasks", "id", "identity"),
    )),
    DomainSpec("people", "people.db", (
        TableSpec("people", "id", "identity"),
        TableSpec("interactions", "id", "identity"),
    )),
    DomainSpec("personal", "personal.db", (
        TableSpec("goals", "id", "identity"),
        TableSpec("habits", "id", "identity"),
    )),
    DomainSpec("triggers", "triggers.db", (
        TableSpec("trigger_rules", "id", "identity"),
        TableSpec("trigger_state", "item_key", "plain"),
        TableSpec("digest_schedule", "id", "singleton"),
        TableSpec("market_price_snapshots", "id", "identity"),
        TableSpec("market_movers_snapshot_schedule", "id", "singleton"),
    )),
)
