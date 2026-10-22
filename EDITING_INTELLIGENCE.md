# Editing intelligence: audit, plan and status

Started 2026-10-22 from the "Premiere editing intelligence upgrade" master prompt. This file is the Phase Zero audit (sections 1-6), the working plan (section 7),
and, at the end, the record of what was built and what is still unverified (section 8). Every number here was measured on Josh's own material unless it says
otherwise. "Verified" means checked in real Premiere; "offline" means tested without Premiere; "mock" means tested against a stand-in for Premiere.

## 1. Architecture map: the life of one edit plan

| Step | Code | What happens | Stored where |
| --- | --- | --- | --- |
| Ingest | `backend/app/post_ingest.py` | copies a card, verifies every file by SHA-256 | `post_job_files` (`source_checksum` = a stable media identity) |
| Analyze Media | `post_media.run_media_analysis` | ffprobe metadata (frame rate, size, colour), exposure | `post_job_file_metadata` |
| Describe clips | `post_moments.py` (model `DESCRIBE_MODEL` = `claude-sonnet-5-5` in `main.py`) | one Claude call per clip on stills every 0.5-1 s (max 40): scene, people, up to 5 moments `{t, kind, punch 0-10, what}` | `<job>/.../edit_plans/moments.json`, keyed by file id + duration |
| Steadiness read | `post_steady.analyse_clips` | local ffmpeg read at 8 fps, low resolution: per-frame motion, sharpness, brightness, cut spikes, 1 thumbnail a second | `edit_plans/steadiness.json` (`CACHE_VERSION` 2) |
| Plan Edit | `post_edit_plan.plan_for_job` | style (`post_style`: reference profiles, or "Your usual pace"), song analysis (`post_music`), cut times on the music's hits (`plan_cut_times`), then a moment for every slot | `edit_plan_latest.json` (+ `edit_plan_prev_*` archive), brand graphics, the music cut `.wav` |
| ...music reels | `build_plan` -> `select_clips_by_moments` + `choose_window` | the clip with the strongest described moment in each stretch of the shoot; the window starts 0.12 s before that moment | |
| ...highlights and stories | `build_highlight_plan` / `build_story_plan` -> `post_edit_story.assign_clips_to_slots` -> `post_pick.Picker` | every slot scores each clip's best 3 described moments (window centred on the moment) by cleanliness, variety against earlier shots, shoot order and punch | |
| Review | `static/edit_review.html` + `post_review.py` | each slot with alternatives; swap / keep / slow motion | the plan file; `review_log.jsonl`, `review_speed_log.jsonl` |
| Build in Premiere | `premiere-plugin/index.js` (`buildMyEdit`, `assembleEdit`) | reads `GET /edit-plan` and `/premiere-prep`, makes a subclip `[source_in, source_in + duration_frames]` per shot, inserts it at `start_frame`, then music, fill-frame scaling, zooms, accents, graphics | a NEW sequence; never touches existing ones |
| Learn | `post_learn.py` (button), `post_autosave.py` (watch) | reads the saved project, compares the sequence with the plan it was built from (`post_plan_history.plan_for_build_time`) | `backend/data/learning/feedback/` |
| Offline evaluation | `backend/learning/` (`evaluate`, `vision_eval`, `taste`, `rhythm`, `slowmo`, `placement`) | 168 of his shots from 21 projects as ground truth, each with a fixed pass bar | `backend/data/learning/` (git-ignored) |

Models: development runs on Opus 5.5 (audit, integration, review) with Sonnet 5.5 sub-agents for bounded modules. The app's runtime models are separate and
unchanged by this work: `MODEL = claude-sonnet-5` (chat), `DESCRIBE_MODEL = claude-sonnet-5-5` (Describe clips), `post_reference_vision.MODEL = claude-sonnet-5`.

## 2. Where weak decisions come from (evidence, not guesses)

