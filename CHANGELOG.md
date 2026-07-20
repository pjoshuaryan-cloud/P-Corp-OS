# Changelog

## 2026-07-20

- Repo created at `~/Desktop/P-Corp`, separate from the trading robot repo, per Joshua's decision.
- Founder Brief received and stored as `FOUNDER_BRIEF.md` (authoritative, v1.0).
- Lean documentation skeleton created: `README.md`, `MASTER_SPEC.md`, `ENGINEERING_MANUAL.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `TECH_STACK.md`, `UI_GUIDELINES.md`, `PERSONALITY_SPEC.md`, `MEMORY_SYSTEM.md`, `WAR_ROOM.md`, `ALPHA_MODE.md`, `TRADING_DIVISION.md`, `SECURITY.md`.
- Scope deliberately limited to what the Founder Brief actually decided, plus explicit open questions — no speculative depth, no tech stack chosen, no production code. Rationale: trading robot remains the active priority (Phase 0, see `ROADMAP.md`).
- **Decided (`TECH_STACK.md`): platform scope is Apple-only (macOS desktop, iOS companion); desktop UI shell is native SwiftUI**, chosen over Electron and Tauri for native feel and direct code/pattern reuse with the iOS companion. Frank's intelligence layer will run as a separate local service (language still open) talking to the SwiftUI shell over local IPC — the UI framework choice does not lock in Frank's backend language.
