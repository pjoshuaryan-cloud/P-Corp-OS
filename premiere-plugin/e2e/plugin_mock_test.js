// Logic tests for the reworked Assemble Rough Cut against a MOCK of Premiere's UXP API.
// This checks OUR logic (order, batching, scan count, fallbacks, tidy). It cannot show Premiere itself
// behaves the same -- that needs a real run.
const fs = require("fs");
const vm = require("vm");

const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

// ---------------------------------------------------------------- mock Premiere
class TickTime {
    constructor(s) { this.seconds = s; this.ticks = String(Math.round(s * 254016000000)); }
    static createWithSeconds(s) { return new TickTime(s); }
    add(o) { return new TickTime(this.seconds + o.seconds); }
    subtract(o) { return new TickTime(this.seconds - o.seconds); }
}
function makeWorld(opts = {}) {
    const stats = { transactions: 0, getItemsCalls: 0, txNames: [], logs: [] };
    const fail = opts.fail || {};
    class Item { constructor(name) { this.name = name; this.isFolder = false; this.isClip = true; } async isSequence() { return false; } }
    class Folder {
        constructor(name) { this.name = name; this.isFolder = true; this.isClip = false; this.children = []; }
        async getItems() { stats.getItemsCalls++; return [...this.children]; }
        createBinAction(name) { if (fail.bin) throw new Error("bin boom"); return { run: () => { let n = name, k = 0; while (this.children.some((c) => c.isFolder && c.name === n)) n = `${name} ${String(++k).padStart(2, "0")}`; this.children.push(new Folder(n)); } }; }  // like Premiere: a taken name gets " 01", " 02"...
        createMoveItemAction(item, newParent) { return { run: () => { this.children = this.children.filter((c) => c !== item); newParent.children.push(item); } }; }
    }
    const root = new Folder("root");
    const video = new Folder("Video");
    root.children.push(video);
    const clipFiles = [];
    const N = opts.clips || 6;
    for (let i = 0; i < N; i++) {
        const name = `MNSTR${2684 + i}.MP4`;
        const clip = new Item(name);
        clip.parent = video;
        clip.createSubClipAction = (subName, start, end) => ({
            run: () => { if (fail.silentSubclip && subName.includes(`RC_${fail.silentSubclip}_`)) return; const s = new Item(subName); s.range = [start.seconds, end.seconds]; video.children.push(s); },
        });
        video.children.push(clip);
        clipFiles.push({ file_id: 100 + i, relative_path: name, creation_time: `2026-10-05T0${i}:00:00Z` });
    }
    // old leftover subclips from a crashed earlier run
    for (let i = 0; i < (opts.leftovers || 0); i++) video.children.push(new Item(`RC_999_${i}_1700000000000`));

    class Settings { constructor() { this.rect = { width: 1920, height: 1080 }; this.rate = 25; }
        async setVideoFrameRect(r) { this.rect = { width: r.width, height: r.height }; return true; }
        setVideoFrameRate(r) { this.rate = r.value; return true; } }
    class Sequence {
        constructor(name) { this.name = name; this.settings = new Settings(); this.tracks = [[]]; this.inserted = []; }
        async getSettings() { const s = new Settings(); s.rect = { ...this.settings.rect }; s.rate = this.settings.rate; return s; }
        createSetSettingsAction(settings) { if (fail.settings) throw new Error("settings boom"); return { run: () => { this.settings = settings; } }; }
        async getFrameSize() { return this.settings.rect; }
        async getVideoTrackCount() { return this.tracks.length; }
        async getVideoTrack(i) { const items = this.tracks[i]; return { getTrackItems: async () => items }; }
    }
    const sequences = [];
    const trackItem = (clip, start) => ({ getStartTime: async () => new TickTime(start), getProjectItem: async () => clip, getName: async () => clip.name });
    if (opts.timelineOrder !== null) {
        const main = new Sequence("JD Sports - MOA Store Opening");
        main.settings.rect = { width: 2160, height: 3840 }; main.settings.rate = 25;
        const order = opts.timelineOrder || [...video.children].filter((c) => c.name.startsWith("MNSTR")).reverse();   // user's order: reversed vs filename
        let t = 0;
        for (const clip of order) { main.tracks[0].push(trackItem(clip, t)); t += 10; }
        if (opts.dupOnTimeline) main.tracks[0].push(trackItem(order[0], t));
        sequences.push(main);
    }
    const project = {
        path: opts.path || "/Volumes/X/10_PREMIERE/JD.prproj",
        async getRootItem() { return root; },
        async lockedAccess(fn) { return fn(); },
        async executeTransaction(fn, name) {
            stats.transactions++; stats.txNames.push(name);
            const actions = []; fn({ addAction: (a) => actions.push(a) });
            if (fail.insertBatch && name === "P Corp POST -- Insert rough cut clips" && !fail._insertFailed) { fail._insertFailed = true; throw new Error("insert batch boom"); }
            actions.forEach((a) => a.run());
        },
        async createSequence(name) { const s = new Sequence(name); sequences.push(s); stats.created = s; return s; },
        async getSequences() { return sequences; },
        async getActiveSequence() { return sequences[0]; },
        async save() { stats.saves = (stats.saves || 0) + 1; },
    };
    const editor = (seq) => ({ createInsertProjectItemAction: (item, time) => ({ run: () => { seq.inserted.push({ name: item.name, at: time.seconds, len: item.range[1] - item.range[0] }); } }) });
    const ppro = {
        Constants: { TrackItemType: { EMPTY: 0, CLIP: 1, TRANSITION: 2 } },
        TickTime,
        RectF: class { constructor() { this.width = 0; this.height = 0; } },
        FrameRate: { createWithValue: (v) => ({ value: v }) },
        FolderItem: { cast: (i) => (i && i.isFolder ? i : null) },
        ClipProjectItem: { cast: (i) => (i && i.isClip ? i : null) },
        SequenceEditor: { getEditor: async (seq) => editor(seq) },
        Project: { getActiveProject: async () => project },
    };
    return { ppro, project, stats, clipFiles, root, video };
}