1. **The task is under-determined.** A clip holds several valid moments and he takes one. On 168 labelled shots Claude's first pick covers half of his shot
   9% of the time (random 6.5%), and one of its top three 25% (random 18%). In review he KEPT the planner's pick in 23 of 50 JD Sports decisions (46%):
   "acceptable" is far more common than "identical".
2. **A wrong rule** (fixed 2026-10-20): the corporate planner took the steadiest stretch of each clip, which was WORSE than random (top-3 10%, random 18%).
3. **A wrong pace** (fixed 2026-10-21): the calm corporate preset was 2.8 times slower than his edits; "Your usual pace" is now the default.
4. **Sampling.** Stills every 0.5-1 s against his 0.5 s shots. A denser second look around Claude's top 3 was tested (2026-10-20): no reliable gain.
5. **Placement around the moment.** Two rules nobody had compared (centred vs 0.12 s before). Tested 2026-10-22 (`learning/placement.py`): equal
   (top-1 9.0% vs 7.8%, top-3 25.1% vs 26.9%). Snapping to the start of a burst of motion is worse (top-3 21.0%). An offset learned per kind of moment on
   held-out projects reached 11.4% / 32.3% (+4 / +12 net shots), short of the fixed bar of +10 on both; used only as extra alternatives it adds nothing.
6. **Candidates.** Each clip offers only Claude's up to 5 moments, then the steadiest stretch. A signal-only candidate generator (motion peaks, onsets,
   settles) was tested 2026-10-19: no better than random at finding his moments.
7. **Nothing explains or identifies a choice.** A planned shot records one line of text (`moment_source`). There is no candidate identity, score
   breakdown, confidence or analysis version, so a decision cannot be traced back to what was offered, and the learning logs cannot link to candidates.
8. **Cache and cost.** The description cache is only invalidated when a clip's duration changes (not when the model or prompt changes); token usage of a
   Describe run lives in memory and is lost after the run.
9. **One plan at a time.** No variants, no comparison, no locked shots, no way to regenerate part of a plan.
10. **Learning is collected but cannot act.** Learn From My Edit, the auto-save watch and the review logs collect data, and the taste ranker has an adoption
    gate, but nothing in the planner reads a learned preference, explicit reasons for a change are never asked for, and records have no schema version.

Root causes 1, 4, 5 and 6 limit how well ANY ranker can do on the strict yardstick. Causes 7-10 are what this upgrade can fix for certain.

## 3. Capability status at the start (2026-10-22)

| Capability | Status |
| --- | --- |
| Prepare POST Project, Transcribe Dialogue, Smart Selects markers, Apply Starting Exposure | verified in real Premiere |
| Assemble Edit (cuts, music, fill-frame, zooms, accents, brand cards, captions, multicam) | verified in real Premiere from saved projects and exported frames |
| Assemble Rough Cut | verified; Premiere Beta 27.1.0 crashed once at 77 of 112 clips |
| Build My Edit | mock only (`plugin_build_test.js`) |
| Learn From My Edit | offline against his saved GWM project; the button itself never clicked in real Premiere |
| Auto-save watch | offline against his real GWM and JD Sports auto-saves; never followed a live session |
| "Your usual pace" default | offline on real GWM clips and a real song; not seen on screen |
| Slow-motion toggle | review page and preview verified in a browser against a mock server; NOT applied in Premiere (no API; see the report) |
| Plan history, progress view, three-question Plan Edit, greyed-out reasons | offline / Swift builds; not seen on screen (app not rebuilt) |

## 4. Baseline before any change (2026-10-22, Joshx SSD and Lexar drives unplugged)

Test suites: picker 52, highlight_planner 41 (then stops at a lost logo fixture), learn_from_edit 31 (+1 skip, needs the SSD), autosave 38 (+1 skip),
taste 20, plan_history 36, pipeline 33, drive_guard 15, rhythm 41 (+1 skip), usual_pace 37 (+1 skip), slowmo 32, slowmo_review 65; plugin mocks:
build, learn, mock, edit, fill, zoom, accents all pass. Zero failures.

