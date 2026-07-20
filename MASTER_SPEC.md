# Master Spec

**Status:** Not started.

## Purpose

The full functional and technical specification of P Corp OS: features, data models, APIs, agent contracts. This is where architecture (`ARCHITECTURE.md`) turns into something buildable.

## Decided

Nothing yet beyond what's already captured in `ARCHITECTURE.md` — the three-layer split, desktop-first with mobile companion, single synced Frank instance.

## Why this is empty

Writing a master spec before the platform layer's core decisions (tech stack, memory architecture) are locked would produce a document that's wrong by the time implementation starts. This file exists as a placeholder and an index of what needs specifying, not a draft.

## What needs specifying, once ready

- Layer 1 data model (users, settings, permissions, memory, sync state)
- Frank's reasoning/coordination contract with agents
- Agent interface/contract (how an agent registers, what it can access, how it reports back)
- Sync protocol across devices
- Notification and permission model

## Next step

Write this once `TECH_STACK.md` and `ARCHITECTURE.md`'s open questions are resolved and there's a first concrete system (likely the memory system) to spec against.
