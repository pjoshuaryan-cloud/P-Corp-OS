/**
 * P Corp POST -- Phase 3 real plugin (2026-09-26).
 *
 * Built directly on the confirmed-working calls from the hands-on spike
 * (see project_pcorp_post_division.md): Project.createProject(),
 * FolderItem.createBinAction()+executeTransaction() run inside
 * project.lockedAccess(), project.importFiles(), and
 * project.createSequence(name, "") -- an empty preset string, proven to
 * create a real sequence without needing a resolved .sqpreset path.
 *
 * A panel with a manual button, not a persistent background poller and
 * not a UXP "command" menu entrypoint (that type was never hands-on
 * verified) -- Josh opens this panel and clicks the button only when a
 * job is actually ready, matching the same "explicit gate" pattern as
 * every other POST phase (/start, /analyze-media). Nothing here runs
 * automatically.
 *
 * Never touches other effects, music, or transitions -- the created
 * sequence is an empty, correctly-named starting point only. Phase 5
 * (2026-09-26) adds Project-panel color LABELING (a real, documented,
 * non-destructive organizational flag, never a grading change) for
 * files P Corp OS's own media analysis flagged as corrupt, exposure-
 * outlier, Log/HDR, or color-cast. Phase 5 (2026-09-28) separately adds
 * "Apply Starting Exposure" -- its own explicit action, confirmed via a
 * real hands-on spike that AE.ADBE Lumetri genuinely inserts onto a bin
 * clip's video component chain -- setting a real, capped (+/-1 stop),
 * disclosed-as-rough Exposure nudge on clips flagged over/underexposed.
 * This is the one real grading value this plugin ever sets; the exact
 * stops value is computed once, server-side (post_media.py's
 * compute_exposure_nudge_stops), never re-derived here.
 *
 * Phase 6 (2026-09-27) adds "Transcribe Dialogue" -- a second, separate
 * manual action (never bundled into "Prepare POST Project", since
 * transcription can take real minutes for a long clip) that runs
 * Premiere's own real, on-device, native transcription
 * (ppro.Transcript.transcribeClipProjectItem/exportToJSON, confirmed
 * genuinely working via a real hands-on spike against Josh's installed
 * Premiere Beta build, real word-level timing, real speaker diarization
 * -- Premiere's own default unlabeled-speaker name is literally
 * "Unknown") and reports the real result back to P Corp OS. Operates on
 * whatever project is CURRENTLY OPEN (ppro.Project.getActiveProject()),
 * matched back to its own P Corp OS job via the real project.path
 * property against that job's stored premiere_project_path -- this is a
 * separate, later action that may run in a different Premiere session
 * entirely from when the project was first created, so it never assumes
 * the `project` variable from a "Prepare POST Project" run is still
 * around.
 */

const output = document.getElementById("output");
const runButton = document.getElementById("runButton");
const transcribeButton = document.getElementById("transcribeButton");
const smartSelectsButton = document.getElementById("smartSelectsButton");
const exposureButton = document.getElementById("exposureButton");
const roughCutButton = document.getElementById("roughCutButton");
const editButton = document.getElementById("editButton");
const learnButton = document.getElementById("learnButton");
const buildButton = document.getElementById("buildButton");
const moreToggle = document.getElementById("moreToggle");
const morePanel = document.getElementById("morePanel");
const settingsButton = document.getElementById("settingsButton");
const tokenRow = document.getElementById("tokenRow");
const tokenInput = document.getElementById("tokenInput");
const saveTokenButton = document.getElementById("saveTokenButton");

const ppro = require("premierepro");

const BACKEND_BASE = "http://127.0.0.1:8731";
const TOKEN_STORAGE_KEY = "pcorp_post_auth_token";

const DRONE_MAKES = ["dji", "autel", "skydio", "parrot"];
const PHONE_MAKES = ["apple", "iphone", "samsung", "google", "pixel"];
const BIN_LABELS = { video: "Video", audio: "Audio", image: "Stills", drone: "Drone", phone: "Phone" };

// Proxies make editing smoother on a slow machine but mean you are cutting the proxy, not the
// camera original. Off by default so a project always opens on the full-resolution footage; the
// proxy files stay on disk and can be attached later by flipping this to true and running Prepare
// on a fresh project. (Premiere has no scripting call to detach one once attached -- use
// right-click > Proxy > Detach Proxy, or turn off Toggle Proxies in the Program monitor.)
const ATTACH_PROXIES = false;

// Phase 5 -- Project-panel color label INDEXES (createSetColorLabelAction
// takes an index, not a color name). Premiere's own label names/colors
// are user-renameable per install, so these indexes are a starting
// guess, not a confirmed color -- the panel logs which index it applied
// to which category so Josh can check what that index actually shows as
// on his own Premiere and rename this mapping if he wants different
// colors for different concerns.
const COLOR_LABEL_INDEX = { CORRUPT: 0, EXPOSURE: 1, LOG_OR_HDR: 2, COLOR_CAST: 3 };

/** Priority when a file has more than one flag: corrupt (Phase 2's own
 * probe_error) > exposure outlier > Log/HDR footage needing a LUT >
 * color cast > no label at all. Returns null when nothing about this
 * file needs visual flagging in the Project panel. */
function colorLabelIndexForFile(file) {
    if (file.probe_error) return COLOR_LABEL_INDEX.CORRUPT;
    if (file.exposure_flag === "underexposed" || file.exposure_flag === "overexposed") return COLOR_LABEL_INDEX.EXPOSURE;
    if (["log", "hdr_hlg", "hdr_pq"].includes(file.color_profile_guess)) return COLOR_LABEL_INDEX.LOG_OR_HDR;
    if (file.color_cast_flag === "warm" || file.color_cast_flag === "cool") return COLOR_LABEL_INDEX.COLOR_CAST;
    return null;
}

function log(line) {
    output.textContent += "\n" + line;
}

// While "Build My Edit" chains Prepare and Assemble, the second step must not wipe what the first one said.
let keepLog = false;

function reset() {
    if (!keepLog) output.textContent = "";
}

function getStoredToken() {
    try {
        return localStorage.getItem(TOKEN_STORAGE_KEY);
    } catch (e) {
        return null;
    }
}

function setStoredToken(token) {
    try {
        localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } catch (e) {
        // Non-fatal -- Josh will just be asked again next time.
    }
}

/** Inline input row in the panel itself, not a modal dialog -- the
 * earlier custom <dialog>+uxpShowModal() approach was never hands-on
 * verified and produced no visible result when tried live, so it's
 * replaced with something simpler and directly visible: a plain input
 * field shown/hidden right in the panel. */
function showTokenRow() {
    tokenRow.classList.remove("hidden");
}

function hideTokenRow() {
    tokenRow.classList.add("hidden");
}

function ensureToken() {
    const token = getStoredToken();
    if (!token) {
        showTokenRow();
        return null;
    }
    hideTokenRow();
    return token;
}

function apiUrl(path, token) {
    const separator = path.includes("?") ? "&" : "?";
    return `${BACKEND_BASE}${path}${separator}token=${encodeURIComponent(token)}`;
}

async function apiGet(path, token) {
    const response = await fetch(apiUrl(path, token));
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return body;
}

async function apiPost(path, token, payload) {
    const response = await fetch(apiUrl(path, token), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return body;
}

/** Best-effort categorization from Phase 2 metadata -- never a confident
 * guess beyond what's actually determinable (see post_media.py's own
 * guess_device_category). Cannot know "Camera A" vs "Camera B" role
 * assignment; unidentified video lands in one shared "Video" bin. */
function categorizeFile(file) {
    const make = (file.camera_make || "").toLowerCase();
    const model = (file.camera_model || "").toLowerCase();
    if (DRONE_MAKES.some((name) => make.includes(name) || model.includes(name))) return "drone";
    if (PHONE_MAKES.some((name) => make.includes(name) || model.includes(name))) return "phone";
    return file.media_type || "other";
}

async function run() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return null;
    }

    runButton.disabled = true;
    reset();

    try {
        log("Looking for a POST job ready for Premiere prep…");
        const { jobs } = await apiGet("/post/jobs?status=ingested", token);
        const readyJobs = jobs.filter((j) => j.media_analyzed_at);
        if (readyJobs.length === 0) {
            log("No jobs are ready. A job needs to be ingested AND have media analysis run (Analyze Media in P Corp OS) first.");
            runButton.disabled = false;
            return null;
        }
        const job = readyJobs[0];
        log(`Found #${job.id} "${job.shoot_name}" (${job.profile}).`);

        log("Fetching prep data (files + metadata)…");
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        log(`${prep.files.length} file(s) to import.`);

        const projectSubfolder = prep.profile === "alpha_mode" ? "10_PREMIERE" : "09_PROJECT FILES";
        const projectPath = `${prep.destination_root}/${projectSubfolder}/${prep.shoot_name}.prproj`;

        log(`Creating project at ${projectPath} …`);
        const project = await ppro.Project.createProject(projectPath);
        if (!project) throw new Error("createProject returned no project");

        const rootItem = await project.getRootItem();

        const byCategory = {};
        for (const file of prep.files) {
            const category = categorizeFile(file);
            (byCategory[category] = byCategory[category] || []).push(file);
        }

        const binsNeeded = Object.keys(byCategory).filter((key) => BIN_LABELS[key] && byCategory[key].length > 0);
        if (binsNeeded.length > 0) {
            log(`Creating bins: ${binsNeeded.map((k) => BIN_LABELS[k]).join(", ")} …`);
            // Real bug found live: calling executeTransaction() separately
            // per bin only ever created the FIRST one -- the rest silently
            // never appeared (files meant for them landed loose in the
            // project root instead). Batching every createBinAction() into
            // ONE compound action inside a single executeTransaction() call
            // is the fix -- all bins now created atomically together.
            await project.lockedAccess(async () => {
                await project.executeTransaction((compoundAction) => {
                    for (const key of binsNeeded) {
                        const binAction = rootItem.createBinAction(BIN_LABELS[key], true);
                        compoundAction.addAction(binAction);
                    }
                });
            });
        }

        // Re-fetch root's children to find the bins we just created.
        // Real bug found live (2026-09-26): rootItem.getItems() returns
        // its children typed as generic ProjectItem, not FolderItem --
        // even though a bin IS semantically a folder, calling a
        // FolderItem-only method (like .getItems() later on, when using
        // this bin as the target for looking up its own imported clips)
        // throws "not a function". ppro.FolderItem.cast() is the real,
        // documented fix -- confirmed necessary the same way
        // project.lockedAccess() was in the original spike: a call
        // failed, so the live object's own real API surface was checked
        // rather than guessed at twice.
        const bins = {};
        try {
            const children = await rootItem.getItems();
            for (const child of children) {
                const childName = typeof child.name === "function" ? await child.name() : child.name;
                for (const key of binsNeeded) {
                    if (childName === BIN_LABELS[key]) bins[key] = ppro.FolderItem.cast(child);
                }
            }
        } catch (e) {
            log(`Warning: couldn't look up created bins (${e}) -- files will import to the project root instead.`);
        }

        for (const [category, files] of Object.entries(byCategory)) {
            const targetBin = bins[category] || rootItem;
            const paths = files.map((f) => f.destination_path);
            log(`Importing ${paths.length} file(s) into "${BIN_LABELS[category] || "root"}"…`);
            try {
                await project.importFiles(paths, true, targetBin, false);
            } catch (e) {
                log(`Warning: import failed for ${category}: ${e}`);
                continue;
            }

            // Look up each newly-imported ClipProjectItem by basename
            // once per bin -- importFiles() doesn't hand these back
            // directly, and both proxy attachment (Phase 4) and color
            // labeling (Phase 5) need the same lookup. Same real bug as
            // the bin lookup above: getItems() returns generic
            // ProjectItem, not ClipProjectItem -- cast is required
            // before calling a ClipProjectItem-only method (attachProxy,
            // createSetColorLabelAction) on one of these.
            let itemByName = {};
            try {
                const items = await targetBin.getItems();
                for (const item of items) {
                    const itemName = typeof item.name === "function" ? await item.name() : item.name;
                    itemByName[itemName] = ppro.ClipProjectItem.cast(item);
                }
            } catch (e) {
                log(`Warning: couldn't look up imported items in "${BIN_LABELS[category] || "root"}" (${e}).`);
            }

            // Phase 4 -- attach a real proxy to each imported file that
            // has one ready. Wrapped in project.lockedAccess() as a
            // precaution -- Phase 3's own real lesson was that an
            // unfamiliar mutating call can silently need it -- verified
            // live rather than assumed either way.
            const proxyFiles = files.filter((f) => f.proxy_path);
            if (!ATTACH_PROXIES && proxyFiles.length > 0) {
                log(`Skipping proxy attachment: ${proxyFiles.length} proxy file(s) exist, but this project is set up on the full-resolution originals.`);
            }
            for (const file of ATTACH_PROXIES ? proxyFiles : []) {
                const baseName = file.destination_path.split("/").pop();
                const clipItem = itemByName[baseName];
                if (!clipItem) {
                    log(`Warning: couldn't find imported clip for "${baseName}" to attach its proxy.`);
                    continue;
                }
                try {
                    await project.lockedAccess(async () => {
                        await clipItem.attachProxy(file.proxy_path, false);
                    });
                    log(`Attached proxy for "${baseName}".`);
                } catch (e) {
                    log(`Warning: attachProxy failed for "${baseName}": ${e}`);
                }
            }

            // Phase 5 -- color-label each imported file that P Corp
            // OS's own media analysis flagged, using the real,
            // documented createSetColorLabelAction() API. All of a
            // bin's label actions are batched into ONE
            // executeTransaction() call -- Phase 3's own real bug was
            // calling executeTransaction separately per action in a
            // loop, which silently only applied the FIRST call; this is
            // the fix pattern already proven for bin creation, reused
            // here rather than risking the same mistake twice.
            const labelTargets = [];
            for (const file of files) {
                const labelIndex = colorLabelIndexForFile(file);
                if (labelIndex === null) continue;
                const baseName = file.destination_path.split("/").pop();
                const clipItem = itemByName[baseName];
                if (!clipItem) continue;  // already warned about above if the lookup itself failed
                labelTargets.push({ clipItem, labelIndex, baseName });
            }
            if (labelTargets.length > 0) {
                try {
                    await project.lockedAccess(async () => {
                        await project.executeTransaction((compoundAction) => {
                            for (const { clipItem, labelIndex } of labelTargets) {
                                compoundAction.addAction(clipItem.createSetColorLabelAction(labelIndex));
                            }
                        });
                    });
                    log(`Color-labeled ${labelTargets.length} file(s) in "${BIN_LABELS[category] || "root"}" `
                        + `(label indexes used: ${[...new Set(labelTargets.map((t) => t.labelIndex))].join(", ")} -- `
                        + `check what these show as on your own Premiere install).`);
                } catch (e) {
                    log(`Warning: color-labeling failed for "${BIN_LABELS[category] || "root"}": ${e}`);
                }
            }
        }

        log("Creating an empty starting sequence…");
        try {
            const startSequence = await project.createSequence(prep.shoot_name, "");
            if (startSequence) {
                const how = await applyJobFormat(project, startSequence, prep);
                log(`Starting sequence format: ${how}; frame size is now ${await describeFormat(startSequence)}.`);
            }
        } catch (e) {
            log(`Warning: sequence creation failed: ${e}`);
        }

        log("Saving project…");
        await project.save();

        log("Reporting completion back to P Corp OS…");
        await apiPost(`/post/jobs/${job.id}/premiere-project-created`, token, { project_path: projectPath });

        log(`Done. "${prep.shoot_name}" is ready in Premiere.`);
        return { job, projectPath };
    } catch (e) {
        log(`Failed: ${e.message || e}`);
        return null;
    } finally {
        runButton.disabled = false;
    }
}