Offline evaluation (no drive needed after a fix to `learning/evaluate.py` on 2026-10-22: cached measurements are found through the inventory's
size and time of each file): 168 shots, random 6.5% / 18.1%; the app's own window chooser: old steadiest rule 2.4% / 14.9%, today's rule 8.9% / 25.6%.

## 5. Compatibility risks

- The plan file is read by the plugin. Only ADD fields; never change what `source_in`, `duration_frames`, `start_frame` mean.
- Any change to the Picker's scoring changes every highlight and story plan. Default settings must reproduce today's plans exactly (regression test).
- Describe-clips cache: adding versions must NOT invalidate existing descriptions (re-describing a shoot costs real money).
- Review routes and the review page: existing requests and responses unchanged; new fields additive.
- Learning: the existing logs stay where they are; new records are additional and versioned.
- No Swift change is required (the desktop app has to be rebuilt by Josh): new UI goes into web pages the backend serves from disk.
- The plugin needs no change for variants: a chosen variant becomes the job's latest plan, which Build My Edit already builds.

## 6. Minimal implementation sequence

1. Offline evaluation without drives (done in Phase Zero) and the placement experiment (done; nothing adopted).
2. Candidate-moment engine: one schema for every candidate (time range, evidence, confidence, provenance, score breakdown), wired into the Picker
   with default settings that reproduce today's plans exactly; explanations attached to every planned shot.
3. Editing Style Library: data-driven profiles that map onto what the planner can execute, with everything else labelled as a proposal.
4. Multi-variant planning: 2-4 plans from one analysis with cross-variant diversity, comparison metrics, choose-one-as-latest.
5. Review additions: lock a shot, regenerate a section, alternative in/out points, optional reasons for a change.
6. Learning events: one versioned, append-only record type for explicit feedback, observed edits and inferences, with confidence; learned preferences
   reach the ranking only through the existing adoption gate.
7. Cost and caching: description provenance (model, prompt version), a persistent per-job API usage ledger, stale-cache reporting without silent re-runs.
8. Minimal UI: a variants page and review-page controls, linked from the existing review page.
9. Docs: this report and `premiere-plugin/REAL_PREMIERE_CHECKLIST.md`.
10. Full test run, independent review, fixes, final report.

## 7. Work log

- 2026-10-22: `learning/evaluate.py` finds cached measurements with the drive unplugged; `learning/placement.py` (placement rules, gate not met).
- 2026-10-22: candidate-moment engine (`post_candidate_moments.py`), wired into the reel, highlight and story planners; golden plans captured from the
  unchanged planner and reproduced exactly (`candidate_engine_test.py`).
- 2026-10-22: description provenance + API usage ledger + list-price estimates (`post_moments.py`, `cost_cache_test.py`, fake client, nothing spent).
- 2026-10-22: Editing Style Library (`post_style_library.py`, Sonnet sub-agent, reviewed; 142 checks). Wording fixed so openings/endings read as preferences.
- 2026-10-22: learning events (`post_learning_events.py`, Sonnet sub-agent, reviewed; now 186 checks) and the producers: review swaps/approvals, slow motion,
  locks, regenerations, reasons, Learn From My Edit, the auto-save watch, choosing a variant.
- 2026-10-22: multi-variant planning (`post_variants.py`) + routes + `static/edit_variants.html`; review additions (`post_review.py`, `post_pick.regenerate`) +
  routes + review-page controls. Live run on GWM; visual check of both pages in a browser against the real routes with synthetic footage.
- 2026-10-22: independent Opus review (section 8): one serious bug (Regenerate threw away his own swaps) and smaller ones, all fixed or answered; the
  second live GWM run then found a bug no test had: a variant set's music cut was taken as the job's song. Fixed. Final: 999 checks + 157 plugin-mock
  checks, 0 failures.
- 2026-10-22 (afternoon, after a status check against the master prompt): the gated path from recorded decisions to the planner (acceptance criterion 10),
  shortened / extended / reordered shots in Learn From My Edit, plan validation (missing media, impossible timecodes) before a variant replaces the plan,
  `learning/verify_build.py` for the real-Premiere checklist, the rest of the section-14 checklist, tests sorted by kind (section 9), a final review.

