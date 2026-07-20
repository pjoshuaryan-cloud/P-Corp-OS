# Engineering Manual

**Status:** Active — first real draft, written now that `TECH_STACK.md`'s core decisions are locked in. Expect this to get refined once actual implementation starts and reveals gaps this draft didn't anticipate; that's normal, not a failure of the draft. Update it when that happens rather than letting it go stale.

## Purpose

Coding standards, repo conventions, branching/review process, testing philosophy, and documentation discipline — written to hold up across a decade, for a codebase built by a solo founder plus an AI pair-programmer, and eventually by agents proposing changes to their own operating environment.

## Code review policy — read this first

Every code change goes through the same gate, regardless of who or what wrote it: a pull request, explicit human review, explicit approval before merge to `main`. This applies identically to:

- Code Joshua writes himself
- Code written with Claude Code's assistance
- Code eventually proposed by Frank or any Layer 3 agent, once that's real

No exception for "the AI probably got it right." This isn't a new idea — it's FOUNDER_BRIEF.md's own Working Rules (never assume, wait for approval) turned into an actual enforced process instead of a stated intention. Every decision in this repo so far — every `TECH_STACK.md` entry — has gone through explain → trade-offs → recommend → wait for approval before being written down; code should get the same discipline documentation has had from day one.

As agents (Layer 3) become capable of proposing real code changes, this is the single most important guardrail in the entire engineering process. It's what keeps "easy to add agents" (`ARCHITECTURE.md`) from quietly turning into "agents that modify their own operating environment unsupervised."

## Repo layout

**Monorepo.** One repository holds the SwiftUI desktop app (and eventually the iOS companion), the Python backend (Frank + agents), and this documentation set.

Rationale: the SwiftUI shell and Python backend are tightly coupled through the IPC contract decided in `TECH_STACK.md`, and are expected to evolve together — a monorepo makes a contract change an atomic commit instead of a coordinated cross-repo PR. One CI pipeline, one git history, consistent with this repo already being the single source of truth for the whole project.

Not permanent by default: if an individual Layer 3 agent grows substantial enough to warrant independent versioning or its own release cadence, it can be split into its own repo later. That's a reversible operational choice, not a structural commitment — the same phasing pattern used for sync hosting and process lifecycle in `TECH_STACK.md`.

Actual directory structure isn't specified yet. It should emerge from the first real prototype (`ROADMAP.md` → Phase 2/3), not be designed in the abstract before any code exists — designing a folder tree for code that doesn't exist yet is the same speculative-fiction risk this whole documentation pass has been avoiding.

## Languages & tooling

**Swift** (desktop shell, eventually iOS companion)
- Tests: XCTest
- Style: swift-format / SwiftLint
- Concurrency: native async/await, consistent with the WebSocket-based streaming design in `TECH_STACK.md`

**Python** (Frank + agent backend)
- Tests: pytest
- Lint + format: ruff
- Type checking: mypy or pyright — not decided yet, both are credible; pick one when the first real Python module is written rather than deciding in the abstract now
- Dependency management: uv, consistent with the packaging decision in `TECH_STACK.md`

**Cross-boundary**
- Integration tests exercise the real IPC contract — spin up the actual FastAPI server, hit it from a test client — rather than only unit-testing each side of the Swift/Python boundary in isolation. A change to the WebSocket/REST contract should have a test that fails if either side silently drifts from it.

## Git workflow

Trunk-based development with short-lived feature branches. No GitFlow-style release branches, hotfix branches, or long-lived develop branches — that ceremony solves a team-coordination problem this project doesn't have.

- `main` is always the source of truth.
- Non-trivial changes go through a branch + PR, even solo — the PR is the actual mechanism that makes the code review policy above enforceable. "Review before merge" needs something to review.
- Trivial documentation-only changes may be committed directly to `main`, consistent with how this repo has operated so far.
- Commit messages state the *why*, not just a summary of the diff. Every decision commit in this repo's history explains the rationale and the alternatives ruled out; that discipline carries into real code commits too, not just documentation ones.

## Documentation discipline

A change isn't done until the docs describing it are updated in the same change:

- `TECH_STACK.md`, `ARCHITECTURE.md`, etc. get updated when a decision they describe changes.
- `README.md`'s document-index status column reflects reality.
- `CHANGELOG.md` gets an entry.

This is the exact discipline this repo has followed for every decision so far. It doesn't start once "real" code shows up — it continues.

## Testing philosophy

- Tests should exist for behavior that matters, not for coverage-percentage's own sake. No test-writing busywork.
- Given a decade-long horizon and a small team (solo founder plus AI pair-programmer, eventually agents), regression protection matters more than exhaustive edge-case coverage early on — prioritize tests that catch "did this change break something that used to work," especially across the Swift/Python IPC boundary and anything touching auth, sync, or the database.
- Security-sensitive code — auth/keypair handling, Keychain access, anything touching the sync layer — warrants deeper review and test coverage than average. Connects directly to `SECURITY.md`, still a stub, and should inform it once that document gets written for real.

## Open questions

- CI/CD: what actually runs on each PR (build both Swift and Python? run the full integration suite?) — not designed yet; decide once there's real code to run CI against, not speculatively.
- mypy vs. pyright for Python type checking — deferred to the first real Python module.
- Versioning/release process for the shipped app itself (distinct from this repo's own commit history) — not needed until there's something to ship.
- Dependency update policy over a 10-year horizon — not urgent, flagged so it isn't forgotten.

## Next step

This document becomes load-bearing once Phase 2 (`ROADMAP.md`) begins — the first real prototype. Expect it to reveal gaps that weren't anticipated here; update it then rather than trying to anticipate everything now.
