# Alpha Mode Integration

**Status:** Built and live (2026-08-02 onward) — Alpha Mode Agent exists, real Supabase integration with the actual Alpha Mode Media Admin app, verified end-to-end against production data. This doc previously described the project as an unstarted "wishlist" long after that stopped being true; rewritten 2026-08-10 to match reality, caught by a full-codebase audit against a new feature spec.

## Purpose

Define what Frank needs to understand about Alpha Mode Media's operations, and how he integrates without undermining the existing leadership structure.

## Decided (from FOUNDER_BRIEF.md)

Frank should eventually understand: projects, CRM, clients, invoices, deadlines, crew, post-production, equipment, suppliers, reporting, SOPs, analytics, operations, knowledge, and workflow improvements. He should strengthen the existing leadership structure (Joshua/Nick/Raoof — see FOUNDER_BRIEF.md → About Me for each founder's focus areas) rather than replace it.

## What actually exists (2026-08-02 onward)

- **Alpha Mode Agent** (`backend/app/alpha_mode_agent.py`) — Frank's second delegated specialist. Handles CRM, projects, invoices, crew, equipment, marketing calendar, reporting.
- **The current tooling question is answered:** Alpha Mode already runs its own real app — Alpha Mode Media Admin (`~/Desktop/alpha-mode-media-app`), Electron + Supabase (Postgres), 9 modules (Dashboard, Marketing, Pre-Production, Production, Post-Production, Invoicing, Cost Estimate, Leads, Team). Found, got running, and verified live end-to-end 2026-08-02 — real Gatekeeper/malware rejection and a real Postgres-Changes real-time bug in the app's own code were both root-caused and fixed along the way.
- **Integration mechanism: direct writes into the real Supabase database**, not a local copy that could drift. `add_project` and invoice-status-update tools (`app/alpha_mode_supabase.py`, using the Postgres `service_role` key server-side — correct here since this runs backend-side, never shipped to a client) write live into the same database the real app reads. Verified with a real test project created through a real conversation, visible in the actual app.
- **Local SQLite** (`app/alpha_mode_db.py`) stays authoritative for clients, deliverables, crew, and equipment — these have no clean 1:1 match in the real Supabase schema (e.g., "client" is just a text field on a project there, not its own table). A deliberate, documented split, not an oversight.
- **Read access to the real `leads` table, added 2026-08-10 (Opportunity Radar).** `alpha_mode_supabase.leads_needing_followup()` reads (never writes) the real Supabase `leads` table for one signal — warm/hot leads with no follow-up sent — surfaced through the existing Insights card. The `leads` table has real headroom beyond that one signal (quote status, contract status, quote-sent dates) not yet used.
- **Security gap, resolved 2026-08-10** (see `SECURITY.md`): the project/invoice writes above auto-execute with no confirmation step, which `SECURITY.md`'s own tier definitions name as needing one ("writing to Alpha Mode's real CRM"). Asked Joshua directly rather than guessing — decided to keep auto-execute now that real audit logging exists (every write is recorded: tool, input, result, timestamp). Revisit only if this becomes an actual problem in practice.

## Open questions

- Do Nick and Raoof get their own access to Frank/Alpha Mode agents, or does this stay Joshua's individual tool that surfaces Alpha Mode context to him alone? Still unaddressed.

## Next step

This integration is stable and in active use — no further build needed unless new Alpha Mode capabilities are requested.