## 8. What was built, what it measured, what is still unverified

### Built (all uncommitted; nothing in `premiere-plugin/index.js` changed)

| Area | Files | Tests |
| --- | --- | --- |
| Candidate engine: every planned shot carries a versioned record (time range, evidence, confidence, provenance, score breakdown) | `post_candidate_moments.py`; `post_pick.py`, `post_edit_story.py`, `post_edit_highlight.py`, `post_edit_plan.py`, `post_steady.py` | `candidate_engine_test.py` 42 (incl. golden opener / bookend / story plans captured from the committed code) |
| Cost and caching: description provenance (model, prompt hash, sampler), per-job usage ledger `api_usage.jsonl`, list-price estimates, stale-version report (never a silent re-run) | `post_moments.py`, `post_edit_plan.py`, `main.py` | `cost_cache_test.py` 20 |
| Editing Style Library: 11 profiles + hybrids; executed vs proposed-only lists | `post_style_library.py` | `style_library_test.py` 142 |
| Multi-variant planning: 2-4 plans from one analysis, each avoiding the stretches the earlier ones used; comparison; pace warnings; closing cards; choose-one-as-plan (old plan archived) | `post_variants.py`, `main.py` (5 routes), `static/edit_variants.html` | `variants_test.py` 59, `routes_test.py` 32 |
| Review additions: lock, regenerate a range (picker, never a stretch the shot already showed), earlier/later timing, reason chips, "why this shot" | `post_review.py`, `post_pick.py` (`_scored_for_slot`, `regenerate`), `main.py` (3 routes + 2 read routes), `static/edit_review.html` | `review_additions_test.py` 55, `routes_test.py` |
| Learning events: one versioned record; explicit / observed / uncertain / inferred kept apart; reason codes; client requests never count as taste (also when given after the swap); counting only | `post_learning_events.py`, producers in `post_review.py`, `post_learn.py`, `main.py` | `learning_events_test.py` 189 |
| Offline evaluation without drives; placement experiment | `learning/evaluate.py`, `learning/placement.py` | (experiment) |

Every new plan field is additive (`candidate`, `variant`, `review.locked`, `review.seen`, `review.previous`, `event_kind` on a regenerated shot,
`candidate_real_time` while a shot is slowed); the plugin reads none of them. With default settings
the planner reproduces the golden plans exactly. No new Claude call anywhere: a variant set makes zero.

### Measured

- **Variants on real footage** (GWM, 165 clips, 179 BPM song), through the live route: 6-7 s, 0 API calls, all 165 steadiness reads from cache, the
  job's current plan byte-identical before and after. Set `20261022T094507` (seed 8, 20 s): Montage 29 shots (0.60 s average), High-energy 31 (0.57 s),
  Premium 21 (0.83 s); no stretch shared between any two; 4-13% of clips shared; music cut 20.0 s for a 20.0 s picture. (The first set,
  `20261022T090321`, came out with High-energy SLOWER than Montage, 0.58 vs 0.55 s: see the next point.)
- **Cross-variant avoidance works:** on synthetic footage the same three directions planned independently reuse 91-92% of each other's stretches; as a
  set, 0-4%.
- **Pace separation is weaker than the names suggest.** GWM, 8 seeds x 20/30/45 s: High-energy averages 13% shorter shots than Montage (0.63 vs 0.72-0.74 s)
  and Premium ~40% longer (1.0-1.04 s), but High-energy was no faster in 2-3 of the 8 seeds; the strong beats decide most cut points. The set now says so
  when it happens, and each new set from the page uses a new seed. The "build" curve shortens the second half by 10-21% on average (12 seeds, 100-175 BPM
  synthetic: 0.78-0.84 vs 1.0-1.1 flat) but can reverse in one plan, so each variant reports its measured halves instead of promising the shape.