/** Collects every non-sequence ClipProjectItem reachable from the
 * project root: root-level clips directly, plus one level into any real
 * bin (this app's own projects never nest bins deeper than that). Same
 * FolderItem/ClipProjectItem .cast() discipline already proven
 * necessary for bin lookup, proxy attachment, and color labeling. */
async function collectAllClips(project) {
    const rootItem = await project.getRootItem();
    const topLevelItems = await rootItem.getItems();
    const clips = [];
    for (const rawItem of topLevelItems) {
        if (!rawItem) continue;
        const clip = ppro.ClipProjectItem.cast(rawItem);
        if (clip) clips.push(clip);
        const bin = ppro.FolderItem.cast(rawItem);
        if (bin) {
            try {
                const rawClips = await bin.getItems();
                for (const rawClip of rawClips) {
                    if (!rawClip) continue;
                    const nestedClip = ppro.ClipProjectItem.cast(rawClip);
                    if (nestedClip) clips.push(nestedClip);
                }
            } catch (e) {
                // Not actually a folder with real items -- skip.
            }
        }
    }
    return clips;
}

async function transcribeDialogue() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }

    transcribeButton.disabled = true;
    reset();

    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }

        log("Looking up the matching P Corp OS job…");
        const { jobs } = await apiGet("/post/jobs?status=premiere_project_created", token);
        const job = jobs.find((j) => j.premiere_project_path === project.path);
        if (!job) {
            log('Couldn\'t find a P Corp OS job matching this open project. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        log("Fetching file info (which clips have audio)…");
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        const fileByName = {};
        for (const file of prep.files) {
            fileByName[file.relative_path] = file;
        }

        const clips = await collectAllClips(project);
        let transcribedCount = 0;
        let skippedCount = 0;

        for (const clip of clips) {
            if (await clip.isSequence()) continue;
            const name = typeof clip.name === "function" ? await clip.name() : clip.name;
            const file = fileByName[name];
            if (!file || !file.audio_codec) {
                skippedCount += 1;
                continue;
            }

            if (ppro.Transcript.hasTranscript(clip)) {
                log(`"${name}" already has a transcript -- exporting it as-is.`);
            } else {
                log(`Transcribing "${name}"… (this may take a while for a longer clip)`);
                let success;
                try {
                    success = await ppro.Transcript.transcribeClipProjectItem(clip);
                } catch (e) {
                    log(`Warning: transcription failed for "${name}": ${e}`);
                    continue;
                }
                if (!success) {
                    log(`Warning: transcription reported failure for "${name}".`);
                    continue;
                }
            }

            try {
                const transcriptJsonString = await ppro.Transcript.exportToJSON(clip);
                const transcriptJson = JSON.parse(transcriptJsonString);
                await apiPost(`/post/jobs/${job.id}/files/${file.file_id}/transcript`, token, {
                    transcript_json: transcriptJson,
                    language: null,
                });
                log(`Saved transcript for "${name}".`);
                transcribedCount += 1;
            } catch (e) {
                log(`Warning: couldn't save transcript for "${name}": ${e}`);
            }
        }

        log(`Done. ${transcribedCount} file(s) transcribed and saved, ${skippedCount} skipped (no matching audio track).`);
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        transcribeButton.disabled = false;
    }
}

runButton.addEventListener("click", () => {
    run().catch((e) => log(`Unhandled error: ${e}`));
});

transcribeButton.addEventListener("click", () => {
    transcribeDialogue().catch((e) => log(`Unhandled error: ${e}`));
});

/**
 * Phase 8a (2026-09-27) -- "Suggest Smart Selects". Real marker
 * creation confirmed working via a hands-on spike against Josh's real
 * Premiere (ppro.Markers/ppro.TickTime, independently read back after
 * writing to confirm it actually landed). For each clip in the active
 * project that already has a real stored transcript, fetches the real
 * candidate soundbites (post_transcripts.py's own deterministic
 * sentence-quality derivation) and adds one real marker per candidate,
 * batched into ONE executeTransaction() per clip -- the exact same
 * "never call executeTransaction once per item in a loop" fix Phase
 * 3's own bin-creation bug already taught this codebase. Suggestions
 * only: never places anything on a timeline, never removes/changes
 * existing markers, never decides which take is "the" take.
 */
async function suggestSmartSelects() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }

    smartSelectsButton.disabled = true;
    reset();

    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }

        log("Looking up the matching P Corp OS job…");
        const { jobs } = await apiGet("/post/jobs?status=premiere_project_created", token);
        const job = jobs.find((j) => j.premiere_project_path === project.path);
        if (!job) {
            log('Couldn\'t find a P Corp OS job matching this open project. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        log("Fetching file info…");
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        const fileByName = {};
        for (const file of prep.files) {
            fileByName[file.relative_path] = file;
        }

        const clips = await collectAllClips(project);
        let clipsMarked = 0;
        let totalMarkers = 0;
        let skippedCount = 0;

        for (const clip of clips) {
            if (await clip.isSequence()) continue;
            const name = typeof clip.name === "function" ? await clip.name() : clip.name;
            const file = fileByName[name];
            if (!file) {
                skippedCount += 1;
                continue;
            }

            let candidates;
            try {
                const result = await apiGet(`/post/jobs/${job.id}/files/${file.file_id}/smart-selects`, token);
                candidates = result.candidates;
            } catch (e) {
                log(`"${name}" has no transcript yet -- run Transcribe Dialogue first. Skipping.`);
                skippedCount += 1;
                continue;
            }
            if (!candidates || candidates.length === 0) {
                log(`"${name}" has a transcript but no clean-sentence candidates found.`);
                continue;
            }

            try {
                const markersContainer = await ppro.Markers.getMarkers(clip);
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => {
                        for (const candidate of candidates) {
                            const startTime = ppro.TickTime.createWithSeconds(candidate.start);
                            const duration = ppro.TickTime.createWithSeconds(candidate.duration);
                            const action = markersContainer.createAddMarkerAction(
                                "Smart Select", "Comment", startTime, duration, candidate.text
                            );
                            compoundAction.addAction(action);
                        }
                    });
                });
                log(`Added ${candidates.length} marker(s) to "${name}".`);
                clipsMarked += 1;
                totalMarkers += candidates.length;
            } catch (e) {
                log(`Warning: couldn't add markers to "${name}": ${e}`);
            }
        }

        log(`Done. ${totalMarkers} marker(s) added across ${clipsMarked} clip(s), ${skippedCount} clip(s) skipped.`);
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        smartSelectsButton.disabled = false;
    }
}

smartSelectsButton.addEventListener("click", () => {
    suggestSmartSelects().catch((e) => log(`Unhandled error: ${e}`));
});

/**
 * Phase 5 (2026-09-28) -- "Apply Starting Exposure", built directly from
 * the confirmed Lumetri spike below: AE.ADBE Lumetri genuinely inserts
 * onto a bin clip's video component chain, and a real "Exposure" param
 * exists on it. The real per-clip nudge value (a rough, capped +/-1
 * stop heuristic -- see post_media.py's compute_exposure_nudge_stops)
 * is computed once, server-side, from Phase 5's own real avg_luma --
 * this function only executes it, it never re-derives the value.
 *
 * The one real "Exposure" param index confirmed during the spike
 * (index 19 on this install) is deliberately NOT hardcoded here --
 * looked up live by displayName every run instead, same "ask Premiere
 * itself, don't guess twice" discipline the spike itself was built on,
 * since a param layout could in principle differ by Premiere version.
 *
 * Deliberately its OWN separate, explicit action -- never bundled into
 * "Prepare POST Project" or run automatically -- this is the first
 * time this app sets a real grading value rather than only organizing/
 * flagging clips, so it gets its own deliberate button and its own
 * disclosed UI copy, matching every other capability's own "explicit
 * gate" discipline in this plugin. Skips any clip that already has a
 * Lumetri instance rather than stacking a second one on a re-run.
 *
 * Phase 9 (2026-09-28) adds "Assemble Rough Cut" -- the one action in
 * this plugin that actually places clips on a sequence timeline, a
 * deliberate, user-confirmed crossing of every prior phase's own
 * "suggestions only, never decides the final edit" boundary. Built on
 * a real, hands-on-verified mechanism: clip.createSubClipAction(...)
 * creates a real, separate ProjectItem for a candidate's time range;
 * the resulting subclip must be looked up and inserted RAW (never
 * passed through ppro.ClipProjectItem.cast()) or
 * sequenceEditor.createInsertProjectItemAction() silently returns
 * undefined with no thrown error. Always creates a new, uniquely
 * timestamped sequence per run and never touches any existing one.
 * Mechanical assembly only (clip order, chronological within each
 * clip) -- never a claim about pacing or which moment is creatively
 * best.
 */
async function applyStartingExposure() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }

    exposureButton.disabled = true;
    reset();

    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }

        log("Looking up the matching P Corp OS job…");
        const { jobs } = await apiGet("/post/jobs?status=premiere_project_created", token);
        const job = jobs.find((j) => j.premiere_project_path === project.path);
        if (!job) {
            log('Couldn\'t find a P Corp OS job matching this open project. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        log("Fetching file info (exposure analysis)…");
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        const fileByName = {};
        for (const file of prep.files) {
            fileByName[file.relative_path] = file;
        }

        const clips = await collectAllClips(project);
        let adjustedCount = 0;
        let alreadyHadLumetriCount = 0;
        let skippedCount = 0;

        for (const clip of clips) {
            if (await clip.isSequence()) continue;
            const name = typeof clip.name === "function" ? await clip.name() : clip.name;
            const file = fileByName[name];
            if (!file || !file.exposure_nudge_stops) {
                skippedCount += 1;
                continue;
            }

            const chain = await clip.getComponentChain(ppro.Constants.MediaType.VIDEO);
            if (!chain) {
                log(`"${name}": no video component chain -- skipping.`);
                skippedCount += 1;
                continue;
            }

            try {
                const existingCount = await chain.getComponentCount();
                let lumetriIndex = -1;
                for (let i = 0; i < existingCount; i++) {
                    const existing = await chain.getComponentAtIndex(i);
                    if ((await existing.getMatchName()) === "AE.ADBE Lumetri") {
                        lumetriIndex = i;
                        break;
                    }
                }

                if (lumetriIndex === -1) {
                    const newComponent = await ppro.VideoFilterFactory.createComponent("AE.ADBE Lumetri");
                    await project.lockedAccess(async () => {
                        await project.executeTransaction((compoundAction) => {
                            compoundAction.addAction(chain.createInsertComponentAction(newComponent, existingCount));
                        }, "P Corp POST -- Add Lumetri Color");
                    });
                    lumetriIndex = existingCount;
                } else {
                    alreadyHadLumetriCount += 1;
                }

                // Re-fetch the chain after any insert -- the freshly-
                // created component reference isn't guaranteed to be the
                // live, inserted instance's own param-bearing object.
                const chainNow = await clip.getComponentChain(ppro.Constants.MediaType.VIDEO);
                const lumetriComponent = await chainNow.getComponentAtIndex(lumetriIndex);

                const paramCount = await lumetriComponent.getParamCount();
                let exposureParam = null;
                for (let p = 0; p < paramCount; p++) {
                    const param = await lumetriComponent.getParam(p);
                    if (param.displayName === "Exposure") {
                        exposureParam = param;
                        break;
                    }
                }
                if (!exposureParam) {
                    log(`"${name}": couldn't find a real "Exposure" param on the Lumetri instance -- skipping.`);
                    skippedCount += 1;
                    continue;
                }

                const keyframe = exposureParam.createKeyframe(file.exposure_nudge_stops);
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => {
                        compoundAction.addAction(exposureParam.createSetValueAction(keyframe, true));
                    }, "P Corp POST -- Set starting Exposure");
                });

                log(`"${name}": set Exposure to ${file.exposure_nudge_stops} stop(s) `
                    + `(${file.exposure_flag}, real avg luma ${file.avg_luma}).`);
                adjustedCount += 1;
            } catch (e) {
                log(`Warning: exposure adjustment failed for "${name}": ${e}`);
            }
        }

        log(`Done. ${adjustedCount} clip(s) adjusted (${alreadyHadLumetriCount} already had Lumetri and were reused), ${skippedCount} skipped (no flag or no video).`);
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        exposureButton.disabled = false;
    }
}

