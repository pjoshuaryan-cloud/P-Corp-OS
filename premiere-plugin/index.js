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
 * Never touches creative color grading, other effects, music, or
 * transitions -- the created sequence is an empty, correctly-named
 * starting point only. Phase 5 (2026-09-26) adds Project-panel color
 * LABELING only (a real, documented, non-destructive organizational
 * flag -- never a Lumetri/grading change) for files P Corp OS's own
 * media analysis flagged as corrupt, exposure-outlier, Log/HDR, or
 * color-cast.
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

function reset() {
    output.textContent = "";
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
        return;
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
            return;
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
            for (const file of files.filter((f) => f.proxy_path)) {
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
            await project.createSequence(prep.shoot_name, "");
        } catch (e) {
            log(`Warning: sequence creation failed: ${e}`);
        }

        log("Saving project…");
        await project.save();

        log("Reporting completion back to P Corp OS…");
        await apiPost(`/post/jobs/${job.id}/premiere-project-created`, token, { project_path: projectPath });

        log(`Done. "${prep.shoot_name}" is ready in Premiere.`);
    } catch (e) {
        log(`Failed: ${e.message || e}`);
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
        const clip = ppro.ClipProjectItem.cast(rawItem);
        if (clip) clips.push(clip);
        const bin = ppro.FolderItem.cast(rawItem);
        if (bin) {
            try {
                const rawClips = await bin.getItems();
                for (const rawClip of rawClips) {
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