- **Learning importer on real data:** the 3 real feedback files convert to 221 events (134 observed, 87 uncertain: the ones compared with a plan the
  sequence was not built from).
- **Placement:** no rule adopted (section 2, cause 5); earlier/later is offered as a one-click choice instead.

### Defects found and fixed during the work

- A client's reason given AFTER a swap did not remove that swap from the taste evidence (the master prompt's "learn the wrong lesson" case). Fixed:
  the reason event names the change it explains (`context.explains`) and the counting skips it.
- A swap or regeneration left the shot's `candidate` describing the old footage. Fixed (`refresh_candidate`); slow motion on/off restores the exact record.
- After a swap a review pick read "judged by Claude from stills, not your taste". Fixed: "your choice".
- A nudge earlier/later would have counted as a vote against that kind of moment. Fixed: it is a `moved` event.
- `highlight_planner_test.py` (pre-existing): its logo fixture was never committed; it now draws one. Its last section needs 4K fixture footage and a song
  that are no longer on this machine and now says SKIP instead of crashing.

### Independent review (Opus, read-only, 2026-10-22) and what was done

| Finding | Outcome |
| --- | --- |
| **Regenerate threw away his own decisions**: a shot he had swapped, kept or slowed was re-picked, the plan was overwritten with no archive, and the dialog promised one-click undo | Fixed. Regenerate never touches a shot he locked, kept, picked or slowed (and says which it left); every regenerated shot offers back what it showed just before ("before regenerate"); the route archives the plan first; dialog text corrected. 8 new checks |
| A shot's `event_kind` from a regeneration survived a later swap, so its record named the wrong kind | Fixed (`apply_choice` drops it); checked |
| The variant music cut used a fixed 1.5 s fade, not the plan's own | Fixed (the longest plan's length and fade); checked |
| A failed music render (and, found live, a song shorter than the edit) gave a 500 | Fixed: both are plain 400s with the reason; checked |
| A variant set ran 2-4 picker passes on the event loop | Moved to a worker thread (the steadiness cache is a plain recompute-on-miss dict, safe to share) |
| Lock, unlock, lock within a second stored as one event | Live events are timed to the millisecond; checked |
| "taste_signals" counted locks and choices | Kept as "trustworthy events"; new "taste_votes" counts only real votes (what a proposal needs 30 of); checked |
| A reason could attach to the wrong change | The swap and regenerate routes return the change's event id; the page sends it; a wrong id is refused, never re-routed; checked |
| A nudge accepted from an out-of-date page was logged as a swap (a vote) | Now labelled earlier/later and logged as "moved"; checked |
| "Pace measured on your edits" overclaimed for the 0.85x / 1.6x multipliers; an unmade brand card was listed as done | Wording says the base rhythm is measured and the multiplier is guidance; an unmade card moves to "suggested", with why; checked |
| Two tests that could not fail; golden plans missed the story / opener / bookend paths | Both rewritten so they can fail; 4 golden plans captured from the committed code (a git worktree at 65392a4) and reproduced exactly |
| Path traversal, XSS, plan compatibility, API calls, route locking | Reviewer found nothing wrong |
| Not done: a reason chip for the variant choice itself; routes_test stubs `_review_context` (the real highlight-plan read path is exercised by the live run only) | Left as is |

**Found by the second live run, not by any test or the review:** the first set's music cut was the newest file in GWM's music folder, so a plan made
without choosing a song (and the planning screen's song list) would have picked that 20 s cut as the song. Fixed in `post_music.is_own_cut` (used by
both places); checked with the real song finder; GWM's default song is `sero - Moon Road.mp3` again.

### Second round: closing the gaps against the master prompt (2026-10-22 afternoon)

