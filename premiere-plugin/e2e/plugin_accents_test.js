// Logic tests for the accent phases against a MOCK of Premiere's UXP API (our logic only; real Premiere is checked from the saved project).
const fs = require("fs");
const vm = require("vm");
const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
const TPS = 254016000000, TPF = 10160640000;
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

class TickTime {
    constructor(t) { this.ticksBig = BigInt(t); this.ticks = String(t); this.ticksNumber = Number(this.ticksBig); this.seconds = this.ticksNumber / TPS; }
    static createWithTicks(t) { return new TickTime(t); }
    static createWithSeconds(s) { return new TickTime(Math.round(s * TPS)); }
}
function world(opts = {}) {
    const stats = { scans: 0, pending: [], log: [] };
    class Item { constructor(name) { this.name = name; this.isFolder = false; this.isClip = true; }
        createSubClipAction(name, start, end, hard, o) { return { run: () => { const s = new Item(name); s.sub = { start: start.ticks, end: end.ticks, hard, o }; root.children.push(s); } }; } }
    class Folder { constructor(name) { this.name = name; this.isFolder = true; this.isClip = false; this.children = []; }
        async getItems() { stats.scans++; for (const p of stats.pending) if (stats.scans >= p.at) { root.children.push(p.item); p.done = true; } stats.pending = stats.pending.filter((p) => !p.done); return [...this.children]; } }
    const root = new Folder("root");
    if (!opts.noAdjustment) root.children.push(Object.assign(new Item("Adjustment Layer"), { defaultFrames: 7 }));
    for (const info of opts.moreLayers || []) root.children.push(Object.assign(new Item("Adjustment Layer"), { defaultFrames: 7, videoInfo: info }));
    // sequence tracks
    const trackItem = (start, frames) => {
        const t = { startTicks: start, endTicks: start + frames * TPF, components: [], getStartTime: async () => new TickTime(t.startTicks) };
        t.getComponentChain = async () => ({
            getComponentCount: async () => t.components.length,
            createInsertComponentAction: (comp, idx) => ({ run: () => { t.components.splice(idx, 0, comp); } }),
            getComponentAtIndex: async (i) => t.components[i],
        });
        t.createSetEndAction = (end) => ({ run: () => { t.endTicks = end.ticksNumber; } });
        return t;
    };
    const video = [[], [], [], []]; const placedAudio = [];
    const shots = [[0, 15], [15, 10], [25, 8], [33, 12], [45, 15], [60, 20]];
    shots.forEach(([s, d]) => video[0].push(trackItem(s * TPF, d)));
    const sequence = { getVideoTrack: async (i) => ({ getTrackItems: async () => video[i] }) };
    if (opts.seqSize) sequence.getFrameSize = async () => ({ width: opts.seqSize[0], height: opts.seqSize[1] });
    const editor = { createOverwriteItemAction: (item, time, v, a) => ({ run: () => {
        if (a > 0 || item.sub && item.sub.o && item.sub.o.takeAudio) { placedAudio.push({ name: item.name, at: time.ticks, audioIndex: a, sub: item.sub }); return; }
        const frames = item.defaultFrames || (item.name.endsWith(".png") ? 150 : 7); video[v].push(trackItem(time.ticksNumber, frames)); video[v][video[v].length - 1].name = item.name; video[v][video[v].length - 1].from = item;
    } }) };
    const project = {
        async getRootItem() { return root; },
        async lockedAccess(fn) { return fn(); },
        async executeTransaction(fn, name) { const acts = []; fn({ addAction: (a) => acts.push(a) }); acts.forEach((a) => a.run()); stats.log.push(name); },
        async importFiles(paths) { for (const p of paths) { const it = new Item(p.split("/").pop()); if (opts.delayImport) stats.pending.push({ item: it, at: stats.scans + opts.delayImport }); else root.children.push(it); } },
        async save() {},
    };
    const mkParam = (name, owner) => ({ displayName: name, createKeyframe: (v) => ({ v }), createSetValueAction: (kf) => ({ run: () => { owner.values[name] = kf.v; } }) });
    const ppro = {
        Constants: { TrackItemType: { CLIP: 1 } }, TickTime,
        ...(opts.layerInfo !== undefined ? { Metadata: { getProjectColumnsMetadata: async (item) => { if (opts.layerInfoThrows) throw new Error('Invalid parameter.'); return JSON.stringify([{ ColumnID: 'Column.Intrinsic.Name', ColumnValue: item.name }, { ColumnID: 'Column.Intrinsic.VideoInfo', ColumnName: 'Video Info', ColumnValue: item.videoInfo || opts.layerInfo }]); } } } : {}),
        FolderItem: { cast: (i) => (i && i.isFolder ? i : null) }, ClipProjectItem: { cast: (i) => (i && i.isClip ? i : null) },
        VideoFilterFactory: { createComponent: async (match) => {
            if (opts.failEffect && opts.failEffect === match) throw new Error("effect not installed");
            const comp = { matchName: match, values: {}, getMatchName: async () => match };
            const names = match.includes("Lumetri") ? ["Exposure", "Contrast"] : match.includes("Zoom") ? ["Zoom", "Variation", "Feather", "Edge Behavior", "Slices"] : [];
            comp.getParamCount = async () => names.length; comp.getParam = async (i) => mkParam(names[i], comp); return comp; } },
    };
    return { ppro, project, sequence, editor, video, placedAudio, stats, root };
}
function loadPlugin(w) {
    const output = { textContent: "" }; const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const sandbox = { document: { getElementById: (id) => (id === "output" ? output : el(id)) }, require: () => w.ppro, localStorage: { getItem: () => "tok", setItem() {} },
        console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object, BigInt, fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }) };
    vm.createContext(sandbox); vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox); return { sandbox, output };
}
const planWith = (accents) => ({ fps: 25, shots: [[0, 15], [15, 10], [25, 8], [33, 12], [45, 15], [60, 20]].map(([s, d], i) => ({ index: i + 1, start_frame: s, duration_frames: d })), accents });
const baseAccents = () => ({
    overlay_track: 2,
    flashes: [{ kind: "flash", start_frame: 14, frames: 2, effect: "AE.ADBE Lumetri", params: { Exposure: 6.2 } }, { kind: "flash", start_frame: 59, frames: 4, effect: "AE.ADBE Lumetri", params: { Exposure: 6.2 } }],
    zoom_hits: [{ kind: "zoom_hit", start_frame: 31, frames: 4, effect: "AE.Impact_Zoom_Blur_FX", params: { Zoom: 25, Variation: 50, Feather: 0, "Edge Behavior": 1, Slices: 0 } }],
    shot_effects: [{ shot_index: 2, effect: "AE.Impact_Zoom_Blur_FX", params: { Zoom: 25, Feather: 142 } }, { shot_index: 5, effect: "AE.ADBE Black & White", params: {} }, { shot_index: 6, effect: "AE.ADBE Black & White", params: {} }],
    logo: { file: "/x/graphics/JD-BLACK.png", start_frame: 60, frames: 20, track: 4 },
    sfx: [{ role: "hit", file: "/lib/Hits/Impact Hit.wav", name: "Impact Hit.wav", start_frame: 10, frames: 14, track: 3 }, { role: "whoosh", file: "/lib/Whooshes/Slide 3 - Whoosh.wav", name: "Slide 3 - Whoosh.wav", start_frame: 21, frames: 30, track: 4 }],
    notes: [],
});
async function run(label, opts, mutate) {
    console.log(`\n== ${label} ==`);
    const w = world(opts); const { sandbox, output } = loadPlugin(w); const accents = baseAccents(); if (mutate) mutate(accents);
    const plan = planWith(accents); const keep = [];
    sandbox.__args = { project: w.project, sequence: w.sequence, editor: w.editor, plan, keep };
    const summary = await vm.runInContext("placeAccents(__args.project, __args.sequence, __args.editor, __args.plan, 10160640000, __args.keep, 1234)", sandbox);
    return { w, summary, output: output.textContent };
}
(async () => {
    let t = await run("A1: all accents on a clean sequence");
    {
        const v2 = t.w.video[1], v1 = t.w.video[0], v4 = t.w.video[3];
        check(v2.length === 3 && v2.map((x) => x.startTicks / TPF).join(",") === "14,31,59", `3 adjustment layers on V2 at frames 14, 31, 59: ${v2.map((x) => x.startTicks / TPF)}`);
        check(v2.map((x) => (x.endTicks - x.startTicks) / TPF).join(",") === "2,4,4", `trimmed to exactly 2, 4 and 4 frames: ${v2.map((x) => (x.endTicks - x.startTicks) / TPF)}`);
        check(v2[0].components[0].matchName === "AE.ADBE Lumetri" && v2[0].components[0].values.Exposure === 6.2 && v2[2].components[0].values.Exposure === 6.2, "flashes carry Lumetri with Exposure 6.2");
        check(v2[1].components[0].matchName === "AE.Impact_Zoom_Blur_FX" && v2[1].components[0].values.Zoom === 25 && v2[1].components[0].values.Variation === 50 && v2[1].components[0].values["Edge Behavior"] === 1, "zoom hit carries Zoom Blur with the style's values");
        check(v1[1].components.length === 1 && v1[1].components[0].values.Feather === 142 && v1[4].components[0].matchName === "AE.ADBE Black & White" && v1[5].components[0].matchName === "AE.ADBE Black & White", "shot 2 has zoom blur (Feather 142); shots 5 and 6 are black & white");
        check(v1[0].components.length === 0 && v1[2].components.length === 0, "other shots untouched");
        check(v4.length === 1 && v4[0].startTicks === 60 * TPF && v4[0].endTicks === 80 * TPF, `logo on V4 from frame 60, trimmed to 20 frames: ${v4[0] && v4[0].endTicks / TPF}`);
        const subs = t.w.placedAudio;
        check(subs.length === 2 && subs[0].sub.start === "0" && subs[0].sub.end === String(14 * TPF) && subs[0].sub.o.takeAudio === true && subs[0].sub.o.takeVideo === false, "each sound effect is cut to exactly its length as an audio-only subclip");
        check(subs[0].at === String(10 * TPF) && subs[0].audioIndex === 2 && subs[1].at === String(21 * TPF) && subs[1].audioIndex === 3, "hit placed on audio index 2 (A3) at frame 10, whoosh on index 3 (A4) at frame 21");
        check(/2 flash\(es\), 1 zoom hit\(s\), 1 shot zoom blur\(s\), 2 black & white shot\(s\), the logo, 2 sound effect\(s\)/.test(t.summary), "summary: " + t.summary);
    }
    t = await run("A2: no 'Adjustment Layer' item in the project", { noAdjustment: true });
    check(/no "Adjustment Layer" item/.test(t.output) && t.w.video[1].length === 0 && t.w.video[0][1].components.length === 1 && t.w.video[3].length === 1 && t.w.placedAudio.length === 2, "flashes/zoom hits skipped with instructions; shot effects, logo and sound effects still placed");
    t = await run("A3: imported logo and sounds appear a few scans late", { delayImport: 3 });
    check(t.w.video[3].length === 1 && t.w.placedAudio.length === 2, "found by retrying");
    t = await run("A4: zoom blur isn't installed on this machine", { failEffect: "AE.Impact_Zoom_Blur_FX" });
    check(/couldn't prepare/.test(t.output) && t.w.video[1].filter((x) => x.components.length).length === 2 && t.w.video[0][4].components.length === 1, "zoom blur skipped with a warning; flashes, black & white, logo, sounds unaffected");
    t = await run("A5: no sound effects and no logo in the plan", {}, (a) => { a.sfx = []; a.logo = null; });
    check(t.w.placedAudio.length === 0 && t.w.video[3].length === 0 && t.w.video[1].length === 3 && /no logo, 0 sound effect/.test(t.summary), "other accents placed, summary says no logo / 0 sound effects");
    t = await run("A6: a shot the plan names isn't on the timeline", {}, (a) => { a.shot_effects.push({ shot_index: 9, effect: "AE.Impact_Zoom_Blur_FX", params: {} }); });
    check(/shot 9 isn't on the timeline/.test(t.output) && t.w.video[0][1].components.length === 1, "reported and skipped, the rest placed");
    t = await run("A7: planner notes are shown", {}, (a) => { a.notes = ["This style ends on a logo card but no logo file was found."]; });
    check(/Note: This style ends on a logo card/.test(t.output), "plan notes reach the log");
    t = await run("A8: the Adjustment Layer is 2160x3840 but the sequence is 3840x2160 (found live)", { layerInfo: "2160 x 3840 (1,0)", seqSize: [3840, 2160] });
    check(/Warning: the "Adjustment Layer" in this project is 2160 x 3840 but this sequence is 3840 x 2160/.test(t.output) && /File > New > Adjustment Layer, width 3840, height 2160/.test(t.output), "warns with both sizes and how to fix it");
    check(/WARNING: the "Adjustment Layer"/.test(t.summary) && t.w.video[1].length === 3, "the summary carries the warning too, and the flashes and zoom hits are still placed (no change in behaviour)");
    check(!/delete/i.test(t.output) && /keep the old one/.test(t.output), "never tells him to delete the old layer (his other sequences use it: deleting it would strip their flashes)");
    t = await run("A11: two Adjustment Layers -- his horizontal's (3840x2180) and one made for the vertical (2160x3840) -- in a 2160x3840 sequence",
        { layerInfo: "3840 x 2180 (1,0)", moreLayers: ["2160 x 3840 (1,0)"], seqSize: [2160, 3840] });
    check(t.w.video[1].length === 3 && t.w.video[1].every((x) => x.from && x.from.videoInfo === "2160 x 3840 (1,0)"), "every flash and zoom hit is a copy of the one that covers the sequence");
    check(!/WARNING/.test(t.summary) && /Using the "Adjustment Layer" that covers this sequence \(the project has 2\)/.test(t.output), "no warning; it says which one it used");
    t = await run("A11b: two layers and neither covers the sequence", { layerInfo: "3840 x 2180 (1,0)", moreLayers: ["1920 x 1080 (1,0)"], seqSize: [2160, 3840] });
    check(/WARNING: the "Adjustment Layer" in this project is 3840 x 2180/.test(t.summary) && t.w.video[1].length === 3 && t.w.video[1].every((x) => !x.from.videoInfo),
        "warns about the first and still places copies of it (unchanged behaviour)");
    t = await run("A9: the Adjustment Layer matches the sequence, or is larger", { layerInfo: "3840 x 2160 (1,0)", seqSize: [3840, 2160] });
    check(!/Adjustment Layer" in this project/.test(t.output) && !/WARNING/.test(t.summary), "same size: no warning");
    t = await run("A9b: larger layer", { layerInfo: "4096 x 4096 (1,0)", seqSize: [3840, 2160] });
    check(!/WARNING/.test(t.summary), "a layer bigger in both directions covers the picture: no warning");
    t = await run("A9c: only one direction too small", { layerInfo: "3840 x 1080 (1,0)", seqSize: [3840, 2160] });
    check(/WARNING/.test(t.summary), "wide enough but not tall enough still warns");
    t = await run("A10: the size can't be read (Metadata call fails / missing / odd text)", { layerInfo: "2160 x 3840 (1,0)", layerInfoThrows: true, seqSize: [3840, 2160] });
    check(!/WARNING/.test(t.summary) && t.w.video[1].length === 3, "Metadata error: nothing is claimed, accents placed");
    t = await run("A10b: no Metadata API at all and no getFrameSize");
    check(!/WARNING/.test(t.summary) && t.w.video[1].length === 3, "older Premiere: silent, accents placed");
    t = await run("A10c: unparseable Video Info", { layerInfo: "unknown", seqSize: [3840, 2160] });
    check(!/WARNING/.test(t.summary), "unparseable text: nothing is claimed");
    console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED"); process.exit(failures ? 1 : 0);
})();
