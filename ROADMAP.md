# Roadmap

**Status:** Active — Phase 1 underway as of 2026-07-20.

## Purpose

Sequence the work so P Corp OS gets built "slowly, correctly, layer by layer" without stalling or getting rushed — per FOUNDER_BRIEF.md → Development Philosophy.

## Phases

**Phase 0 — Foundations. Complete as of 2026-07-20.** Documentation and repo structure (this repo), `TECH_STACK.md`'s full decision set, and `ENGINEERING_MANUAL.md`. No production code was written, per the brief's own instruction. Trading robot remained the active priority throughout.

**Phase 1 — The interview. In progress, started 2026-07-20.** Multi-session process where Frank (via Claude) interviews Joshua to build a mental model of his personality, communication, decision-making, values, goals, risk tolerance, etc. (full list in FOUNDER_BRIEF.md → Before Frank Exists). This happens before any Layer 2 code, not alongside it. Open thread within this phase: how interview content gets recorded, especially for sensitive categories (marriage, health, finances) — flagged in `MEMORY_SYSTEM.md`/`SECURITY.md` as needing privacy handling that doesn't exist yet, so nothing sensitive is being committed to this repo verbatim until that's resolved with Joshua directly.

**Phase 2 — Platform layer (Layer 1). Started 2026-07-23.** Build the minimum P Corp OS platform needed to support one real use case end to end.

Begun with the desktop UI shell — a static SwiftUI layout (sidebar, War Room center, right rail), per Joshua's own phased UI plan (visual shell first, interactivity and intelligence layered in afterward). By 2026-07-24 the shell had grown well past static: real navigation, dark mode, a working particle-based presence for Frank, keyboard shortcuts, an app icon, and the visual/logo work all landed — see `UI_GUIDELINES.md` for the full decision log.

**Backend started 2026-07-24.** First real Python service (`backend/`, FastAPI via `uv`) proving the IPC contract decided in `TECH_STACK.md` — a `/health` endpoint and a `/ws` WebSocket that streams responses back — and the SwiftUI shell's "Talk to Frank" input is now genuinely wired to it. Started echo-first to prove the IPC plumbing independent of LLM complexity, then upgraded the same day to real Claude reasoning: the plain `anthropic` SDK (not the Agent SDK — see `TECH_STACK.md` for why), a real system prompt distilled from `PERSONALITY_SPEC.md` (`backend/app/personality.py`), and conversation persistence in SQLite (`backend/app/db.py`) — one continuous conversation, loaded from disk on connect, matching "there is only ever one Frank." **Verified end-to-end 2026-07-24**, sooner than the "next week" originally planned: Joshua added a real Anthropic API key to `backend/.env`, and the full path — SwiftUI "Talk to Frank" input → WebSocket → Python backend → real Claude reasoning → streamed response back into the UI, with SQLite persistence confirmed across separate connections — genuinely works. First real conversation with Frank in the project's history.

**Typed memory records, same day.** `MEMORY_SYSTEM.md` — previously a stub — now has a working first layer: durable facts/context (`backend/app/memory.py`, `backend/app/db.py`), separate from raw conversation history, reusing the existing Claude Code memory scheme's four types. Frank's first tool call: one hardcoded `save_memory` tool, deliberately distinct from (and much smaller-risk than) the deferred Agent SDK. Verified: Frank saved a real memory mid-conversation, and a fresh connection recalled it unprompted.

**Memory made visible, same day.** One of the shell's 9 placeholder sections ("Frank") is now real — a read-only view of everything in `memory_records`, backed by a new `GET /memory` endpoint. Closes the loop: memory isn't just something Frank privately writes to disk anymore, Joshua can actually see what's been remembered.

The full per-device-keypair auth and `SMAppService` packaging haven't been started — flagged as explicit next steps, not forgotten. Real *agentic* Frank (general tool-use, the Agent SDK) is still Phase 3, gated on `SECURITY.md`'s permission model.

**Phase 3 — Frank (Layer 2) + first agent (Layer 3).** Stand up Frank against one real, low-risk agent rather than all twelve at once. Candidate: a read-only Trading Division assistant, since that domain is already deeply understood (see `TRADING_DIVISION.md`).

**Phase 4+ — Expand agents, deepen Alpha Mode and Trading Division integration, build out desktop War Room UX.** Order not yet decided — depends on what Phase 3 reveals.

## Explicitly not decided

- No calendar dates. The brief is explicit about not rushing; a roadmap with dates on a 10-year platform would be exactly the kind of speculative fiction the founder brief warns against.

## Priority check-in (2026-07-24)

Asked directly, after a status review against `FOUNDER_BRIEF.md`'s "Current Priority" section (which names the trading robot as the actual priority, P Corp OS as the long-term background project): several consecutive sessions of substantial P Corp OS build time had accumulated, worth a deliberate check rather than assuming momentum should continue by default. **Joshua confirmed: trading robot stays the priority.** P Corp OS work pauses here, not abandoned — Phase 2 is mid-flight (working shell, backend, and first memory layer), just not the next thing to pick up by default.

**Resumed 2026-07-24, explicitly at Joshua's request** (not by default/momentum — matches the guidance above). Asked which Layer 1 gap to build next (auth, cloud sync, or `SECURITY.md`'s permission model); Joshua chose `SECURITY.md`, since it's the explicit gate already blocking general tool-use and eventually the Trading Division integration. Now has a real, decided permission model (threat model scoped to what actually exists today, a three-tier tool classification borrowed directly from the same framework governing Claude's own actions this whole project) — see `SECURITY.md`. Deliberately document-only this pass: the local-auth-token gap it identified (no auth at all on the backend today) is real but was kept as a separate, explicitly flagged next step rather than bundled in.

## Next step

Add the local-auth-token check to the backend (`SECURITY.md`'s own flagged next step) — the one concrete gap identified but not yet fixed.