exposureButton.addEventListener("click", () => {
    applyStartingExposure().catch((e) => log(`Unhandled error: ${e}`));
});

// ---------------------------------------------------------------- Assemble Rough Cut
//
// REWORKED 2026-10-06 after the first real run crashed Premiere Pro (Beta)
// 27.1.0 at 77 of 112 clips: a crash in Premiere's own UXP runtime (a V8
// garbage-collection weak-reference callback, dvascripting thread). The old
// version re-scanned every project item by name after EVERY piece (tens of
// thousands of short-lived wrapper objects) and ran two transactions per
// piece. This version works in phases with a handful of large transactions
// and ONE project scan, holds every Premiere object it creates until the run
// ends, and saves between phases so a crash costs little:
//   1. read the clip order straight off the user's own ordered timeline
//   2. ask P Corp OS for each clip's best moments
//   3. new sequence in the same format as that timeline
//   4. create ALL subclips (batched), save
//   5. find them all with a single scan
//   6. insert them in order (batched), save
//   7. tidy the pieces into their own bin, save, report back
// Whether this stops the crash is untested -- it can't be exercised outside
// Premiere -- but it removes the specific behaviour that stressed the runtime.

// How many moments to take from each clip. 1 = only each clip's single best
// moment (the highest-ranked pick: steadiest/sharpest and rated as showing
// something intended). Josh asked for this on 2026-10-06 to keep the cut short;
// raise it to take more per clip (the backend stores up to 3, best first).
const ROUGH_CUT_MAX_CANDIDATES_PER_CLIP = 1;
// Actions per transaction. One transaction per piece (the old way) was part of
// what crashed Premiere; one giant transaction risks a long freeze.
const ROUGH_CUT_BATCH_SIZE = 20;
const ROUGH_CUT_PIECES_BIN = "Rough Cut Pieces";
const ROUGH_CUT_PAUSE_MS = 40;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function itemName(item) {
    if (!item) return "";  // Premiere can hand back empty entries in an item list
    return typeof item.name === "function" ? await item.name() : item.name;
}

/** Frame size the job's own NEW SHOOT choices call for, or null when the
 * job's format isn't a standard one we can derive a size from. */
function deliverableFrameSize(prep) {
    if (prep.resolution !== "4k_uhd" && prep.resolution !== "4k_dci") return null;
    const longEdge = prep.resolution === "4k_dci" ? 4096 : 3840;
    const shortEdge = 2160;
    switch (prep.deliverable_format) {
        case "16:9": return { width: longEdge, height: shortEdge };
        case "9:16": return { width: shortEdge, height: longEdge };
        case "1:1": return { width: shortEdge, height: shortEdge };
        case "4:5": return { width: shortEdge, height: 2700 };
        default: return null;
    }
}

function deliverableFrameRate(prep) {
    const table = { "23.976": 24000 / 1001, "24": 24, "25": 25, "29.97": 30000 / 1001, "30": 30, "50": 50, "59.94": 60000 / 1001 };
    return table[prep.frame_rate] || null;
}

/** Sets a new sequence's frame size and rate from the job's own choices
 * (previously the plugin ignored them and every sequence came out
 * landscape 1080p). Returns a short description for the log; never throws. */
async function applyJobFormat(project, sequence, prep) {
    try {
        const size = deliverableFrameSize(prep);
        const rate = deliverableFrameRate(prep);
        if (!size && !rate) return "left at Premiere's default (the job's format isn't a standard preset)";
        const settings = await sequence.getSettings();
        if (size) {
            const rect = new ppro.RectF();
            rect.width = size.width;
            rect.height = size.height;
            await settings.setVideoFrameRect(rect);
        }
        if (rate) settings.setVideoFrameRate(ppro.FrameRate.createWithValue(rate));
        await project.lockedAccess(async () => {
            await project.executeTransaction((compoundAction) => {
                compoundAction.addAction(sequence.createSetSettingsAction(settings));
            }, "P Corp POST -- Set sequence format");
        });
        return `set from the job's choices (${prep.deliverable_format}, ${prep.resolution}, ${prep.frame_rate} fps)`;
    } catch (e) {
        return `COULD NOT BE SET (${e}) -- left at Premiere's default`;
    }
}

/** Copies one sequence's settings onto another so the rough cut comes out in
 * exactly the format of the timeline the user already set up. */
async function matchSequenceFormat(project, source, target) {
    try {
        const settings = await source.getSettings();
        await project.lockedAccess(async () => {
            await project.executeTransaction((compoundAction) => {
                compoundAction.addAction(target.createSetSettingsAction(settings));
            }, "P Corp POST -- Match sequence format");
        });
        return "matched to your ordered timeline";
    } catch (e) {
        return `COULD NOT BE MATCHED to your timeline (${e})`;
    }
}

async function describeFormat(sequence) {
    try {
        const rect = await sequence.getFrameSize();
        return `${rect.width}x${rect.height}`;
    } catch (e) {
        return "unknown";
    }
}

/** The clip order the user already laid out: finds the sequence named after
 * the shoot (or the active one if it isn't a rough cut), reads its video
 * tracks' clips and orders them by position on the timeline. Returns
 * { source: Sequence | null, names: [clip name, ...] } -- first occurrence of
 * each clip only. */
async function readTimelineOrder(project, shootName) {
    let source = null;
    try {
        const sequences = await project.getSequences();
        source = sequences.find((sequence) => sequence.name === shootName) || null;
    } catch (e) {
        // fall through to the active sequence
    }
    if (!source) {
        try {
            const active = await project.getActiveSequence();
            if (active && !String(active.name).includes("Rough Cut")) source = active;
        } catch (e) {
            // no usable sequence
        }
    }
    if (!source) return { source: null, names: [] };

    const entries = [];
    const trackCount = await source.getVideoTrackCount();
    for (let trackIndex = 0; trackIndex < trackCount; trackIndex++) {
        const track = await source.getVideoTrack(trackIndex);
        const trackItems = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
        for (const trackItem of trackItems) {
            const start = await trackItem.getStartTime();
            let name = null;
            try {
                name = await itemName(await trackItem.getProjectItem());
            } catch (e) {
                // fall back to the track item's own name
            }
            if (!name) {
                try {
                    name = await trackItem.getName();
                } catch (e) {
                    // unnamed
                }
            }
            if (name) entries.push({ name, start: start.seconds, track: trackIndex });
        }
    }
    entries.sort((a, b) => a.start - b.start || a.track - b.track);
    const seen = new Set();
    const names = [];
    for (const entry of entries) {
        if (!seen.has(entry.name)) {
            seen.add(entry.name);
            names.push(entry.name);
        }
    }
    return { source, names };
}

/** One pass over the project (root + each top-level bin, one level deep)
 * finding the project items with the given names. RAW items, never cast --
 * a cast item makes the insert silently return undefined. */
async function findItemsByName(project, wantedNames) {
    const found = new Map();
    let nulls = 0;  // empty entries Premiere returned in place of items it couldn't wrap
    const rootItem = await project.getRootItem();
    const topLevelItems = await rootItem.getItems();
    const bins = [];
    for (const item of topLevelItems) {
        if (!item) { nulls += 1; continue; }
        const name = await itemName(item);
        if (wantedNames.has(name)) found.set(name, { item, parent: rootItem });
        const bin = ppro.FolderItem.cast(item);
        if (bin) bins.push(bin);
    }
    for (const bin of bins) {
        let children = [];
        try {
            children = await bin.getItems();
        } catch (e) {
            continue;
        }
        for (const child of children) {
            if (!child) { nulls += 1; continue; }
            const name = await itemName(child);
            if (wantedNames.has(name)) found.set(name, { item: child, parent: bin });
        }
    }
    return { found, rootItem, nulls };
}

/** Which job is this open project? Exact stored path first, then the same
 * file name, then -- if exactly one job has a Premiere project -- that one
 * (a recovered or re-saved project has a different path). */
async function findJobForProject(project, token, { lenient = true } = {}) {
    const { jobs } = await apiGet("/post/jobs?status=premiere_project_created", token);
    let job = jobs.find((j) => j.premiere_project_path === project.path);
    if (!job) {
        const baseName = String(project.path || "").split("/").pop();
        job = jobs.find((j) => String(j.premiere_project_path || "").split("/").pop() === baseName);
    }
    // The last guess ("the only prepared job must be this project") is fine for a button you pressed on purpose, but not for deciding whether the open project
    // is a prepared one at all: another project open in Premiere would be taken for it.
    if (!job && lenient && jobs.length === 1) {
        job = jobs[0];
        log("Note: this project's file path differs from the one P Corp OS stored (recovered or re-saved?) -- using the only job that has a Premiere project.");
    }
    return job || null;
}

/** Moves every rough-cut subclip ("RC_..." -- this run's and any left by an
 * earlier run) into one bin so they stop cluttering the Video bin. Cosmetic
 * and non-destructive: nothing is deleted. */
