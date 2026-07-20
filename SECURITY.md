# Security

**Status:** Stub — ownership is decided, no threat model or controls exist yet.

## Purpose

Define the security principles P Corp OS operates under — non-negotiable given it will eventually hold personal, business, and financial data, and agents that can take real-world actions (trading, email, etc.).

## Decided (from FOUNDER_BRIEF.md)

Authentication, security, and permissions are explicitly owned by Layer 1 (P Corp OS platform) — not scattered across Frank or individual agents.

## Open questions

- Threat model: what's actually being protected against (device compromise, cloud provider breach, a compromised agent acting outside its intended scope)?
- Credential storage and secrets management across desktop + mobile + any cloud sync backend.
- Agent sandboxing: specialized agents with real authority (trading, email, calendar) need explicit, auditable permission boundaries — should an agent's access be scoped per-task, per-session, or standing?
- Data-at-rest and in-transit approach, once `TECH_STACK.md` picks a backend.
- What P Corp OS builds itself vs. relies on the host OS or a cloud provider (e.g., OS keychain, managed auth provider) for.

## Next step

Must be drafted before any Layer 1 implementation begins — this is not a bolt-on. Should be revisited every time a new agent with real-world write access (not just read) is added.
