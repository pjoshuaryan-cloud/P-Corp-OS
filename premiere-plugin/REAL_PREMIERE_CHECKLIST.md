# Real-Premiere checklist: editing intelligence upgrade (2026-10-22)

What in this upgrade has been checked **without** real Premiere, and exactly what to do in Premiere to check the rest. Nothing below has been run in real
Premiere yet. The plugin (`index.js`) was not changed: variants and review changes only change the plan file the existing **Build My Edit** reads.

Legend: **offline** = tested in code with no Premiere; **live backend** = run through the real local backend on real footage; **browser** = the page looked at
in a browser against the real routes with synthetic footage; **Premiere** = still to do, below.

| What | Checked so far | Still to check in Premiere |
| --- | --- | --- |
| Variant plans (2-4 directions from one analysis) | offline (59 checks), live backend on GWM job 48 (set `20261022T094507`) | Build a chosen variant |
| Choosing a variant (current plan archived, variant becomes the plan) | offline + route test | Build it; Restore the old plan |
| Closing brand card on a variant that ends on a brand card | offline (card drawn, sits on the closing hold) | The card lands on V2 over the closing hold |
| Lock / Regenerate / earlier-later / reason chips | offline (55 checks), route test (32), browser | Build after using them |
| "Why this shot" lines | offline, browser | none (backend only) |
| Learning events from Learn From My Edit and the auto-save watch | offline on the 3 real feedback files (224 events, incl. a real trimmed shot) | One real Learn From My Edit click |
| The build matches its plan frame by frame | `learning/verify_build.py`, offline on synthetic sequences (12 checks) | Run it on the sequence you build in section 1 |

## 1. Build a variant (about 10 minutes)

1. In your browser open `http://127.0.0.1:8731/static/edit_variants.html?job=48` (or click **Variants** at the top of the review page).
   A set already exists for GWM (`20261022T094507`: Music-led montage 29 shots, High-energy commercial 31, Premium / luxury 21; 20 s each). Or build a fresh
   one: tick 2-4 directions, **Build variants** (about 7 seconds, no Claude call). (An older set, `20261022T090321`, was made before two fixes; ignore it.)
2. Click **Use this variant** on one. Expect: "… is now the plan"; your previous plan is listed in Plan history.
3. In Premiere (Beta), open the GWM project and **save it once before building** (or tell me first and I copy the saved .prproj): that copy is what proves
   afterwards that no existing sequence changed. Then run **Build My Edit**.
4. Expect:
   - a NEW sequence; nothing existing changed;
   - the number of shots and the average shot length the variants page showed for that variant (e.g. Premium: 21 shots, 0.83 s on average);
   - the music is the file `sero - Moon Road_variants_20261022T094507.wav`, exactly 20.0 s (each set has its own music cut; your earlier plan's music file
     is untouched, and these cuts are never offered as songs when you plan);
   - High-energy and Premium end on your closing brand card on V2 over the closing hold (GWM has a logo, so it was drawn: `corp_card_closer_e24056e5.png`,
     2160 × 3840, the last 62 frames); Music-led montage ends on a held hero shot with no card. No opening card and no logo bug in any variant;
   - hard cuts only. Anything listed under "suggested" on the variants page (dissolves, speed ramps, colour, sound design) is NOT built.
5. Save the project and tell me. I run the frame-by-frame check on the saved project (or you can, from `backend/`):

   ```
   .venv/bin/python -m learning.verify_build --project "<the .prproj>" --plan "<edit_plans>/edit_plan_latest.json" --before "<the copy from step 3>"
   ```

   It prints PASS/FAIL per check: every shot's clip, source in point (within one source frame), timeline start and length (within half a frame), the total
   length, the brand card on V2, and that no other sequence changed. It reads video tracks only, so music, zooms, scaling and captions are checked by eye (section 4).
6. To go back: Plan history in P Corp OS, **Restore** the previous plan.

## 2. Review controls, then build (about 10 minutes)

1. Open the review page for the job (P Corp OS opens it, or `http://127.0.0.1:8731/static/edit_review.html?job=48`).
2. **Lock** one shot, **Keep this** on another, swap a third. **Regenerate shots…** over a range that includes all three. Expect: "regenerated N shots,
   3 of yours left as they were"; those three do not change; each regenerated shot offers back what it showed before ("before regenerate"), and Plan
   history has the plan from before the regeneration.