**Learning can now reach the planner, through a gate (acceptance criterion 10).** Every learning event is also mirrored to one local store
(`backend/data/learning/events/events.jsonl`). `learning/adopt_preferences.py` imports the existing logs, and once there are at least 30 votes on a kind of
moment it proposes a nudge per kind (at most +-0.15) and tests it on his 168 labelled shots from other projects, leaving out any shot whose clip appears
in the events. Only a pass of the usual bar (+10 net shots on BOTH first pick and top three) writes `data/learning/adopted_kind_preferences.json`; Plan
Edit (highlight and "Your usual pace") and every variant read it, and the plan says when it did. Without the file every plan is exactly as before (tested
through `plan_for_job` itself).

**The first real run said no.** From 274 real events (his 50 JD review clicks and the auto-save comparisons of his GWM and JD edits) there are 96 votes: he
keeps planned **hero** moments (11 of 12) and changes **reactions** (18 of 25). As a nudge (hero +0.15, reaction -0.15) that made the planner WORSE on his
other projects: first pick 9.0% -> 4.8% (net -7 shots), top three 25.1% -> 21.6% (net -6). Gate not met, nothing adopted. What he keeps when reviewing a
plan on one shoot is not what he cuts on across his work (the taste study found the same: hero was the kind he used least, 7%).

**Learn From My Edit now also records timing and order:** a kept shot trimmed or lengthened by at least 2 frames and 10% is `shortened` / `extended`, and
the fewest kept shots that explain a change of order are `moved` (longest increasing subsequence). These never vote. On his real GWM edit it finds the one
kept shot he cut from 3.84 s to 0.76 s.

**Plan validation.** `post_variants.validate_plan` checks a plan's timeline (back to back from frame 0, lengths add up), every source window (possible,
fills its slot at its speed, inside its clip) and, given the job, that every clip is still the job's and on the drive. Every variant is checked when built,
and again before "Use this variant" replaces the plan (a clip missing from the drive is a 400 naming it; the current plan is left alone).

**`learning/verify_build.py`** reads a saved project and checks a built sequence against its plan: clip per slot, source in within one source frame,
timeline start and length within half a frame, total length, brand cards on V2, and (with a copy saved before the build) that no other sequence changed.
Tested on synthetic sequences only; it is for the real-Premiere checklist, which now also lists every section-14 item and how it is checked.

**A defect I introduced and caught (2026-10-22):** the new Learn hook wrote learning events into the job's REAL folder even when a test had redirected the
Learn log to a temp folder. `autosave_test.py` reads his real GWM auto-saves, so each of my four full-suite runs left 81 test events in GWM's
`10_PREMIERE/edit_plans/learning_events.jsonl` (324 in all), and my first import copied them into the central store. Fixed: the event copy follows the log
(no copy when the log is redirected), `autosave_test.py` now also checks the job's plans folder is untouched, the central store was cleaned (274 genuine
events left), and the votes were never inflated (repeated observations of a shot collapse to one). **Still to do when the Joshx SSD is plugged in again:
delete GWM's `learning_events.jsonl`** -- every line in it is a test artefact from today.

### Final review (Opus, read-only, after the second round) and what was done

| Finding | Outcome |
| --- | --- |
| `verify_build` expected a slowed shot at its real-time in point; the plugin builds every shot from `source_in` (so a slowed shot starts a quarter slot later). Every slowed shot would have FAILED the real-Premiere check; its own test asserted the same wrong model; the checklist said a slowed shot "shows half as much footage" | Fixed to what `index.js` does; test now builds the shot the plugin's way and also proves the old expectation fails; checklist corrected |
| `verify_build` tolerance ignored the plugin's snapping of in points to the SEQUENCE frame grid (59.94 fps footage in a 25 fps edit is up to 1.2 source frames off) | Tolerance = the larger of one source frame and half a sequence frame; checked with 59.94 fps |
| Lock then Unlock left the shot "kept", so Regenerate still skipped it, contrary to the Unlock tooltip | A lock's own approval is taken back on unlock; a Keep, swap or slow motion in between stands; checked both ways |
| Three "Keep this" clicks counted as three taste votes; keeping a moment he picked himself counted as the planner's kind being kept | Explicit votes collapse per shot and stretch (latest wins); decisions about his own picks never vote; checked. Real votes 97 -> 96 |
| The adopted-file reader accepted NaN; its docstring overclaimed | Finite numbers only; wording says a hand-edited file could steer a plan and every plan says when a nudge was applied |
| A test asserted his real adopted file must not exist (breaks once he adopts); another followed his real file | Both now compare the real file's state before/after or point at a temp path |
| The reason fallback could attach to a "moved" seen in a finished timeline | Only his own review-page changes |
| Regenerate's picker pass ran on the event loop | Worker thread (the only shared cache is identity-checked) |
| The use route took two extra pooled connections; Regenerate archived even when nothing changed; variants' fade values didn't match the shared cut; a song of his named "..._variants_..." would have been hidden | All fixed |
| Left as is: after a Regenerate, the NEIGHBOURS' "why this shot" text (scored against the old neighbours) is not recomputed | Known, minor |
| Clean: the temp-folder guard on macOS paths, `_longest_increasing` (3000 random cases), `validate_plan` (no false positives across all 10 buildable styles at 23.976-59.94 fps), regenerate/lock logic, the held-out leakage guard, no test writing to real data | -- |

