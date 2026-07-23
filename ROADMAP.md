# Roadmap

**Status:** Active — Phase 1 underway as of 2026-07-20.

## Purpose

Sequence the work so P Corp OS gets built "slowly, correctly, layer by layer" without stalling or getting rushed — per FOUNDER_BRIEF.md → Development Philosophy.

## Phases

**Phase 0 — Foundations. Complete as of 2026-07-20.** Documentation and repo structure (this repo), `TECH_STACK.md`'s full decision set, and `ENGINEERING_MANUAL.md`. No production code was written, per the brief's own instruction. Trading robot remained the active priority throughout.

**Phase 1 — The interview. In progress, started 2026-07-20.** Multi-session process where Frank (via Claude) interviews Joshua to build a mental model of his personality, communication, decision-making, values, goals, risk tolerance, etc. (full list in FOUNDER_BRIEF.md → Before Frank Exists). This happens before any Layer 2 code, not alongside it. Open thread within this phase: how interview content gets recorded, especially for sensitive categories (marriage, health, finances) — flagged in `MEMORY_SYSTEM.md`/`SECURITY.md` as needing privacy handling that doesn't exist yet, so nothing sensitive is being committed to this repo verbatim until that's resolved with Joshua directly.

**Phase 2 — Platform layer (Layer 1). Started 2026-07-23.** Build the minimum P Corp OS platform needed to support one real use case end to end. Begun with the desktop UI shell specifically — a static SwiftUI layout (sidebar, War Room center, right rail) with no backend calls, no wired-up logic, and no real data, per Joshua's own phased UI plan (visual shell first, interactivity and intelligence layered in afterward). Memory + sync + the actual Python backend haven't been started yet — this is deliberately UI-first, not the "memory is the foundational system" sequencing floated earlier in `TECH_STACK.md`'s discussion; Joshua chose to start with the shell instead, and that's a legitimate call, not an inconsistency.

**Phase 3 — Frank (Layer 2) + first agent (Layer 3).** Stand up Frank against one real, low-risk agent rather than all twelve at once. Candidate: a read-only Trading Division assistant, since that domain is already deeply understood (see `TRADING_DIVISION.md`).

**Phase 4+ — Expand agents, deepen Alpha Mode and Trading Division integration, build out desktop War Room UX.** Order not yet decided — depends on what Phase 3 reveals.

## Explicitly not decided

- No calendar dates. The brief is explicit about not rushing; a roadmap with dates on a 10-year platform would be exactly the kind of speculative fiction the founder brief warns against.
- What triggers Phase 0 → Phase 1 (a trading-robot milestone? a calendar check-in? Joshua's own call).

## Next step

Nothing — this phase list only needs revisiting when Joshua signals he's ready to move past Phase 0.
