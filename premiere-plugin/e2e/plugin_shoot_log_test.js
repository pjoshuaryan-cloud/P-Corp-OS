// Logic tests for Log This Shoot, Apply Shoot Log and the search-bin fix in walkProject, against a MOCK of Premiere's UXP API and the backend.
// Checks OUR logic. What Premiere really does was proven separately on 2026-11-02 in a throwaway project; the mock copies what that showed: search bins show clips that live elsewhere,
// a clip's Media Type is the only way to tell a search bin, and an action made before an await dies ("The script object is no longer valid").
const fs = require("fs");
const vm = require("vm");

const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

function world(opts = {}) {
    const state = { transactions: 0, marksMade: [], binsMade: [], searchMade: [], moves: [], opened: [], saved: 0, deadActions: 0, posts: [] };
    let inTransaction = false, generation = 0;
    const item = (name, kind, extra = {}) => ({ name, kind, children: [], meta: {}, markers: [], ...extra });
    const root = item("Root", "root");
    const add = (parent, child) => { parent.children.push(child); child.home = parent; return child; };
    const clips = {};
    for (const n of opts.clips || ["C1.MP4", "C2.MP4", "C3.MP4", "C4.MP4"]) clips[n] = add(root, item(n, "clip", { path: `/card/${n}` }));
    add(root, item("Sequence 01", "sequence", { path: "" }));
    if (opts.subclip) add(root, item("RC_1", "clip", { path: "/card/C1.MP4" }));
    if (opts.existingSearchBin) { const s = add(root, item("Mine", "search", { query: "subject_product" })); s.children = [clips["C1.MP4"]]; }
    for (const [n, m] of Object.entries(opts.meta || {})) clips[n].meta = { ...m };
    const live = (fn) => { const born = generation; return () => { if (born !== generation) { state.deadActions++; throw new Error("The script object is no longer valid."); } fn(); }; };
    const NS = "NS";
    class XMPMeta {
        constructor(xml) { this.d = JSON.parse(xml.split("|||")[1]); this.head = xml.split("|||")[0]; }
        doesPropertyExist(_, k) { return k in this.d; }
        getProperty(_, k) { return { value: this.d[k] }; }
        setProperty(_, k, v) { this.d[k] = v; }
        serialize() { return `${this.head}|||${JSON.stringify(this.d)}`; }
    }
    const folderActions = (f) => {
        f.getItems = async () => f.children.slice();
        f.createBinAction = (name) => live(() => { add(f, folder(item(name, "bin"))); state.binsMade.push(name); });
        f.createMoveItemAction = (it, target) => live(() => { it.home.children = it.home.children.filter((x) => x !== it); add(target, it); state.moves.push(`${it.name}>${target.name}`); });
        f.createSmartBinAction = (name, query) => live(() => { add(f, folder(item(name, "search", { query }))); state.searchMade.push(`${name}=${query}`); });
        return f;
    };
    const folder = folderActions;
    folder(root);
    const project = {
        name: "Birkenstock.prproj", path: "/projects/Birkenstock.prproj",
        getRootItem: async () => root,
        lockedAccess: async (fn) => fn(),
        executeTransaction: async (build) => {
            if (inTransaction) throw new Error("nested");
            state.transactions++;
            const list = []; inTransaction = true;
            build({ addAction: (a) => list.push(a) });
            inTransaction = false;
            list.forEach((a) => a());
            generation++;   // what was made before this commit, and not used in it, is dead
        },
        save: async () => { state.saved++; },
    };
    const ppro = {
        Project: { getActiveProject: async () => (opts.noProject ? null : project) },
        FolderItem: { cast: (it) => (it && ["root", "bin", "search"].includes(it.kind) ? it : null) },
        ClipProjectItem: { cast: (it) => {
            if (!it || !["clip", "sequence"].includes(it.kind)) return null;
            it.getMediaFilePath = async () => it.path; return it; } },
        Metadata: {
            getProjectMetadata: async (it) => {
                const type = it.kind === "search" ? "Search Bin" : it.kind === "clip" ? "Movie" : "Bin";
                return `<x:Column.Intrinsic.MediaType>${type}</x:Column.Intrinsic.MediaType>|||${JSON.stringify(it.meta)}`;
            },
            createSetProjectMetadataAction: (it, xml, fields) => {
                if (!inTransaction) state.outsideTransaction = true;
                return live(() => { const d = JSON.parse(xml.split("|||")[1]); for (const f of fields) it.meta[f] = d[f]; });
            },
        },
        Markers: { getMarkers: async (it) => ({
            getMarkers: async () => it.markers.map((m) => ({ getName: async () => m.name, getStart: async () => ({ seconds: m.t }) })),
            createAddMarkerAction: (name, type, start, dur, comment) => live(() => { it.markers.push({ name, t: start.s, comment }); state.marksMade.push(`${it.name}@${start.s}`); }),
        }) },
        TickTime: { createWithSeconds: (s) => ({ s }) },
    };
    const uxp = { xmp: { XMPMeta }, shell: { openExternal: async (url) => { if (opts.noBrowser) throw new Error("denied"); state.opened.push(url); } } };
    const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {}, contains: () => false }, addEventListener() {}, style: {} });
    const output = { textContent: "" };
    const planFor = () => opts.plan || ({ key: "p1", name: "Birkenstock", note_prefix: "[Shoot Log]", counts: { selects: 1, rejects: 1 },
        bins: { parent: "Shoot Log", selects: "Selects", rejects: "Rejects", groups: [{ bin: "By Subject", search: [{ name: "Product", query: "subject_product" }, { name: "Talent", query: "subject_talent" }] }, { bin: "By Shot Size", search: [{ name: "Wide", query: "shot_wide" }] }] },
        clips: [
            { id: "1", name: "C1.MP4", path: "/card/C1.MP4", status: "select", note: "shot_wide subject_product", description: "Bottle held up", previous: opts.previous || {}, markers: [{ t: 1.5, seconds: 0.5, comment: "Lifted" }, { t: 2.5, seconds: 0.5, comment: "Turns" }] },
            { id: "2", name: "C2.MP4", path: "/card/C2.MP4", status: "reject", note: "rejected", description: "", previous: {}, markers: [] },
            { id: "3", name: "C3.MP4", path: "/card/C3.MP4", status: "none", note: "shot_wide subject_talent", description: "Host", previous: {}, markers: [{ t: 0.5, seconds: 0.5, comment: "Waves" }] },
            { id: "9", name: "GONE.MP4", path: "/card/GONE.MP4", status: "none", note: "shot_wide", description: "x", previous: {}, markers: [] },
        ] });
    const sandbox = {
        document: { getElementById: (id) => (id === "output" ? output : el(id)) },
        require: (m) => (m === "uxp" ? uxp : ppro),
        localStorage: { getItem: () => (opts.noToken ? null : "tok"), setItem() {} },
        console, setTimeout: (f) => setTimeout(f, 0), Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object, URL, encodeURIComponent, Error,
        fetch: async (url, init) => {
            const u = new URL(url), body = init && init.body ? JSON.parse(init.body) : null;
            state.posts.push({ path: u.pathname, body });
            if (u.pathname === "/post/shoot-log/start") return { ok: true, status: 200, json: async () => ({ key: "p1", clips: body.clips.length, skipped: opts.skipped || [], review_path: "/static/shoot_log.html?log=p1" }) };
            if (u.pathname === "/post/shoot-log/apply-plan") return opts.noLog ? { ok: false, status: 404, json: async () => ({ detail: "This project hasn't been logged yet. Click Log This Shoot first." }) } : { ok: true, status: 200, json: async () => planFor() };
            if (u.pathname === "/post/shoot-log/p1/applied") return { ok: true, status: 200, json: async () => ({ ok: true }) };
            return { ok: false, status: 404, json: async () => ({ detail: "unexpected" }) };
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox);
    return { sandbox, state, output, root, clips, els };
}
const inBin = (w, parent, child) => { const p = w.root.children.find((x) => x.name === "Shoot Log"); const b = p && p.children.find((x) => x.name === parent); return !!b && b.children.some((x) => x.name === child); };

