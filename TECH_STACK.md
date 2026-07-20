# Tech Stack

**Status:** Skeleton — UI shell platform, backend language, and IPC mechanism are decided; process lifecycle, database, sync, and auth are still open.

## Purpose

Record the technology choices for each layer, with the trade-offs that justified them — not just the final pick.

## Decided (from FOUNDER_BRIEF.md)

- Primary experience is a desktop application, not a web application.
- Mobile is a companion app, not the primary surface.

## Decided (2026-07-20)

- **Platform scope: Apple-only.** Desktop is macOS; mobile companion is iOS. No Windows/Linux requirement — this is a deliberate choice, not an oversight, and should be revisited explicitly (not silently) if that ever changes (e.g. if Nick, Raoof, or a future hire need non-Apple access).
- **Desktop UI shell: native SwiftUI.** Chosen over Electron and Tauri. Rationale: (1) highest ceiling for the "headquarters, not an app" feel the Founder Brief calls for — real menu bar integration, native notifications, OS keychain, Spotlight-style quick actions; (2) SwiftUI is Apple's shared UI framework across macOS and iOS, so the iOS companion app can reuse real code and patterns from the desktop shell rather than being a fully separate build — this is the most direct way to satisfy "one Frank, seamless across devices" at the UI layer. Electron was ruled out once cross-platform reach stopped being a requirement (its main advantage), leaving it the heaviest option for no corresponding benefit. Tauri remains a credible fallback if a strong reason emerges to keep the UI layer in TypeScript instead of Swift, but was not chosen because it forces a second, separate mobile codebase.
- **Frank's intelligence layer runs as a separate local service**, not inside the SwiftUI app itself, communicating with the UI shell over local IPC. This decouples Frank/agent logic from the UI framework choice.
- **Backend language: Python**, via the Claude Agent SDK. Rationale: Trading Division is the flagged likely first real specialized agent (`ROADMAP.md` → Phase 3, `TRADING_DIVISION.md`), and the existing trading-robot repo's analysis/backtesting/statistics tooling is already Python (135 Python files vs. 19 MQL5 files, confirmed 2026-07-20) — the EA itself is MQL5, but every layer of walkforward/edge validation on top of it is Python. Building Frank's backend in Python means direct reuse of, and familiarity with, that existing tooling, rather than a second implementation or a cross-language shell-out. TypeScript's main advantage (sharing a language with the UI shell) no longer applies now that the shell is native Swift; its remaining edge (event-loop concurrency) is a theoretical advantage for a personal assistant's load, not a concrete one, and doesn't outweigh the Trading Division fit.
- **IPC mechanism: local HTTP + WebSocket, served by the Python backend (FastAPI), bound strictly to `127.0.0.1` with a local auth token.** REST endpoints handle simple request/response calls; a WebSocket connection carries streaming Frank responses (token-by-token) and unprompted push notifications from Frank to the UI (serving Layer 1's "Notifications" responsibility). Chosen over XPC, a raw Unix domain socket, and gRPC because it's the only option that is simultaneously (a) native to Python's ecosystem, (b) capable of real streaming and server-initiated push, and (c) the *same interface* that can later be exposed for remote/mobile access — bound to a real network address behind proper auth and TLS instead of loopback — rather than a separate integration. XPC and Unix sockets were ruled out specifically because they're local-only by design and would have to be rebuilt once iOS/remote sync (per FOUNDER_BRIEF.md → Platforms) becomes real; gRPC was ruled out because maintaining protobuf schemas across Swift and Python is ongoing overhead this scale doesn't justify.

## Open questions

- Process lifecycle: whether the Python backend is spawned by the SwiftUI app on launch (simpler, but Frank only exists while the app is open) vs. runs as a persistent background service via `launchd` (lets Frank push notifications and do background agent work even when the UI is closed — closer to the "second brain" framing, but adds real service-management complexity). Directly relevant now that the backend is a long-lived HTTP/WebSocket server rather than something spawned per-call.
- Backend/sync: self-hosted vs. managed cloud backend for the automatic memory/task/project/conversation sync across devices.
- Database for memory/state.
- Auth provider/approach for Layer 1 (the local auth token used for loopback access today is not a substitute for this — it only secures the local connection, not the eventual remote/multi-device story).
- Packaging: how a Python backend service gets bundled and shipped alongside a native macOS app (bundled runtime, separate installed dependency, etc.) — not yet solved, flagged here so it isn't forgotten.
- iOS companion specifics: how much of the SwiftUI desktop code is literally shared vs. adapted per-platform (this is a real question even with SwiftUI — "shared framework" isn't "zero mobile-specific work").

## Next step

Process lifecycle (spawned-by-app vs. persistent `launchd` service) is the next concrete decision — it was surfaced directly by locking in a long-lived local server and determines whether Frank can be proactive when the UI isn't open.
