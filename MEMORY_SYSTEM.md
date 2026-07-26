# Memory System

**Status:** First real layer built and verified, 2026-07-24 — conversation history plus typed memory records both working end to end. Forgetting/versioning added 2026-07-25/26. Semantic search and cross-device sync remain open.

## Purpose

Give Frank persistent, cross-device memory — the mechanism that actually makes him a "second brain" rather than a stateless chatbot.

## Decided (from FOUNDER_BRIEF.md)

Memory, tasks, projects, and conversations should all synchronize automatically across every device. There is only ever one Frank — no per-device forks of memory or identity.

## Decided (2026-07-24)

- **Two separate tables, two lifecycles**, both in the SQLite database `TECH_STACK.md` already settled: `messages` (the single, ever-continuing conversation — see below) and `memory_records` (durable facts/context, independent of any one exchange). Conversation history is not memory; memory is not conversation history — conflating them into one table would make it impossible to reason about what Frank durably knows versus what was just said once.
- **Typed records: the same four types (user/feedback/project/reference) the existing Claude Code memory system uses** — evaluated directly against the open question below, and adopted rather than invented fresh, since Joshua has already seen this scheme work. `user` = a durable fact/preference about Joshua; `feedback` = guidance on how Frank should behave; `project` = state of an ongoing initiative; `reference` = a pointer to an external system. Answers the open "build on it, replace it, or run alongside it" question: P Corp OS's runtime memory is its own SQLite-backed system (it has to be — it's a different environment, a different retrieval mechanism, no Claude Code CLI in the loop), but it deliberately reuses the *scheme*, not the file-based mechanism itself.
- **Creation mechanism: Frank gets exactly one tool, `save_memory`** (`backend/app/memory.py`), via the plain `anthropic` SDK's tool-use/function-calling — asked Joshua directly rather than assumed, since this is Frank's first real tool call of any kind. Explicitly distinguished from the Agent SDK deferral elsewhere in `TECH_STACK.md`: this is one hardcoded action with no file or shell access, a materially smaller risk category, not a reversal of that decision. Chosen over requiring Joshua to manually trigger every save, because proactive capture is what the founder brief's "name patterns unprompted" mandate actually requires — a purely manual mechanism would mean Frank never remembers anything he didn't explicitly ask it to.
- **Retrieval: load every record into the system prompt on each turn**, no ranking or filtering yet. Correct-enough at the record counts a personal system produces early on (dozens, not thousands); revisit only once that stops being true, not speculatively now.
- **Privacy: a plain `sensitive` boolean column, not encryption.** There's no sync yet, so nothing about this table creates new exposure beyond what `messages` already has (both are local-only SQLite, same as before). The flag exists so the eventual encrypt-before-sync work (already flagged in `TECH_STACK.md` for the Turso/libSQL decision) has something to filter on later, without having to retrofit a schema change once sync is real.
- **Forgetting/versioning: explicitly deferred.** No auto-expiry; records only change via manual update/delete (not yet built). A real lifecycle is more machinery than a first pass needs — revisit once stale records actually become a problem in practice, not before.

## Decided (2026-07-25/26)

- **Forgetting: soft-delete (`deleted_at`), not a real DELETE.** Reversible in principle — matches the "regular" permission tier both memory tools sit in (`SECURITY.md`) — and gives a rudimentary audit trail for free: a forgotten row's original content still exists, just excluded from what Frank sees and what the UI shows. Two paths in, one mechanism underneath: Frank's own `forget_memory` tool (matches by title, since row IDs are never surfaced to him), and a manual trash-icon affordance in `FrankView` for things Joshua notices later outside conversation.
- **Versioning: forget-then-resave, not a separate update mechanism.** No version-history schema (superseded-by pointers, etc.) — that would be speculative complexity with no evidence yet that reviewing historical versions of a fact matters. If something changes, Frank forgets the old record and saves a new one.
- **Not built:** an "undo"/view-forgotten-records UI. Natural small follow-up if it's ever wanted, not needed for the real use case that prompted this (removing a test/incorrect fact).

## Open questions

- Cross-device sync (this only exists on one machine right now — see `TECH_STACK.md`'s libSQL/Turso decision for the general sync plan, not yet wired to this table specifically).
- Semantic/vector search over `memory_records`, once "load everything" stops scaling.
- Whether `feedback`-type records should ever feed back into `personality.py` directly (today they're just retrieved context, not distilled into the static system prompt the way `PERSONALITY_SPEC.md` is).

## Next step

Watch how the four types actually get used in practice before adding structure (ranking, decay, cross-references) beyond what's here — this was deliberately built against the real first use case (Frank's live conversations), not designed in the abstract.
