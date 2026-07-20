# Architecture

**Status:** Skeleton — layer boundaries are decided; nothing inside each layer is designed yet.

## Purpose

Define how P Corp OS is structured so that layers stay decoupled, agents stay easy to add, and the platform survives 10+ years of change.

## Decided (from FOUNDER_BRIEF.md)

Three layers:

**Layer 1 — P Corp OS (the platform).** Owns: authentication, security, cloud sync, settings, memory, notifications, permissions, integrations, database, device synchronization.

**Layer 2 — Frank (the executive intelligence).** Reasons, learns, plans, researches, coordinates, automates, delegates, communicates. Frank is not a product surface — he's the intelligence the platform exposes.

**Layer 3 — Specialized agents.** Research, trading, operations, creative, marketing, finance, coding, calendar, email, documents, legal research, client success. Must be easy to add — new agents should not require touching Layer 1 or 2 internals.

Cross-cutting constraint: there is only ever one Frank. Every device (desktop primary, mobile companion) connects to the same intelligence; memory, tasks, projects, and conversations sync automatically.

## Open questions

- What is the actual mechanism for "easy to add" agents — a plugin/SDK contract, sandboxed processes, something else? What does an agent's interface to Frank look like concretely?
- Is Frank an orchestrator that calls agents as tools, a peer that delegates, or something else architecturally?
- Where does memory physically live, and what makes sync "automatic" — a central cloud store Frank/agents read from, or per-device stores reconciled?
- How much of Layer 2/3 can build on the Claude Agent SDK (already in use for this session) vs. needs custom infrastructure?
- What's the trust/permission boundary between an agent and the data it can touch (e.g., should the email agent be able to read financial data)?

## Next step

Architecture can't get concrete until there's a first real target to design against — most likely the memory system plus one low-risk agent (see `MEMORY_SYSTEM.md`, `TRADING_DIVISION.md`). Don't design Layer 1 in the abstract; design it against that first use case, then generalize.
