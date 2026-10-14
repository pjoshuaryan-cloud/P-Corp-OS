// Logic tests for the fill-the-frame step (fillFrameScale) against a MOCK of Premiere's UXP API (our logic only; the real thing is checked in real Premiere).
const fs = require("fs");
const vm = require("vm");
const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
const TPF = 10160640000;
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };
class TickTime { constructor(t) { this.ticks = String(t); this.ticksNumber = Number(t); } static createWithTicks(t) { return new TickTime(t); } static createWithSeconds(s) { return new TickTime(Math.round(s * 254016000000)); } }
function world(opts = {}) {
    const stats = { transactions: [] };
    const sizes = opts.sizes || ["3840 x 2160 (1,0)", "2160 x 3840 (1,0)", "1920 x 1080 (1,0)", "2160 x 3840 (1,0)", "1080 x 1920 (1,0)"];
    const shots = sizes.map((_, i) => [i * 48, 48]);
    const makeScale = () => { const prm = { displayName: "Scale", value: 100, createKeyframe: (v) => ({ value: v }), areKeyframesSupported: async () => true,
        createSetValueAction: (kf) => ({ run: () => { prm.value = kf.value; } }), getValueAtTime: async () => ({ value: opts.wrongReadBack ? 1 : prm.value }) }; return prm; };
    const items = shots.map(([s, f], i) => {
        const scale = makeScale(); const motion = { getMatchName: async () => "AE.ADBE Motion", getParamCount: async () => 2, getParam: async (k) => (k === 1 ? scale : { displayName: "Position" }) };
        return { startTicks: s * TPF, scale, size: sizes[i], getStartTime: async () => new TickTime(s * TPF),
            getProjectItem: async () => { if (opts.noProjectItem === i) throw new Error("no project item"); return { name: "clip" + i, size: sizes[i] }; },
            getComponentChain: async () => ({ getComponentCount: async () => 1, getComponentAtIndex: async () => motion }) };
    });
    const sequence = { getVideoTrack: async () => ({ getTrackItems: async () => items }), getFrameSize: async () => (opts.noFrame ? null : { width: opts.seq ? opts.seq[0] : 2160, height: opts.seq ? opts.seq[1] : 3840 }) };
    const project = { async lockedAccess(fn) { return fn(); }, async executeTransaction(fn, name) { const acts = []; fn({ addAction: (a) => acts.push(a) });
        if (opts.failTransaction && stats.transactions.length + 1 === opts.failTransaction) { stats.transactions.push({ name, failed: true }); throw new Error("transaction refused"); }
        acts.forEach((a) => a.run()); stats.transactions.push({ name, actions: acts.length }); }, async save() {} };
    const ppro = { Constants: { TrackItemType: { CLIP: 1 } }, TickTime, FolderItem: { cast: () => null }, ClipProjectItem: { cast: () => null },
        Metadata: { getProjectColumnsMetadata: async (pi) => { if (opts.badMetadata) throw new Error("Invalid parameter."); return JSON.stringify([{ ColumnID: "Column.Intrinsic.VideoInfo", ColumnValue: opts.unreadable ? "" : pi.size }]); } } };
    return { ppro, project, sequence, items, shots, stats };
}
function loadPlugin(w) {
    const output = { textContent: "" }; const els = {}; const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const sandbox = { document: { getElementById: (id) => (id === "output" ? output : el(id)) }, require: () => w.ppro, localStorage: { getItem: () => "tok", setItem() {} }, console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object, BigInt, fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }) };
    vm.createContext(sandbox); vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox); return { sandbox, output };
}
async function run(label, opts) {
    console.log(`\n== ${label} ==`);
    const w = world(opts); const { sandbox, output } = loadPlugin(w); const keep = [];
    const plan = { fps: 24, fit: "fill", shots: w.shots.map(([s, f], i) => ({ index: i + 1, start_frame: s, duration_frames: f })) };
    sandbox.__a = { project: w.project, sequence: w.sequence, plan, keep };
    const summary = await vm.runInContext("fillFrameScale(__a.project, __a.sequence, __a.plan, 10160640000, __a.keep)", sandbox);
    return { w, summary, output: output.textContent };
}
(async () => {
    let t = await run("F1: five clips in a 2160 x 3840 (vertical) sequence", {});
    const v = t.w.items.map((i) => i.scale.value);
    check(Math.abs(v[0] - 177.78) < 1e-9, `a 3840 x 2160 clip is scaled to 177.78% (centred cover): ${v[0]}`);
    check(v[1] === 100 && v[3] === 100, `a clip that is already 2160 x 3840 is left at 100: ${v[1]}, ${v[3]}`);
    check(Math.abs(v[2] - 355.56) < 1e-9, `a 1920 x 1080 clip needs 355.56% to fill a 2160 x 3840 frame: ${v[2]}`);
    check(Math.abs(v[4] - 200) < 1e-9, `a 1080 x 1920 vertical clip is scaled to exactly 200%: ${v[4]}`);
    check(/3 of 3 clip\(s\) scaled to cover 2160 x 3840 \(3 read back correctly\), 2 already the right size\./.test(t.summary), "summary: " + t.summary);
    check(t.w.stats.transactions.length === 1 && t.w.stats.transactions[0].actions === 3, JSON.stringify(t.w.stats.transactions));

    t = await run("F2: a 16:9 sequence (3840 x 2160)", { seq: [3840, 2160] });
    const w2 = t.w.items.map((i) => i.scale.value);
    check(w2[0] === 100 && Math.abs(w2[1] - 177.78) < 1e-9 && Math.abs(w2[2] - 200) < 1e-9 && Math.abs(w2[4] - 355.56) < 1e-9, `16:9 clip untouched; a 2160 x 3840 clip fills by 177.78 (cropping top and bottom); 1080p 16:9 scales 200; a 1080 x 1920 clip needs 355.56: ${w2}`);

    t = await run("F3: the size of a clip can't be read", { unreadable: true });
    check(t.w.items.every((i) => i.scale.value === 100) && /0 of 0 clip\(s\)/.test(t.summary) && /5 left alone because their size couldn't be read/.test(t.summary), t.summary);

    t = await run("F4: the metadata call fails outright (older Premiere)", { badMetadata: true });
    check(t.w.items.every((i) => i.scale.value === 100) && /left alone/.test(t.summary), t.summary);

    t = await run("F5: one clip has no project item", { noProjectItem: 0 });
    check(t.w.items[0].scale.value === 100 && Math.abs(t.w.items[2].scale.value - 355.56) < 1e-9 && /couldn't read the size of shot 1/.test(t.output) && /1 left alone/.test(t.summary), t.summary);

    t = await run("F6: the sequence size can't be read", { noFrame: true });
    check(/couldn't read the sequence size/.test(t.summary) && t.w.items.every((i) => i.scale.value === 100), t.summary);

    t = await run("F7: Premiere refuses the batch", { failTransaction: 1 });
    check(/a batch of frame-filling scales failed/.test(t.output) && /0 of 3 clip\(s\) scaled/.test(t.summary), t.summary);

    t = await run("F8: what Premiere reads back doesn't match", { wrongReadBack: true });
    check(/reads back as 1/.test(t.output) && /0 read back correctly/.test(t.summary), t.summary);

    console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED"); process.exit(failures ? 1 : 0);
})();
