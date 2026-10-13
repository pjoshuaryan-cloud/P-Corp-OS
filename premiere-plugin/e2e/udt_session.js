// One session: load the plugin into the real Premiere, attach the debugger (CDP) and evaluate code inside the plugin's context.
const { Udt } = require("./udt.js");
const PLUGIN_DIR = "/Users/joshuapeters/Desktop/P-Corp/premiere-plugin";
async function openSession() {
    const u = await new Udt().connect(); const id = u.clients[0].id;
    const load = await u.proxy(id, { command: "Plugin", action: "load", params: { provider: { type: "disk", path: PLUGIN_DIR } }, breakOnStart: false, isPlaygroundPlugin: false }, 60000);
    if (!load.pluginSessionId) throw new Error("load failed: " + JSON.stringify(load).slice(0, 300));
    const dbg = await u.proxy(id, { command: "Plugin", action: "debug", pluginSessionId: load.pluginSessionId });
    if (!dbg.wsdebugUrl) throw new Error("no debug url: " + JSON.stringify(dbg).slice(0, 300));
    return { u, id, sid: load.pluginSessionId, wsUrl: dbg.wsdebugUrl.replace(/^ws=/, "ws://"), dbg };
}
class Cdp {
    constructor(url) { this.url = url; this.n = 0; this.p = new Map(); this.logs = []; }
    async connect() {
        this.ws = new WebSocket(this.url);
        this.ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && this.p.has(m.id)) { this.p.get(m.id)(m); this.p.delete(m.id); } else if (m.method === "Runtime.executionContextCreated") { if (this.ctx === undefined || m.params.context.auxData.isDefault) this.ctx = m.params.context.id; } else if (m.method === "Runtime.consoleAPICalled") this.logs.push(m.params.args.map((a) => a.value ?? a.description).join(" ")); };
        await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error("CDP connect failed")); });
        await this.send("Runtime.enable"); this.ws.send(JSON.stringify({ id: ++this.n, method: "Runtime.runIfWaitingForDebugger" }));
        await new Promise((r) => setTimeout(r, 2500));  // the page's execution context is announced a moment after enabling
        if (this.ctx === undefined) throw new Error("no execution context for the plugin (is its panel created?)"); return this;
    }
    send(method, params = {}, timeout = 30000) { return new Promise((res, rej) => { const id = ++this.n; const t = setTimeout(() => rej(new Error("CDP timeout " + method)), timeout); this.p.set(id, (m) => { clearTimeout(t); res(m); }); this.ws.send(JSON.stringify({ id, method, params })); }); }
    async eval(expression, { awaitPromise = true, timeout = 600000 } = {}) {
        const r = await this.send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true, contextId: this.ctx }, timeout);
        if (r.error) throw new Error(JSON.stringify(r.error)); const res = r.result;
        if (res.exceptionDetails) throw new Error("page exception: " + JSON.stringify(res.exceptionDetails).slice(0, 500));
        return res.result.value;
    }
}
module.exports = { openSession, Cdp };
if (require.main === module) (async () => {
    const s = await openSession(); console.log("session", s.sid, "\ndebug url:", s.wsUrl);
    const c = await new Cdp(s.wsUrl).connect();
    console.log("typeof document:", await c.eval("typeof document"), "| typeof assembleEdit:", await c.eval("typeof assembleEdit"), "| typeof run:", await c.eval("typeof run"));
    console.log("title:", await c.eval("document.title || '(none)'"), "| output box text:", JSON.stringify(await c.eval("(document.getElementById('output')||{}).textContent")));
    s.u.close(); process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
