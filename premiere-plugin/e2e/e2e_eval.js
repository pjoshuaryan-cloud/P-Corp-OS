// usage: node e2e_eval.js '<async JS expression body that returns a value>'  -- READ/DEBUG: evaluates inside the plugin in the real Premiere (fire + poll, because awaitPromise doesn't resolve) and prints the JSON result.
const { openSession, Cdp } = require("./udt_session.js");
(async () => {
    const body = process.argv[2];
    const s = await openSession(); const c = await new Cdp(s.wsUrl).connect();
    await c.eval(`window.__ev = null; (async () => { ${body} })().then((v) => { window.__ev = JSON.stringify(v === undefined ? null : v) || 'null'; }).catch((e) => { window.__ev = JSON.stringify({ error: String(e && e.message || e) }); }); true`, { awaitPromise: false });
    let out = null; for (let i = 0; i < 120 && !out; i++) { await new Promise((r) => setTimeout(r, 1000)); out = await c.eval("window.__ev"); }
    console.log(out ? JSON.stringify(JSON.parse(out), null, 1) : "TIMEOUT"); s.u.close(); process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
