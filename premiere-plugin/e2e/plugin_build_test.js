// Logic tests for "Build My Edit" and the "More" toggle against a MOCK of Premiere's UXP API and the backend. "Prepare POST Project" (run) and "Assemble Edit"
// (assembleEdit) are replaced by recorders: what is tested is the DECISIONS Build My Edit makes (which of them to call, in what order, and when to stop and say why),
// not Premiere. Those two actions have their own suites; whether Premiere behaves the same needs a real run.
const fs = require("fs");
const vm = require("vm");

const SRC = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.js";
const HTML = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin/index.html";
let failures = 0;
const check = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) failures++; };

function world(opts = {}) {
    const calls = [];
    let activePath = opts.activePath === undefined ? "/Volumes/X/10_PREMIERE/Other.prproj" : opts.activePath;
    const ppro = { Project: { getActiveProject: async () => (activePath === null ? null : { path: activePath }) } };
    const els = {};
    const mkClassList = () => { const set = new Set(); return { add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c), _set: set }; };
    const el = (id) => (els[id] = els[id] || { id, textContent: "", disabled: false, value: "", classList: mkClassList(), handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; } });
    const output = { textContent: "" };
    const sandbox = {
        document: { getElementById: (id) => (id === "output" ? output : el(id)) },
        require: () => ppro,
        localStorage: { getItem: () => (opts.noToken ? null : "tok"), setItem() {} },
        console, setTimeout, Date, Promise, Set, Map, Math, JSON, String, Number, Array, Object,
        fetch: async (url) => {
            const u = new URL(url);
            const status = u.searchParams.get("status");
            if (u.pathname === "/post/jobs" && status === "premiere_project_created") return { ok: true, status: 200, json: async () => ({ jobs: opts.prepared || [] }) };
            if (u.pathname === "/post/jobs" && status === "ingested") return { ok: true, status: 200, json: async () => ({ jobs: opts.ingested || [] }) };
            const m = u.pathname.match(/^\/post\/jobs\/(\d+)\/edit-plan$/);
            if (m) {
                calls.push("plan-check");
                return opts.noPlan ? { ok: false, status: 404, json: async () => ({ detail: "no plan" }) } : { ok: true, status: 200, json: async () => ({ shots: [1] }) };
            }
            return { ok: false, status: 404, json: async () => ({ detail: "unexpected " + u.pathname }) };
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox);
    // stand-ins for the two actions Build My Edit chains
    sandbox.run = async () => {
        calls.push("run"); sandbox.reset(); sandbox.log("prepare ran");
        if (opts.runFails) return null;
        if (opts.switchOnRun) activePath = opts.runProjectPath;
        return { job: opts.ingested[0], projectPath: opts.runProjectPath };
    };
    sandbox.assembleEdit = async () => { calls.push("assemble"); sandbox.reset(); sandbox.log("assemble ran"); };
    return { sandbox, output, calls, els, ppro };
}

const JD_PREPARED = { id: 34, shoot_name: "JD Sports", premiere_project_path: "/Volumes/X/10_PREMIERE/JD.prproj" };
const GWM_READY = { id: 48, shoot_name: "GWM", media_analyzed_at: "2026-10-20T10:00:00" };

