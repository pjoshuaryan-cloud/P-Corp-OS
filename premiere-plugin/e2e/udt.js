// Minimal client for the UXP Developer Tools service (ws://localhost:14001/socket/cli): find Premiere, load/reload the plugin, run code in it via CDP.
const ws0 = () => new WebSocket("ws://localhost:14001/socket/cli");
class Udt {
    constructor() { this.clients = []; this.pending = new Map(); this.id = 0; this.events = []; }
    async connect() {
        this.ws = ws0();
        this.ws.onmessage = (ev) => {
            let m; try { m = JSON.parse(ev.data); } catch { return; }
            if (m.requestId && this.pending.has(m.requestId)) { this.pending.get(m.requestId)(m); this.pending.delete(m.requestId); return; }
            this.events.push(m);
            if (m.command === "didAddRuntimeClient") this.clients.push(m.client || m);
            if (m.command === "didRemoveRuntimeClient") this.clients = this.clients.filter((c) => (c.id || c.clientId) !== ((m.client || m).id || m.clientId));
        };
        await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error("can't reach the UXP service on 14001")); });
        await new Promise((r) => setTimeout(r, 1500));
        return this;
    }
    req(obj, timeout = 20000) {
        return new Promise((resolve, reject) => {
            obj.requestId = ++this.id; const t = setTimeout(() => { this.pending.delete(obj.requestId); reject(new Error("timeout: " + JSON.stringify(obj).slice(0, 120))); }, timeout);
            this.pending.set(obj.requestId, (m) => { clearTimeout(t); resolve(m); }); this.ws.send(JSON.stringify(obj));
        });
    }
    proxy(clientId, message, timeout) { return this.req({ command: "proxy", clientId, message }, timeout); }
    close() { try { this.ws.close(); } catch {} }
}
module.exports = { Udt };
if (require.main === module) (async () => {
    const u = await new Udt().connect();
    console.log("events after connect:", JSON.stringify(u.events).slice(0, 1200));
    console.log("runtime clients:", JSON.stringify(u.clients).slice(0, 800));
    u.close(); process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
