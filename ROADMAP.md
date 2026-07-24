# Roadmap

**Status:** Active — Phase 1 underway as of 2026-07-20.

## Purpose

Sequence the work so P Corp OS gets built "slowly, correctly, layer by layer" without stalling or getting rushed — per FOUNDER_BRIEF.md → Development Philosophy.

## Phases

**Phase 0 — Foundations. Complete as of 2026-07-20.** Documentation and repo structure (this repo), `TECH_STACK.md`'s full decision set, and `ENGINEERING_MANUAL.md`. No production code was written, per the brief's own instruction. Trading robot remained the active priority throughout.

**Phase 1 — The interview. In progress, started 2026-07-20.** Multi-session process where Frank (via Claude) interviews Joshua to build a mental model of his personality, communication, decision-making, values, goals, risk tolerance, etc. (full list in FOUNDER_BRIEF.md → Before Frank Exists). This happens before any Layer 2 code, not alongside it. Open thread within this phase: how interview content gets recorded, especially for sensitive categories (marriage, health, finances) — flagged in `MEMORY_SYSTEM.md`/`SECURITY.md` as needing privacy handling that doesn't exist yet, so nothing sensitive is being committed to this repo verbatim until that's resolved with Joshua directly.

**Phase 2 — Platform layer (Layer 1). Started 2026-07-23.** Build the minimum P Corp OS platform needed to support one real use case end to end.

Begun with the desktop UI shell — a static SwiftUI layout (sidebar, War Room center, right rail), per Joshua's own phased UI plan (visual shell first, interactivity and intelligence layered in afterward). By 2026-07-24 the shell had grown well past static: real navigation, dark mode, a working particle-based presence for Frank, keyboard shortcuts, an app icon, and the visual/logo work all landed — see `UI_GUIDELINES.md` for the full decision log.

**Backend started 2026-07-24.** First real Python service (`backend/`, FastAPI via `uv`) proving the IPC contract decided in `TECH_STACK.md` — a `/health` endpoint and a `/ws` WebSocket that streams responses back — and the SwiftUI shell's "Talk to Frank" input is now genuinely wired to it. Deliberately scoped as echo-first: the backend sends back canned, streamed responses, not real Claude Agent SDK reasoning yet, so the IPC plumbing itself gets proven independently of LLM complexity. Real Frank intelligence is Phase 3. Memory/SQLite, the full per-device-keypair auth, and `SMAppService` packaging haven't been started — flagged as explicit next steps, not forgotten.

**Phase 3 — Frank (Layer 2) + first agent (Layer 3).** Stand up Frank against one real, low-risk agent rather than all twelve at once. Candidate: a read-only Trading Division assistant, since that domain is already deeply understood (see `TRADING_DIVISION.md`).

**Phase 4+ — Expand agents, deepen Alpha Mode and Trading Division integration, build out desktop War Room UX.** Order not yet decided — depends on what Phase 3 reveals.

## Explicitly not decided

- No calendar dates. The brief is explicit about not rushing; a roadmap with dates on a 10-year platform would be exactly the kind of speculative fiction the founder brief warns against.
- What triggers Phase 0 → Phase 1 (a trading-robot milestone? a calendar check-in? Joshua's own call).

## Next step

Nothing — this phase list only needs revisiting when Joshua signals he's ready to move past Phase 0.