3. On one shot click **later →** (or **← earlier**). Expect: the same clip, re-timed by the stated seconds (half the shot's length, 0.2-1 s).
4. After a swap, click a reason chip (try **Client asked for it** once). Expect: "Reason saved … (not counted as your taste)".
5. **Build My Edit**, save, tell me. Expect: cut points identical to before (only which footage fills them changes), the locked shots exactly as they were,
   the nudged shot starting later/earlier by the stated amount.

## 3. One Learn From My Edit click (2 minutes)

1. After editing a built sequence a little, click **Learn From My Edit** in the plugin.
2. Expect the usual report. Then `GET /post/jobs/48/learning-events` (or tell me) should show new `observed_edit` events: `observed` if the sequence was built
   from the current plan, `uncertain` otherwise; a kept shot you trimmed or lengthened shows as `shortened` / `extended`, one you moved as `moved`. Nothing
   changes any plan: `learning.adopt_preferences` decides whether anything learned may, and on 22 Oct its held-out test said no.

## 3b. A project of your own (not a P Corp shoot), e.g. HAUS WINE - CAMPAIGN (added 2026-10-22)

1. Reload the plugin in Premiere (it changed: Learn now handles projects P Corp didn't make).
2. With the project open and your cut's sequence active, click **Learn From My Edit**. Expect: "This project isn't one of P Corp OS's shoots ...", then
   either your cut read as-is (shots, pace) or, for a stringout like `horizontal` today, "... is your clips laid end to end ... nothing was saved"; in both
   cases "Watching this project's auto-saves from now on".
3. Keep cutting. 45 minutes after you stop changing the cut it is logged by itself (`GET /post/autosave-watch` lists the project and its sequences).

## 3c. The learned vertical in HAUS WINE - CAMPAIGN (added 2026-10-22)

0. (2026-10-23, the full version) First: set `vertical` to 2160 x 3840 (Sequence Settings) -- the logo/end-card images are drawn for that size and are
   refused otherwise -- and, with `vertical` open, File > New > Adjustment Layer at 2160 x 3840 (keep the old one). Expect in the build: shots picked
   by picture, his music on A2, his 11 sounds on A3/A4, 2 flashes + 3 zoom hits on V2 copied from the NEW adjustment layer ("Using the Adjustment Layer
   that covers this sequence"), zoom blur on 3 shots, B&W on 4, 12 punch-ins, logo (fading in 3 steps) and end card on V3. Then paste his titles.
1. Reload the plugin. Open the HAUS project. Click **Build My Edit**. Expect "This project isn't a P Corp shoot, but it has a plan learned from your
   own cut." then "Building the plan learned from "horizontal - CUT LOCK" ...", and a NEW sequence
   `HAUS WINE  - CAMPAIGN (vertical, learned) - Edit <time>`, settings copied from `vertical`. Since 2026-10-23 the plan is his FINISHED cut: 35 shots,
   535 frames (22.31 s at 23.976), cut points identical to his, plus his song ("Lamb Truck Keys", from 10.594 s, -5 dB, hard end) on A2:
   "Music "...from10.594s_535f_-5.0dB.wav" placed on audio track 2." No camera sound, SFX, effects or graphics yet. Nothing else in the project changes.
   (The 20:33 rough-cut plan, 50 shots / 2824 frames, is kept in the workspace as `edit_plan_learned_vertical_20261022T205439.json`.)
2. Save the project (Cmd+S), then tell me: `learning/verify_build.py` checks every shot against the plan from the saved file.
3. Change whatever you'd change, then click **Learn From My Edit** on that sequence. Expect "how much of it you kept": shots kept, moved to another
   moment in the same clip, or dropped. That number is the score of the transfer.

## 4. The full list (master prompt section 14) and how each is checked

| Check | How | Expected |
| --- | --- | --- |
| Source media mapping | `verify_build`: clip per slot | every shot uses the planned file |
| Frame-accurate in/out points | `verify_build`: source in within one source frame; length within half a timeline frame | all PASS |
| Sequence timebase | Sequence > Sequence Settings | the job's frame rate (GWM: 25 fps) and its frame size (GWM: 2160 × 3840) |
| Track placement | `verify_build` (V1 footage, V2 cards) + eye | footage on V1, cards on V2, nothing on V3/V4 for a highlight |
| Music placement | eye/ear | the set's own music cut on A1 from 0, ends with the picture, fades out |
| Variant sequence creation | the Project panel | one NEW sequence per build, named `<shoot> - Edit <time>` |
| Timeline duration | `verify_build` | the plan's length to the frame |
| Markers and metadata | eye | unchanged: this upgrade adds none |
| Media scaling | eye (Effect Controls > Motion) | every clip fills the vertical frame, centred (fill-frame) |
| Supported effects | eye | hard cuts only; slow zooms only where the plan lists them; nothing from the "suggested" lists |
| Recovery from an interrupted build | close Premiere mid-build, reopen, Build My Edit again | a second NEW sequence; the half-built one is left for you to delete; nothing else changed |
| Learn From My Edit observations | section 3 | new events, honest confidence |
| Original sequences untouched | `verify_build --before` | "no existing sequence was changed or removed" PASS |

## Known limits (not bugs)

- Pace differences are smaller than the direction names suggest. On GWM over 8 seeds, High-energy averaged 13% shorter shots than Music-led montage but was no
  faster in 2-3 of the 8; every cut snaps to a strong beat, and the beats decide. The variants page now says so when it happens. Premium is reliably ~40% slower.
- Slow motion is still NOT applied in Premiere (no scripting API for it; see the slow-motion spike). A shot you slowed in review is built at NORMAL speed:
  a full slot of footage starting a quarter of the slot later than the un-slowed moment (the plan's half-length window plays on past its end).
  `verify_build` expects exactly that and says so in a note.
- Opening/closing "preferences" are preferences: each variant says what it actually opened and closed on.
