# Engineering Manual

**Status:** Not started.

## Purpose

Coding standards, repo conventions, branching/review process, testing philosophy, and documentation discipline for a codebase meant to last a decade.

## Decided

Nothing yet — no language, framework, or repo layout has been chosen (see `TECH_STACK.md`).

## Why this is empty

A style guide and workflow for a stack that doesn't exist yet would be guesswork. This file is a placeholder and an index of what needs deciding, not a draft.

## What needs deciding, once ready

- Language(s) and framework(s) per layer
- Monorepo vs. polyrepo (P Corp OS platform, Frank, agents, mobile — one repo or several?)
- Testing strategy and CI/CD
- Code review process — notably, this project may eventually have Frank agents proposing or writing code themselves, which is a review-process question most engineering manuals don't have to answer
- Documentation discipline: how docs in this repo stay in sync with what's actually built (this repo's own stub files are the first test of that discipline)

## Next step

Write this once `TECH_STACK.md` is decided and before the first line of platform code is written — per FOUNDER_BRIEF.md → Development Philosophy, every layer should be planned before it's built.
