# Client Shoot Onboarding SOP (Version 1.0)

**Status:** Active. Covers both businesses — Alpha Mode Media (agency-side) and Joshx (Josh's independent freelance business) — one flow, two sets of tracked entities underneath it. Use this from first inquiry through shoot-day readiness; it hands off into the Post-Shoot Editing SOP (Joshx) at the point footage exists.

**Date:** 2026-09-04 (v1.0).

---

## The problem this fixes

Onboarding currently happens in whatever order the conversation with a client goes, which means scoping sometimes happens before the deposit is discussed, crew/equipment sometimes gets assigned the night before a shoot instead of at booking, and location/logistics details end up scattered across chat threads instead of one place. Nothing here is about adding bureaucracy to a two-and-a-bit-person operation — it's making sure the same handful of steps happen in the same order every time, so shoot-day readiness is a checklist you can actually run down, not a feeling.

**Which track applies:**
- **Alpha Mode job** → tracked in the real Alpha Mode Media Admin app (Supabase — projects/invoices) plus local Alpha Mode tables (clients/deliverables/crew/equipment). Frank writes via `add_project`, invoice-status tools, `add_client`, `add_deliverable`, `add_crew_member`, `add_equipment`.
- **Joshx job** → tracked entirely in Joshx's own tables (clients/leads/projects/invoices/expenses). Frank writes via `add_joshx_client`/`add_lead`/`convert_lead_to_project`/`add_project` (Joshx)/`add_joshx_invoice`.

Don't mix the two — a job is one or the other, never both, and the tables are deliberately never merged.

---

## Stage 1 — Intake & brief capture (on first real contact)

**Time: 15–20 min**, same call/message thread as the inquiry if possible — don't let this wait for a "proper" follow-up.

Capture, in one place, before anything else happens:
1. Client name, company (if any), contact name/email/phone, how they found you (lead source).
2. What they actually want: project type (video/photo/highlight/product/event/etc.), rough deliverable count and length, any hard deadline (event date, launch date).
3. Budget signal — even a range. Don't scope in detail before you know roughly what you're scoping to.

**Hook into tracked entities:**
- Alpha Mode: log the client now (`add_client`) even if the deal isn't confirmed — a client with a real project underway later needs this row to already exist so status flips to `active` correctly.
- Joshx: log as a **lead**, not a project yet (`add_lead` — client_name, project_description, service, estimated_value/budget, lead_source, stage: `new`). Projects only get created once a lead is actually booked (Stage 3), via `convert_lead_to_project` — don't jump straight to a project on a first inquiry, that's what leaves stale "leads" sitting open after the fact.

---

## Stage 2 — Scoping & quoting

**Time: 30–60 min**, same day or next business day — quoting slowly is a real way to lose a job to someone faster, not a sign of diligence.

1. Turn the brief into a real deliverable list (specific: "hero video 60s + 3 social cutdowns," not "some content").
2. Quote using the turnaround-tier logic from the Post-Shoot Editing SOP (Joshx) as your floor: 3 business days minimum per deliverable, +1 day per additional deliverable, +2 days for a slow/particular or first-time client, +1 day for heavy footage volume. Don't answer "when can you deliver" in the moment — buy the 5 minutes to run the formula.
3. Price the job. For Joshx, standard structure is 50% deposit / 50% on delivery unless otherwise agreed (matches the Andiswa Mngomezulu precedent: R9k job, 50% deposit, balance invoiced on delivery).
4. Send the quote in writing (email or a message the client can refer back to) — verbal-only quotes are how scope disputes start later.

**Hook into tracked entities:**
- Joshx: update the lead's `estimated_value`/`budget`/`probability`/`follow_up_date` (`add_lead` upsert) as the quote firms up. Don't create the project yet — a quote isn't a booking.

---

## Stage 3 — Contract & deposit handling (booking confirmed)

This is the actual conversion point — a lead becomes a real job here, not before.

1. Get written confirmation the client accepts the quote (email reply, signed agreement, or at minimum a clear "yes, go ahead" in writing).
2. Deposit invoiced and paid **before** the shoot gets calendar-blocked as confirmed (tentative hold is fine pre-deposit; firm booking isn't). Standard: 50% deposit, Joshx; Alpha Mode follows whatever the specific contract/PO terms are for that client.
3. Contract/PO signed if the job size or client relationship warrants one — not every small Joshx job needs a full contract, but get the scope + price + deadline in writing at minimum.

**Hook into tracked entities:**
- Joshx: `convert_lead_to_project` — this is the one call that does the real conversion (creates the project, links `source_lead_id`, flips the client to `active`, marks the lead `booked`). Pass `shoot_date`/`due_date`/`priority`/`deliverables` here if known.
- Then `add_joshx_invoice` for the deposit (amount, status `sent`, due_date), and `record_joshx_invoice_payment` once it clears. `payment_status` on the project auto-syncs from invoice totals — don't manually override it once a real invoice exists.
- Alpha Mode: `add_project` (Supabase) with client/project name/type — this is the call that also auto-closes the matching open lead and flips the client active. Invoice/deposit tracking follows whatever the real Alpha Mode Media Admin app's invoicing module expects.

---

## Stage 4 — Scheduling & calendar blocking

**Do this the same day the deposit clears, not later.**

1. Block the shoot date on the calendar — call time to expected wrap, not just a placeholder. (Reference: Malondie SS26 — Pere House, Midrand, call 8:00 AM, wrap 7:00 PM — that's the level of specificity every shoot-day block should have.)
2. Block a buffer day immediately after the shoot for Stage 0 ingest + rest (see Post-Shoot Editing SOP) — don't let the calendar imply editing starts the same evening beyond the 30–45 min ingest window.
3. If this is a Tier 2/3 (compressed/rush) turnaround, block the compressed edit days now too, not after the shoot — you already know the constraint at booking time.

**Hook into tracked entities:**
- Joshx: set `shoot_date`/`due_date` on the project row (`add_project` upsert) if not already set during conversion.
- Alpha Mode: reflect the shoot date in the project's pre-production stage in the real Admin app.

---

## Stage 5 — Crew & equipment assignment

**Do this at booking, not the week of.** Waiting until days-before is the single most common cause of a scramble.

1. Decide who's shooting: solo (Joshx default) or crewed (Alpha Mode default for larger jobs). If Jared or any other support is needed, confirm his availability now — he assists occasionally, not on every job, so don't assume he's free without checking.
2. Decide equipment needs based on project type (video vs. photo, single location vs. multiple, any specific gear a client brief calls for — gimbal, drone, lighting kit, extra audio).
3. Check equipment status before the shoot, not on shoot morning — anything flagged as unavailable/in-repair needs a substitute or rental lined up with lead time.

**Hook into tracked entities (Alpha Mode only — Joshx has no crew/equipment tables yet, track this in the project's own notes field):**
- `add_crew_member` / `update_status("crew", name, status)` to confirm who's assigned and available.
- `add_equipment` / `update_status("equipment", name, status)` to confirm gear is available, not just assumed free.

---

## Stage 6 — Logistics & location confirmation

**Time: 15–30 min**, ideally a week out and reconfirmed 24–48 hrs before.

1. Confirm exact location/address, parking/loading access, any permission or access requirements (building security, site contact name/number).
2. Confirm call time and expected wrap — put both on the calendar block (Stage 4), not just in a chat message.
3. Confirm who's the on-site point of contact for the client (not always the same person who booked the job).
4. Reconfirm 24–48 hrs before shoot day — locations and contacts change; catching that Wednesday beats finding out Friday at 7:45 AM.

---

## Stage 7 — Pre-shoot checklist (shoot day minus 1)

Run this the evening before, every time, no exceptions:

- [ ] Location, call time, wrap time confirmed in writing (not just calendar-blocked)
- [ ] Crew confirmed and briefed on the shot list / deliverable list from Stage 2
- [ ] Equipment charged, packed, tested (batteries, cards formatted-but-verified-empty, backup gear for anything single-point-of-failure)
- [ ] Deposit cleared (never shoot on an unpaid deposit unless explicitly agreed otherwise)
- [ ] Shot list / deliverable list printed or accessible offline on-site
- [ ] **BTS capture reminder: grab 60 sec of behind-the-scenes footage during the shoot** (Alpha Mode Media — ties this SOP's shoot-day phase to the Client Marketing & Acquisition SOP; capturing BTS while already on set costs zero extra time versus producing marketing content separately after the fact. Do this on Joshx jobs too where it's easy — same logic applies)
- [ ] Backup drive/cloud slot ready for same-night ingest (Stage 0 of the Post-Shoot Editing SOP starts the moment the shoot wraps)

---

## Stage 8 — Handoff into production

The shoot happening is not the handoff — the handoff is confirming these three things transfer cleanly:

1. **Project status moves forward.** Joshx: `update_project_status` → `production` on shoot day, `post_production` once shooting wraps. Alpha Mode: matching stage update in the real Admin app.
2. **Post-Shoot Editing SOP takes over** starting with Stage 0 (same-night ingest, non-negotiable, 30–45 min) — this SOP's job is done once footage is safely ingested and the project status reflects post-production.
3. **Remaining invoice queued**, not forgotten. Log the balance due (amount, due date) now — Joshx: `add_joshx_invoice` for the balance if not already created, so it's tracked from day one rather than remembered manually once the edit is delivered (see Andiswa Mngomezulu: balance gets invoiced on delivery — the trigger should be "deliverable marked delivered," not "whenever it's remembered").

---

## One-line version to keep in your head

*"Lead before project, deposit before firm booking, crew and equipment locked at booking not the week of, BTS grabbed on shoot day for free, and the balance invoice queued the moment the job moves to post — not remembered later."*
