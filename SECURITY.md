# Security

**Status:** First real permission model decided (2026-07-24) — scoped to what actually exists today, not the full 10-year vision. Credential storage across a future multi-device/cloud-sync setup remains genuinely open.

## Purpose

Define the security principles P Corp OS operates under — non-negotiable given it will eventually hold personal, business, and financial data, and agents that can take real-world actions (trading, email, etc.).

## Decided (from FOUNDER_BRIEF.md)

Authentication, security, and permissions are explicitly owned by Layer 1 (P Corp OS platform) — not scattered across Frank or individual agents.

## Decided (2026-07-24)

- **Threat model, scoped to what's real today, not speculative.** Right now: one machine, no cloud sync, one client (the desktop app) talking to a backend already bound to `127.0.0.1` only (`TECH_STACK.md`). The two real, current risks: (1) **no auth at all today** — any other local process on this Mac could connect to the backend and impersonate the desktop app; (2) as more tools get added beyond `save_memory`, there's no consistent, auditable way to reason about what a given tool is allowed to do before it does it. The full future threat model (device compromise, cloud-provider breach, a compromised agent) matters once those things exist — revisit this section when cloud sync or a second device becomes real, not before.
- **Permission model for agent/tool actions: a three-tier classification**, deliberately modeled on the same framework that's governed every action Claude has taken building this project — a pattern already proven across an entire real working session, not invented from scratch:
  - **Regular (auto-allowed):** local-only, reversible, no external effect. Frank's current tool, `save_memory`, is classified here — it only writes to the local `memory_records` SQLite table, nothing leaves the device, any record can be corrected or removed later.
  - **Needs explicit confirmation:** anything with a real external effect or that's hard to reverse — a live trading action, sending an email, writing to Alpha Mode's real CRM, anything crossing outside this device. No tool in this tier exists yet; the rule is decided so the *next* tool gets classified deliberately, not defaulted into "regular" just because that's what existed so far.
  - **Prohibited, regardless of confirmation:** credentials/API keys/payment details, permanent data deletion, financial transfers, anything bypassing another system's own security controls. Mirrors the hard-line list already governing this entire project (e.g., Frank's API key has never been pasted into chat, only ever edited directly in `.env` by Joshua).
  - New tools must be classified into one of these tiers before being added — not an afterthought once something's already built and working, matching `ENGINEERING_MANUAL.md`'s existing "no exceptions" code-review discipline.
- **What this decision does NOT cover yet, on purpose:** the actual enforcement mechanism for the "needs confirmation" tier (there's nothing to enforce until a tool exists that needs it — building a confirmation-pause pipeline now would be speculative machinery for a hypothetical tool); the local-auth-token fix for the "no auth at all" gap identified above (real, but deliberately deferred as a separate, smaller next step rather than bundled into this document-only pass); full per-device keypair auth and credential storage across a future multi-device/cloud-sync setup (still genuinely open, unchanged from before — see `TECH_STACK.md`'s own auth section).

## Open questions

- The local-auth-token gap identified above — real and known, not yet fixed.
- Credential storage and secrets management across desktop + mobile + any cloud sync backend, once those exist.
- Data-at-rest and in-transit approach for cloud sync, once that's built.
- What P Corp OS builds itself vs. relies on the host OS or a cloud provider (e.g., OS keychain, managed auth provider) for.

## Next step

Add the local-auth-token check to the backend (both the WebSocket and REST endpoints) — the one concrete, scoped gap this pass identified but deliberately didn't fix. Beyond that: revisit this document every time a new tool or agent is added, to classify it into one of the three tiers above before it ships, not after.