async function tidyRoughCutPieces(project) {
    const rootItem = await project.getRootItem();
    // Reuse the bin from an earlier run: asking Premiere to create a bin whose name is taken makes it add an
    // empty "Rough Cut Pieces 01", "02", ... next to it on every run.
    const findPiecesBin = async () => {
        const items = await rootItem.getItems();
        for (const item of items) {
            if ((await itemName(item)) === ROUGH_CUT_PIECES_BIN) {
                const bin = ppro.FolderItem.cast(item);
                if (bin) return { bin, items };
            }
        }
        return { bin: null, items };
    };
    let { bin: piecesBin, items: topLevelItems } = await findPiecesBin();
    if (!piecesBin) {
        await project.lockedAccess(async () => {
            await project.executeTransaction((compoundAction) => {
                compoundAction.addAction(rootItem.createBinAction(ROUGH_CUT_PIECES_BIN, true));
            }, "P Corp POST -- Create Rough Cut Pieces bin");
        });
        // Premiere can list a new item a moment late
        for (let attempt = 0; attempt < 6 && !piecesBin; attempt++) {
            if (attempt) await sleep(400);
            ({ bin: piecesBin, items: topLevelItems } = await findPiecesBin());
        }
    }
    if (!piecesBin) throw new Error("couldn't find the new bin");

    const toMove = [];
    const bins = [];
    for (const item of topLevelItems) {
        if (!item) continue;
        const name = await itemName(item);
        if (name.startsWith("RC_")) toMove.push({ item, parent: rootItem });
        const bin = ppro.FolderItem.cast(item);
        if (bin && name !== ROUGH_CUT_PIECES_BIN) bins.push(bin);
    }
    for (const bin of bins) {
        for (const child of await bin.getItems()) {
            if (child && (await itemName(child)).startsWith("RC_")) toMove.push({ item: child, parent: bin });
        }
    }
    for (let i = 0; i < toMove.length; i += ROUGH_CUT_BATCH_SIZE) {
        const batch = toMove.slice(i, i + ROUGH_CUT_BATCH_SIZE);
        await project.lockedAccess(async () => {
            await project.executeTransaction((compoundAction) => {
                for (const { item, parent } of batch) compoundAction.addAction(parent.createMoveItemAction(item, piecesBin));
            }, "P Corp POST -- Move rough cut pieces");
        });
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    return toMove.length;
}

/**
 * "Assemble Rough Cut" -- builds a real sequence from each clip's best
 * moments, in the order of the user's own timeline. It actually places clips
 * on a timeline (a deliberate, user-confirmed crossing of this plugin's
 * "suggestions only" line), always into a NEW, separately-named sequence;
 * it never touches an existing one. Mechanism, confirmed live earlier:
 * clipProjectItem.createSubClipAction(...) makes a real subclip ProjectItem
 * for just the moment's range; the RAW (never cast) item is what
 * createInsertProjectItemAction needs.
 */
async function assembleRoughCut() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }

    roughCutButton.disabled = true;
    reset();
    // Hold every Premiere wrapper object until the run ends: letting them be
    // garbage-collected mid-run is what Premiere (Beta)'s runtime crashed on.
    const keepAlive = [];

    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }
        keepAlive.push(project);

        log("Looking up the matching P Corp OS job…");
        const job = await findJobForProject(project, token);
        if (!job) {
            log('Couldn\'t find a P Corp OS job with a Premiere project matching this one. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        log("Fetching file info…");
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        const fileByName = {};
        for (const file of prep.files) fileByName[file.relative_path] = file;

        // 1. ORDER -- the user's own timeline decides it.
        log("Reading the clip order from your timeline…");
        const timeline = await readTimelineOrder(project, prep.shoot_name);
        keepAlive.push(timeline);
        let orderedFiles = [];
        for (const name of timeline.names) {
            if (fileByName[name]) orderedFiles.push(fileByName[name]);
        }
        if (orderedFiles.length > 0) {
            log(`Using the order of "${timeline.source.name}": ${orderedFiles.length} clip(s).`);
        } else {
            orderedFiles = [...prep.files].sort((a, b) =>
                String(a.creation_time || "").localeCompare(String(b.creation_time || "")) || a.relative_path.localeCompare(b.relative_path));
            log("No clips found on a timeline named after this shoot -- using the order they were filmed (camera timestamps).");
        }

        // 2. PLAN -- each clip's best moments from P Corp OS.
        const clips = await collectAllClips(project);
        keepAlive.push(clips);
        const clipByName = {};
        for (const clip of clips) {
            if (await clip.isSequence()) continue;
            clipByName[await itemName(clip)] = clip;
        }
        const runId = Date.now();
        const pieces = [];
        let clipsSkipped = 0;
        let clipsUsed = 0;

        /** One clip's moments: its Smart Selects if it has a transcript, else its
         * best-moment picks. null when it has neither. */
        const fetchMoments = async (file) => {
            try {
                const result = await apiGet(`/post/jobs/${job.id}/files/${file.file_id}/smart-selects`, token);
                if (result.candidates && result.candidates.length > 0) return { candidates: result.candidates, source: "dialogue" };
            } catch (e) {
                // No transcript -- use the best-moment picks instead.
            }
            try {
                const result = await apiGet(`/post/jobs/${job.id}/files/${file.file_id}/highlights`, token);
                if (result.candidates && result.candidates.length > 0) return { candidates: result.candidates, source: "best moment" };
            } catch (e) {
                // none
            }
            return null;
        };

        // Fetched a few at a time (one at a time took minutes and printed
        // nothing, so it looked frozen), then used strictly in timeline order.
        log(`Collecting each clip's best moments (${orderedFiles.length} clips)…`);
        const moments = new Array(orderedFiles.length).fill(null);
        const FETCH_AT_ONCE = 8;
        for (let i = 0; i < orderedFiles.length; i += FETCH_AT_ONCE) {
            const chunk = orderedFiles.slice(i, i + FETCH_AT_ONCE);
            const got = await Promise.all(chunk.map((file) => (clipByName[file.relative_path] ? fetchMoments(file) : null)));
            got.forEach((value, k) => { moments[i + k] = value; });
            if ((i / FETCH_AT_ONCE) % 3 === 2 || i + FETCH_AT_ONCE >= orderedFiles.length) {
                log(`  collected ${Math.min(i + FETCH_AT_ONCE, orderedFiles.length)} of ${orderedFiles.length}`);
            }
        }
        orderedFiles.forEach((file, index) => {
            const clip = clipByName[file.relative_path];
            if (!clip) {
                clipsSkipped += 1;
                log(`"${file.relative_path}": not in the project -- skipping.`);
                return;
            }
            const found = moments[index];
            if (!found) {
                clipsSkipped += 1;
                return;
            }
            // Best first (rank 1 = best; Smart Selects have no rank, so their
            // own confidence decides), keep the top N, then back to time order.
            const byQuality = [...found.candidates].sort((a, b) =>
                (a.rank ?? 99) - (b.rank ?? 99) || (b.confidence ?? 0) - (a.confidence ?? 0));
            const sorted = byQuality.slice(0, ROUGH_CUT_MAX_CANDIDATES_PER_CLIP).sort((a, b) => a.start - b.start);
            sorted.forEach((candidate, i) => {
                pieces.push({ clip, file, source: found.source, candidate, name: `RC_${file.file_id}_${i}_${runId}` });
            });
            clipsUsed += 1;
        });
        if (pieces.length === 0) {
            log('Nothing to assemble: no clip has best moments or Smart Selects yet. Run "Detect Highlights" in P Corp OS first.');
            return;
        }
        const plannedSeconds = pieces.reduce((sum, p) => sum + p.candidate.duration, 0);
        log(`Plan: ${pieces.length} moment(s) from ${clipsUsed} clip(s), about ${(plannedSeconds / 60).toFixed(1)} min. ${clipsSkipped} clip(s) skipped.`);

        // 3. SEQUENCE -- same format as the user's own timeline.
        const sequenceName = `${prep.shoot_name} - Rough Cut ${new Date().toISOString()}`;
        log(`Creating a new sequence "${sequenceName}" (never touches any existing sequence)…`);
        const sequence = await project.createSequence(sequenceName, "");
        if (!sequence) throw new Error("createSequence returned no sequence");
        keepAlive.push(sequence);
        let formatNote = timeline.source ? await matchSequenceFormat(project, timeline.source, sequence) : null;
        if (!formatNote || formatNote.startsWith("COULD NOT")) {
            if (formatNote) log(`Note: format ${formatNote}; trying the job's own format instead.`);
            formatNote = await applyJobFormat(project, sequence, prep);
        }
        log(`Sequence format ${formatNote}; frame size is ${await describeFormat(sequence)}.`);
        const sequenceEditor = await ppro.SequenceEditor.getEditor(sequence);
        keepAlive.push(sequenceEditor);

        // 4. CREATE every subclip, in batches.
        log(`Creating ${pieces.length} subclip(s) in batches of ${ROUGH_CUT_BATCH_SIZE}…`);
        for (let i = 0; i < pieces.length; i += ROUGH_CUT_BATCH_SIZE) {
            const batch = pieces.slice(i, i + ROUGH_CUT_BATCH_SIZE);
            for (const piece of batch) {
                piece.startTime = ppro.TickTime.createWithSeconds(piece.candidate.start);
                piece.endTime = ppro.TickTime.createWithSeconds(piece.candidate.start + piece.candidate.duration);
                piece.length = piece.endTime.subtract(piece.startTime);
                keepAlive.push(piece);
            }
            const createAction = (piece) =>
                piece.clip.createSubClipAction(piece.name, piece.startTime, piece.endTime, true, { takeVideo: true, takeAudio: true });
            try {
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => {
                        for (const piece of batch) compoundAction.addAction(createAction(piece));
                    }, "P Corp POST -- Create rough cut subclips");
                });
            } catch (e) {
                log(`Warning: a batch of subclips failed (${e}) -- retrying that batch one at a time.`);
                for (const piece of batch) {
                    try {
                        await project.lockedAccess(async () => {
                            await project.executeTransaction((compoundAction) => {
                                compoundAction.addAction(createAction(piece));
                            }, "P Corp POST -- Create rough cut subclip");
                        });
                    } catch (e2) {
                        piece.failed = true;
                        log(`Warning: couldn't create a subclip for "${piece.file.relative_path}" (${e2}).`);
                    }
                }
            }
            await sleep(ROUGH_CUT_PAUSE_MS);
        }
        await project.save();

        // 5. FIND them all with ONE scan.
        log("Locating the new subclips (one scan of the project)…");
        const wanted = new Set(pieces.filter((p) => !p.failed).map((p) => p.name));
        const { found } = await findItemsByName(project, wanted);
        for (const piece of pieces) {
            const hit = found.get(piece.name);
            if (hit) {
                piece.item = hit.item;
                piece.parent = hit.parent;
                keepAlive.push(hit);
            }
        }
        const placeable = pieces.filter((p) => p.item);
        if (placeable.length < pieces.length) log(`Warning: ${pieces.length - placeable.length} subclip(s) couldn't be found and will be skipped.`);

        // 6. INSERT in order, in batches.
        log(`Placing ${placeable.length} moment(s) on "${sequenceName}"…`);
        let insertionPoint = ppro.TickTime.createWithSeconds(0);
        keepAlive.push(insertionPoint);
        let placed = 0;
        let dialoguePlaced = 0;
        let bestPlaced = 0;
        const note = (piece) => {
            placed += 1;
            if (piece.source === "dialogue") dialoguePlaced += 1;
            else bestPlaced += 1;
        };
        for (let i = 0; i < placeable.length; i += ROUGH_CUT_BATCH_SIZE) {
            const batch = placeable.slice(i, i + ROUGH_CUT_BATCH_SIZE);
            const batchStart = insertionPoint;
            try {
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => {
                        for (const piece of batch) {
                            compoundAction.addAction(sequenceEditor.createInsertProjectItemAction(piece.item, insertionPoint, 0, 0, false));
                            insertionPoint = insertionPoint.add(piece.length);
                            keepAlive.push(insertionPoint);
                        }
                    }, "P Corp POST -- Insert rough cut clips");
                });
                batch.forEach(note);
            } catch (e) {
                log(`Warning: a batch of inserts failed (${e}) -- retrying that batch one at a time.`);
                insertionPoint = batchStart;
                for (const piece of batch) {
                    try {
                        await project.lockedAccess(async () => {
                            await project.executeTransaction((compoundAction) => {
                                compoundAction.addAction(sequenceEditor.createInsertProjectItemAction(piece.item, insertionPoint, 0, 0, false));
                            }, "P Corp POST -- Insert rough cut clip");
                        });
                        insertionPoint = insertionPoint.add(piece.length);
                        keepAlive.push(insertionPoint);
                        note(piece);
                    } catch (e2) {
                        log(`Warning: couldn't place a moment from "${piece.file.relative_path}" (${e2}).`);
                    }
                }
            }
            log(`  placed ${Math.min(i + ROUGH_CUT_BATCH_SIZE, placeable.length)} of ${placeable.length}`);
            await sleep(ROUGH_CUT_PAUSE_MS);
        }
        log("Saving project…");
        await project.save();

        // 7. TIDY (cosmetic -- never fatal) and report.
        try {
            const moved = await tidyRoughCutPieces(project);
            log(`Moved ${moved} rough-cut subclip(s) into the "${ROUGH_CUT_PIECES_BIN}" bin.`);
            await project.save();
        } catch (e) {
            log(`Note: couldn't tidy the subclips into their own bin (${e}). The rough cut itself is fine.`);
        }

        log("Reporting completion back to P Corp OS…");
        await apiPost(`/post/jobs/${job.id}/rough-cut-assembled`, token, {
            sequence_name: sequenceName,
            clip_count: clipsUsed,
            candidate_count: placed,
        });

        log(`Done. ${placed} moment(s) from ${clipsUsed} clip(s) placed on "${sequenceName}" `
            + `(${bestPlaced} best-moment, ${dialoguePlaced} dialogue). `
            + `This is a mechanical assembly of the best-looking moments -- review and re-edit it before using it anywhere real.`);
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        roughCutButton.disabled = false;
        keepAlive.length = 0;
    }
}

roughCutButton.addEventListener("click", () => {
    assembleRoughCut().catch((e) => log(`Unhandled error: ${e}`));
});

// ------------------------------------------------------------------ Assemble Edit
const TICKS_PER_SECOND = 254016000000;

/** Ticks in one frame at `fps`, exact for the broadcast rates (23.976 = 24000/1001 etc.). */
function exactFrameTicks(fps) {
    const broadcast = [[23.976, 24000 / 1001], [29.97, 30000 / 1001], [59.94, 60000 / 1001]];
    const hit = broadcast.find(([rate]) => Math.abs(rate - fps) < 0.01);
    return Math.round(TICKS_PER_SECOND / (hit ? hit[1] : fps));
}

/** Premiere lists a freshly imported file a moment AFTER importFiles() returns (found live: the first scan came
 * back empty although the file was in the project), so look again for a few seconds before giving up. */
async function waitForItemByName(project, name, tries = 12, delayMs = 400) {
    for (let i = 0; i < tries; i++) {
        const { found, rootItem } = await findItemsByName(project, new Set([name]));
        if (found.has(name)) return { hit: found.get(name), rootItem };
        await sleep(delayMs);
    }
    return { hit: null };
}

/** Imports the plan's music cut if the project doesn't have it yet and puts it on audio track 2 at 0.
 * Never fatal: returns a note describing what happened. */
async function placeMusic(project, sequenceEditor, plan, keepAlive) {
    const musicPath = plan.music && plan.music.cut_path;
    if (!musicPath) return "The plan has no music cut, so no music was placed.";
    const baseName = musicPath.split("/").pop();
    try {
        const first = await findItemsByName(project, new Set([baseName]));
        let hit = first.found.get(baseName);
        if (!hit) {
            await project.lockedAccess(async () => {
                await project.importFiles([musicPath], true, first.rootItem, false);
            });
            ({ hit } = await waitForItemByName(project, baseName));
        }
        if (!hit) throw new Error("imported, but it still isn't listed in the project after waiting");
        keepAlive.push(hit);
        const zero = ppro.TickTime.createWithTicks("0");
        keepAlive.push(zero);
        await project.lockedAccess(async () => {
            await project.executeTransaction((compoundAction) => {
                compoundAction.addAction(sequenceEditor.createInsertProjectItemAction(hit.item, zero, 0, 1, false));
            }, "P Corp POST -- Place edit music");
        });
        return `Music "${baseName}" placed on audio track 2.`;
    } catch (e) {
        return `COULD NOT place the music (${e}). It is in your project (or at ${musicPath}): drag "${baseName}" onto an audio track at the start.`;
    }
}


