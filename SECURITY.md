# Security

**Status:** First real permission model decided (2026-07-24), local-auth-token gap closed (2026-07-25), real audit logging added and the Alpha Mode tier-classification question resolved (2026-08-10) — scoped to what actually exists today, not the full 10-year vision. Credential storage across a future multi-device/cloud-sync setup remains genuinely open.

## Purpose

Define the security principles P Corp OS operates under — non-negotiable given it will eventually hold personal, business, and financial data, and agents that can take real-world actions (trading, email, etc.).

## Decided (from FOUNDER_BRIEF.md)

Authentication, security, and permissions are explicitly owned by Layer 1 (P Corp OS platform) — not scattered across Frank or individual agents.

## Decided (2026-07-24)

- **Threat model, scoped to what's real today, not speculative.** Right now: one machine, no cloud sync, one client (the desktop app) talking to a backend bound to `127.0.0.1` only (`TECH_STACK.md`). The full future threat model (device compromise, cloud-provider breach, a compromised agent) matters once those things exist — revisit this section when cloud sync or a second device becomes real, not before.
- **Permission model for agent/tool actions: a three-tier classification**, deliberately modeled on the same framework that's governed every action Claude has taken building this project — a pattern already proven across an entire real working session, not invented from scratch:
  - **Regular (auto-allowed):** local-only, reversible, no external effect. Frank's original tool, `save_memory`, is classified here — it only writes to the local `memory_records` SQLite table, nothing leaves the device, any record can be corrected or removed later.
  - **Needs explicit confirmation:** anything with a real external effect or that's hard to reverse — a live trading action, sending an email, writing to Alpha Mode's real CRM, anything crossing outside this device.
  - **Prohibited, regardless of confirmation:** credentials/API keys/payment details, permanent data deletion, financial transfers, anything bypassing another system's own security controls. Mirrors the hard-line list already governing this entire project (e.g., Frank's API key has never been pasted into chat, only ever edited directly in `.env` by Joshua).
  - New tools must be classified into one of these tiers before being added — not an afterthought once something's already built and working, matching `ENGINEERING_MANUAL.md`'s existing "no exceptions" code-review discipline.
- **Full per-device keypair auth and credential storage across a future multi-device/cloud-sync setup** remain genuinely open — see `TECH_STACK.md`'s own auth section.

## Decided (2026-07-25)

- **Local-auth-token gap closed.** The backend now checks a machine-generated shared secret (`backend/app/auth.py`) on every route, both WebSocket and REST — any other local process on this Mac can no longer connect and impersonate the desktop app. Closes the one concrete gap identified in the threat model above.

## Decided (2026-08-10)

- **Real audit logging added.** Every tool call, from any agent, is now recorded (`app/audit_db.py`) with tool name, full input, a truncated result, and a timestamp — closes the "no consistent, auditable way to reason about what a tool did" gap this document flagged from the start. One insertion point in `main.py`'s existing dispatch loop, no individual agent touched.
- **Alpha Mode tier-classification gap, resolved.** A 2026-08-10 audit against a new feature spec surfaced that Alpha Mode Agent's `add_project`/invoice-status tools (built 2026-08-02) auto-execute against the real production database with no confirmation step — this document's own example of a "needs explicit confirmation" action, sitting in practice in "Regular" instead. Asked Joshua directly rather than reclassifying unilaterally: **decided to keep auto-execute, now that audit logging (above) provides a real record of every write.** Revisit only if this becomes an actual problem in practice, not preemptively.
- **Shadow Mode classified as "Regular," with the invasiveness question handled by scope rather than by tier.** `get_recent_activity`/`log_activity` are local-only, reversible (the whole `activity_log` table can be cleared), no external effect — same tier as `save_memory`. The real risk with a passive-observation feature isn't the permission tier, it's scope creep toward genuinely invasive capture; handled by confirming the boundary directly with Joshua before building (app name only, event-driven via a no-permission-needed public API, never window titles/URLs/file contents) rather than by escalating the tier.
- **Legacy Vault classified as "Regular" too, with the real risk handled by an absolute content restriction rather than a tier escalation.** `save_to_legacy_vault`/`list_legacy_vault`/`delete_from_legacy_vault` are local-only and reversible (soft delete, same as `forget_memory`) — but this tool's whole purpose is holding consequential, sensitive succession information, so its own tool description carries an explicit, unconditional line: never a password, API key, account number, or other credential, matching the "Prohibited" tier's existing hard line on credentials elsewhere in this project. Verified live: a deliberate attempt to save a bank password was correctly refused before the tool was ever called — confirmed via the audit log, not just trusted from the system prompt.

## Open questions

- Credential storage and secrets management across desktop + mobile + any cloud sync backend, once those exist.
- Data-at-rest and in-transit approach for cloud sync, once that's built.
- What P Corp OS builds itself vs. relies on the host OS or a cloud provider (e.g., OS keychain, managed auth provider) for.

## Next step

Revisit this document every time a new tool or agent is added, to classify it into one of the three tiers above before it ships, not after.
