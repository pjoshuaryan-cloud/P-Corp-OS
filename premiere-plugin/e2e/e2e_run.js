// usage: node e2e_run.js <plugin function name> [max seconds]   -- runs it INSIDE the real Premiere via the UXP developer service and streams the panel output.
const { execFileSync } = require("child_process");
const { openSession, Cdp } = require("./udt_session.js");
const fn = process.argv[2], maxSec = Number(process.argv[3] || 900);
const token = execFileSync("/Users/joshuapeters/Desktop/P-Corp/backend/.venv/bin/python", ["-I", "-c", "import sys; sys.path.insert(0,'/Users/joshuapeters/Desktop/P-Corp/backend'); from app.auth import get_or_create_token; print(get_or_create_token(), end='')"]).toString();
(async () => {
    const s = await openSession(); const c = await new Cdp(s.wsUrl).connect();
    if (!(await c.eval("!!getStoredToken()"))) { await c.eval(`setStoredToken(${JSON.stringify(token)}); true`); console.log("(saved the token into the plugin's storage)"); } else console.log("(the plugin already has a token)");
    await c.eval("document.getElementById('output').textContent = ''; window.__e2e = 'running'; true");
    await c.eval(`${fn}().then(() => { window.__e2e = 'done'; }).catch((e) => { window.__e2e = 'ERROR ' + (e && e.message || e); }); true`, { awaitPromise: false });
    let shown = 0; const t0 = Date.now(); let state = "running";
    while (Date.now() - t0 < maxSec * 1000) {
        await new Promise((r) => setTimeout(r, 2000));
        const out = await c.eval("document.getElementById('output').textContent"); state = await c.eval("window.__e2e");
        if (out.length > shown) { process.stdout.write(out.slice(shown)); shown = out.length; }
        if (state !== "running") break;
    }
    const out = await c.eval("document.getElementById('output').textContent"); if (out.length > shown) process.stdout.write(out.slice(shown));
    console.log(`\n--- ${fn}() finished: ${state} after ${Math.round((Date.now() - t0) / 1000)} s`);
    s.u.close(); process.exit(state === "done" ? 0 : 2);
})().catch((e) => { console.log("RUNNER ERROR:", e.message); process.exit(1); });