// ------------------------------------------------------------------ Accents
//
// Placed from plan.accents (see backend/app/post_accents.py): flashes and zoom hits (copies of an existing
// "Adjustment Layer" item on V2, trimmed to exact frames, with an effect and values), per-shot effects on V1
// (zoom blur, black & white), the logo on V4, and sound effects on A3/A4. Every mechanism here was verified in a
// real Premiere run (spikes, checked from the saved project file). Each phase is non-fatal: a failure is logged
// and the rest continues, so a missing Adjustment Layer or logo never costs the edit.
const ACCENT_BATCH = 20;
const ADJUSTMENT_LAYER_NAME = "Adjustment Layer";

async function transact(project, name, build) {
    await project.lockedAccess(async () => {
        await project.executeTransaction(build, name);
    });
}

/** Adds an effect to timeline track items, then sets parameter values on it. targets: [{trackItem, matchName, params, what}]. */
async function addEffects(project, targets, keepAlive, label) {
    let added = 0;
    for (let i = 0; i < targets.length; i += ACCENT_BATCH) {
        const prepared = [];
        for (const t of targets.slice(i, i + ACCENT_BATCH)) {
            try {
                const chain = await t.trackItem.getComponentChain();
                keepAlive.push(chain);
                const before = await chain.getComponentCount();
                const component = await ppro.VideoFilterFactory.createComponent(t.matchName);
                if (!component) throw new Error("that effect isn't available in this Premiere");
                keepAlive.push(component);
                prepared.push({ ...t, chain, before, component });
            } catch (e) {
                log(`Warning: ${label}: couldn't prepare ${t.what} (${e}).`);
            }
        }
        if (prepared.length === 0) continue;
        try {
            await transact(project, `P Corp POST -- Add ${label}`, (compound) => {
                for (const p of prepared) compound.addAction(p.chain.createInsertComponentAction(p.component, p.before));
            });
        } catch (e) {
            log(`Warning: ${label}: a batch of effects failed (${e}).`);
            continue;
        }
        added += prepared.length;
        const sets = [];
        for (const p of prepared) {
            const names = Object.keys(p.params || {});
            if (names.length === 0) continue;
            try {
                const live = await (await p.trackItem.getComponentChain()).getComponentAtIndex(p.before);
                keepAlive.push(live);
                const count = await live.getParamCount();
                const byName = new Map();
                for (let k = 0; k < count; k++) {
                    const prm = await live.getParam(k);
                    byName.set(prm.displayName, prm);
                }
                for (const n of names) {
                    const prm = byName.get(n);
                    if (!prm) log(`Note: ${p.what}: no "${n}" setting on ${p.matchName}.`);
                    else sets.push({ prm, value: p.params[n] });
                }
            } catch (e) {
                log(`Warning: ${p.what}: couldn't read its settings (${e}).`);
            }
        }
        if (sets.length > 0) {
            try {
                await transact(project, `P Corp POST -- Set ${label} values`, (compound) => {
                    for (const s of sets) {
                        const keyframe = s.prm.createKeyframe(s.value);
                        keepAlive.push(keyframe);
                        compound.addAction(s.prm.createSetValueAction(keyframe, true));
                    }
                });
            } catch (e) {
                log(`Warning: ${label}: couldn't set some values (${e}).`);
            }
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    return added;
}

/** Finds the project items made as subclips/imports by name, looking again for a few seconds. Sets piece.item. */
async function locatePieces(project, pieces, keepAlive) {
    for (let attempt = 0; attempt < 10; attempt++) {
        const { found } = await findItemsByName(project, new Set(pieces.filter((p) => !p.item).map((p) => p.name)));
        for (const piece of pieces) {
            const hit = found.get(piece.name);
            if (hit && !piece.item) {
                piece.item = hit.item;
                keepAlive.push(hit);
            }
        }
        if (pieces.every((p) => p.item)) return;
        await sleep(500);
    }
}

async function trackItemsByStart(sequence, kind, trackIndex) {
    const track = kind === "video" ? await sequence.getVideoTrack(trackIndex) : await sequence.getAudioTrack(trackIndex);
    const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    const map = new Map();
    for (const item of items) map.set((await item.getStartTime()).ticksNumber, item);
    return map;
}

async function placeShotEffects(project, sequence, plan, tpf, keepAlive) {
    const wanted = plan.accents.shot_effects || [];
    if (wanted.length === 0) return { zoom: 0, bw: 0 };
    const byStart = await trackItemsByStart(sequence, "video", 0);
    const targets = [];
    for (const e of wanted) {
        const shot = plan.shots.find((s) => s.index === e.shot_index);
        const trackItem = shot ? byStart.get(shot.start_frame * tpf) : null;
        if (!trackItem) {
            log(`Note: shot ${e.shot_index} isn't on the timeline, so its ${e.effect.includes("Black") ? "black & white" : "zoom blur"} was skipped.`);
            continue;
        }
        targets.push({ trackItem, matchName: e.effect, params: e.params, what: `shot ${e.shot_index}` });
    }
    const zoom = await addEffects(project, targets.filter((t) => !t.matchName.includes("Black")), keepAlive, "shot zoom blur");
    const bw = await addEffects(project, targets.filter((t) => t.matchName.includes("Black")), keepAlive, "black & white");
    return { zoom, bw };
}

/** The Project panel's "Video Info" text ("2160 x 3840 (1,0)", decimal comma depends on the locale) -> {width, height} or null. */
function parseVideoInfo(text) {
    const m = /(\d+)\s*x\s*(\d+)/i.exec(String(text || ""));
    return m ? { width: Number(m[1]), height: Number(m[2]) } : null;
}

/** An adjustment layer only changes what lies inside its own frame. Found live (2026-10-13): a layer made for a 2160x3840
 * sequence, used in a 3840x2160 one, flashed and zoom-blurred only a centred strip. Returns a plain-English warning when the
 * item can't cover the sequence, otherwise null (also null when the size can't be read -- then nothing is claimed). */
async function adjustmentLayerCoverageProblem(item, sequence) {
    try {
        const columns = JSON.parse(await ppro.Metadata.getProjectColumnsMetadata(item));
        const info = columns.find((c) => c.ColumnID === "Column.Intrinsic.VideoInfo");
        const size = parseVideoInfo(info && info.ColumnValue);
        const frame = await sequence.getFrameSize();
        if (!size || !frame || !frame.width || !frame.height) return null;
        if (size.width >= frame.width && size.height >= frame.height) return null;
        return `the "${ADJUSTMENT_LAYER_NAME}" in this project is ${size.width} x ${size.height} but this sequence is ${frame.width} x ${frame.height}, `
            + `so the flashes and zoom hits only affect part of the picture. Make a new one at the sequence's size `
            + `(File > New > Adjustment Layer, width ${frame.width}, height ${frame.height}), delete the old one, then run Assemble Edit again.`;
    } catch (e) {
        return null;
    }
}

async function placeOverlays(project, sequence, editor, plan, tpf, keepAlive) {
    const overlays = [...(plan.accents.flashes || []), ...(plan.accents.zoom_hits || [])].sort((a, b) => a.start_frame - b.start_frame);
    if (overlays.length === 0) return { flashes: 0, zoomHits: 0 };
    const { found } = await findItemsByName(project, new Set([ADJUSTMENT_LAYER_NAME]));
    const adjustment = found.get(ADJUSTMENT_LAYER_NAME);
    if (!adjustment) {
        log(`Note: this project has no "${ADJUSTMENT_LAYER_NAME}" item, so the ${overlays.length} flashes and zoom hits were skipped. `
            + `Make one (File > New > Adjustment Layer), then run Assemble Edit again.`);
        return { flashes: 0, zoomHits: 0 };
    }
    keepAlive.push(adjustment);
    const coverage = await adjustmentLayerCoverageProblem(adjustment.item, sequence);
    if (coverage) log(`Warning: ${coverage}`);
    const trackIndex = (plan.accents.overlay_track || 2) - 1;
    const at = (frame) => ppro.TickTime.createWithTicks(String(frame * tpf));
    // 1. place in time order (overwrite never shifts anything), 2. trim each to its length, 3. add its effect and values
    for (let i = 0; i < overlays.length; i += ACCENT_BATCH) {
        const batch = overlays.slice(i, i + ACCENT_BATCH);
        try {
            await transact(project, "P Corp POST -- Place adjustment layers", (compound) => {
                for (const o of batch) {
                    const time = at(o.start_frame);
                    keepAlive.push(time);
                    compound.addAction(editor.createOverwriteItemAction(adjustment.item, time, trackIndex, 0));
                }
            });
        } catch (e) {
            log(`Warning: a batch of adjustment layers failed (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    const placed = await trackItemsByStart(sequence, "video", trackIndex);
    const ready = overlays.map((o) => ({ o, trackItem: placed.get(o.start_frame * tpf) })).filter((x) => x.trackItem);
    if (ready.length < overlays.length) log(`Warning: ${overlays.length - ready.length} adjustment layer(s) didn't land and were skipped.`);
    for (let i = 0; i < ready.length; i += ACCENT_BATCH) {
        const batch = ready.slice(i, i + ACCENT_BATCH);
        try {
            await transact(project, "P Corp POST -- Trim adjustment layers", (compound) => {
                for (const x of batch) {
                    const end = at(x.o.start_frame + x.o.frames);
                    keepAlive.push(end);
                    compound.addAction(x.trackItem.createSetEndAction(end));
                }
            });
        } catch (e) {
            log(`Warning: couldn't trim a batch of adjustment layers (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    const targets = ready.map((x) => ({ trackItem: x.trackItem, matchName: x.o.effect, params: x.o.params, what: `${x.o.kind.replace("_", " ")} at frame ${x.o.start_frame}`, kind: x.o.kind }));
    const flashes = await addEffects(project, targets.filter((t) => t.kind === "flash"), keepAlive, "flash");
    const zoomHits = await addEffects(project, targets.filter((t) => t.kind === "zoom_hit"), keepAlive, "zoom hit");
    return { flashes, zoomHits, coverage };
}

async function placeLogo(project, sequence, editor, plan, tpf, keepAlive) {
    const logo = plan.accents.logo;
    if (!logo) return 0;
    const name = logo.file.split("/").pop();
    const first = await findItemsByName(project, new Set([name]));
    let hit = first.found.get(name);
    if (!hit) {
        await project.lockedAccess(async () => {
            await project.importFiles([logo.file], true, first.rootItem, false);
        });
        ({ hit } = await waitForItemByName(project, name));
    }
    if (!hit) throw new Error(`couldn't find the imported logo "${name}"`);
    keepAlive.push(hit);
    const at = (frame) => ppro.TickTime.createWithTicks(String(frame * tpf));
    const start = at(logo.start_frame);
    keepAlive.push(start);
    await transact(project, "P Corp POST -- Place logo", (compound) => {
        compound.addAction(editor.createOverwriteItemAction(hit.item, start, logo.track - 1, 0));
    });
    const placed = (await trackItemsByStart(sequence, "video", logo.track - 1)).get(logo.start_frame * tpf);
    if (!placed) throw new Error("the logo isn't on its track after placing it");
    const end = at(logo.start_frame + logo.frames);
    keepAlive.push(end);
    await transact(project, "P Corp POST -- Trim logo", (compound) => compound.addAction(placed.createSetEndAction(end)));
    return 1;
}

async function placeSoundEffects(project, editor, plan, tpf, keepAlive, runId) {
    const sfx = plan.accents.sfx || [];
    if (sfx.length === 0) return 0;
    const at = (frame) => ppro.TickTime.createWithTicks(String(frame * tpf));
    // import each distinct file once, find it, then cut a subclip of exactly the length wanted (so no audio trim call is needed)
    const files = [...new Set(sfx.map((x) => x.file))];
    const root = (await findItemsByName(project, new Set(["__none__"]))).rootItem;
    const imported = files.map((file) => ({ file, name: file.split("/").pop() }));
    const existing = await findItemsByName(project, new Set(imported.map((x) => x.name)));
    const toImport = imported.filter((x) => !existing.found.has(x.name)).map((x) => x.file);
    if (toImport.length > 0) {
        await project.lockedAccess(async () => {
            await project.importFiles(toImport, true, root, false);
        });
    }
    for (const x of imported) {
        const hit = existing.found.get(x.name) || (await waitForItemByName(project, x.name)).hit;
        if (hit) {
            x.item = ppro.ClipProjectItem.cast(hit.item) || hit.item;
            keepAlive.push(hit);
        }
    }
    const byFile = new Map(imported.map((x) => [x.file, x]));
    const pieces = [];
    sfx.forEach((x, i) => {
        const source = byFile.get(x.file);
        if (!source || !source.item) {
            log(`Note: couldn't find the sound effect "${x.name}" after importing, so it was skipped.`);
            return;
        }
        pieces.push({ x, source, name: `RC_FX_${i + 1}_${runId}`, start: ppro.TickTime.createWithTicks("0"), end: ppro.TickTime.createWithTicks(String(x.frames * tpf)) });
    });
    for (let i = 0; i < pieces.length; i += ACCENT_BATCH) {
        const batch = pieces.slice(i, i + ACCENT_BATCH);
        try {
            await transact(project, "P Corp POST -- Cut sound effects", (compound) => {
                for (const p of batch) compound.addAction(p.source.item.createSubClipAction(p.name, p.start, p.end, true, { takeVideo: false, takeAudio: true }));
            });
        } catch (e) {
            log(`Warning: a batch of sound effects failed (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    await locatePieces(project, pieces, keepAlive);
    const ready = pieces.filter((p) => p.item).sort((a, b) => a.x.start_frame - b.x.start_frame);
    if (ready.length < pieces.length) log(`Warning: ${pieces.length - ready.length} sound effect(s) couldn't be cut and were skipped.`);
    let placed = 0;
    for (let i = 0; i < ready.length; i += ACCENT_BATCH) {
        const batch = ready.slice(i, i + ACCENT_BATCH);
        try {
            await transact(project, "P Corp POST -- Place sound effects", (compound) => {
                for (const p of batch) {
                    const time = at(p.x.start_frame);
                    keepAlive.push(time);
                    compound.addAction(editor.createOverwriteItemAction(p.item, time, 0, p.x.track - 1));
                }
            });
            placed += batch.length;
        } catch (e) {
            log(`Warning: a batch of sound effects couldn't be placed (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    return placed;
}

// ------------------------------------------------------------------ Fill the frame (corporate highlight)
//
// plan.fit === "fill": every clip is scaled so its picture covers the whole sequence frame, centred. A 16:9 clip in a vertical sequence would otherwise show as an
// unscaled square with black bars above and below (Premiere places clips at their native size); a smaller clip in a bigger sequence would sit small in the middle.
// The size is read from the project item's "Video Info" column -- what Premiere itself sees, so rotated phone footage is right too. A clip that already has the
// sequence's shape and size is left at 100. Scale is set as a plain value (centre stays centred); a slow zoom afterwards reads this as its base.
async function fillFrameScale(project, sequence, plan, tpf, keepAlive) {
    const frame = await sequence.getFrameSize();
    if (!frame || !frame.width || !frame.height) return "Fill the frame: couldn't read the sequence size, so clips were left at their own size.";
    const byStart = await trackItemsByStart(sequence, "video", 0);
    const todo = [];
    let already = 0, unreadable = 0;
    for (const shot of plan.shots) {
        const trackItem = byStart.get(shot.start_frame * tpf);
        if (!trackItem) continue;
        try {
            const projectItem = await trackItem.getProjectItem();
            keepAlive.push(projectItem);
            const columns = JSON.parse(await ppro.Metadata.getProjectColumnsMetadata(projectItem));
            const info = columns.find((c) => c.ColumnID === "Column.Intrinsic.VideoInfo");
            const size = parseVideoInfo(info && info.ColumnValue);
            if (!size) { unreadable++; continue; }
            const cover = Math.ceil(Math.max(frame.width / size.width, frame.height / size.height) * 10000) / 100;  // rounded UP to 0.01%: never a hair short of the frame edge
            if (Math.abs(cover - 100) < 0.5) { already++; continue; }
            const scale = await findMotionScale(trackItem, keepAlive);
            if (!scale) { unreadable++; continue; }
            const keyframe = scale.createKeyframe(cover);
            keepAlive.push(keyframe);
            todo.push({ shot, scale, keyframe, cover });
        } catch (e) {
            unreadable++;
            log(`Warning: couldn't read the size of shot ${shot.index}'s clip (${e}).`);
        }
    }
    let applied = 0;
    for (let i = 0; i < todo.length; i += ACCENT_BATCH) {
        const batch = todo.slice(i, i + ACCENT_BATCH);
        try {
            await transact(project, "P Corp POST -- Fill the frame", (compound) => {
                for (const t of batch) compound.addAction(t.scale.createSetValueAction(t.keyframe, true));
            });
            applied += batch.length;
        } catch (e) {
            log(`Warning: a batch of frame-filling scales failed (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    let verified = 0;
    for (const t of todo) {
        try {
            const value = Number((await t.scale.getValueAtTime(ppro.TickTime.createWithTicks("0"))).value);
            if (Math.abs(value - t.cover) < 0.05) verified++;
            else log(`Warning: shot ${t.shot.index}: the scale reads back as ${value} (wanted ${t.cover}).`);
        } catch (e) { /* the read-back is a check, not a step */ }
    }
    return `Fill the frame: ${applied} of ${todo.length} clip(s) scaled to cover ${frame.width} x ${frame.height} (${verified} read back correctly), ${already} already the right size`
        + (unreadable ? `, ${unreadable} left alone because their size couldn't be read.` : ".");
}

// ------------------------------------------------------------------ Slow zooms (corporate edits)
//
// plan.zooms.items: [{shot_index, start_frame, frames, direction: "in"|"out", percent}] -- only shots whose footage is static (backend/app/post_steady.py).
// Each is Motion > Scale animated over the whole shot by two keyframes, linear: push-in goes from the shot's current scale to current x (1 + percent/100), pull-out the
// other way round. The current scale is read first (100 normally) so a project with another default media scaling still gets the right percentage.
//
// Two things found in real Premiere (2026-10-14) that a read-back through the API does NOT reveal -- only exported frames and the saved project file do:
//   1. keyframe times count from the start of the SOURCE clip, so they are the shot's in-point (trackItem.getInPoint()) plus the offset into the shot. Keyframes at 0 and
//      the shot's length, on a shot that begins 4 s into its clip, were already over when the shot started: it sat at the end value the whole time (10 of 15 shots).
//   2. the order: time-varying switch first, then the keyframes. Without the switch the animation renders but is not saved into the project file.
// Verified with static textured clips (so only the zoom can change between frames): 15 of 15 shots render the keyframed scale and 15 of 15 are saved in the .prproj.
const ZOOM_BATCH = 20;

async function findMotionScale(trackItem, keepAlive) {
    const chain = await trackItem.getComponentChain();
    keepAlive.push(chain);
    const count = await chain.getComponentCount();
    for (let i = 0; i < count; i++) {
        const component = await chain.getComponentAtIndex(i);
        keepAlive.push(component);
        if ((await component.getMatchName()) !== "AE.ADBE Motion") continue;
        const params = await component.getParamCount();
        for (let k = 0; k < params; k++) {
            const param = await component.getParam(k);
            if (param.displayName === "Scale") return param;
        }
    }
    return null;
}

async function placeShotZooms(project, sequence, plan, tpf, keepAlive) {
    const items = (plan.zooms && plan.zooms.items) || [];
    if (items.length === 0) return "";
    const byStart = await trackItemsByStart(sequence, "video", 0);
    const zeroTick = ppro.TickTime.createWithTicks("0");
    keepAlive.push(zeroTick);
    const prepared = [];
    let skipped = 0;
    for (const z of items) {
        const trackItem = byStart.get(z.start_frame * tpf);
        if (!trackItem) {
            log(`Note: shot ${z.shot_index} isn't on the timeline, so its slow zoom was skipped.`);
            skipped++;
            continue;
        }
        try {
            const scale = await findMotionScale(trackItem, keepAlive);
            if (!scale) throw new Error("no Scale setting found on the clip");
            if (!(await scale.areKeyframesSupported())) throw new Error("Scale can't be keyframed on this clip");
            // Keyframe times count from the start of the SOURCE clip, not from the start of the shot (found live 2026-10-14: keyframes at 0..2.5 s
            // on a shot that begins 4 s into its clip were already over when the shot started, so it sat at the end value the whole time).
            const inTicks = Number((await trackItem.getInPoint()).ticksNumber);
            const atTicks = ppro.TickTime.createWithTicks(String(inTicks));
            keepAlive.push(atTicks);
            const base = Number((await scale.getValueAtTime(atTicks)).value);
            const far = base * (1 + z.percent / 100);
            const from = z.direction === "in" ? base : far;
            const to = z.direction === "in" ? far : base;
            const first = scale.createKeyframe(from);
            first.position = ppro.TickTime.createWithTicks(String(inTicks));
            const last = scale.createKeyframe(to);
            last.position = ppro.TickTime.createWithTicks(String(inTicks + z.frames * tpf));
            keepAlive.push(first, last);
            prepared.push({ z, scale, first, last, from, to, inTicks });
        } catch (e) {
            log(`Warning: couldn't prepare the slow zoom on shot ${z.shot_index} (${e}).`);
            skipped++;
        }
    }
    let applied = 0;
    for (let i = 0; i < prepared.length; i += ZOOM_BATCH) {
        const batch = prepared.slice(i, i + ZOOM_BATCH);
        try {
            // order matters (tested live 2026-10-14): the time-varying switch FIRST, then the two keyframes. Keyframes added without the switch
            // render but are NOT saved into the project file; the order used here is the one that renders AND persists.
            await transact(project, "P Corp POST -- Slow zooms", (compound) => {
                for (const p of batch) {
                    compound.addAction(p.scale.createSetTimeVaryingAction(true));
                    compound.addAction(p.scale.createAddKeyframeAction(p.first));
                    compound.addAction(p.scale.createAddKeyframeAction(p.last));
                }
            });
            applied += batch.length;
        } catch (e) {
            log(`Warning: a batch of slow zooms failed (${e}).`);
            skipped += batch.length;
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    // read every one back: the animation must really be there and end where the plan says
    let verified = 0;
    for (const p of prepared) {
        try {
            const endValue = Number((await p.scale.getValueAtTime(ppro.TickTime.createWithTicks(String(p.inTicks + p.z.frames * tpf)))).value);
            if ((await p.scale.isTimeVarying()) && Math.abs(endValue - p.to) < 0.05) verified++;
            else log(`Warning: shot ${p.z.shot_index}: the slow zoom reads back as ${endValue} at its end (wanted ${p.to.toFixed(2)}).`);
        } catch (e) {
            log(`Warning: couldn't read back the slow zoom on shot ${p.z.shot_index} (${e}).`);
        }
    }
    const pushIn = prepared.filter((p) => p.z.direction === "in").length;
    return `Slow zooms: ${applied} of ${items.length} placed (${pushIn} push-in, ${prepared.length - pushIn} pull-out), ${verified} read back correctly`
        + (skipped ? `, ${skipped} skipped.` : ".");
}

/** Runs every accent phase; each one is non-fatal. Returns a one-line summary. */
async function placeAccents(project, sequence, editor, plan, tpf, keepAlive, runId) {
    const a = plan.accents;
    const result = { flashes: 0, zoomHits: 0, zoom: 0, bw: 0, logo: 0, sfx: 0 };
    const phase = async (label, run) => {
        try {
            return await run();
        } catch (e) {
            log(`Note: ${label} failed (${e}); the rest of the accents continue.`);
            return null;
        }
    };
    const shots = await phase("shot effects", () => placeShotEffects(project, sequence, plan, tpf, keepAlive));
    if (shots) { result.zoom = shots.zoom; result.bw = shots.bw; }
    const overlays = await phase("flashes and zoom hits", () => placeOverlays(project, sequence, editor, plan, tpf, keepAlive));
    if (overlays) { result.flashes = overlays.flashes; result.zoomHits = overlays.zoomHits; result.coverage = overlays.coverage || null; }
    result.logo = (await phase("the logo", () => placeLogo(project, sequence, editor, plan, tpf, keepAlive))) || 0;
    result.sfx = (await phase("sound effects", () => placeSoundEffects(project, editor, plan, tpf, keepAlive, runId))) || 0;
    for (const note of a.notes || []) log(`Note: ${note}`);
    return `Accents placed: ${result.flashes} flash(es), ${result.zoomHits} zoom hit(s), ${result.zoom} shot zoom blur(s), ${result.bw} black & white shot(s), `
        + `${result.logo ? "the logo" : "no logo"}, ${result.sfx} sound effect(s).`
        + (result.coverage ? ` WARNING: ${result.coverage}` : "");
}

// ---------------------------------------------------------------------------------------------------------------------
// Brand cards, logo bug and burned-in captions of a corporate story (plan.graphics, made by backend/app/post_brand_graphics.py).
//
// Every one is an IMAGE the size of the sequence, laid over the b-roll on an upper track: V2 cards, V3 logo bug, V4 captions.
// Why images: Premiere's scripting can't create captions or titles (its caption classes only read and rename tracks), and a
// full-frame image needs no Motion edits -- it is the same placement already verified for the logo (import, overwrite onto an empty
// upper track at an exact time, trim). What is NEW here, and so checked after the fact instead of assumed: a still's default length
// can be shorter or longer than its slot, so every end time is READ BACK; an image that is too long and won't trim is DISABLED (it
// must never cover footage it shouldn't), one that is too short and won't stretch is continued with copies.
// ---------------------------------------------------------------------------------------------------------------------
const STILL_BATCH = 10;
const STILL_FILL_ROUNDS = 4;

/** Imports the images the project doesn't already hold (in chunks) and returns Map(file name -> hit). Premiere lists new items late. */
async function importStills(project, files, keepAlive) {
    const baseName = (f) => f.split("/").pop();
    const names = [...new Set(files.map(baseName))];
    let { found, rootItem } = await findItemsByName(project, new Set(names));
    const toImport = [...new Set(files)].filter((f) => !found.has(baseName(f)));
    for (let i = 0; i < toImport.length; i += 20) {
        const chunk = toImport.slice(i, i + 20);
        try {
            await project.lockedAccess(async () => {
                await project.importFiles(chunk, true, rootItem, false);
            });
        } catch (e) {
            log(`Warning: couldn't import ${chunk.length} image(s) (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    for (let attempt = 0; attempt < 15; attempt++) {
        ({ found } = await findItemsByName(project, new Set(names)));
        if (names.every((n) => found.has(n))) break;
        await sleep(500);
    }
    for (const hit of found.values()) keepAlive.push(hit);
    return found;
}

/** Places each image at its frame on one video track, trims it to its exact length, then reads every end time back and repairs.
 * items: [{file, start_frame, frames}]. Returns counts. Never throws for a single image. */
async function placeStills(project, sequence, editor, items, trackIndex, tpf, keepAlive, what) {
    const out = { wanted: items.length, placed: 0, exact: 0, filled: 0, disabled: 0, missing: 0 };
    if (items.length === 0) return out;
    const at = (frame) => ppro.TickTime.createWithTicks(String(Math.round(frame * tpf)));
    const nameOf = (x) => x.file.split("/").pop();
    const list = [...items].sort((a, b) => a.start_frame - b.start_frame);
    const hits = await importStills(project, list.map((x) => x.file), keepAlive);
    const ready = list.filter((x) => hits.has(nameOf(x)));
    out.missing = list.length - ready.length;
    if (out.missing) log(`Warning: ${out.missing} ${what} image(s) weren't in the project after importing and were skipped.`);

    // 1. place, in time order (an overwrite never shifts anything)
    for (let i = 0; i < ready.length; i += STILL_BATCH) {
        const batch = ready.slice(i, i + STILL_BATCH);
        try {
            await transact(project, `P Corp POST -- Place ${what}`, (compound) => {
                for (const x of batch) {
                    const t = at(x.start_frame);
                    keepAlive.push(t);
                    compound.addAction(editor.createOverwriteItemAction(hits.get(nameOf(x)).item, t, trackIndex, 0));
                }
            });
        } catch (e) {
            log(`Warning: a batch of ${what} images failed to place (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    // 2. what landed, trimmed to the exact length
    let onTrack = await trackItemsByStart(sequence, "video", trackIndex);
    const landed = ready.filter((x) => onTrack.has(Math.round(x.start_frame * tpf)));
    out.placed = landed.length;
    if (landed.length < ready.length) log(`Warning: ${ready.length - landed.length} ${what} image(s) didn't land on the timeline.`);
    for (let i = 0; i < landed.length; i += STILL_BATCH) {
        const batch = landed.slice(i, i + STILL_BATCH);
        try {
            await transact(project, `P Corp POST -- Trim ${what}`, (compound) => {
                for (const x of batch) {
                    const end = at(x.start_frame + x.frames);
                    keepAlive.push(end);
                    compound.addAction(onTrack.get(Math.round(x.start_frame * tpf)).createSetEndAction(end));
                }
            });
        } catch (e) {
            log(`Warning: couldn't trim a batch of ${what} images (${e}).`);
        }
        await sleep(ROUGH_CUT_PAUSE_MS);
    }
    // 3. read every end time back; fix what didn't take
    onTrack = await trackItemsByStart(sequence, "video", trackIndex);
    const endOf = async (item) => Number((await item.getEndTime()).ticksNumber);
    for (const x of landed) {
        let item = onTrack.get(Math.round(x.start_frame * tpf));
        if (!item) continue;
        const target = Math.round((x.start_frame + x.frames) * tpf);
        let actual;
        try {
            actual = await endOf(item);
        } catch (e) {
            out.exact++;  // this Premiere can't report the end time: nothing to check against, so take the trim as done
            continue;
        }
        if (Math.abs(actual - target) <= tpf / 2) { out.exact++; continue; }
        if (actual > target) {
            // too long and it wouldn't trim: it would cover footage that isn't its own, so switch it off rather than leave it
            try {
                await transact(project, `P Corp POST -- Disable ${what}`, (compound) => compound.addAction(item.createSetDisabledAction(true)));
                out.disabled++;
                log(`Warning: a ${what} image at frame ${x.start_frame} wouldn't trim to its length (it ran ${((actual - target) / tpf).toFixed(0)} frames long), so it was DISABLED. Trim it by hand and enable it.`);
            } catch (e) {
                log(`Warning: a ${what} image at frame ${x.start_frame} is ${((actual - target) / tpf).toFixed(0)} frames too long and could not be disabled either (${e}). Check that spot.`);
            }
            continue;
        }
        // shorter than planned: the image wouldn't stretch. Continue it with copies from where it stops.
        let cursor = actual;
        for (let round = 0; round < STILL_FILL_ROUNDS && cursor < target - tpf / 2; round++) {
            const t = ppro.TickTime.createWithTicks(String(cursor));
            keepAlive.push(t);
            try {
                await transact(project, `P Corp POST -- Continue ${what}`, (compound) => compound.addAction(editor.createOverwriteItemAction(hits.get(nameOf(x)).item, t, trackIndex, 0)));
                onTrack = await trackItemsByStart(sequence, "video", trackIndex);
                item = onTrack.get(cursor);
                if (!item) break;
                const end = ppro.TickTime.createWithTicks(String(target));
                keepAlive.push(end);
                await transact(project, `P Corp POST -- Trim continued ${what}`, (compound) => compound.addAction(item.createSetEndAction(end)));
                onTrack = await trackItemsByStart(sequence, "video", trackIndex);
                item = onTrack.get(cursor) || item;
                actual = await endOf(item);
                if (actual > target + tpf / 2) {
                    await transact(project, `P Corp POST -- Disable ${what}`, (compound) => compound.addAction(item.createSetDisabledAction(true)));
                    out.disabled++;
                    log(`Warning: the continuation of a ${what} image at frame ${x.start_frame} wouldn't trim, so it was DISABLED.`);
                    break;
                }
                cursor = actual;
            } catch (e) {
                log(`Warning: couldn't continue a ${what} image at frame ${x.start_frame} (${e}).`);
                break;
            }
        }
        if (cursor >= target - tpf / 2) { out.filled++; log(`Note: a ${what} image at frame ${x.start_frame} wouldn't stretch to ${x.frames} frames, so it was continued with copies.`); }
        else log(`Warning: a ${what} image at frame ${x.start_frame} stops ${((target - cursor) / tpf).toFixed(0)} frames short.`);
    }
    return out;
}

async function placeBrandGraphics(project, sequence, editor, plan, tpf, keepAlive) {
    const g = plan.graphics;
    const result = { cards: 0, bug: 0, captions: 0, problems: 0 };
    let size = null;
    try {
        const rect = await sequence.getFrameSize();
        size = { w: Math.round(rect.width), h: Math.round(rect.height) };
    } catch (e) {
        log(`Note: couldn't read the sequence's size (${e}); placing the images anyway.`);
    }
    if (size && g.frame_size && (size.w !== g.frame_size[0] || size.h !== g.frame_size[1])) {
        log(`The sequence is ${size.w}x${size.h} but the brand images were drawn for ${g.frame_size[0]}x${g.frame_size[1]}, and an image is placed at its own size, so they would not line up. `
            + `They were NOT placed. Set the job's deliverable format and 4K resolution (so the sequence comes out the right size), then plan again.`);
        return "Brand cards, logo bug and captions: not placed (the sequence size doesn't match the images).";
    }
    const phase = async (label, run) => {
        try {
            return await run();
        } catch (e) {
            log(`Note: ${label} failed (${e}); the rest of the brand graphics continue.`);
            result.problems++;
            return null;
        }
    };
    const trackOf = (key, fallback) => ((g.tracks && g.tracks[key]) || fallback) - 1;
    const tally = (r) => (r ? r.exact + r.filled : 0);
    const cards = await phase("the brand cards", () => placeStills(project, sequence, editor, (g.cards || []).map((c) => ({ file: c.file, start_frame: c.start_frame, frames: c.frames })), trackOf("cards", 2), tpf, keepAlive, "brand card"));
    result.cards = tally(cards);
    const bug = await phase("the logo bug", () => placeStills(project, sequence, editor, g.logo_bug ? [{ file: g.logo_bug.file, start_frame: g.logo_bug.start_frame, frames: g.logo_bug.frames }] : [], trackOf("logo_bug", 3), tpf, keepAlive, "logo bug"));
    result.bug = tally(bug);
    const burned = (g.captions && g.captions.burned_in) || [];
    const captions = await phase("the captions", () => placeStills(project, sequence, editor, burned.map((c) => ({ file: c.file, start_frame: c.start_frame, frames: c.frames })), trackOf("captions", 4), tpf, keepAlive, "caption"));
    result.captions = tally(captions);
    for (const r of [cards, bug, captions]) if (r) result.problems += r.disabled + r.missing + (r.placed - r.exact - r.filled - r.disabled > 0 ? r.placed - r.exact - r.filled - r.disabled : 0);
    const srt = g.captions && g.captions.srt_path;
    if (srt) {
        try {
            await project.lockedAccess(async () => {
                const root = await project.getRootItem();
                await project.importFiles([srt], true, root, false);
            });
            log(`Imported ${srt.split("/").pop()} into the project. To get EDITABLE captions, drag it onto the timeline (and remove the burned-in caption images on V4).`);
        } catch (e) {
            log(`Note: couldn't import ${srt.split("/").pop()} into the project (${e}); import it yourself from ${srt}.`);
        }
    }
    return `Brand graphics placed: ${result.cards} of ${(g.cards || []).length} card(s), ${result.bug} of ${g.logo_bug ? 1 : 0} logo bug, ${result.captions} of ${burned.length} caption image(s)`
        + (result.problems ? ` -- ${result.problems} problem(s), see the warnings above.` : ".");
}

/**
 * "Assemble Edit" -- builds the sequence described by the job's saved edit plan: video-only hard cuts at the
 * planned frames, music on its own track. Always a NEW sequence; never touches an existing one. No effects,
 * flashes or sound effects (those are a separate, not-yet-built step). Same safe mechanism as Assemble Rough
 * Cut: subclips in batches, ONE scan, batched inserts, everything held alive, saves between phases.
 */
async function assembleEdit() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }
    editButton.disabled = true;
    reset();
    const keepAlive = [];
    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }
        keepAlive.push(project);
        const job = await findJobForProject(project, token);
        if (!job) {
            log('Couldn\'t find a P Corp OS job with a Premiere project matching this one. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        log("Fetching the edit plan…");
        let plan;
        try {
            plan = await apiGet(`/post/jobs/${job.id}/edit-plan`, token);
        } catch (e) {
            log("This job has no edit plan yet. Plan the edit in P Corp OS first (style + music), then run this again.");
            return;
        }
        const prep = await apiGet(`/post/jobs/${job.id}/premiere-prep`, token);
        const tpf = exactFrameTicks(plan.fps);
        log(`Plan: ${plan.shots.length} shot(s), ${plan.duration_seconds}s at ${plan.fps} fps, style "${plan.style}".`);

        const clips = await collectAllClips(project);
        keepAlive.push(clips);
        const clipByName = {};
        for (const clip of clips) {
            if (await clip.isSequence()) continue;
            clipByName[await itemName(clip)] = clip;
        }
        const runId = Date.now();
        const pieces = [];
        for (const shot of plan.shots) {
            const clip = clipByName[shot.name];
            if (!clip) {
                log(`"${shot.name}" (shot ${shot.index}) isn't in the project -- that slot will be empty.`);
                continue;
            }
            const startTicks = Math.round((shot.source_in * TICKS_PER_SECOND) / tpf) * tpf;
            pieces.push({
                shot, clip, name: `RC_ED_${shot.index}_${runId}`,
                startTime: ppro.TickTime.createWithTicks(String(startTicks)),
                endTime: ppro.TickTime.createWithTicks(String(startTicks + shot.duration_frames * tpf)),
                position: ppro.TickTime.createWithTicks(String(shot.start_frame * tpf)),
                length: ppro.TickTime.createWithTicks(String(shot.duration_frames * tpf)),
            });
            keepAlive.push(pieces[pieces.length - 1]);
        }
        if (pieces.length === 0) {
            log("None of the plan's clips are in this project.");
            return;
        }

        const sequenceName = `${plan.shoot_name || prep.shoot_name} - Edit ${new Date().toISOString()}`;
        log(`Creating a new sequence "${sequenceName}" (never touches any existing sequence)…`);
        const sequence = await project.createSequence(sequenceName, "");
        if (!sequence) throw new Error("createSequence returned no sequence");
        keepAlive.push(sequence);
        const formatNote = await applyJobFormat(project, sequence, prep);
        log(`Sequence format ${formatNote}; frame size is ${await describeFormat(sequence)}. The plan assumes ${plan.fps} fps.`);
        const sequenceEditor = await ppro.SequenceEditor.getEditor(sequence);
        keepAlive.push(sequenceEditor);

        log(`Creating ${pieces.length} subclip(s) in batches of ${ROUGH_CUT_BATCH_SIZE}…`);
        for (let i = 0; i < pieces.length; i += ROUGH_CUT_BATCH_SIZE) {
            const batch = pieces.slice(i, i + ROUGH_CUT_BATCH_SIZE);
            // video only: the music replaces the camera sound. hasHardBoundaries is FALSE on purpose: with true, Premiere
            // restricts trims to the subclip's exact range (StartBoundary/EndBoundary in the project file), so a shot
            // could not be stretched afterwards; false leaves the rest of the source clip available to trim into.
            const createAction = (piece) =>
                piece.clip.createSubClipAction(piece.name, piece.startTime, piece.endTime, false, { takeVideo: true, takeAudio: false });
            try {
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => {
                        for (const piece of batch) compoundAction.addAction(createAction(piece));
                    }, "P Corp POST -- Create edit subclips");
                });
            } catch (e) {
                log(`Warning: a batch of subclips failed (${e}) -- retrying that batch one at a time.`);
                for (const piece of batch) {
                    try {
                        await project.lockedAccess(async () => {
                            await project.executeTransaction((compoundAction) => {
                                compoundAction.addAction(createAction(piece));
                            }, "P Corp POST -- Create edit subclip");
                        });
                    } catch (e2) {
                        piece.failed = true;
                        log(`Warning: couldn't cut shot ${piece.shot.index} from "${piece.shot.name}" (${e2}).`);
                    }
                }
            }
            await sleep(ROUGH_CUT_PAUSE_MS);
        }
        await project.save();

        // Premiere lists new items a moment after a transaction, and may return EMPTY entries for subclips it can't
        // wrap -- so look again for a few seconds, and skip empty entries instead of choking on them.
        const locate = async (list) => {
            let nulls = 0;
            for (let attempt = 0; attempt < 10; attempt++) {
                const result = await findItemsByName(project, new Set(list.filter((p) => !p.failed && !p.item).map((p) => p.name)));
                nulls = result.nulls;
                for (const piece of list) {
                    const hit = result.found.get(piece.name);
                    if (hit && !piece.item) {
                        piece.item = hit.item;
                        keepAlive.push(hit);
                    }
                }
                if (list.every((p) => p.failed || p.item)) break;
                await sleep(500);
            }
            return nulls;
        };
        log("Locating the new subclips (looking again for a few seconds if Premiere is slow to list them)…");
        const emptyEntries = await locate(pieces);
        let missing = pieces.filter((p) => !p.failed && !p.item);
        if (missing.length > 0) {
            log(`Premiere would not show ${missing.length} of the unrestricted shot(s) (${emptyEntries} empty entr${emptyEntries === 1 ? "y" : "ies"} in its item list). `
                + `Rebuilding just those with trim limits so the edit still completes -- they can't be stretched past their cut.`);
            for (let i = 0; i < missing.length; i += ROUGH_CUT_BATCH_SIZE) {
                const batch = missing.slice(i, i + ROUGH_CUT_BATCH_SIZE);
                for (const piece of batch) { piece.name = `${piece.name}_h`; piece.restricted = true; }
                try {
                    await project.lockedAccess(async () => {
                        await project.executeTransaction((compoundAction) => {
                            for (const piece of batch) {
                                compoundAction.addAction(piece.clip.createSubClipAction(piece.name, piece.startTime, piece.endTime, true, { takeVideo: true, takeAudio: false }));
                            }
                        }, "P Corp POST -- Create restricted edit subclips");
                    });
                } catch (e) {
                    log(`Warning: couldn't rebuild a batch with trim limits (${e}).`);
                }
                await sleep(ROUGH_CUT_PAUSE_MS);
            }
            await project.save();
            await locate(missing);
            missing = pieces.filter((p) => !p.failed && !p.item);
        }
        const placeable = pieces.filter((p) => p.item);
        const restrictedCount = placeable.filter((p) => p.restricted).length;
        if (missing.length > 0) log(`Warning: ${missing.length} shot(s) couldn't be built at all and will be empty slots.`);
        if (restrictedCount > 0) log(`Note: ${restrictedCount} shot(s) have trim limits (can't be stretched past their cut); ${placeable.length - restrictedCount} can be stretched.`);

        log(`Placing ${placeable.length} shot(s) at their planned frames…`);
        let placed = 0;
        for (let i = 0; i < placeable.length; i += ROUGH_CUT_BATCH_SIZE) {
            const batch = placeable.slice(i, i + ROUGH_CUT_BATCH_SIZE);
            const insertAll = (compoundAction, list) => {
                for (const piece of list) compoundAction.addAction(sequenceEditor.createInsertProjectItemAction(piece.item, piece.position, 0, 0, false));
            };
            try {
                await project.lockedAccess(async () => {
                    await project.executeTransaction((compoundAction) => insertAll(compoundAction, batch), "P Corp POST -- Insert edit shots");
                });
                placed += batch.length;
            } catch (e) {
                log(`Warning: a batch of inserts failed (${e}) -- retrying that batch one at a time.`);
                for (const piece of batch) {
                    try {
                        await project.lockedAccess(async () => {
                            await project.executeTransaction((compoundAction) => insertAll(compoundAction, [piece]), "P Corp POST -- Insert edit shot");
                        });
                        placed += 1;
                    } catch (e2) {
                        log(`Warning: couldn't place shot ${piece.shot.index} (${e2}).`);
                    }
                }
            }
            log(`  placed ${Math.min(i + ROUGH_CUT_BATCH_SIZE, placeable.length)} of ${placeable.length}`);
            await sleep(ROUGH_CUT_PAUSE_MS);
        }
        if (plan.fit === "fill") {
            log("Scaling the clips to fill the frame…");
            try { log(await fillFrameScale(project, sequence, plan, tpf, keepAlive)); } catch (e) { log(`Note: the fill-the-frame step failed (${e}). The edit itself is fine.`); }
        }
        await project.save();

        log("Placing the music…");
        log(await placeMusic(project, sequenceEditor, plan, keepAlive));
        await project.save();

        if (plan.zooms && plan.zooms.items && plan.zooms.items.length > 0) {
            log(`Adding slow zooms to the ${plan.zooms.items.length} shot(s) whose footage is static…`);
            try {
                log(await placeShotZooms(project, sequence, plan, tpf, keepAlive));
            } catch (e) {
                log(`Note: the slow zoom step failed (${e}). The edit itself is fine.`);
            }
            await project.save();
        }

        if (plan.accents) {
            log("Placing accents (flashes, zoom hits, effects, logo, sound effects)…");
            try {
                log(await placeAccents(project, sequence, sequenceEditor, plan, tpf, keepAlive, runId));
            } catch (e) {
                log(`Note: the accents step failed (${e}). The edit itself is fine.`);
            }
            await project.save();
        }

        if (plan.graphics) {
            log("Placing brand cards, logo bug and captions over the b-roll (V2 cards, V3 logo bug, V4 captions)…");
            try {
                log(await placeBrandGraphics(project, sequence, sequenceEditor, plan, tpf, keepAlive));
            } catch (e) {
                log(`Note: the brand graphics step failed (${e}). The edit itself is fine.`);
            }
            await project.save();
        }

        try {
            const moved = await tidyRoughCutPieces(project);
            log(`Moved ${moved} subclip(s) into the "${ROUGH_CUT_PIECES_BIN}" bin.`);
            await project.save();
        } catch (e) {
            log(`Note: couldn't tidy the subclips into their own bin (${e}). The edit itself is fine.`);
        }

        log("Reporting completion back to P Corp OS…");
        await apiPost(`/post/jobs/${job.id}/rough-cut-assembled`, token, {
            sequence_name: sequenceName,
            clip_count: new Set(placeable.map((p) => p.shot.file_id)).size,
            candidate_count: placed,
        });
        log(`Done. ${placed} of ${plan.shots.length} planned shot(s) placed on "${sequenceName}" `
            + `(${placeable.length - restrictedCount} can be stretched past their cut, ${restrictedCount} cannot). `
            + (plan.accents ? "With the accents listed above." : (plan.graphics ? "Hard cuts with the brand graphics" + ((plan.zooms && plan.zooms.items && plan.zooms.items.length) ? " and slow zooms" : "") + " listed above." : ((plan.zooms && plan.zooms.items && plan.zooms.items.length) ? "Hard cuts with slow zooms on the static shots listed above." : "Hard cuts only -- no effects, flashes or sound effects."))));
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        editButton.disabled = false;
        keepAlive.length = 0;
    }
}

editButton.addEventListener("click", () => {
    assembleEdit().catch((e) => log(`Unhandled error: ${e}`));
});

/** "Learn From My Edit" (2026-10-20): saves the open project, then asks P Corp OS to read the SAVED file, find the sequence that is open, and compare it with the job's
 * plan (kept / changed / dropped, and how its moments line up with Claude's described ones). The comparison is logged on the backend so Josh's taste accumulates as
 * real data. Read-only: it changes nothing in the project except saving it, and nothing in the plan. */
async function learnFromEdit() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }
    learnButton.disabled = true;
    reset();
    try {
        log("Getting the active project…");
        const project = await ppro.Project.getActiveProject();
        if (!project) {
            log("No project is currently open in Premiere.");
            return;
        }
        const job = await findJobForProject(project, token);
        if (!job) {
            log('Couldn\'t find a P Corp OS job with a Premiere project matching this one. Run "Prepare POST Project" for this shoot first.');
            return;
        }
        log(`Found #${job.id} "${job.shoot_name}".`);

        let sequenceName = null;
        try {
            const active = await project.getActiveSequence();
            sequenceName = active ? active.name : null;
        } catch (e) {
            sequenceName = null;
        }
        if (!sequenceName) {
            log("No sequence is open. Open the sequence you cut (click its tab in the timeline) and try again.");
            return;
        }
        log(`Learning from the sequence "${sequenceName}".`);

        log("Saving the project so P Corp OS reads exactly what you see…");
        await project.save();
        await sleep(1500);   // let the file finish landing on the drive before the backend opens it

        log("Comparing your edit with the plan…");
        const result = await apiPost(`/post/jobs/${job.id}/learn-from-edit`, token, { sequence_name: sequenceName, project_path: project.path });
        for (const line of result.lines || []) {
            log(line);
        }
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        learnButton.disabled = false;
    }
}

learnButton.addEventListener("click", () => {
    learnFromEdit().catch((e) => log(`Unhandled error: ${e}`));
});

/** "Build My Edit" (2026-10-20): the one button for getting from a plan to a sequence. If the open project is already a P Corp project it builds the edit from the job's
 * plan; if not, it sets up the project for the next ready shoot first (only when that shoot already has a plan, so no project is made for nothing) and then builds.
 * Everything else the plugin can do stays under "More". It chains the same two actions the buttons below it run, so it can't do anything they can't. */
async function buildMyEdit() {
    const token = ensureToken();
    if (!token) {
        reset();
        log("Paste your P Corp OS auth token above and click Save first.");
        return;
    }
    buildButton.disabled = true;
    reset();
    keepLog = true;
    try {
        const project = await ppro.Project.getActiveProject();
        const prepared = project ? await findJobForProject(project, token, { lenient: false }) : null;
        if (prepared) {
            log(`This is the Premiere project for "${prepared.shoot_name}".`);
            await assembleEdit();
            return;
        }

        const { jobs } = await apiGet("/post/jobs?status=ingested", token);
        const candidate = jobs.find((j) => j.media_analyzed_at);
        if (!candidate) {
            log("Nothing is ready to build. A shoot needs to be copied and analysed in P Corp OS first (that now happens on its own after Start), then planned with Plan Edit.");
            return;
        }
        try {
            await apiGet(`/post/jobs/${candidate.id}/edit-plan`, token);
        } catch (e) {
            log(`"${candidate.shoot_name}" has no edit plan yet. In P Corp OS, open the shoot and press Plan Edit, then click Build My Edit again.`);
            return;
        }
        log(`Setting up the Premiere project for "${candidate.shoot_name}" first…`);
        const made = await run();
        if (!made) return;   // run() has already said why
        const active = await ppro.Project.getActiveProject();
        if (!active || active.path !== made.projectPath) {
            log(`The project is ready at ${made.projectPath}. Open it in Premiere (File > Open Recent) and click Build My Edit again to build the edit.`);
            return;
        }
        log("Now building the edit…");
        await assembleEdit();
    } catch (e) {
        log(`Failed: ${e.message || e}`);
    } finally {
        keepLog = false;
        buildButton.disabled = false;
    }
}

buildButton.addEventListener("click", () => {
    buildMyEdit().catch((e) => log(`Unhandled error: ${e}`));
});

/** Everything except Build and Learn lives behind "More", closed by default. */
function setMoreOpen(open) {
    if (open) morePanel.classList.remove("hidden");
    else morePanel.classList.add("hidden");
    moreToggle.textContent = open ? "Less ▴" : "More ▾";
}

moreToggle.addEventListener("click", () => {
    setMoreOpen(morePanel.classList.contains("hidden"));
});

saveTokenButton.addEventListener("click", () => {
    const value = tokenInput.value.trim();
    if (!value) return;
    setStoredToken(value);
    tokenInput.value = "";
    hideTokenRow();
    reset();
    log("Token saved. Click \"Prepare POST Project\" to continue.");
});

settingsButton.addEventListener("click", () => {
    showTokenRow();
});

// Show the token row immediately on load if nothing is stored yet, so
// it's obvious what to do first rather than waiting for a failed run.
if (!getStoredToken()) {
    showTokenRow();
} else {
    hideTokenRow();
}
