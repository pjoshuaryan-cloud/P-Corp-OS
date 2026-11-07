# Security

**Status:** First real permission model decided (2026-07-24), local-auth-token gap closed (2026-07-25), real audit logging added and the Alpha Mode tier-classification question resolved (2026-08-10), second-device threat model updated now that mobile access over Tailscale is real and verified (2026-08-10) — scoped to what actually exists today, not the full 10-year vision. Credential storage across a future cloud-sync setup remains genuinely open.

## Purpose

Define the security principles P Corp OS operates under — non-negotiable given it will eventually hold personal, business, and financial data, and agents that can take real-world actions (trading, email, etc.).

## Decided (from FOUNDER_BRIEF.md)

Authentication, security, and permissions are explicitly owned by Layer 1 (P Corp OS platform) — not scattered across Frank or individual agents.

## Decided (2026-07-24)

- **Threat model, scoped to what's real today, not speculative.** ~~Right now: one machine, no cloud sync, one client (the desktop app) talking to a backend bound to `127.0.0.1` only (`TECH_STACK.md`).~~ **Updated 2026-08-10 — this section's own trigger fired: a second device is now real.** The backend runs two listeners: `127.0.0.1` (desktop app, unchanged) and a second one bound specifically to this Mac's Tailscale-assigned IP, reachable only from devices on Joshua's own private Tailnet (not `0.0.0.0` — that would also expose it to the regular Wi-Fi/Ethernet interface, reachable by anyone else on the same network, deliberately ruled out). No app-level TLS on the Tailscale link — intentional, not an oversight: Tailscale's own WireGuard tunnel already encrypts everything between the two devices, so a second encryption layer on top would be redundant. Re-enabled and verified live from Joshua's actual iPhone 15 (real chat round-trip with Frank over `/mobile`), after being built but left dormant since 2026-07-31. Still no cloud sync, still single-user, still the same shared auth token on both listeners. The full future threat model (device compromise, cloud-provider breach, a compromised agent) still matters more once cloud sync specifically becomes real — that part of the original trigger hasn't fired yet.
- **Permission model for agent/tool actions: a three-tier classification**, deliberately modeled on the same framework that's governed every action Claude has taken building this project — a pattern already proven across an entire real working session, not invented from scratch:
  - **Regular (auto-allowed):** local-only, reversible, no external effect. Frank's original tool, `save_memory`, is classified here — it only writes to the local `memory_records` SQLite table, nothing leaves the device, any record can be corrected or removed later.
  - **Needs explicit confirmation:** anything with a real external effect or that's hard to reverse — a live trading action, sending an email, writing to Alpha Mode's real CRM, anything crossing outside this device.
  - **Prohibited, regardless of confirmation:** credentials/API keys/payment details, permanent data deletion, financial transfers, anything bypassing another system's own security controls. Mirrors the hard-line list already governing this entire project (e.g., Frank's API key has never been pasted into chat, only ever edited directly in `.env` by Joshua).
  - New tools must be classified into one of these tiers before being added — not an afterthought once something's already built and working, matching `ENGINEERING_MANUAL.md`'s existing "no exceptions" code-review discipline.
- **Full per-device keypair auth and credential storage across a future multi-device/cloud-sync setup** remain genuinely open — see `TECH_STACK.md`'s own auth section.

## Decided (2026-07-25)

- **Local-auth-token gap closed.** The backend now checks a machine-generated shared secret (`backend/app/auth.py`) on every route, both WebSocket and REST — any other local process on this Mac can no longer connect and impersonate the desktop app. Closes the one concrete gap identified in the threat model above.

## Decided (2026-08-10)

