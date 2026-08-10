# Security

**Status:** First real permission model decided (2026-07-24), local-auth-token gap closed (2026-07-25) — scoped to what actually exists today, not the full 10-year vision. Credential storage across a future multi-device/cloud-sync setup remains genuinely open. A real gap in the *tier classification* itself was surfaced during a 2026-08-10 audit against a new feature spec — see the note under "Decided (2026-07-24)" below.

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
- **Real gap surfaced by a 2026-08-10 audit, not yet resolved:** this document's own example of a "needs explicit confirmation" action — "writing to Alpha Mode's real CRM" — is literally what the Alpha Mode Agent's `add_project`/invoice-status tools do (built 2026-08-02), and they currently auto-execute with no confirmation step and no audit log, sitting in practice in the "Regular" tier rather than the one this document itself says they belong in. Not silently reclassified either way — flagged as an open decision for Joshua: accept the current auto-execute behavior explicitly, or add a confirmation step and/or audit log before these writes.
- **Full per-device keypair auth and credential storage across a future multi-device/cloud-sync setup** remain genuinely open — see `TECH_STACK.md`'s own auth section.

## Decided (2026-07-25)

- **Local-auth-token gap closed.** The backend now checks a machine-generated shared secret (`backend/app/auth.py`) on every route, both WebSocket and REST — any other local process on this Mac can no longer connect and impersonate the desktop app. Closes the one concrete gap identified in the threat model above.

## Open questions

- The Alpha Mode Agent tier-classification gap above — real and known, not yet resolved either way.
- No audit logging exists anywhere yet for any tool call (any agent, any tier) — no record of who/what/when/input/result. Flagged by the same 2026-08-10 audit as the highest-value, lowest-risk near-term addition, since one single tool-dispatch point already exists in `main.py` that every agent's call already flows through.
- Credential storage and secrets management across desktop + mobile + any cloud sync backend, once those exist.
- Data-at-rest and in-transit approach for cloud sync, once that's built.
- What P Corp OS builds itself vs. relies on the host OS or a cloud provider (e.g., OS keychain, managed auth provider) for.

## Next step

Add real audit logging at the existing single tool-dispatch choke point (no architecture change needed) — the clearest immediate win from the 2026-08-10 audit. Separately, resolve the Alpha Mode tier-classification gap above with Joshua directly. Beyond that: revisit this document every time a new tool or agent is added, to classify it into one of the three tiers above before it ships, not after.