## 9. Tests by kind (master prompt section 13)

As run on 2026-10-22 afternoon, after the final review's fixes, with the Joshx SSD and Lexar drives UNPLUGGED: 1059 checks passed, 0 failed, 6 sections
skipped (5 need a drive, 1 needs 4K fixture footage that is no longer on this machine). Plugin mocks: 157 passed. Backend restarted onto this code.

| Kind | What it means | Files |
| --- | --- | --- |
| Unit | pure functions on synthetic data, no tools, no network | `learning_events_test`, `style_library_test`, `candidate_engine_test` (incl. golden plans from the committed code), `picker_test`, `review_additions_test`, `variants_test` (pure part), `adopt_preferences_test` (gate, reader, importer), `verify_build_test`, `taste_test`, `rhythm_test`, `slowmo_test`, `usual_pace_test`, `pipeline_test`, `plan_history_test`, `drive_guard_test` |
| Offline integration | real tools or real files, no Premiere | `cost_cache_test` (real ffmpeg sampling), `slowmo_review_test` (real ffmpeg renders), `adopt_preferences_test` (his real GWM feedback file); with the drives: `autosave_test` (his real GWM auto-saves), `learn_from_edit_test` (his real GWM project), `rhythm_test` / `usual_pace_test` (his real projects and clips), the live GWM variant runs through the real backend (manual, recorded in section 8) |
| Mock (a stand-in at one boundary) | the logic is real; one side is faked | `routes_test` (FastAPI TestClient; token, job lookup, audit log and drive folder stubbed), `variants_test` job-level flow and `adopt_preferences_test` planner hook (database, song analysis and music render stubbed), `cost_cache_test` (fake Claude client), `plugin_*_test.js` x7 (a mock of Premiere's UXP API), the browser look at both pages (real app, synthetic footage) |
| Real Premiere | nothing yet | `premiere-plugin/REAL_PREMIERE_CHECKLIST.md`, sections 1-4 |

### Still unverified

- **Nothing here has run in real Premiere.** The plugin is unchanged and a variant is an ordinary highlight plan, so it goes through the build path that
  was verified for highlight plans; a closing card without an opening card has not been seen in Premiere. See `premiere-plugin/REAL_PREMIERE_CHECKLIST.md`.
- The review controls were looked at against the real routes with synthetic footage, not on a real job (they would change his real plan).
- Learning events from a real Learn From My Edit click (the importer is tested on his 3 real feedback files; the hook offline).
- **Learned preferences change no plan today**: the path exists and is tested, but the first real gate run (96 votes) failed, so nothing is adopted.
  It re-runs with `learning.adopt_preferences --save` as his decisions accumulate.
- The real-GWM half of `autosave_test.py` (including the new plans-folder check) did not run this afternoon: the SSD was unplugged.
- The desktop app was not rebuilt; the new pages are reached from the review page (Variants link) or by URL.