- **Real audit logging added.** Every tool call, from any agent, is now recorded (`app/audit_db.py`) with tool name, full input, a truncated result, and a timestamp — closes the "no consistent, auditable way to reason about what a tool did" gap this document flagged from the start. One insertion point in `main.py`'s existing dispatch loop, no individual agent touched.
- **Alpha Mode tier-classification gap, resolved.** A 2026-08-10 audit against a new feature spec surfaced that Alpha Mode Agent's `add_project`/invoice-status tools (built 2026-08-02) auto-execute against the real production database with no confirmation step — this document's own example of a "needs explicit confirmation" action, sitting in practice in "Regular" instead. Asked Joshua directly rather than reclassifying unilaterally: **decided to keep auto-execute, now that audit logging (above) provides a real record of every write.** Revisit only if this becomes an actual problem in practice, not preemptively.
- **Shadow Mode classified as "Regular," with the invasiveness question handled by scope rather than by tier.** `get_recent_activity`/`log_activity` are local-only, reversible (the whole `activity_log` table can be cleared), no external effect — same tier as `save_memory`. The real risk with a passive-observation feature isn't the permission tier, it's scope creep toward genuinely invasive capture; handled by confirming the boundary directly with Joshua before building (app name only, event-driven via a no-permission-needed public API, never window titles/URLs/file contents) rather than by escalating the tier.
- **Legacy Vault classified as "Regular" too, with the real risk handled by an absolute content restriction rather than a tier escalation.** `save_to_legacy_vault`/`list_legacy_vault`/`delete_from_legacy_vault` are local-only and reversible (soft delete, same as `forget_memory`) — but this tool's whole purpose is holding consequential, sensitive succession information, so its own tool description carries an explicit, unconditional line: never a password, API key, account number, or other credential, matching the "Prohibited" tier's existing hard line on credentials elsewhere in this project. Verified live: a deliberate attempt to save a bank password was correctly refused before the tool was ever called — confirmed via the audit log, not just trusted from the system prompt.

## Decided (2026-08-27)

- **Engineering Agent — the first tool needing a live, blocking, mid-turn human approval.** `AGENTS_VISION.md` had deliberately deferred this agent from day one, precisely because it's the general agentic tool-use capability (file access, git) this document's permission model didn't yet cover. Resolved by applying the existing three-tier framework to a new tool category rather than inventing a new one:
  - **Regular (auto-allowed):** `read_file`, `list_directory`, `git_log`, `git_diff`, `git_show`, `run_build_check` — all read-only, local-only, no write capability at all.
  - **Needs explicit confirmation:** `propose_file_edit` — the only tool that can ever touch disk, and it never writes directly. It sends Joshua a real approval card (path, summary, diff) over the existing websocket and blocks until he approves or rejects; only writes on explicit approval.
  - **Prohibited entirely, this version, not silently omitted:** arbitrary shell execution, `git commit`/`git push`/any git write operation, editing `.env`/secrets/keys, deleting files. No tool for any of these exists.
  - This is new infrastructure, not a reuse of Alpha Mode's 2026-08-10 auto-execute-with-audit-logging decision — that was a deliberate one-time call for a specific already-shipped tool, not a template for every future write. `propose_file_edit` is the first tool in the project that pauses a turn and waits on a real human decision before proceeding.
  - **New shared boundary helper**, `backend/app/agent_file_safety.py` — every path-taking tool resolves through it first. Refuses anything resolving outside the repo root, and separately refuses a denylist regardless of path: any file named `.env`, anything under `backend/data/`, anything touching `.git/`, and `*.pem`/`*.key` files.
  - **Audit coverage extended to cover this correctly:** Engineering Agent's own inner tool calls (`read_file`, `git_log`, `propose_file_edit`, etc.) are individually recorded via `record_tool_call` inside `engineering_agent.py` itself — `main.py`'s existing single insertion point only logs the outer `consult_engineering_agent` call, which would otherwise leave no audit trail for exactly the action (a proposed file edit, approved or rejected) that most needs one.
  - **Scope, explicitly:** Engineering Agent only, this pass. Design/Operations/Communications Agents are not wired into this approval mechanism yet — a deliberate follow-up once this proves out in real use, not bundled into this change.
  - **Update, same day:** proved out in real use, extended to Design Agent and Operations Agent — both have a real codebase to touch (SwiftUI source; `automations_registry.py`/Knowledge docs). Same tier classification, same shared `agent_codebase_tools.py` toolset/safety boundary/approval flow, no new infrastructure. Communications Agent deliberately excluded — its whole domain is external email/message drafts, no source of its own to read or edit.

## Decided (2026-09-18)

