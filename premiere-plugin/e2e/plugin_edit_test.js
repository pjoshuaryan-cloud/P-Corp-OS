// Logic tests for "Assemble Edit" against a MOCK of Premiere's UXP API (checks OUR logic only).
const fs = require("fs");
const vm = require("vm");
const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
const TPS = 254016000000;
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

class TickTime {
    constructor(ticks) { this.ticksBig = BigInt(ticks); this.ticks = String(ticks); this.seconds = Number(this.ticksBig) / TPS; }
    static createWithSeconds(s) { return new TickTime(Math.round(s * TPS)); }
    static createWithTicks(t) { return new TickTime(t); }
    add(o) { return new TickTime((this.ticksBig + o.ticksBig).toString()); }
    subtract(o) { return new TickTime((this.ticksBig - o.ticksBig).toString()); }
}
function makeWorld(opts = {}) {
    const stats = { transactions: 0, txNames: [], saves: 0, imports: [] };
    const fail = opts.fail || {};
    class Item { constructor(name) { this.name = name; this.isFolder = false; this.isClip = true; } async isSequence() { return false; } }
    class Folder {
        constructor(name) { this.name = name; this.isFolder = true; this.isClip = false; this.children = []; }
        async getItems() { if (this.isRoot) { stats.scans = (stats.scans || 0) + 1; for (const p of stats.pending || []) if (stats.scans >= p.at) { (p.into || this).children.push(p.item); p.done = true; } stats.pending = (stats.pending || []).filter((p) => !p.done); } return [...this.children]; }
        createBinAction(name) { return { run: () => { let n = name, k = 0; while (this.children.some((c) => c.isFolder && c.name === n)) n = `${name} ${String(++k).padStart(2, "0")}`; this.children.push(new Folder(n)); } }; }
        createMoveItemAction(item, newParent) { return { run: () => { this.children = this.children.filter((c) => c !== item); newParent.children.push(item); } }; }
    }
    const root = new Folder("root"); root.isRoot = true; const video = new Folder(opts.nested ? "vertical" : "Video");
    if (opts.nested) { const footage = new Folder("footage"); footage.children.push(video); root.children.push(footage); } else root.children.push(video);   // his own projects: footage > vertical > clips
    const N = opts.clips || 6; const subclipLog = [];
    for (let i = 0; i < N; i++) {
        const name = `MNSTR${2684 + i}.MP4`;
        if (opts.missingClip === name) continue;
        const clip = new Item(name);
        clip.createSubClipAction = (subName, start, end, hard, o) => ({
            run: () => {
                if (fail.subclipBatchOnce && !fail._done && subclipLog.length === 0) { fail._done = true; throw new Error("subclip batch boom"); }
                const s = new Item(subName); s.startTicks = start.ticks; s.endTicks = end.ticks; s.opts = o; s.hard = hard; subclipLog.push(s);
                const unwrappable = !hard && (fail.nullUnrestricted || (fail.nullShots && [...fail.nullShots].some((n) => subName.startsWith(`RC_ED_${n}_`))));
                if (unwrappable) video.children.push(null);                       // Premiere returns an EMPTY entry for it
                else if (fail.lateSubclips) (stats.pending = stats.pending || []).push({ item: s, at: (stats.scans || 0) + fail.lateSubclips, into: video });
                else video.children.push(s);
            },
        });
        video.children.push(clip);
    }
    class Settings { constructor() { this.rect = { width: 1920, height: 1080 }; this.rate = 25; }
        async setVideoFrameRect(r) { this.rect = { width: r.width, height: r.height }; return true; }
        setVideoFrameRate(r) { this.rate = r.value; return true; } }
    class Sequence {
        constructor(name) { this.name = name; this.settings = new Settings(); this.tracks = [[]]; this.inserted = []; }
        async getSettings() { const s = new Settings(); s.rect = { ...this.settings.rect }; s.rate = this.settings.rate; return s; }
        createSetSettingsAction(settings) { return { run: () => { this.settings = settings; } }; }
        async getFrameSize() { return this.settings.rect; }
        async getVideoTrackCount() { return this.tracks.length; }
        async getVideoTrack(i) { return { getTrackItems: async () => this.tracks[i] }; }
    }
    const sequences = [];
    for (const own of opts.ownSequences || []) { const s = new Sequence(own.name); s.settings.rect = own.rect; sequences.push(s); }   // sequences he made himself
    const project = {
        path: "/Volumes/X/10_PREMIERE/JD.prproj",
        async getRootItem() { return root; },
        async lockedAccess(fn) { return fn(); },
        async executeTransaction(fn, name) {
            stats.transactions++; stats.txNames.push(name);
            const actions = []; fn({ addAction: (a) => actions.push(a) });
            actions.forEach((a) => a.run());
        },
        async importFiles(paths, suppress, target) {
            if (fail.import) throw new Error("import boom");
            for (const p of paths) {
                const it = new Item(p.split("/").pop()); stats.imports.push(p);
                if (fail.delayScans) { (stats.pending = stats.pending || []).push({ item: it, at: (stats.scans || 0) + fail.delayScans }); } else (target || root).children.push(it);
            }
        },
        async createSequence(name) { const s = new Sequence(name); sequences.push(s); stats.created = s; return s; },
        async getSequences() { return sequences; },
        async save() { stats.saves++; },
    };
    const editor = (seq) => ({ createInsertProjectItemAction: (item, time, v, a, limit) => {
        if (fail.insertMusic && !item.startTicks) throw new Error("audio insert boom");
        return { run: () => { seq.inserted.push({ name: item.name, atTicks: time.ticks, v, a, startTicks: item.startTicks, endTicks: item.endTicks }); } };
    } });
    const ppro = {
        Constants: { TrackItemType: { EMPTY: 0, CLIP: 1, TRANSITION: 2 } }, TickTime,
        RectF: class { constructor() { this.width = 0; this.height = 0; } }, FrameRate: { createWithValue: (v) => ({ value: v }) },
        FolderItem: { cast: (i) => (i && i.isFolder ? i : null) }, ClipProjectItem: { cast: (i) => (i && i.isClip ? i : null) },
        SequenceEditor: { getEditor: async (seq) => editor(seq) }, Project: { getActiveProject: async () => project },
    };
    return { ppro, project, stats, root, video, subclipLog };
}
function load(world, backend) {
    const output = { textContent: "" }; const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const sandbox = {
        document: { getElementById: (id) => (id === "output" ? output : el(id)) }, require: () => world.ppro,
        localStorage: { getItem: () => "tok", setItem() {} }, console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object, BigInt,
        fetch: async (url, init) => { const u = new URL(url); const res = backend(u.pathname, init && init.method); return { ok: res.ok !== false, status: res.ok === false ? 404 : 200, json: async () => res.body }; },
    };
    vm.createContext(sandbox); vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox);
    return { sandbox, output };
}
function makePlan(fps, world) {
    const frames = [[0, 12], [12, 8], [20, 13], [33, 12], [45, 15], [60, 20]];
    return {
        style: "test-style", fps, duration_frames: 80, duration_seconds: +(80 / fps).toFixed(2), shoot_name: "JD Sports - MOA Store Opening",
        music: { cut_path: "/Volumes/X/07_MUSIC/Song_reelcut.wav", in_seconds: 18.8 },
        shots: frames.map(([s, d], i) => ({ index: i + 1, role: "body", file_id: 100 + i, name: `MNSTR${2684 + i}.MP4`, start_frame: s, duration_frames: d, source_in: 1.0 + i * 0.5, source_out: 1.0 + i * 0.5 + d / fps })),
    };
}
function backendFor(plan, posts, opts = {}) {
    return (pathname, method) => {
        if (pathname === "/post/jobs") return { body: { jobs: [{ id: 34, shoot_name: "JD Sports - MOA Store Opening", premiere_project_path: "/Volumes/X/10_PREMIERE/JD.prproj" }] } };
        if (pathname === "/post/jobs/34/premiere-prep") return { body: { job_id: 34, shoot_name: "JD Sports - MOA Store Opening", profile: "alpha_mode", deliverable_format: "9:16", resolution: "4k_uhd", frame_rate: "25", files: [] } };
        if (pathname === "/post/jobs/34/edit-plan") return opts.noPlan ? { ok: false, body: { detail: "no plan" } } : { body: plan };
        if (pathname === "/post/jobs/34/rough-cut-assembled") { posts.push(pathname); return { body: { ok: true } }; }
        return { ok: false, body: { detail: "unexpected " + pathname } };
    };
}
async function run(label, worldOpts, fps, backendOpts) {
    console.log(`\n== ${label} ==`);
    const world = makeWorld(worldOpts); const plan = makePlan(fps, world); const posts = [];
    const { sandbox, output } = load(world, backendFor(plan, posts, backendOpts));
    await vm.runInContext("assembleEdit()", sandbox);
    return { world, plan, posts, output: output.textContent };
}
(async () => {
    {
        const { sandbox } = load(makeWorld(), () => ({ body: {} }));
        const tpf = (f) => vm.runInContext(`exactFrameTicks(${f})`, sandbox);
        console.log("== frame ticks ==");
        check(tpf(25) === 10160640000, "25 fps -> 10160640000 ticks/frame (exact)");
        check(tpf(23.976) === 10594584000 && tpf(29.97) === 8475667200 && tpf(24) === 10584000000, `23.976 / 29.97 / 24 exact: ${tpf(23.976)} ${tpf(29.97)} ${tpf(24)}`);
    }
    let t = await run("E1: normal edit at 25 fps", { clips: 6 }, 25);
    {
        const seq = t.world.stats.created; const TPF = 10160640000n;
        const shots = seq.inserted.filter((i) => i.startTicks); const music = seq.inserted.filter((i) => !i.startTicks);
        check(/Done\. 6 of 6 planned shot/.test(t.output), "all 6 shots placed: " + (t.output.match(/Done\.[^\n]*/) || [""])[0].slice(0, 60));
        check(shots.every((s, i) => BigInt(s.atTicks) === BigInt(t.plan.shots[i].start_frame) * TPF), "every shot starts at EXACTLY start_frame x ticks-per-frame");
        check(shots.every((s, i) => BigInt(s.endTicks) - BigInt(s.startTicks) === BigInt(t.plan.shots[i].duration_frames) * TPF), "every subclip is EXACTLY duration_frames long (no drift)");
        let contiguous = true; for (let i = 1; i < shots.length; i++) if (BigInt(shots[i].atTicks) !== BigInt(shots[i - 1].atTicks) + (BigInt(shots[i - 1].endTicks) - BigInt(shots[i - 1].startTicks))) contiguous = false;
        check(contiguous, "each shot begins exactly where the previous one ends (gapless)");
        check(t.world.subclipLog.every((s) => s.opts.takeVideo === true && s.opts.takeAudio === false && s.hard === false), "subclips are video-only and NOT restricted to their boundaries (so shots can be stretched later)");
        check(t.world.subclipLog.every((s, i) => BigInt(s.startTicks) % TPF === 0n), "source in-points sit on the frame grid");
        check(music.length === 1 && music[0].atTicks === "0" && music[0].a === 1, `music inserted at tick 0 on audio track index 1: ${JSON.stringify(music[0])}`);
        check(t.world.stats.imports.length === 1 && t.world.stats.imports[0].endsWith("Song_reelcut.wav"), "music cut imported once from the plan's path");
        check(t.posts.length === 1, "completion reported once");
        check(seq.name.startsWith("JD Sports - MOA Store Opening - Edit "), "new, separately named sequence: " + seq.name);
        const bin = t.world.root.children.find((c) => c.name === "Rough Cut Pieces");
        check(bin && bin.children.length === 6, "the 6 subclips were tidied into the pieces bin");
        check(new Set(t.world.subclipLog.map((s) => s.name)).size === 6, "subclip names unique");
        check(t.world.stats.transactions <= 8, `few transactions (${t.world.stats.transactions})`);
        check(seq.settings.rect.width === 2160 && seq.settings.rect.height === 3840, "sequence set to the job's 9:16 4K format");
    }
    t = await run("E2: music import fails -> edit still completes, tells you which file to drag in", { clips: 6, fail: { import: true } }, 25);
    check(/COULD NOT place the music/.test(t.output) && /Song_reelcut\.wav/.test(t.output) && /Done\. 6 of 6/.test(t.output), "failure of the music step is non-fatal and actionable");
    t = await run("E3: music insert throws", { clips: 6, fail: { insertMusic: true } }, 25);
    check(/COULD NOT place the music/.test(t.output) && /Done\. 6 of 6/.test(t.output), "audio insert failure handled the same way");
    t = await run("E4: no plan saved yet", { clips: 6 }, 25, { noPlan: true });
    check(/no edit plan yet/i.test(t.output) && !t.world.stats.created && t.posts.length === 0, "friendly message, nothing created, nothing reported");
    t = await run("E5: one planned clip isn't in the project -> that slot is empty, the others stay at their planned frames", { clips: 6, missingClip: "MNSTR2686.MP4" }, 25);
    {
        const shots = t.world.stats.created.inserted.filter((i) => i.startTicks); const TPF = 10160640000n;
        check(/shot 3\) isn't in the project/.test(t.output) && shots.length === 5, `5 placed, 1 reported missing`);
        check(shots.every((s) => t.plan.shots.some((p) => BigInt(p.start_frame) * TPF === BigInt(s.atTicks))), "no other shot shifted from its planned frame");
    }
    t = await run("E6: 23.976 fps plan -> exact broadcast ticks", { clips: 6 }, 23.976);
    {
        const TPF = 10594584000n; const shots = t.world.stats.created.inserted.filter((i) => i.startTicks);
        check(shots.every((s, i) => BigInt(s.atTicks) === BigInt(t.plan.shots[i].start_frame) * TPF), "positions use the exact 23.976 frame length");
    }
    t = await run("E7: first subclip batch fails -> retried one at a time, all shots placed", { clips: 6, fail: { subclipBatchOnce: true } }, 25);
    check(/retrying that batch one at a time/.test(t.output) && /Done\. 6 of 6/.test(t.output), "batch failure falls back and completes");
    t = await run("E8: Premiere lists the imported music a moment late (the real failure) -> found by retrying, music placed", { clips: 6, fail: { delayScans: 3 } }, 25);
    {
        const music = t.world.stats.created.inserted.filter((i) => !i.startTicks);
        check(music.length === 1 && music[0].a === 1 && /Music ".*" placed/.test(t.output) && !/COULD NOT/.test(t.output), "music found after a few scans and placed on audio track index 1");
    }
    t = await run("E9: the imported music never shows up -> still a clear, actionable message after waiting", { clips: 6, fail: { delayScans: 1000 } }, 25);
    check(/COULD NOT place the music/.test(t.output) && /still isn't listed/.test(t.output) && /Done\. 6 of 6/.test(t.output), "gives up politely, edit still complete");
    t = await run("E10: Premiere returns EMPTY entries for every unrestricted subclip -> fallback rebuilds them with trim limits, edit completes", { clips: 6, fail: { nullUnrestricted: true } }, 25);
    {
        const seq = t.world.stats.created; const TPF = 10160640000n; const shots = seq.inserted.filter((i) => i.startTicks);
        check(/Premiere would not show 6 of the unrestricted/.test(t.output) && /Rebuilding just those with trim limits/.test(t.output), "says what happened and what it is doing about it");
        check(shots.length === 6 && shots.every((x, i) => BigInt(x.atTicks) === BigInt(t.plan.shots[i].start_frame) * TPF), "all 6 shots still placed at their exact planned frames");
        check(/\(0 can be stretched past their cut, 6 cannot\)/.test(t.output), "final line tells the truth: 0 stretchable, 6 not");
        check(t.world.subclipLog.filter((x) => x.hard === true).length === 6 && t.world.subclipLog.filter((x) => x.hard === false).length === 6, "6 unrestricted attempts, then 6 restricted rebuilds");
        check(/Done\. 6 of 6/.test(t.output), "run completes (the earlier build threw 'Cannot read properties of null' and left an empty sequence)");
    }
    t = await run("E11: only shot 3 is unwrappable -> only that one is rebuilt restricted, the other five stay stretchable", { clips: 6, fail: { nullShots: new Set([3]) } }, 25);
    check(/Premiere would not show 1 of the unrestricted/.test(t.output) && /\(5 can be stretched past their cut, 1 cannot\)/.test(t.output) && /Done\. 6 of 6/.test(t.output), "partial fallback: 5 stretchable, 1 restricted");
    t = await run("E12: Premiere lists the new subclips a few scans late -> found by retrying, no fallback needed", { clips: 6, fail: { lateSubclips: 3 } }, 25);
    check(!/Premiere would not show/.test(t.output) && /\(6 can be stretched past their cut, 0 cannot\)/.test(t.output) && /Done\. 6 of 6/.test(t.output), "late listing handled by the retry");
    {   // 2026-10-22: a plan LEARNED from his own cut, built in a project that is not a P Corp shoot (Build My Edit hands it to assembleEdit)
        console.log("\n== E13: a learned plan in his own project: no job, the format of his own 'vertical' sequence, no music ==");
        const world = makeWorld({ clips: 6, ownSequences: [{ name: "vertical", rect: { width: 2180, height: 3480 } }] });
        const plan = makePlan(25, world);
        Object.assign(plan, { music: {}, fit: null, format_from_sequence: "vertical", mode: "learned_transfer", shoot_name: "HAUS WINE  - CAMPAIGN (vertical, learned)", learned_from: { cut: "horizontal - CUT LOCK" } });
        const posts = []; const seen = [];
        const backend = (pathname, method) => { seen.push(pathname); if (pathname === "/post/project-plan/built") { posts.push(pathname); return { body: { recorded: true } }; } return { ok: false, body: { detail: "unexpected " + pathname } }; };
        const { sandbox, output } = load(world, backend);
        sandbox.__learned = plan;
        await vm.runInContext("assembleEdit(__learned)", sandbox);
        const out = output.textContent; const seq = world.stats.created; const TPF = 10160640000n;
        const shots = seq.inserted.filter((i) => i.startTicks);
        check(!seen.some((x) => x.startsWith("/post/jobs")), "no P Corp shoot is looked up or fetched");
        check(/Building the plan learned from "horizontal - CUT LOCK"/.test(out), "it says what it is building");
        check(seq.settings.rect.width === 2180 && seq.settings.rect.height === 3480 && /copied from your "vertical" sequence/.test(out), "the new sequence takes the format of his own 'vertical' sequence");
        check(shots.length === 6 && shots.every((x, i) => BigInt(x.atTicks) === BigInt(plan.shots[i].start_frame) * TPF), "every shot at its exact planned frame");
        check(seq.inserted.every((i) => i.startTicks) && /no music cut/.test(out), "no music is placed (the plan has none) and it says so");
        check(posts.length === 1 && /Done\. 6 of 6/.test(out), "completion is reported to /post/project-plan/built, and the run finishes");
        check(world.stats.created.name.startsWith("HAUS WINE  - CAMPAIGN (vertical, learned) - Edit "), "a NEW sequence, named after the learned plan");
    }
    {
        console.log("\n== E14: the learned plan names a format sequence that doesn't exist ==");
        const world = makeWorld({ clips: 6 }); const plan = makePlan(25, world);
        Object.assign(plan, { music: {}, format_from_sequence: "vertical", learned_from: { cut: "x" } });
        const { sandbox, output } = load(world, (pathname) => (pathname === "/post/project-plan/built" ? { body: {} } : { ok: false, body: {} }));
        sandbox.__learned = plan;
        await vm.runInContext("assembleEdit(__learned)", sandbox);
        check(/left at Premiere's default \(no sequence called "vertical"\)/.test(output.textContent) && /Done\. 6 of 6/.test(output.textContent), "it says the format was left at the default, and still builds");
    }
    {   // 2026-10-23: the learned plan of his FINISHED horizontal carries his song (cut from where his starts, at his level) -- placed like any plan's music
        console.log("\n== E15: a learned plan at 23.976 with his music ==");
        const world = makeWorld({ clips: 6, ownSequences: [{ name: "vertical", rect: { width: 2180, height: 3480 } }] });
        const plan = makePlan(23.976, world);
        Object.assign(plan, { music: { cut_path: "/x/edit_plans/Lamb Truck Keys_from10.594s_535f_-5.0dB.wav", in_seconds: 10.594, gain_db: -5.0 }, fit: null,
                              format_from_sequence: "vertical", mode: "learned_transfer", shoot_name: "HAUS WINE  - CAMPAIGN (vertical, learned)", learned_from: { cut: "horizontal - CUT LOCK" } });
        const posts = [];
        const { sandbox, output } = load(world, (pathname) => { if (pathname === "/post/project-plan/built") { posts.push(pathname); return { body: {} }; } return { ok: false, body: {} }; });
        sandbox.__learned = plan;
        await vm.runInContext("assembleEdit(__learned)", sandbox);
        const out = output.textContent; const seq = world.stats.created; const TPF = 10594584000n;
        const shots = seq.inserted.filter((i) => i.startTicks); const music = seq.inserted.filter((i) => !i.startTicks);
        check(shots.length === 6 && shots.every((x, i) => BigInt(x.atTicks) === BigInt(plan.shots[i].start_frame) * TPF), "every shot on its exact 23.976 frame (his cut points)");
        check(music.length === 1 && music[0].a === 1 && /Music "Lamb Truck Keys_from10\.594s_535f_-5\.0dB\.wav" placed/.test(out), "his song is placed from the start, on audio track index 1");
        check(posts.length === 1 && /Done\. 6 of 6/.test(out), "completion reported, run finishes");
    }
    {   // 2026-10-23, found live in HAUS: his clips sit two bins deep (footage > vertical), and the build found none of them
        console.log("\n== E16: a learned plan whose clips are two bins deep (footage > vertical), subclips landing next to them ==");
        const world = makeWorld({ clips: 6, nested: true, ownSequences: [{ name: "vertical", rect: { width: 2160, height: 3840 } }] });
        const plan = makePlan(23.976, world);
        Object.assign(plan, { music: { cut_path: "/x/edit_plans/song_cut.wav" }, fit: null, format_from_sequence: "vertical", mode: "learned_transfer",
                              shoot_name: "HAUS WINE  - CAMPAIGN (vertical, learned)", learned_from: { cut: "horizontal - CUT LOCK" } });
        const { sandbox, output } = load(world, (pathname) => (pathname === "/post/project-plan/built" ? { body: {} } : { ok: false, body: {} }));
        sandbox.__learned = plan;
        await vm.runInContext("assembleEdit(__learned)", sandbox);
        const out = output.textContent; const TPF = 10594584000n; const shots = world.stats.created.inserted.filter((i) => i.startTicks);
        check(!/isn't in the project/.test(out) && shots.length === 6 && shots.every((x, i) => BigInt(x.atTicks) === BigInt(plan.shots[i].start_frame) * TPF),
            "all 6 clips found two bins deep, every shot at its frame");
        check(/Done\. 6 of 6/.test(out) && world.video.children.filter((c) => c && String(c.name).startsWith("RC_")).length === 0,
            "the working subclips made next to his clips are tidied out of his footage bin");
    }
    console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
    process.exit(failures ? 1 : 0);
})();
