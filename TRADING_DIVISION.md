# Trading Division

**Status:** Skeleton — relationship to the trading robot is decided, integration mechanism is not.

## Purpose

Define how Frank eventually assists the trading robot/division without absorbing or duplicating it.

## Decided (from FOUNDER_BRIEF.md)

The trading robot (built separately, in its own repo) remains its own system — it does not get rebuilt inside P Corp. Frank should eventually assist with: research, backtesting, performance analysis, risk analysis, optimization, documentation, statistics, version tracking, development, and growing small trading accounts.

## Open questions

- Integration boundary: does Frank start as a read-only reporting/analysis agent over the trading repo's existing outputs, or get deeper hooks into the EA codebase itself?
- How much of the validation work already happening in the trading repo (walkforward testing, edge validation) could eventually be delegated to a Frank trading agent, versus staying manual/Joshua-driven?
- Does "assist growing small trading accounts" imply live account access/actions eventually — which would push hard on `SECURITY.md`'s permission-boundary questions.

## Next step

Likely candidate for Frank's first real specialized agent (see `ROADMAP.md` → Phase 3), precisely because this domain is already deeply understood and validated — low ambiguity, high familiarity. Not started until the trading robot itself is stable and Joshua has bandwidth to shift focus.
