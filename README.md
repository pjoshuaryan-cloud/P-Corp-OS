# P Corp OS

A personal AI operating system, built layer by layer over a multi-year horizon. Not a product for others — an operating environment for Joshua Peters, with an executive-intelligence layer named **Frank** at its center.

**Phase:** 2 — platform layer (desktop UI shell started 2026-07-23). Phase 0 (foundations) and the Phase 1 interview baseline are complete; Phase 1 continues informally per FOUNDER_BRIEF.md. See `ROADMAP.md`.

## Start here

Every session working on this repo should begin by reading, in order:
1. [`FOUNDER_BRIEF.md`](FOUNDER_BRIEF.md) — the authoritative source of truth: vision, philosophy, architecture, working rules.
2. [`MASTER_SPEC.md`](MASTER_SPEC.md) — functional/technical specification (not started).
3. [`ENGINEERING_MANUAL.md`](ENGINEERING_MANUAL.md) — coding standards and process (not started).

Then: summarize your understanding, flag any architectural concerns, and propose a plan. Wait for approval before writing production code. This is a standing rule, not a one-time instruction — see `FOUNDER_BRIEF.md` → Working Rules.

## Document index

| Document | Purpose | Status |
|---|---|---|
| [FOUNDER_BRIEF.md](FOUNDER_BRIEF.md) | Vision, philosophy, architecture, working rules | Authoritative |
| [MASTER_SPEC.md](MASTER_SPEC.md) | Functional/technical spec | Stub |
| [ENGINEERING_MANUAL.md](ENGINEERING_MANUAL.md) | Coding standards, process | Active |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture (3 layers) | Skeleton |
| [ROADMAP.md](ROADMAP.md) | Phased plan | Active — Phase 1 underway |
| [TECH_STACK.md](TECH_STACK.md) | Technology decisions | Skeleton — all core decisions made; only iOS companion specifics open |
| [UI_GUIDELINES.md](UI_GUIDELINES.md) | Design philosophy ("War Room") | Active |
| [PERSONALITY_SPEC.md](PERSONALITY_SPEC.md) | Frank's personality/voice | Active |
| [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) | Cross-device memory architecture | Stub |
| [WAR_ROOM.md](WAR_ROOM.md) | Home-screen / mission-control UX | Stub |
| [ALPHA_MODE.md](ALPHA_MODE.md) | Alpha Mode Media integration | Skeleton |
| [TRADING_DIVISION.md](TRADING_DIVISION.md) | Relationship to the trading robot | Skeleton |
| [SECURITY.md](SECURITY.md) | Security principles | Stub |
| [CHANGELOG.md](CHANGELOG.md) | Log of what actually changed, when | Active |

"Skeleton" = grounded only in decisions already stated in the Founder Brief, plus explicit open questions. "Stub" = purpose and open questions only, no decisions made yet. Nothing here should read as more finished than it is — see `FOUNDER_BRIEF.md` → Working Rules on not writing speculative fiction ahead of real design work.

## Code

`desktop/` — the SwiftUI desktop shell, a Swift Package Manager executable (no Xcode project yet — see `ENGINEERING_MANUAL.md` → Repo layout). Static visual layout only right now: sidebar, War Room center, right rail. No backend, no wired-up logic, no real data. Build and run with:

```
cd desktop && swift run
```

No `backend/` yet — the Python backend hasn't been started.

## Current priority

The trading robot (separate repo) is the active priority. P Corp OS work is intentionally paced behind it — see `ROADMAP.md` → Phase 0.
