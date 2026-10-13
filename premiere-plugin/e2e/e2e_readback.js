// READ-ONLY readback from the real Premiere: for the newest "- Edit" sequence of the ACTIVE project, count items per video track and how many are disabled; look for the .srt in the project.
const { openSession, Cdp } = require("./udt_session.js");
(async () => {
    const s = await openSession(); const c = await new Cdp(s.wsUrl).connect();
    await c.eval(`window.__rb = null; (async () => {
        try {
            const p = await ppro.Project.getActiveProject(); if (!p) return { error: "no active project" };
            const seqs = await p.getSequences(); let seq = null; const all = [];
            for (const q of seqs) { all.push(String(q.name)); if (/ - Edit /.test(String(q.name))) seq = q; }
            if (!seq) return { error: "no edit sequence", sequences: all, project: String(p.path) };
            const n = await seq.getVideoTrackCount(); const tracks = [];
            for (let i = 0; i < n; i++) {
                const t = await seq.getVideoTrack(i);
                const items = await t.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
                let disabled = 0; for (const it of items) { try { if (await it.isDisabled()) disabled++; } catch (e) {} }
                tracks.push({ track: "V" + (i + 1), items: items.length, disabled });
            }
            const root = await p.getRootItem(); const srt = [];
            const walk = async (f, d) => { for (const it of await f.getItems()) { const nm = String(it.name); if (/\\.srt$/i.test(nm)) srt.push(nm); const folder = ppro.FolderItem.cast(it); if (folder && d < 4) await walk(folder, d + 1); } };
            await walk(root, 0);
            return { project: String(p.path), sequence: String(seq.name), sequences: all, tracks, srtItemsInProject: srt };
        } catch (e) { return { error: String(e && e.message || e) }; }
    })().then((v) => { window.__rb = JSON.stringify(v); }).catch((e) => { window.__rb = JSON.stringify({ error: String(e) }); }); true`, { awaitPromise: false });
    let out = null; for (let i = 0; i < 60 && !out; i++) { await new Promise((r) => setTimeout(r, 1000)); out = await c.eval('window.__rb'); }
    console.log(typeof out, out ? JSON.stringify(JSON.parse(out), null, 1) : 'TIMEOUT'); s.u.close(); process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
