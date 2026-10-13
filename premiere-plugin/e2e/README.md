# Real-Premiere test harness (scripts only, no media)

These drive the REAL Premiere through Adobe's UXP Developer Tools service (ws://localhost:14001/socket/cli),
so the plugin can be tested without clicking. Needs: Premiere (Beta) running, the UXP Developer Tools app/service running.

- `udt.js` / `udt_session.js` -- load the plugin, attach the debugger (CDP). The plugin session lives only while the CLI websocket stays open.
  `Runtime.evaluate` needs the contextId from `Runtime.executionContextCreated`; do NOT await `Debugger.enable` (it hangs).
  **`awaitPromise` does NOT resolve in this context** -- fire the async call, store the result in a `window.__x` variable, poll it (see `e2e_run.js`, `e2e_readback.js`).
- `e2e_run.js <function> [maxSeconds]` -- runs a plugin function (e.g. `assembleEdit`) inside Premiere and streams the panel log.
- `e2e_readback.js` -- READ-ONLY: items per video track, disabled count, `.srt` in the project, for the newest "- Edit" sequence.
- `e2e_frames.js` -- exports frames from the timeline to look at.
- `e2e_make_job.py`, `e2e_api.py` -- make a throwaway ("ZZ TEST ... (delete me)") POST job / call the backend (token read from the backend, never printed).
- `check_corporate_graphics.py <project.prproj> <edit_plan_latest.json> [sequence]` and `check_multicam.py` -- verify from the SAVED project, frame by frame.

Always delete the throwaway jobs afterwards (`DELETE /post/jobs/{id}`) and tell Josh before running anything in his Premiere.

Added 2026-10-13 (accents re-test):
- `e2e_eval.js '<async JS body returning a value>'` -- run any read/debug snippet inside the plugin in the real Premiere (fire + poll) and print the JSON.
- `accents_prepare.py <job id>` -- adds accents to a scratch job's saved plan using STAND-IN sound effects made in `e2e/sfx_lib` (the real library lives on the Joshx SSD); never touches the real cached SFX index.
- `check_accents.py <project.prproj> <sequence prefix> <edit_plan_latest.json>` -- verifies shots, per-shot effects, V2 adjustment layers (values), logo and sound effects from the SAVED project.
- `plugin_accents_test.js` -- the accents mock suite (includes the Adjustment Layer size check).
- `E2E_FORMAT=9:16 python e2e_make_job.py ...` makes a vertical job.
- The scratch project has no "Adjustment Layer" item and Premiere can't create one: import a COPY of a project that has one (`project.importFiles([copy.prproj], true, root, false)`); the item arrives with that project's frame size -- see the size warning in the plugin.
