// Exports still frames from the newest "- Edit" sequence in Premiere's ACTIVE project at the given times (does not modify the project).
const fs = require("fs"); const { openSession, Cdp } = require("./udt_session.js");
const [planPath, outDir, ...labels] = process.argv.slice(2);
const plan = JSON.parse(fs.readFileSync(planPath, "utf8")); const fps = plan.fps;
const sh = plan.shots; const body = sh.filter((s) => s.role === "body"); const m = Math.floor(body.length / 2);
const at = { opener: (sh[0].start_frame + sh[0].duration_frames / 2) / fps, early: (body[0].start_frame + 20) / fps, mid: (body[m].start_frame + body[m].duration_frames / 2) / fps,
  late: (body[body.length - 1].start_frame + 15) / fps, closer: (sh[sh.length - 1].start_frame + sh[sh.length - 1].duration_frames / 2) / fps, closer_end: (plan.duration_frames - 6) / fps };
(async () => {
    const s = await openSession(); const c = await new Cdp(s.wsUrl).connect();
    const shotTime = (k) => { const m = /^s(\d+)$/.exec(k); if (!m) return at[k]; const s = sh[Number(m[1]) - 1]; return (s.start_frame + s.duration_frames / 2) / fps; };
    const times = (labels.length ? labels : Object.keys(at)).map((k) => [k, shotTime(k)]);
    const res = await c.eval(`(async () => {
        const p = await ppro.Project.getActiveProject(); const seqs = await p.getSequences(); let seq = null;
        for (const q of seqs) { if (/ - Edit /.test(String(q.name))) seq = q; }
        if (!seq) return { error: "no '- Edit' sequence in the active project", have: seqs.map((q) => String(q.name)) };
        const out = []; const size = await seq.getFrameSize();
        for (const [label, t] of ${JSON.stringify(times)}) {
            try { const ok = await ppro.Exporter.exportSequenceFrame(seq, ppro.TickTime.createWithSeconds(t), "frame_" + label + ".png", ${JSON.stringify(outDir)} + "/", 1280, 720); out.push([label, Math.round(t * 100) / 100, ok]); }
            catch (e) { out.push([label, t, "ERROR " + (e && e.message || e)]); }
        }
        return { sequence: String(seq.name), frame: [size.width, size.height], out };
    })()`, { timeout: 180000 });
    console.log(JSON.stringify(res)); s.u.close(); process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