// ---------------------------------------------------------------- load the plugin script into a sandbox
function load(world, backend) {
    const output = { textContent: "" };
    const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const sandbox = {
        document: { getElementById: (id) => (id === "output" ? output : el(id)) },
        require: () => world.ppro,
        localStorage: { getItem: () => "tok", setItem() {} },
        console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object,
        fetch: async (url) => {
            const u = new URL(url); const path = u.pathname + u.search.replace(/[?&]token=[^&]*/, "");
            const res = backend(path, u.pathname);
            return { ok: res.ok !== false, status: res.ok === false ? 404 : 200, json: async () => res.body };
        },
    };
    sandbox.fetch.post = [];
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox);
    return { sandbox, output };
}

function backendFor(world, opts = {}) {
    const posts = [];
    const fn = (path, pathname) => {
        if (path.startsWith("/post/jobs?status=premiere_project_created")) return { body: { jobs: [{ id: 34, shoot_name: "JD Sports - MOA Store Opening", premiere_project_path: opts.jobPath || "/Volumes/X/10_PREMIERE/JD.prproj" }] } };
        if (pathname === "/post/jobs/34/premiere-prep") return { body: { job_id: 34, shoot_name: "JD Sports - MOA Store Opening", profile: "alpha_mode", deliverable_format: "9:16", resolution: "4k_uhd", frame_rate: "25", files: world.clipFiles } };
        let m = pathname.match(/\/files\/(\d+)\/smart-selects/); if (m) return { ok: false, body: { detail: "no transcript" } };
        m = pathname.match(/\/files\/(\d+)\/highlights/);
        if (m) { const id = Number(m[1]); return opts.noHighlightsFor === id ? { ok: false, body: { detail: "none" } } : { body: { candidates: [{ start: 2.0 + (id % 3), duration: 3.0, source: "best", rank: 2 }, { start: 8.0, duration: 3.0, source: "best", rank: 1 }] } }; }
        if (pathname === "/post/jobs/34/rough-cut-assembled") { posts.push(pathname); return { body: { ok: true } }; }
        return { ok: false, body: { detail: "unexpected " + pathname } };
    };
    fn.posts = posts; return fn;
}
// POSTs use fetch too (apiPost sends POST) -> same mock handles by path

async function run(label, worldOpts, backendOpts, extra) {
    console.log(`\n== ${label} ==`);
    const world = makeWorld(worldOpts); const backend = backendFor(world, backendOpts);
    const { sandbox, output } = load(world, backend);
    await vm.runInContext("assembleRoughCut()", sandbox);
    return { world, backend, output: output.textContent };
}