(async () => {
    console.log("walking a project with a search bin");
    {
        const w = world({ existingSearchBin: true });
        const all = await vm.runInContext("(async () => { const p = await ppro.Project.getActiveProject(); return collectAllClips(p); })()", w.sandbox);
        check(all.filter((c) => c.name === "C1.MP4").length === 1, "a clip shown in a search bin is counted once (was 8 -> 19 in real Premiere)");
        const found = await vm.runInContext("(async () => { const p = await ppro.Project.getActiveProject(); return (await findItemsByName(p, new Set(['C1.MP4']))).found.get('C1.MP4'); })()", w.sandbox);
        check(found.parent.name === "Root", "a clip's parent is where it really lives, never the search bin");
        const every = await vm.runInContext("(async () => { const p = await ppro.Project.getActiveProject(); return findAllItemsByName(p, 'C1.MP4'); })()", w.sandbox);
        check(every.length === 1, "findAllItemsByName sees it once too");
    }

    console.log("Log This Shoot");
    {
        const w = world({ subclip: true, skipped: ["NOTE.WAV"] });
        await w.sandbox.logThisShoot();
        const sent = w.state.posts.find((p) => p.path === "/post/shoot-log/start").body;
        check(sent.project_path === "/projects/Birkenstock.prproj", "says which project");
        check(sent.clips.length === 4 && sent.clips.every((c) => c.path.startsWith("/card/")), "sends each camera file once: no sequences, no subclips");
        check(sent.clips.find((c) => c.path === "/card/C1.MP4").name === "C1.MP4", "a clip with a subclip goes under the clip's own name");
        check(w.state.opened[0].includes("/static/shoot_log.html?log=p1#token=tok"), "opens the review page with the token after the #, which never reaches a server");
        check(!w.output.textContent.includes("tok"), "the panel never shows the token");
        check(w.output.textContent.includes("Left out 1"), "says what it left out");
        check(w.state.transactions === 0 && w.state.saved === 0, "changes nothing in the project");
        check(!w.els.logShootButton.disabled, "the button comes back");
    }
    {
        const w = world({ noBrowser: true });
        await w.sandbox.logThisShoot();
        check(/paste that link/.test(w.output.textContent) && /shoot_log\.html\?log=p1/.test(w.output.textContent), "if the browser can't open, it gives the link instead");
    }
    {
        const w = world({ clips: [] });
        await w.sandbox.logThisShoot();
        check(/no clips yet/.test(w.output.textContent) && !w.state.posts.length, "an empty project says so and sends nothing");
        const n = world({ noProject: true });
        await n.sandbox.logThisShoot();
        check(/Open a project/.test(n.output.textContent), "no project open says so");
    }

    console.log("Apply Shoot Log, first time");
    {
        const w = world({ meta: { "C3.MP4": { "Column.Intrinsic.LogNote": "from the camera" }, "C1.MP4": { "Column.PropertyText.Description": "" } } });
        await w.sandbox.applyShootLog();
        check(!/Failed/.test(w.output.textContent), `runs without error (${w.output.textContent.split("\n").filter((l) => /Failed/.test(l))[0] || "ok"})`);
        check(w.state.deadActions === 0, "every action is made inside its transaction, so none is dead when used");
        check(inBin(w, "Selects", "C1.MP4"), "a select goes to Selects");
        check(inBin(w, "Rejects", "C2.MP4"), "a reject goes to Rejects");
        check(w.root.children.some((x) => x.name === "C3.MP4"), "a clip with no choice stays where it is");
        check(w.clips["C1.MP4"].meta["Column.Intrinsic.LogNote"] === "[Shoot Log] shot_wide subject_product", "tags go in Log Note");
        check(w.clips["C2.MP4"].meta["Column.Intrinsic.LogNote"] === "[Shoot Log] rejected", "a reject has no search words");
        check(w.clips["C3.MP4"].meta["Column.Intrinsic.LogNote"] === "from the camera [Shoot Log] shot_wide subject_talent", "what was already in Log Note is kept");
        check(w.clips["C1.MP4"].meta["Column.PropertyText.Description"] === "Bottle held up", "the one-line description goes in Description");
        check(w.clips["C1.MP4"].meta["Column.PropertyBool.Good"] === "true" && w.clips["C3.MP4"].meta["Column.PropertyBool.Good"] === undefined, "selects get the Good tick; others are left alone");
        check(JSON.stringify(w.state.marksMade) === JSON.stringify(["C1.MP4@1.5", "C1.MP4@2.5", "C3.MP4@0.5"]), "markers on the described moments");
        check(w.clips["C1.MP4"].markers[0].name === "Shoot Log" && w.clips["C1.MP4"].markers[0].comment === "Lifted", "markers say what happens");
        check(w.state.searchMade.join() === "Product=subject_product,Talent=subject_talent,Wide=shot_wide", "search bins by subject and shot size");
        check(w.state.binsMade.join() === "Shoot Log,Selects,Rejects,By Subject,By Shot Size", "bins inside one Shoot Log bin");
        check(w.state.saved === 1, "saves the project");
        const report = w.state.posts.find((p) => p.path === "/post/shoot-log/p1/applied").body.report;
        check(report.moved === 2 && report.markers === 3 && report.search_bins === 3 && report.not_in_project === 1, "reports back what it did");
        check(/1 logged clips aren't in this project/.test(w.output.textContent), "says when a logged clip has gone");
        check(/deletes it from the project/.test(w.output.textContent), "warns about deleting from a search bin");
        check(!w.els.applyLogButton.disabled, "the button comes back");

        // ---- and again, unchanged
        const before = { ...w.state, moves: w.state.moves.length, marks: w.state.marksMade.length, bins: w.state.binsMade.length, search: w.state.searchMade.length };
        const note = w.clips["C3.MP4"].meta["Column.Intrinsic.LogNote"];
        await w.sandbox.applyShootLog();
        check(w.state.moves.length === before.moves, "running it again moves nothing");
        check(w.state.marksMade.length === before.marks, "running it again adds no markers");
        check(w.state.binsMade.length === before.bins && w.state.searchMade.length === before.search, "running it again makes no bins");
        check(w.clips["C3.MP4"].meta["Column.Intrinsic.LogNote"] === note, "running it again doesn't stack up the tags");
        const all = await vm.runInContext("(async () => { const p = await ppro.Project.getActiveProject(); return collectAllClips(p); })()", w.sandbox);
        check(all.length === 5, "after search bins exist, the plugin still sees each clip once (4 clips and a sequence)");
    }

    console.log("Apply Shoot Log, after he changes his mind");
    {
        const plan = (status, note, description, previous) => ({ key: "p1", name: "x", note_prefix: "[Shoot Log]", counts: { selects: 0, rejects: 0 }, bins: { parent: "Shoot Log", selects: "Selects", rejects: "Rejects", groups: [] },
            clips: [{ id: "1", name: "C1.MP4", path: "/card/C1.MP4", status, note, description, previous, markers: [] }] });
        const opts = { plan: plan("select", "shot_wide", "First words", {}) };
        const w = world(opts);
        await w.sandbox.applyShootLog();
        opts.plan = plan("none", "shot_close", "Second words", { status: "select", description: "First words" });
        await w.sandbox.applyShootLog();
        check(w.root.children.some((x) => x.name === "C1.MP4") && !inBin(w, "Selects", "C1.MP4"), "a clip he un-selects comes back out of Selects");
        check(w.clips["C1.MP4"].meta["Column.Intrinsic.LogNote"] === "[Shoot Log] shot_close", "its tags are replaced, not added to");
        check(w.clips["C1.MP4"].meta["Column.PropertyText.Description"] === "Second words", "a description it wrote itself gets updated");
        check(w.clips["C1.MP4"].meta["Column.PropertyBool.Good"] === "false", "its Good tick comes off");
        w.clips["C1.MP4"].meta["Column.PropertyText.Description"] = "Josh typed this";
        opts.plan = plan("reject", "rejected", "Third words", { status: "none", description: "Second words" });
        await w.sandbox.applyShootLog();
        check(w.clips["C1.MP4"].meta["Column.PropertyText.Description"] === "Josh typed this", "a description he typed in Premiere is never overwritten");
        check(inBin(w, "Rejects", "C1.MP4"), "and a new choice still moves the clip");
    }

    console.log("Apply Shoot Log, when there's nothing to do");
    {
        const w = world({ noLog: true });
        await w.sandbox.applyShootLog();
        check(/Click Log This Shoot first/.test(w.output.textContent) && w.state.transactions === 0, "a project never logged says what to do and changes nothing");
        const e = world({ plan: { key: "p1", name: "x", note_prefix: "[Shoot Log]", counts: {}, bins: { parent: "Shoot Log", selects: "Selects", rejects: "Rejects", groups: [] }, clips: [{ id: "1", name: "C1.MP4", path: "/card/C1.MP4", status: "none", note: "", description: "", previous: {}, markers: [] }] } });
        await e.sandbox.applyShootLog();
        check(/Nothing to apply yet/.test(e.output.textContent) && e.state.transactions === 0 && e.state.binsMade.length === 0, "no tags and no choices yet: no empty bins made");
    }
    console.log(`\nFAILS: ${failures}`);
    process.exit(failures ? 1 : 0);
})().catch((e) => { console.log("CRASH", e); process.exit(2); });
