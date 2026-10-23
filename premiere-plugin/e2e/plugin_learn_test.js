// Logic tests for "Learn From My Edit" against a MOCK of Premiere's UXP API and the backend.
// Checks OUR logic (what is saved, in what order, what is sent, what is shown, errors). It cannot show Premiere itself behaves the same -- that needs a real run.
const fs = require("fs");
const vm = require("vm");

const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

function world(opts = {}) {
    const events = [];
    const project = {
        path: opts.path || "/Volumes/X/10_PREMIERE/GWM.prproj",
        async getActiveSequence() { if (opts.noSequence) return null; return { name: opts.sequenceName || "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z" }; },
        async save() { events.push("save"); },
    };
    const ppro = { Project: { getActiveProject: async () => (opts.noProject ? null : project) } };
    const els = {};
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: { add() {}, remove() {} }, addEventListener() {} });
    const output = { textContent: "" };
    const posts = [];
    const sandbox = {
        document: { getElementById: (id) => (id === "output" ? output : el(id)) },
        require: () => ppro,
        localStorage: { getItem: () => (opts.noToken ? null : "tok"), setItem() {} },
        console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object,
        fetch: async (url, init) => {
            const u = new URL(url);
            events.push((init && init.method) || "GET");
            if (u.pathname === "/post/jobs" && u.searchParams.get("status") === "premiere_project_created") {
                const other = [{ id: 48, shoot_name: "GWM - Highlight Video", premiere_project_path: "/Volumes/X/10_PREMIERE/GWM.prproj" }];
                return { ok: true, status: 200, json: async () => ({ jobs: opts.noJob ? [] : (opts.otherJobOnly ? other : [{ id: 48, shoot_name: "GWM - Highlight Video", premiere_project_path: project.path }]) }) };
            }
            if (u.pathname === "/post/learn-from-project") {
                posts.push({ route: "project", ...JSON.parse(init.body) });
                return { ok: true, status: 200, json: async () => ({ lines: ["Read your edit \"BTS cut\" from BTS.prproj: 31 shots.", "Watching this project's auto-saves from now on: ..."] }) };
            }
            if (u.pathname === "/post/jobs/48/learn-from-edit") {
                posts.push(JSON.parse(init.body));
                if (opts.backendError) return { ok: false, status: 400, json: async () => ({ detail: opts.backendError }) };
                return { ok: true, status: 200, json: async () => ({ lines: ["Read your edit: 46 shots.", "Of the plan's 78 shots: 5 kept."] }) };
            }
            return { ok: false, status: 404, json: async () => ({ detail: "unexpected " + u.pathname }) };
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox);
    return { sandbox, output, events, posts, els };
}

(async () => {
    console.log("== Learn From My Edit ==");
    {
        const w = world();
        await vm.runInContext("learnFromEdit()", w.sandbox);
        const text = w.output.textContent;
        check(w.events.filter((e) => e === "save").length === 1, "the project is saved exactly once");
        check(w.events.indexOf("save") < w.events.indexOf("POST"), "it is saved BEFORE the backend is asked to read it");
        check(w.posts.length === 1 && w.posts[0].sequence_name === "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z", "the open sequence's name is what is sent");
        check(w.posts[0].project_path === "/Volumes/X/10_PREMIERE/GWM.prproj", "the open project's path is sent");
        check(text.includes("Read your edit: 46 shots.") && text.includes("5 kept."), "the backend's report is shown line by line");
        check(w.els.learnButton.disabled === false, "the button is usable again afterwards");
    }
    {
        const w = world({ backendError: "The saved project has no sequence called \"X\"" });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        check(w.output.textContent.includes("Failed: The saved project has no sequence called") && w.els.learnButton.disabled === false, "a backend problem is explained plainly and the button comes back");
    }
    {
        const w = world({ noSequence: true });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        check(w.output.textContent.includes("No sequence is open") && !w.events.includes("save") && w.posts.length === 0, "with no open sequence it says so, saves nothing and sends nothing");
    }
    {   // 2026-10-22: a project he started himself (not a P Corp shoot) is learned from as it is, instead of being refused
        const w = world({ noJob: true, path: "/Volumes/Lexar - A/Clients/BTS/BTS.prproj", sequenceName: "BTS cut" });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        const t = w.output.textContent;
        check(t.includes("isn't one of P Corp OS's shoots") && t.includes("saved as it is"), "a project that isn't a shoot is explained: no plan, the cut is saved as it is");
        check(w.events.filter((e) => e === "save").length === 1 && w.events.indexOf("save") < w.events.lastIndexOf("POST"), "...it is saved once, before the backend reads it");
        check(w.posts.length === 1 && w.posts[0].route === "project" && w.posts[0].project_path === "/Volumes/Lexar - A/Clients/BTS/BTS.prproj" && w.posts[0].sequence_name === "BTS cut",
              "...and sent to /post/learn-from-project with its path and the open sequence");
        check(t.includes("31 shots") && t.includes("Watching this project") && w.els.learnButton.disabled === false, "...the backend's report is shown and the button comes back");
    }
    {   // strict lookup: with ONE prepared shoot, a different project must not be taken for it (the old lenient guess would have)
        const w = world({ otherJobOnly: true, path: "/Volumes/Lexar - A/Clients/BTS/BTS.prproj" });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        check(w.posts.length === 1 && w.posts[0].route === "project" && !w.output.textContent.includes("Found #48"), "a project of his own is never taken for the only prepared shoot");
    }
    {
        const w = world({ noProject: true });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        check(w.output.textContent.includes("No project is currently open") && w.posts.length === 0, "with no project open it says so");
    }
    {
        const w = world({ noToken: true });
        await vm.runInContext("learnFromEdit()", w.sandbox);
        check(w.output.textContent.includes("Paste your P Corp OS auth token") && w.events.length === 0, "without a token it asks for one and calls nothing");
    }
    console.log(failures ? `\nFAILURES: ${failures}` : "\nAll checks passed.");
    process.exit(failures ? 1 : 0);
})();
