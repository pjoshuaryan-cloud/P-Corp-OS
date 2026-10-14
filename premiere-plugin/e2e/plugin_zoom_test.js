// Logic tests for the slow-zoom step (placeShotZooms) against a MOCK of Premiere's UXP API (our logic only; the real thing is checked in real Premiere).
const fs = require("fs");
const vm = require("vm");
const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
const TPF = 10160640000;
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

class TickTime {
    constructor(t) { this.ticks = String(t); this.ticksNumber = Number(t); }
    static createWithTicks(t) { return new TickTime(t); }
    static createWithSeconds(s) { return new TickTime(Math.round(s * 254016000000)); }
}
function world(opts = {}) {
    const stats = { transactions: [], log: [] };
    const makeScale = (base) => {
        const prm = { displayName: "Scale", timeVarying: false, keys: [], base,
            areKeyframesSupported: async () => !opts.noKeyframes,
            isTimeVarying: async () => prm.timeVarying,
            createKeyframe: (v) => ({ value: v, position: null }),
            createSetTimeVaryingAction: (on) => ({ run: () => { prm.timeVarying = on; } }),
            createAddKeyframeAction: (kf) => ({ run: () => { prm.keys.push({ value: kf.value, at: kf.position.ticksNumber }); prm.keys.sort((a, b) => a.at - b.at); } }),
            getValueAtTime: async (t) => {
                if (opts.wrongReadBack) return { value: 999 };
                if (!prm.timeVarying || prm.keys.length < 2) return { value: prm.base };
                const [a, b] = [prm.keys[0], prm.keys[prm.keys.length - 1]];
                const f = Math.min(1, Math.max(0, (t.ticksNumber - a.at) / (b.at - a.at)));
                return { value: a.value + (b.value - a.value) * f };
            } };
        return prm;
    };
    const trackItem = (startFrame, frames, inFrames = 0) => {
        const scale = opts.noScale ? null : makeScale(opts.base || 100);
        const motion = { getMatchName: async () => "AE.ADBE Motion", getParamCount: async () => (scale ? 3 : 1), getParam: async (k) => (scale && k === 1 ? scale : { displayName: k === 0 ? "Position" : "Rotation" }) };
        const opacity = { getMatchName: async () => "AE.ADBE Opacity", getParamCount: async () => 0, getParam: async () => null };
        const t = { startTicks: startFrame * TPF, frames, inFrames, scale, getStartTime: async () => new TickTime(startFrame * TPF),
            getInPoint: async () => { if (opts.noInPoint) throw new Error("getInPoint is not available"); return new TickTime(inFrames * TPF); },
            getComponentChain: async () => ({ getComponentCount: async () => 2, getComponentAtIndex: async (i) => (i === 0 ? opacity : motion) }) };
        return t;
    };
    // [start frame on the timeline, length, in-point into the SOURCE clip in frames] -- keyframe times count from the source clip's start
    const starts = opts.starts || [[0, 48, 0], [48, 60, 96], [108, 36, 240], [144, 72, 24], [216, 48, 0]];
    const video = [starts.filter((s) => !(opts.missing || []).includes(s[0])).map(([s, f, i]) => trackItem(s, f, i)), [], [], []];
    const sequence = { getVideoTrack: async (i) => ({ getTrackItems: async () => video[i] }) };
    const project = {
        async lockedAccess(fn) { return fn(); },
        async executeTransaction(fn, name) {
            const acts = []; fn({ addAction: (a) => acts.push(a) });
            if (opts.failTransaction && stats.transactions.length + 1 === opts.failTransaction) { stats.transactions.push({ name, failed: true }); throw new Error("transaction refused"); }
            acts.forEach((a) => a.run()); stats.transactions.push({ name, actions: acts.length });
        },
        async save() {}, async getRootItem() { return { getItems: async () => [] }; },
    };
    return { ppro: { Constants: { TrackItemType: { CLIP: 1 } }, TickTime, FolderItem: { cast: () => null }, ClipProjectItem: { cast: () => null } }, project, sequence, video, stats };
}
function loadPlugin(w) {
    const output = { textContent: "" }; const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const sandbox = { document: { getElementById: (id) => (id === "output" ? output : el(id)) }, require: () => w.ppro, localStorage: { getItem: () => "tok", setItem() {} },
        console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object, BigInt, fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }) };
    vm.createContext(sandbox); vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox); return { sandbox, output };
}
async function run(label, opts, items) {
    console.log(`\n== ${label} ==`);
    const w = world(opts); const { sandbox, output } = loadPlugin(w); const keep = [];
    const plan = { fps: 24, zooms: { items } };
    sandbox.__a = { project: w.project, sequence: w.sequence, plan, keep };
    const summary = await vm.runInContext("placeShotZooms(__a.project, __a.sequence, __a.plan, 10160640000, __a.keep)", sandbox);
    return { w, summary, output: output.textContent };
}
const item = (shot, start, frames, direction, percent) => ({ shot_index: shot, start_frame: start, frames, direction, percent });
(async () => {
    let t = await run("Z1: one push-in and one pull-out on a project whose shots are at 100%", {}, [item(2, 48, 60, "in", 3.5), item(4, 144, 72, "out", 4.0)]);
    const a = t.w.video[0][1].scale, b = t.w.video[0][3].scale;
    check(a.timeVarying && a.keys.length === 2 && a.keys[0].at === 96 * TPF && a.keys[1].at === (96 + 60) * TPF, `push-in: keyframes at the shot's SOURCE in-point (96 frames) and at in-point + its exact length: ${a.keys.map((k) => k.at / TPF)}`);
    check(Math.abs(a.keys[0].value - 100) < 1e-9 && Math.abs(a.keys[1].value - 103.5) < 1e-9, `push-in goes 100 -> 103.5: ${a.keys.map((k) => k.value)}`);
    check(b.timeVarying && Math.abs(b.keys[0].value - 104) < 1e-9 && Math.abs(b.keys[1].value - 100) < 1e-9 && b.keys[0].at === 24 * TPF && b.keys[1].at === (24 + 72) * TPF, `pull-out goes 104 -> 100 over its 72 frames, keyframes from its in-point (24 frames): ${b.keys.map((k) => k.value)} at ${b.keys.map((k) => k.at / TPF)}`);
    check(!t.w.video[0][0].scale.timeVarying && !t.w.video[0][2].scale.timeVarying && !t.w.video[0][4].scale.timeVarying, "shots that aren't in the plan are untouched");
    check(/2 of 2 placed \(1 push-in, 1 pull-out\), 2 read back correctly\./.test(t.summary), "summary: " + t.summary);
    check(t.w.stats.transactions.length === 1 && t.w.stats.transactions[0].actions === 6, `one batch, 3 actions per shot: ${JSON.stringify(t.w.stats.transactions)}`);

    t = await run("Z2: the project's default scaling puts the clips at 50% -- percentages follow the CURRENT scale", { base: 50 }, [item(1, 0, 48, "in", 4.0), item(3, 108, 36, "out", 5.0)]);
    check(Math.abs(t.w.video[0][0].scale.keys[1].value - 52) < 1e-9 && Math.abs(t.w.video[0][0].scale.keys[0].value - 50) < 1e-9, `push-in 50 -> 52: ${t.w.video[0][0].scale.keys.map((k) => k.value)}`);
    check(Math.abs(t.w.video[0][2].scale.keys[0].value - 52.5) < 1e-9 && Math.abs(t.w.video[0][2].scale.keys[1].value - 50) < 1e-9, `pull-out 52.5 -> 50: ${t.w.video[0][2].scale.keys.map((k) => k.value)}`);

    t = await run("Z3: a planned shot isn't on the timeline", { missing: [108] }, [item(1, 0, 48, "in", 3), item(3, 108, 36, "in", 3), item(5, 216, 48, "out", 3)]);
    check(/shot 3 isn't on the timeline/.test(t.output) && /2 of 3 placed/.test(t.summary) && /1 skipped/.test(t.summary), t.summary);
    check(t.w.video[0][0].scale.timeVarying && t.w.video[0][3].scale.timeVarying, "the other zooms are still placed");

    t = await run("Z4: the clip has no Scale setting", { noScale: true }, [item(1, 0, 48, "in", 3)]);
    check(/couldn't prepare the slow zoom on shot 1/.test(t.output) && /0 of 1 placed/.test(t.summary), t.output.trim().split("\n").pop());

    t = await run("Z5: keyframes can't be used on this clip", { noKeyframes: true }, [item(1, 0, 48, "in", 3)]);
    check(/can't be keyframed/.test(t.output) && /0 of 1 placed/.test(t.summary), t.summary);

    t = await run("Z6: one batch of zooms is refused by Premiere", { failTransaction: 1, starts: Array.from({ length: 45 }, (_, i) => [i * 24, 24]) }, Array.from({ length: 45 }, (_, i) => item(i + 1, i * 24, 24, "in", 3)));
    check(/a batch of slow zooms failed/.test(t.output) && /25 of 45 placed/.test(t.summary) && /20 skipped/.test(t.summary), t.summary);
    check(t.w.stats.transactions.length === 3 && t.w.stats.transactions.map((x) => x.actions || 0).join(",") === "0,60,15", `batches of 20, 20, 5 (first refused): ${JSON.stringify(t.w.stats.transactions)}`);

    t = await run("Z7: what Premiere reads back doesn't match", { wrongReadBack: true }, [item(2, 48, 60, "in", 3.5)]);
    check(/reads back as 999/.test(t.output) && /0 read back correctly/.test(t.summary), t.summary);

    t = await run("Z8: nothing planned", {}, []);
    check(t.summary === "" && t.w.stats.transactions.length === 0, "no zooms: no output, no transactions");

    t = await run("Z9: a shot far into its clip -- the case that silently failed before the fix", { starts: [[0, 60, 300], [60, 60, 0]] }, [item(1, 0, 60, "in", 4.0), item(2, 60, 60, "in", 4.0)]);
    const far = t.w.video[0][0].scale, near = t.w.video[0][1].scale;
    check(far.keys[0].at === 300 * TPF && far.keys[1].at === 360 * TPF, `a shot that begins 300 frames into its source gets its keyframes at 300 and 360 frames, not at 0 and 60: ${far.keys.map((k) => k.at / TPF)}`);
    check(near.keys[0].at === 0 && near.keys[1].at === 60 * TPF, "a shot that begins at the very start of its source still gets 0 and its length");
    check(Math.abs(far.keys[1].value - 104) < 1e-9 && /2 of 2 placed/.test(t.summary) && /2 read back correctly/.test(t.summary), t.summary);

    t = await run("Z10: the in-point can't be read (older Premiere) -- never guess a time base", { noInPoint: true }, [item(2, 48, 60, "in", 3.5)]);
    check(/couldn't prepare the slow zoom on shot 2/.test(t.output) && /0 of 1 placed/.test(t.summary) && !t.w.video[0][1].scale.timeVarying, "skipped with a warning; nothing animated at a guessed time");

    console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED"); process.exit(failures ? 1 : 0);
})();