(async () => {
    console.log("== Build My Edit ==");
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/JD.prproj", prepared: [JD_PREPARED], ingested: [GWM_READY] });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "assemble", "in a project that is already set up it just builds the edit (no new project)");
        check(w.output.textContent.includes('Premiere project for "JD Sports"') && w.output.textContent.includes("assemble ran"), "it says which shoot it is building and shows the build's own report");
        check(w.els.buildButton.disabled === false && vm.runInContext("keepLog", w.sandbox) === false, "the button comes back and the panel will clear normally next time");
    }
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/Other.prproj", prepared: [], ingested: [GWM_READY], runProjectPath: "/Volumes/X/10_PREMIERE/GWM.prproj", switchOnRun: true });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check,run,assemble", "in any other project it checks the plan exists, sets up the project, then builds");
        const text = w.output.textContent;
        check(text.indexOf("Setting up the Premiere project") >= 0 && text.indexOf("prepare ran") > text.indexOf("Setting up") && text.indexOf("assemble ran") > text.indexOf("prepare ran"), "the log keeps everything in order across the two steps (the second step doesn't wipe the first)");
        check(text.includes("Now building the edit"), "and says when it moves on to building");
    }
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/Other.prproj", prepared: [], ingested: [GWM_READY], noPlan: true });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check", "a shoot with no plan gets no project made for it");
        check(w.output.textContent.includes('"GWM" has no edit plan yet') && w.output.textContent.includes("Plan Edit"), "it says to press Plan Edit in P Corp OS and click again");
    }
    {
        const w = world({ prepared: [], ingested: [] });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.length === 0 && w.output.textContent.includes("Nothing is ready to build"), "with no ready shoot it says so and does nothing");
    }
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/Other.prproj", prepared: [], ingested: [GWM_READY], runProjectPath: "/Volumes/X/10_PREMIERE/GWM.prproj", runFails: true });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check,run", "if setting up the project fails it stops there (that step has already said why)");
    }
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/Other.prproj", prepared: [], ingested: [GWM_READY], runProjectPath: "/Volumes/X/10_PREMIERE/GWM.prproj", switchOnRun: false });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check,run" && w.output.textContent.includes("Open it in Premiere") && w.output.textContent.includes("GWM.prproj"), "if Premiere didn't switch to the new project it says to open it and click again, rather than building into the wrong one");
    }
    {
        const w = world({ activePath: "/Volumes/X/10_PREMIERE/Other.prproj", prepared: [JD_PREPARED], ingested: [GWM_READY], runProjectPath: "/Volumes/X/10_PREMIERE/GWM.prproj", switchOnRun: true });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check,run,assemble", "a different project open while ONE shoot is prepared is not mistaken for that shoot's project");
    }
    {
        const w = world({ activePath: null, prepared: [], ingested: [GWM_READY], runProjectPath: "/Volumes/X/10_PREMIERE/GWM.prproj", switchOnRun: true });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.join(",") === "plan-check,run,assemble", "with no project open at all it still sets up the next ready shoot and builds it");
    }
    {
        const w = world({ noToken: true, prepared: [], ingested: [] });
        await vm.runInContext("buildMyEdit()", w.sandbox);
        check(w.calls.length === 0 && w.output.textContent.includes("Paste your P Corp OS auth token"), "without a token it asks for one and does nothing");
    }

    console.log("== the panel ==");
    {
        const w = world({ prepared: [], ingested: [] });
        const html = fs.readFileSync(HTML, "utf8");
        const ids = ["buildButton", "learnButton", "moreToggle", "morePanel", "runButton", "transcribeButton", "smartSelectsButton", "exposureButton", "editButton", "roughCutButton", "settingsButton", "output", "tokenRow"];
        check(ids.every((id) => html.includes(`id="${id}"`)), "every button the script looks for is still in the panel");
        check((html.match(/id="learnButton"/g) || []).length === 1 && (html.match(/id="buildButton"/g) || []).length === 1, "each main button is there once");
        const head = html.slice(0, html.indexOf('id="morePanel"'));
        check(head.includes('id="buildButton"') && head.includes('id="learnButton"') && head.includes('id="moreToggle"'), "Build and Learn are above More");
        const more = html.slice(html.indexOf('id="morePanel"'), html.indexOf("<script"));
        check(["runButton", "transcribeButton", "smartSelectsButton", "exposureButton", "editButton", "roughCutButton"].every((id) => more.includes(`id="${id}"`)), "the other six actions are inside More");
        check(html.includes('id="morePanel" class="hidden"'), "More starts closed");
        const toggle = w.els.moreToggle.handlers.click;
        w.els.morePanel.classList.add("hidden");
        toggle();
        check(!w.els.morePanel.classList.contains("hidden") && w.els.moreToggle.textContent === "Less ▴", "clicking More opens it");
        toggle();
        check(w.els.morePanel.classList.contains("hidden") && w.els.moreToggle.textContent === "More ▾", "clicking again closes it");
    }
    console.log(failures ? `\nFAILURES: ${failures}` : "\nAll checks passed.");
    process.exit(failures ? 1 : 0);
})();
