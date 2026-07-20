# Tech Stack

**Status:** Skeleton — UI shell platform is decided; backend language, database, sync, and auth are still open.

## Purpose

Record the technology choices for each layer, with the trade-offs that justified them — not just the final pick.

## Decided (from FOUNDER_BRIEF.md)

- Primary experience is a desktop application, not a web application.
- Mobile is a companion app, not the primary surface.

## Decided (2026-07-20)

- **Platform scope: Apple-only.** Desktop is macOS; mobile companion is iOS. No Windows/Linux requirement — this is a deliberate choice, not an oversight, and should be revisited explicitly (not silently) if that ever changes (e.g. if Nick, Raoof, or a future hire need non-Apple access).
- **Desktop UI shell: native SwiftUI.** Chosen over Electron and Tauri. Rationale: (1) highest ceiling for the "headquarters, not an app" feel the Founder Brief calls for — real menu bar integration, native notifications, OS keychain, Spotlight-style quick actions; (2) SwiftUI is Apple's shared UI framework across macOS and iOS, so the iOS companion app can reuse real code and patterns from the desktop shell rather than being a fully separate build — this is the most direct way to satisfy "one Frank, seamless across devices" at the UI layer. Electron was ruled out once cross-platform reach stopped being a requirement (its main advantage), leaving it the heaviest option for no corresponding benefit. Tauri remains a credible fallback if a strong reason emerges to keep the UI layer in TypeScript instead of Swift, but was not chosen because it forces a second, separate mobile codebase.
- **Frank's intelligence layer runs as a separate local service**, not inside the SwiftUI app itself, communicating with the UI shell over local IPC. This decouples Frank/agent logic from the UI framework choice — the backend can be Python or TypeScript (see open questions) regardless of the shell being native.

## Open questions

- Backend language for Frank/agents: Python vs. TypeScript, running as the local service the SwiftUI shell talks to. Claude Agent SDK is available in both; this is now a narrower, more concrete decision than it was before the UI shell was picked.
- Local IPC mechanism between the SwiftUI shell and the Frank backend service (e.g. local HTTP/gRPC, XPC, something else).
- Backend/sync: self-hosted vs. managed cloud backend for the automatic memory/task/project/conversation sync across devices.
- Database for memory/state.
- Auth provider/approach for Layer 1.
- iOS companion specifics: how much of the SwiftUI desktop code is literally shared vs. adapted per-platform (this is a real question even with SwiftUI — "shared framework" isn't "zero mobile-specific work").

## Next step

Backend language (Python vs. TypeScript) is the next concrete decision — worth its own trade-off discussion rather than folding into this one, since it determines the Claude Agent SDK integration path and a good chunk of `ENGINEERING_MANUAL.md`.