(async () => {
    // pure helpers
    {
        const world = makeWorld(); const { sandbox } = load(world, () => ({ body: {} }));
        const f = (p) => vm.runInContext(`deliverableFrameSize(${JSON.stringify(p)})`, sandbox);
        const r = (p) => vm.runInContext(`deliverableFrameRate(${JSON.stringify(p)})`, sandbox);
        console.log("== format helpers ==");
        check(JSON.stringify(f({ resolution: "4k_uhd", deliverable_format: "9:16" })) === '{"width":2160,"height":3840}', "9:16 + 4K UHD -> 2160x3840 (the job's own choice)");
        check(JSON.stringify(f({ resolution: "4k_uhd", deliverable_format: "16:9" })) === '{"width":3840,"height":2160}', "16:9 + 4K UHD -> 3840x2160");
        check(JSON.stringify(f({ resolution: "4k_dci", deliverable_format: "9:16" })) === '{"width":2160,"height":4096}', "9:16 + 4K DCI -> 2160x4096");
        check(JSON.stringify(f({ resolution: "4k_uhd", deliverable_format: "4:5" })) === '{"width":2160,"height":2700}' && JSON.stringify(f({ resolution: "4k_uhd", deliverable_format: "1:1" })) === '{"width":2160,"height":2160}', "4:5 and 1:1");
        check(f({ resolution: "custom", deliverable_format: "9:16" }) === null && f({ resolution: "4k_uhd", deliverable_format: "custom" }) === null, "custom resolution/format -> null (left at default)");
        check(Math.abs(r({ frame_rate: "29.97" }) - 30000 / 1001) < 1e-9 && r({ frame_rate: "25" }) === 25 && r({ frame_rate: "other" }) === null, "frame rates incl. 29.97 -> 30000/1001, 'other' -> null");
    }

    let t = await run("T1: normal run, user's timeline order is the REVERSE of filename order, leftovers from a crashed run", { clips: 6, leftovers: 4 });
    {
        const seq = t.world.stats.created;
        check(/Done\. 6 moment\(s\) from 6 clip\(s\)/.test(t.output), "ONE moment per clip placed: " + (t.output.match(/Done\.[^\n]*/) || [""])[0].slice(0, 70));
        const order = [...new Set(seq.inserted.map((i) => i.name.split("_")[1]))];
        check(order.join(",") === "105,104,103,102,101,100", `inserted in the TIMELINE's order (reverse), not filename order: ${order}`);
        let ok = true, expect = 0; for (const ins of seq.inserted) { if (Math.abs(ins.at - expect) > 1e-6) ok = false; expect += ins.len; }
        check(ok, "each piece starts exactly where the previous one ended (gapless, tick-accumulated)");
        check(seq.settings.rect.width === 2160 && seq.settings.rect.height === 3840, `rough cut format matched to the user's timeline: ${JSON.stringify(seq.settings.rect)}`);
        check(t.world.stats.getItemsCalls <= 12, `project scanned a small, bounded number of times (getItems calls: ${t.world.stats.getItemsCalls}) -- the old code did one full scan PER PIECE`);
        check(t.world.stats.transactions <= 12, `few transactions (${t.world.stats.transactions}) vs 2-per-piece before (${6 * 2}+)`);
        const bins = t.world.root.children.filter((c) => c.isFolder && c.name === "Rough Cut Pieces");
        check(bins.length === 1 && bins[0].children.length === 6 + 4, `all 10 RC_ items (6 new + 4 leftovers from the crashed run) moved into one 'Rough Cut Pieces' bin: ${bins[0] && bins[0].children.length}`);
        check(!t.world.video.children.some((c) => c.name.startsWith("RC_")), "Video bin no longer cluttered with RC_ items; originals untouched: " + t.world.video.children.filter((c) => c.name.startsWith("MNSTR")).length + " clips");
        check(t.backend.posts.length === 1, "completion reported to P Corp OS once");
        check(t.world.stats.saves >= 3, `project saved between phases (${t.world.stats.saves} saves)`);
        check(new Set(seq.inserted.map((i) => i.name)).size === seq.inserted.length, "every subclip name unique");
        const subs = t.world.root.children.find((c) => c.name === "Rough Cut Pieces").children.filter((c) => c.range && c.name.includes("_0_") && !c.name.startsWith("RC_999"));
        check(subs.length === 6 && subs.every((c) => c.range[0] === 8.0), `the moment used from each clip is the RANK-1 one (starts at 8.0s), not the chronologically first (${subs.map((c) => c.range[0])})`);
    }

    t = await run("T2: no timeline named after the shoot -> falls back to camera-timestamp order; job's own 9:16 4K 25fps format applied", { clips: 4, timelineOrder: null });
    {
        const seq = t.world.stats.created;
        const order = [...new Set(seq.inserted.map((i) => i.name.split("_")[1]))];
        check(order.join(",") === "100,101,102,103", `camera-timestamp order used: ${order}`);
        check(seq.settings.rect.width === 2160 && seq.settings.rect.height === 3840 && seq.settings.rate === 25, `format set from the job's choices: ${JSON.stringify(seq.settings.rect)} @${seq.settings.rate}`);
        check(/No clips found on a timeline/.test(t.output), "log says why the order fell back");
    }

    t = await run("T3: first INSERT batch fails -> retried one piece at a time, positions stay gapless", { clips: 6, fail: { insertBatch: true } });
    {
        const seq = t.world.stats.created; let ok = true, expect = 0;
        for (const ins of seq.inserted) { if (Math.abs(ins.at - expect) > 1e-6) ok = false; expect += ins.len; }
        check(seq.inserted.length === 6 && ok, `all 6 placed after the fallback, gapless: ${seq.inserted.length}`);
        check(/retrying that batch one at a time/.test(t.output), "warning logged");
    }

    t = await run("T4: project path differs from the stored one (recovered project) but only one job exists", { clips: 3, path: "/Volumes/X/Recovery/JD--abc.prproj" });
    check(/using the only job/.test(t.output) && /Done\./.test(t.output), "falls back to the only job and completes");

    t = await run("T5: one subclip silently never appears -> skipped with a warning, the rest placed", { clips: 4, fail: { silentSubclip: 101 } });
    check(/couldn't be found and will be skipped/.test(t.output) && t.world.stats.created.inserted.every((i) => !i.name.startsWith("RC_101_")) && t.world.stats.created.inserted.length > 0, "missing subclip skipped, others placed");

    t = await run("T6: tidy fails (bin creation throws) -> rough cut still completes and is reported", { clips: 3, fail: { bin: true } });
    check(/couldn't tidy/.test(t.output) && /Done\./.test(t.output) && t.backend.posts.length === 1, "tidy failure is non-fatal");

    t = await run("T7: sequence-format copy fails -> falls back to the job's own format", { clips: 3, fail: { settings: true } });
    check(/COULD NOT/.test(t.output) && /Done\./.test(t.output), "format failure is logged, run completes: " + (t.output.match(/Sequence format[^\n]*/) || [""])[0].slice(0, 110));

    t = await run("T8: a clip has no best moments -> skipped, others used; duplicates on the timeline counted once", { clips: 4, dupOnTimeline: true }, { noHighlightsFor: 102 });
    check(/3 clip\(s\)/.test(t.output) && !t.world.stats.created.inserted.some((i) => i.name.startsWith("RC_102_")), "clip without moments skipped; no duplicate pieces from the duplicated timeline clip");


    {
        console.log("\n== T9: two rough cuts in the same project -> the pieces bin is reused, no empty 'Rough Cut Pieces 01' bins pile up ==");
        const world = makeWorld({ clips: 4 }); const backend = backendFor(world, {});
        const { sandbox, output } = load(world, backend);
        await vm.runInContext("assembleRoughCut()", sandbox);
        await vm.runInContext("assembleRoughCut()", sandbox);
        const bins = world.root.children.filter((c) => c.isFolder && c.name.startsWith("Rough Cut Pieces"));
        check(bins.length === 1 && bins[0].name === "Rough Cut Pieces", `one pieces bin after two runs: ${bins.map((b) => b.name)}`);
        check(bins[0].children.length >= 8 && !world.video.children.some((c) => c.name.startsWith("RC_")), `both runs' pieces are in it (${bins[0].children.length}), none left in the Video bin`);
        check(/Done\./.test(output.textContent), "second run completed");
    }

    console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
    process.exit(failures ? 1 : 0);
})();
