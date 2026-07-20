# Tech Stack

**Status:** Stub — deliberately undecided today (see repo `CHANGELOG.md` for why this was scoped out of the first pass).

## Purpose

Record the technology choices for each layer, with the trade-offs that justified them — not just the final pick.

## Decided (from FOUNDER_BRIEF.md)

- Primary experience is a desktop application, not a web application.
- Mobile is a companion app, not the primary surface.

That's it — no framework, language, database, or hosting decisions have been made.

## Open questions

- Desktop framework: native (Swift/AppKit) vs. cross-platform (Tauri, Electron) — trade-off between "premium, native-feeling War Room UX" (favors native) and "one codebase, faster iteration, easier mobile companion reuse" (favors Tauri/Electron + a shared web-tech layer).
- Backend/sync: self-hosted vs. managed cloud backend for the automatic memory/task/project/conversation sync across devices.
- LLM orchestration: Claude Agent SDK is the natural default given it's already in active use, but this should be a deliberate decision once Layer 2/3 requirements exist, not an assumption.
- Database for memory/state.
- Auth provider/approach for Layer 1.
- Mobile framework (native per-platform vs. shared with desktop).

## Next step

This is the first genuinely open engineering decision in the project — a good candidate for a dedicated session once Joshua wants to move on it. Should be approached the way FOUNDER_BRIEF.md's Working Rules demand: objective, trade-offs, recommendation, wait for approval — not decided inside a documentation pass.
