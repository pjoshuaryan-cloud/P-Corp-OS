# War Room

**Status:** Built and in daily use — the primary interface, not a stub. This doc previously said "the contents aren't decided" long after that stopped being true; rewritten 2026-08-10 to match reality, caught by a full-codebase audit against a new feature spec.

## Purpose

Define what actually appears on the home screen / mission-control surface — the first thing Joshua sees when he opens the app.

## Decided (from FOUNDER_BRIEF.md)

The home screen should eventually become the War Room — Mission Control. It should feel like entering headquarters, not opening an app: purposeful, minimal, professional, disciplined, premium, communicating readiness/clarity/focus.

## What actually exists

- **Live Frank chat** — real streaming replies, push-to-talk voice in, spoken voice out (ElevenLabs with a local Piper fallback), searchable date-grouped conversation history, and (2026-08-06 onward) image upload with real Claude vision — including Design Agent's Design Critic actually seeing an attached image directly, not a description of it.
- **Today's Agenda** (right rail) — real macOS Calendar data via AppleScript, not placeholder.
- **Frank's Insights** (right rail) — real computed insights (overdue/soon-due Alpha Mode invoices and Operations tasks), deliberately not LLM-generated (cost/hallucination risk for what's just date comparisons over data that already exists), with an honest empty state when nothing's due.
- **Mission Status** (right rail) — still static/hardcoded text and percentage ("Create Leverage. Freedom Tomorrow." / 68%). The one real remaining gap on this screen — a natural first target if Focus Lock (see the additive feature spec) gets built, since that's exactly the real, settable state this card should be showing instead.
- **Quick Actions** (right rail) — 2 of 4 buttons are real ("Ask Frank", voice-adjacent); "New Mission" and "Run Report" are still no-ops in the code.

## Open questions

- Whether/how to surface future capabilities here once real (Focus Lock's objective, Situation Room's alert, Opportunity Radar's surfaced items) — deliberately not designed speculatively ahead of those existing.
- The two remaining no-op Quick Action buttons.

## Next step

Wire up Mission Status to something real once Focus Lock (or an equivalent "current objective" concept) exists — the most concrete, already-identified next step for this screen.
