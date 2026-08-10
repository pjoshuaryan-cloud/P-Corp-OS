# War Room

**Status:** Built and in daily use — the primary interface, not a stub. This doc previously said "the contents aren't decided" long after that stopped being true; rewritten 2026-08-10 to match reality, caught by a full-codebase audit against a new feature spec.

## Purpose

Define what actually appears on the home screen / mission-control surface — the first thing Joshua sees when he opens the app.

## Decided (from FOUNDER_BRIEF.md)

The home screen should eventually become the War Room — Mission Control. It should feel like entering headquarters, not opening an app: purposeful, minimal, professional, disciplined, premium, communicating readiness/clarity/focus.

## What actually exists

- **Live Frank chat** — real streaming replies, push-to-talk voice in, spoken voice out (ElevenLabs with a local Piper fallback), searchable date-grouped conversation history, and (2026-08-06 onward) image upload with real Claude vision — including Design Agent's Design Critic actually seeing an attached image directly, not a description of it.
- **Today's Agenda** (right rail) — real macOS Calendar data via AppleScript, not placeholder.
- **Frank's Insights** (right rail) — real computed insights (overdue/soon-due Alpha Mode invoices and Operations tasks, plus Opportunity Radar's warm/hot-lead-needs-follow-up signal, 2026-08-10), deliberately not LLM-generated (cost/hallucination risk for what's just date comparisons over data that already exists), with an honest empty state when nothing's due.
- **Mission Status** (right rail) — the "Focus: ..." line is now real (Focus Lock, 2026-08-10): Frank can set it via `set_focus_objective`, persisted in `app_state`, fetched live over `GET /focus`. Deliberately scoped small — the tagline ("Create Leverage. Freedom Tomorrow.") and the 68% progress bar are still static/hardcoded; Focus Lock only ever committed to making the objective line itself real, not the rest of the card.
- **Situation Room banner** (top of War Room, above the chat, 2026-08-10) — a deliberately separate, more prominent surface from Insights: only appears when something crosses a real severity threshold (invoice 30+ days overdue, task 14+ days overdue, client outreach 45+ days stale), red-accented, meant to read as "interrupt" rather than routine list. Empty (hidden entirely) the common case.
- **Quick Actions** (right rail) — 2 of 4 buttons are real ("Ask Frank", voice-adjacent); "New Mission" and "Run Report" are still no-ops in the code.

## Open questions

- Whether the tagline and progress bar ever become real, and what the progress bar would even measure — not scoped or decided.
- Whether Situation Room's thresholds (30/14/45 days) are right — first-guess numbers, not tuned against real usage.
- The two remaining no-op Quick Action buttons.

## Next step

No concrete next step identified for this screen specifically — revisit if a future feature names a reason to add to it.
