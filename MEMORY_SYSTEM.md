# Memory System

**Status:** Stub — purpose is clear, architecture is not.

## Purpose

Give Frank persistent, cross-device memory — the mechanism that actually makes him a "second brain" rather than a stateless chatbot.

## Decided (from FOUNDER_BRIEF.md)

Memory, tasks, projects, and conversations should all synchronize automatically across every device. There is only ever one Frank — no per-device forks of memory or identity.

## Open questions

- This Claude Code environment already has a working file-based memory system (per-project, markdown files with an index) that's actively being used in the trading-robot repo. Worth evaluating explicitly: does P Corp's memory system build on that pattern, replace it, or run alongside it?
- What's the data model — flat notes, typed records (user/feedback/project/reference, as the existing system uses), a graph, something else?
- Privacy boundaries: some of what Frank should remember is deeply personal (marriage, family, health). Does that need separation from business/trading memory, and if so, at what layer (storage, access control, or just convention)?
- Forgetting/versioning: memory that goes stale (a completed project, an outdated goal) needs a lifecycle, not just accumulation.

## Next step

Strong candidate for the first real Layer 1 system to prototype, since almost everything else (Frank, every agent, the War Room) depends on it. Should be designed against a concrete first use case rather than in the abstract — see `ARCHITECTURE.md`.