- **Email send capability, reversing this document's own "read-only" framing for Gmail — a real "needs explicit confirmation" example named directly in this document since 2026-07-24 ("...sending an email...") finally gets a real tool.** `AGENTS_VISION.md`'s Communications Agent section had recorded "no send tool at all, rather than a send tool gated behind confirmation" as a standing decision — a genuinely stronger position than this document's own tier framework required. Asked Josh directly before touching anything, given the stakes (real email to real third parties, not easily reversible): offered Gmail-drafts-only, approval-gated send, unconstrained direct send, or leave it read-only. **He chose approval-gated send.**
  - New `propose_send_email` tool (`email_tools.py`) — classified **"Needs explicit confirmation."** Never sends immediately: sends Josh a real approval card (recipient, subject, full body) over the existing websocket and blocks until he approves or rejects, exactly mirroring `calendar_tools.py`'s/`alpha_mode_tools.py`'s own `propose_*`/`_request_approval` shape (own request id, fails closed on rejection/mismatch/malformed reply). A fifth independent instance of this pattern.
  - Needs a new Google OAuth scope (`gmail.send`, added to `google_oauth.py`'s `SCOPES`) — Josh must re-consent once via `/auth/google/start` before this actually works; the existing refresh token predates the new scope and Google does not retroactively grant it.
  - `AGENTS_VISION.md`'s Communications Agent section updated to match — see that file for the corresponding entry.

## Decided (2026-11-04)

**The on-set phone link (Shoot Logger Phase 3): P Corp's first thing on the public internet that doesn't need the main token.** Shooters at a venue can't reach this Mac and shouldn't get a login that opens everything, so a phone link opens one job's shot list and nothing else. Code: `backend/app/on_set_db.py`, the `/set/` routes in `main.py`, `backend/app/static/on_set*`. Tests: `premiere-plugin/e2e/on_set_test.py`.

- **What it is:** a 256-bit random token, made by an explicit click, on the Mac after the list has been approved or on the owner's phone (below). It's looked up by its SHA-256 hash. The full token is kept in a file only the Mac's owner can read, and in the shared database's `meta` table so a list can be re-sent from the phone. See "Changed the same day" below.
- **Keeping it out of logs:** it sits after the `#` in the address, which browsers never send, and travels in a header. It's never in a query string.
- **What it can reach:** two routes. It can read that one list and add ticks to it. It can't edit the list or reach a plan, brief, file, frame, cost, or anything else in P Corp, and it can't cause a Claude call. `verify_token` doesn't accept it, and the `/set/` routes accept nothing else (tested on the private routes, both ways).
- **What a phone gets:** shot descriptions, moments, times, sizes, priorities, camera names, the job and client name, and other shooters' ticks and notes. Not the brief, the linked shoot, file paths or costs.
- **Ending it:** a stopped link fails on the phone's next request and wipes the saved list off the phone. A link runs out 3 days after the shoot date. An unknown, stopped and expired link all get the same answer. A list edit never brings a run-out link back.
- **Floods:** before any database work, 300 requests a minute per link, and 120 a minute across all links not recently seen, so made-up links can't tie up the pool while real ones keep working. Bodies stop at 64 KB, 50 ticks a request, 5,000 ticks a job. The limits are in memory and reset on restart, which is fine: they protect the database, they don't count anything.
- **The page:** a Content-Security-Policy with no outside scripts or connections and no inline scripts, no referrer, `noindex`. Anything people typed goes on screen as text, never HTML, and is escaped in the PDF. The offline copy holds only the page's own files.

**Accepted, knowingly:**
- It's a shared link, not a login: anyone it's forwarded to can see and tick the list until it's stopped, and the name on a tick is whatever they typed. So it can be mischief, but a tick can't do damage: it never decides whether a shot is covered, and all ticks are kept.
- Phones keep the list in their browser's storage until the link stops, or they clear it.
- The limits are per server process, and a shot list is client information sitting on the cloud database. Stopping a link closes it to phones, but the list and its ticks stay in the database, because the report needs the ticks, until he deletes the list. Deleting takes the list, its ticks and its stored link out in one step and needs the link stopped first; only what a draft cost stays, with no shots in it, so the daily limit still counts it. A shoot under a strict NDA shouldn't use a phone link unless he deletes it afterwards, and even then it was on the cloud for the life of the link.

**The owner's phone, added the same day: shot lists with no Mac.** He asked to make, change and send lists, and draft them from a brief, with no Mac. Code: `backend/app/on_set_manage.py`, `/set/manage/` in `main.py`, `backend/app/static/on_set_manage*`. Tests: `premiere-plugin/e2e/on_set_manage_test.py`.

- **Only he starts or stops a link (his instruction, 2026-11-04).** Starting and stopping takes the Mac's main token or the phone login. A crew link can't do either, and can't make lists or see the owner's page. Tested from each side, along with a made-up login and the main token used as one. A crew member can still forward their own crew link, which lets someone else see and tick the list until he stops it.
- **Its own login, not the main token.** The Mac shows a QR code holding a one-time code that works once, for 15 minutes, so a photo of it is worthless afterwards. Scanning it swaps the code for a 256-bit key, stored by hash, in a cookie: `HttpOnly`, so the page's scripts can't read it, `SameSite=Strict`, so other sites can't trigger it, `Secure` over https, and limited to `/set/manage`. `verify_token` doesn't accept it, it isn't a crew link, and neither of those works as it (tested both ways on the private routes). The Mac can turn a phone off at once. Whoever scans the code first gets the login, so he should scan it himself: the Mac's list shows each phone, and any he doesn't recognise can be turned off.
- **What it can reach:** shot lists, and the links to them. It can make, change, stop and delete lists, and see ticks. A lost phone could delete stopped lists from the cloud, but never anything on the Mac, whose copies stay until they're deleted there; the crew's link can't delete anything. It can't reach plans, footage, logs, files, costs or anything else in P Corp. Crew links it has already sent keep working after it's turned off, so a lost phone means turning it off and stopping any links that matter.
- **It can spend money, within a limit.** Drafting from a brief calls Claude, which he asked for by name. A login on a phone can be lost, so drafts stop at 15 a day or $1.50 a day across all phones, whichever comes first, counted in the shared database and checked before any call. It's a ceiling on one day's loss, not a guard against a bad draft: a person still reads the list. A double tap can't pay twice, and only a couple can run at once. The Mac's own prompt treats the brief as information and never instructions, and the call has no tools. A brief isn't kept.
- **Nothing in an address is a login.** The page's address opens nothing on any other phone, so forwarding it by accident gives nothing away. It was first built with the key in the address, and changed when he said he should be the only one who can start or stop links. Being logged out at a venue with no Mac is the failure to avoid, and a cookie set by the server isn't caught by Safari's 7-day limit on script-written data. Clearing Safari's data does log the phone out, and then it needs a new QR code from the Mac. Not tested on a real iPhone over days.

**Changed the same day, knowingly:** the shared database used to hold only a link's hash, and now also holds the full link in `meta`, because a list has to be re-sendable from a phone with no Mac. Someone able to read that database could already read every shot list and tick in it. All this adds is that they could also tick. The phone-login key and setup codes are still hash-only.

## Decided (2026-11-07)

**The private journal in Personal: voice notes and writing that only he can read.** His choices, asked before building: encrypted on both his iPhone and his Mac, Frank never sees it, and Face ID or Touch ID every time it opens. Code: `PCorpKit/Sources/PCorpKit/Journal*.swift`, `backend/app/journal_db.py`, the `/journal/` routes in `main.py`. Tests: `premiere-plugin/e2e/journal_test.py` (the server's rules, on SQLite and on a throwaway Postgres) and `journal_swift_test.swift` (encryption, the recovery key, two devices syncing, through the real routes on a throwaway server).

- **Encrypted on the device, before anything is saved.** A 256-bit key, made on the device that starts the journal, seals each note, recording and the category list with ChaChaPoly. Each item is sealed with its own name, so one can't be swapped for another or changed without it failing to open. The key never leaves his two devices. The server, the shared database and its backups hold only sealed bytes.
- **What the server can see:** how many items there are, which are written notes and which are recordings, their sizes, when each changed and which were deleted. A recording's size gives its rough length. It can't see words, titles, categories, transcripts or sound. It also keeps a check value of the key, a keyed hash, so a second device can't start a second journal and a wrong recovery key is caught. The key can't be worked out from it.
- **Frank never sees it.** It isn't a tool, it isn't in his context, memory or search, and nothing in the backend except the `/journal/` routes touches it. Those routes can't read it anyway, because the backend never has the key, so a bug or a prompt-injected Frank can't either. The routes need the main token. The phone login and crew links don't work there.
- **Where the key is kept:**
  - On the iPhone, the Keychain item itself demands Face ID or the passcode before it can be read. It's not in iCloud Keychain, and it can't be moved to another phone, even through a backup.
  - On the Mac, the app has no entitlement for that kind of item, so the key is in his login Keychain. The app asks for Touch ID or his password before reading it. That check is the app's own, not enforced by the Keychain, so on the Mac the real protection is his login password.
- **On each device:**
  - The device keeps only sealed copies. On the iPhone they're also unreadable while the phone is locked.
  - Notes are decrypted into memory only while the journal is open. Locking forgets the key and every decrypted note, and recordings play from memory.
  - It locks when he leaves it, when the iPhone app goes to the background or the Mac app loses focus, and after 5 minutes untouched. The iPhone's app switcher shows a lock, not the page.
  - Network calls keep no cache on disk, and the server marks every sealed item it sends `no-store`.
- **Voice notes:**
  - What a note said is worked out on the device only. If the device can't do that, the note keeps its recording and no words. It's never sent anywhere to transcribe.
  - While recording, the sound goes to a temporary file in readable form until it's saved or thrown away, then it's deleted straight away. On the iPhone that file is unreadable while the phone is locked, and locking ends the recording. Leftovers from a crash are deleted the next time the journal opens.
  - Recordings stop at 30 minutes, and the server takes at most 30 MB a recording and 512 KB a note.
- **The recovery key** is the key plus a 2-byte checksum, as 11 groups of five letters that avoid I, L, O and U. It opens the journal on a new device, and it's the only way back if he loses both devices.
  - It's shown when he starts the journal, and keeps coming back until he types its last group.
  - After that it's only shown after Face ID or Touch ID. On the Mac it's also shown as a QR code for the iPhone's camera.
  - Anyone with it can read the journal.
- **Removing it from a device** deletes that device's key and copies, after Face ID or Touch ID. It refuses while any note hasn't reached the server yet, because that device's copy would be the only one.

**Added the same evening: sorting and highlights, still on his devices only.** He asked for notes to be filed by what they say, and for "your thoughts this week" and "what you thought this month" highlights. Asked first, he chose to keep everything on his devices over letting Claude read the journal. Code: `PCorpKit/Sources/PCorpKit/JournalInsight.swift`. Tests: in the same two journal test files.
- **Who reads it.** Only his devices, and only while the journal is open and unlocked.
  - The Mac uses Apple's on-device model (FoundationModels). It runs on the Mac and nothing is sent anywhere.
  - His iPhone 15 can't run that model. It uses Apple's built-in on-device language tools and word lists instead.
  - Frank, the backend and Anthropic still never see a word of it.
- **Filing:** done as a note is saved, unless he picks a category himself. On made-up test notes the Mac got about 9 in 10 right, and so did the iPhone. Filing learns from the notes he's already put in each category.
- **Highlights:** counts, mood, recurring themes and a few of his own sentences, worked out on whichever device he's on.
  - Mood comes only from feeling words he wrote. Apple's built-in sentiment scoring was tried and rejected: it rated "I feel really anxious" as upbeat.
  - The Mac also writes a short summary and up to three things worth remembering. It's sealed like a note and synced as an `h-week-YYYY-MM-DD` or `h-month-YYYY-MM-DD` item.
  - A summary is only shown while it still matches the notes it came from. Deleting a note deletes the summary of its week or month too, so nothing of it is left.
- **What the server learns that's new:** which weeks and months have a written summary, and how big each one is. Item dates already showed when he wrote.
- **Reminders:** on the iPhone only, Sunday at 7pm and the 25th at 7pm. They say only that highlights are ready, never anything from the journal. They can be turned off in the journal's menu.
- **Sync:** an item the server turns away no longer holds up the others queued behind it. It stays queued.

**Accepted, knowingly:**
- The Mac's summaries can blur a plan into something done ("you invoiced" for "invoice once approved"). His own sentences are shown under every summary.
- Apple's safety filter blocks words like "shoot" when the model replies in a set structure, so the summary asks for plain text and is split up on the Mac. If the model still declines, the card shows the counted highlights only.
- Nobody can recover it for him. Losing both devices and the recovery key loses the journal.
- Anyone with the main token can't read it, but could delete it or overwrite it with junk on the server, and both devices would follow: a deleted note disappears and a junk one won't open. That's a loss, never a leak. Reading it needs one of his unlocked devices or the recovery key.
- What he types goes through the iPhone's keyboard like anywhere else. A third-party keyboard given "Full Access" could see it. Screenshots aren't blocked.
- **Proven on his devices on 2026-11-07:** Face ID, Touch ID, the QR scan, and recording, transcription and playback on the iPhone. **Not yet:** sorting and highlights on his real devices, and the reminders actually firing. Those were tested in the Simulator and on the Mac's own model, with made-up notes.

## Open questions

- Credential storage and secrets management across desktop + mobile + any cloud sync backend, once those exist.
- Data-at-rest and in-transit approach for cloud sync, once that's built.
- What P Corp OS builds itself vs. relies on the host OS or a cloud provider (e.g., OS keychain, managed auth provider) for.

## Next step

Revisit this document every time a new tool or agent is added, to classify it into one of the three tiers above before it ships, not after.
