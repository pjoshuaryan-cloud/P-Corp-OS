"""Tests for the one-flow shoot pipeline (backend/app/post_pipeline.py + the automatic analysis and notifications in post_ingest.py).
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python pipeline_test.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_ingest, post_pipeline  # noqa: E402
from app.post_pipeline import _minutes, describe_pipeline  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


def job(status, **kw):
    base = {"id": 1, "status": status, "shoot_name": "GWM", "total_files": 342, "total_bytes": 1000, "files_copied": 0, "bytes_copied": 0, "media_analyzed_at": None,
            "error_message": None, "estimated_remaining_seconds": None}
    return {**base, **kw}


def states(p):
    return [s["state"] for s in p["stages"]]


# ---- the description -----------------------------------------------------------------------------------------------------------------------
p = describe_pipeline(job("created"))
check("a shoot that hasn't started says so and has nothing active", states(p) == ["pending"] * 4 and p["percent"] == 0 and "Press Start" in p["headline"], p["headline"])
p = describe_pipeline(job("scanning"))
check("scanning: the first stage is active", states(p) == ["active", "pending", "pending", "pending"] and "Reading the drive" in p["headline"])
p = describe_pipeline(job("ingesting", files_copied=118, bytes_copied=350, estimated_remaining_seconds=5820))
check("copying shows real counts and a time left", states(p) == ["done", "active", "pending", "pending"] and "118 of 342" in p["headline"] and "about 1 h 35 min left" in p["headline"] and p["eta_seconds"] == 5820, p["headline"])
check("the percentage counts finished stages plus real progress inside the active one", p["percent"] == int(3 + 47 * 0.35), p["percent"])
p = describe_pipeline(job("verifying", files_copied=342, bytes_copied=1000), files_verified=90)
check("checking shows how many files are checked, and no invented time", states(p) == ["done", "done", "active", "pending"] and "90 of 342" in p["headline"] and p["eta_seconds"] is None, p["headline"])
p = describe_pipeline(job("verifying", files_copied=342, bytes_copied=1000))
check("checking with no count yet doesn't make one up", "of 342" not in p["headline"] and p["percent"] == 50, p["headline"])
p = describe_pipeline(job("analyzing_media", files_copied=342, bytes_copied=1000), analysis=(40, 342))
check("analysing shows the live count", states(p) == ["done", "done", "done", "active"] and "40 of 342" in p["headline"] and p["percent"] == int(85 + 15 * 40 / 342), (p["headline"], p["percent"]))
p = describe_pipeline(job("analyzing_media"))
check("analysing with no count yet just says it is working", p["headline"] == "Analysing the clips…" and p["percent"] == 85)
p = describe_pipeline(job("ingested", files_copied=342, bytes_copied=1000, media_analyzed_at="2026-10-20T10:00:00"))
check("a finished, analysed shoot is 100% and ready", states(p) == ["done"] * 4 and p["percent"] == 100 and p["headline"].startswith("Ready"), p["headline"])
p = describe_pipeline(job("ingested", files_copied=342, bytes_copied=1000))
check("a copied shoot that was never analysed points at the button, and is not 100%", states(p) == ["done", "done", "done", "pending"] and p["percent"] == 85 and "Analyze Media" in p["headline"], p["headline"])
p = describe_pipeline(job("premiere_project_created", files_copied=342, bytes_copied=1000, media_analyzed_at="x"))
check("later statuses (project created) still read as ready", p["percent"] == 100 and states(p) == ["done"] * 4)
p = describe_pipeline(job("ingest_failed", files_copied=200, bytes_copied=600, error_message="Not enough space on the destination drive"))
check("a copy that stopped marks the copy stage failed and says why", states(p) == ["done", "failed", "pending", "pending"] and p["needs_attention"] and "Not enough space" in p["headline"], states(p))
p = describe_pipeline(job("ingest_failed", total_files=0, total_bytes=0, error_message='The drive "Joshx SSD" isn\'t connected.'))
check("a failure before any file was read marks the first stage", states(p)[0] == "failed" and "isn't connected" in p["headline"])
p = describe_pipeline(job("ingest_failed", files_copied=342, bytes_copied=1000, error_message="2 file(s) failed to copy or verify."))
check("everything copied but the check failed marks the check stage", states(p) == ["done", "done", "failed", "pending"])
p = describe_pipeline(job("cancelled", files_copied=10, bytes_copied=20))
check("a cancelled shoot says cancelled", p["headline"] == "Cancelled." and not p["needs_attention"])
order = [describe_pipeline(job("scanning")), describe_pipeline(job("ingesting", bytes_copied=500, files_copied=100)), describe_pipeline(job("ingesting", bytes_copied=1000, files_copied=342)),
         describe_pipeline(job("verifying"), files_verified=170), describe_pipeline(job("analyzing_media"), analysis=(100, 342)),
         describe_pipeline(job("ingested", media_analyzed_at="x"))]
pct = [x["percent"] for x in order]
check("the percentage only ever goes up through the run, and reaches 100 only at the end", pct == sorted(pct) and pct[-1] == 100 and all(x < 100 for x in pct[:-1]), pct)
check("times read plainly", (_minutes(40), _minutes(600), _minutes(5400), _minutes(5820), _minutes(7200)) == ("about a minute", "about 10 min", "about 1 h 30 min", "about 1 h 35 min", "about 2 h"), (_minutes(40), _minutes(600), _minutes(5400), _minutes(5820), _minutes(7200)))

# ---- why Plan Edit is greyed out --------------------------------------------------------------------------------------------------------------
blocker = lambda status, analysed=False: describe_pipeline(job(status, media_analyzed_at="x" if analysed else None))["plan_edit_blocker"]
check("Plan Edit is open on a copied and analysed shoot", blocker("ingested", True) is None and blocker("premiere_project_created", True) is None and blocker("complete", True) is None)
check("before Start it says to press Start", "Press Start" in blocker("created"), blocker("created"))
check("while the shoot is running it says it unlocks when copy, check and analysis are done", all("copied, checked and analysed" in blocker(st) for st in ("scanning", "ready", "ingesting", "verifying", "analyzing_media")))
check("a copied shoot that was never analysed says to press Analyze Media", "Analyze Media" in blocker("ingested", False), blocker("ingested", False))
check("a failed copy says to press Retry", "Retry" in blocker("ingest_failed") and "stopped" in blocker("ingest_failed"))
check("a cancelled shoot says to press Retry", "cancelled" in blocker("cancelled") and "Retry" in blocker("cancelled"))
check("while proxies or highlights are being made it says what it is waiting for", "proxies" in blocker("generating_proxies", True) and "highlight" in blocker("analyzing_color", True))
check("every blocker is a sentence that says what to do or wait for (never empty)", all(blocker(st, a) for st in ("created", "scanning", "ready", "ingesting", "verifying", "analyzing_media", "ingest_failed", "cancelled") for a in (True, False)))

# ---- the automatic flow in the ingest worker (everything below it replaced by fakes) ------------------------------------------------------
notes: list[tuple[str, str]] = []
log: list[str] = []


def run_flow(*, verify_outcome="ingested", analysis_raises=False, start="verifying", auto=True):
    db = {"id": 1, "status": start, "shoot_name": "GWM", "total_files": 5, "media_analyzed_at": None, "error_message": None, "premiere_project_path": None}
    notes.clear(); log.clear()

    async def reload(job_id, conn):
        return dict(db)

    async def update(job_id, status, *, from_statuses=None, error_message=None, postgres_conn=None):
        if from_statuses is not None and db["status"] not in from_statuses:
            return False
        db["status"] = status
        if error_message:
            db["error_message"] = error_message
        return True

    async def verify(job_id, conn):
        db["status"] = verify_outcome
        if verify_outcome == "ingest_failed":
            db["error_message"] = "2 file(s) failed to copy or verify."
        log.append("verify")

    async def analyse(job_id, conn):
        log.append("analyse")
        if analysis_raises:
            raise RuntimeError("ffprobe fell over")
        db["media_analyzed_at"] = "now"

    saved = {n: getattr(post_ingest, n) for n in ("_reload", "update_post_job_status", "_run_verify_phase", "run_media_analysis", "notify", "AUTO_ANALYSE_AFTER_INGEST")}
    post_ingest._reload, post_ingest.update_post_job_status, post_ingest._run_verify_phase = reload, update, verify
    post_ingest.run_media_analysis, post_ingest.notify, post_ingest.AUTO_ANALYSE_AFTER_INGEST = analyse, lambda t, b: notes.append((t, b)), auto
    try:
        asyncio.run(post_ingest.run_ingest_job(dict(db), None))
    finally:
        for n, v in saved.items():
            setattr(post_ingest, n, v)
    return db


db = run_flow()
check("a clean copy goes straight on to the analysis", log == ["verify", "analyse"] and db["status"] == "ingested" and db["media_analyzed_at"] == "now", (log, db["status"]))
check("and a notification says the shoot is ready", len(notes) == 1 and "GWM is ready" in notes[0][0] and "5 files" in notes[0][1], notes)
db = run_flow(verify_outcome="ingest_failed")
check("a copy that fails the check does not start the analysis", log == ["verify"] and db["status"] == "ingest_failed" and db["media_analyzed_at"] is None, log)
check("and the notification says it needs attention, with the reason", len(notes) == 1 and "needs attention" in notes[0][0] and "failed to copy or verify" in notes[0][1], notes)
db = run_flow(analysis_raises=True)
check("an analysis that falls over leaves the shoot copied and usable (status back to ingested)", db["status"] == "ingested" and db["media_analyzed_at"] is None, db["status"])
check("and the notification says the copy is safe and how to run the analysis again", len(notes) == 1 and "is copied" in notes[0][0] and "Analyze Media" in notes[0][1] and not any("ready" in n[0] for n in notes), notes)
db = run_flow(auto=False)
check("with the automatic step switched off the old manual gate is back (no analysis, no notification)", log == ["verify"] and db["status"] == "ingested" and notes == [], (log, notes))
db = run_flow(start="analyzing_media")
check("pressing Analyze Media by hand re-runs only the analysis, with no 'ready' pop-up", log == ["analyse"] and db["status"] == "ingested" and notes == [], (log, notes))

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
