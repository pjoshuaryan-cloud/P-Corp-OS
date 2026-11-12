"""Copy only the shoot you're editing (2026-11-12): a card's files grouped by the day they were recorded, a preview before anything
copies, and a job that copies only the ticked days -- through the real create route and the real copy and verify code, on temp folders,
a temp database and a made-up token. Analysis is replaced by a stand-in.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python post_source_days_test.py"""
import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, post_db, post_ingest, post_sources  # noqa: E402

fails = 0
REAL_DB = post_db.DB_PATH


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def put(path: Path, size: int, day: str, hour: int = 12):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    t = time.mktime(datetime.strptime(f"{day} {hour:02d}:00", "%Y-%m-%d %H:%M").timetuple())
    os.utime(path, (t, t))


tmp = Path(tempfile.mkdtemp())
card = tmp / "card"
CLIP = "PRIVATE/M4ROOT/CLIP"
for n in range(3):
    put(card / CLIP / f"C30{29 + n}.MP4", 40_000, "2026-11-02")
    put(card / CLIP / f"C30{29 + n}M01.XML", 500, "2026-11-02")
for n in range(4):
    put(card / CLIP / f"JD_MIDLANDS_{3033 + n}.MP4", 60_000, "2026-11-09", hour=10 + n)
    put(card / CLIP / f"JD_MIDLANDS_{3033 + n}M01.XML", 500, "2026-11-09", hour=10 + n)
for n in range(5):
    put(card / "DCIM/100MSDCF" / f"JSH00{125 + n}.ARW", 30_000, "2026-10-24")
put(card / ".DS_Store", 10, "2026-11-09")
for n in range(4):
    put(card / "PRIVATE/M4ROOT/THMBNL" / f"JD_MIDLANDS_{3033 + n}T01.JPG", 300, "2026-11-09", hour=10 + n)

files = post_sources.scan_by_day(str(card))
check("every real file is read, junk left out", len(files) == 3 * 2 + 4 * 3 + 5, len(files))
days = post_sources.summarize_days(files)
check("grouped by recording day, newest first", [d["day"] for d in days] == ["2026-11-09", "2026-11-02", "2026-10-24"], [d["day"] for d in days])
jd = days[0]
check("a day counts its clips, photos and other files; the camera's clip thumbnails aren't photos", (jd["clips"], jd["photos"], jd["other"], jd["files"]) == (4, 0, 8, 12), jd)
check("and how big it is", jd["bytes"] == 4 * 60_000 + 4 * 500 + 4 * 300, jd["bytes"])
check("and its first and last clip", (jd["first_clip"], jd["last_clip"]) == ("JD_MIDLANDS_3033.MP4", "JD_MIDLANDS_3036.MP4"), jd)
check("photos are counted as photos", days[2]["photos"] == 5 and days[2]["clips"] == 0)
check("only the chosen days are kept", {f[3] for f in post_sources.only_days(files, ["2026-11-09"])} == {"2026-11-09"} and len(post_sources.only_days(files, ["2026-11-09"])) == 12)

# ---- the routes
post_db.DB_PATH = tmp / "post.db"
main.DATA_BACKEND = "sqlite"


async def no_audit(*a, **kw):
    return None
main.record_tool_call = no_audit
asyncio.run(post_db.init_post_db(None))
main.AUTH_TOKEN = "made-up"
T = {"token": "made-up"}
web = TestClient(main.app)
post_sources.same_drive = lambda a, b: False   # these temp folders are one disk; pretend the card is its own drive

preview = web.post("/post/sources/preview", params=T, json={"source_path": str(card)})
check("the preview lists what's on the card by day", preview.status_code == 200 and [d["day"] for d in preview.json()["days"]] == ["2026-11-09", "2026-11-02", "2026-10-24"], preview.text[:300])
check("and the totals", preview.json()["files"] == 23)
check("a card that isn't plugged in says so", web.post("/post/sources/preview", params=T, json={"source_path": str(tmp / "gone")}).status_code == 404)
check("the preview needs the token", web.post("/post/sources/preview", json={"source_path": str(card)}).status_code in (403, 422))

dest = tmp / "ssd"
dest.mkdir()
base = {"profile": "joshx", "source_path": str(card), "destination_volume_path": str(dest)}
made = web.post("/post/jobs", params=T, json={**base, "shoot_name": "JD Midlands", "recorded_on": ["2026-11-09"]})
check("a job for just the JD day is created", made.status_code == 200, made.text)
job_id = made.json()["id"]
listed = asyncio.run(post_db.list_post_job_files(job_id, postgres_conn=None))
check("before Start, the job already lists exactly that day's files", sorted(Path(f["relative_path"]).name for f in listed) == sorted(
    [f"JD_MIDLANDS_{3033 + n}.MP4" for n in range(4)] + [f"JD_MIDLANDS_{3033 + n}M01.XML" for n in range(4)] + [f"JD_MIDLANDS_{3033 + n}T01.JPG" for n in range(4)]), [f["relative_path"] for f in listed])
job = asyncio.run(post_db.get_post_job(job_id, None))
check("and shows their count and size", (job["total_files"], job["total_bytes"]) == (12, 4 * 60_000 + 4 * 500 + 4 * 300), (job.get("total_files"), job.get("total_bytes")))
check("its folders are made on the destination", (dest / "JD Midlands").is_dir())

nothing = web.post("/post/jobs", params=T, json={**base, "shoot_name": "Empty", "recorded_on": ["2025-01-01"]})
check("days with nothing on them are refused, with why", nothing.status_code == 400 and "recorded on the days" in nothing.json()["detail"], nothing.text)
check("a badly written day is refused", web.post("/post/jobs", params=T, json={**base, "shoot_name": "Bad", "recorded_on": ["9 Nov"]}).status_code == 400)


async def fake_analysis(job_id, conn=None, only_new=False):
    await post_db.update_post_job_media_analyzed(job_id, postgres_conn=conn)
post_ingest.run_media_analysis = fake_analysis
post_ingest.notify = lambda *a: None
asyncio.run(post_ingest.run_ingest_job(asyncio.run(post_db.get_post_job(job_id, None)), None))
copied = sorted(p.name for p in (dest / "JD Midlands").rglob("*") if p.is_file())
check("Start copies the JD day and nothing else", copied == sorted([f"JD_MIDLANDS_{3033 + n}.MP4" for n in range(4)] + [f"JD_MIDLANDS_{3033 + n}M01.XML" for n in range(4)] + [f"JD_MIDLANDS_{3033 + n}T01.JPG" for n in range(4)]), copied)
done = asyncio.run(post_db.get_post_job(job_id, None))
check("every copied file is verified", all(f["status"] == "verified" for f in asyncio.run(post_db.list_post_job_files(job_id, postgres_conn=None))), done.get("status"))
check("the card is untouched", len(post_sources.scan_by_day(str(card))) == 23)

everything = web.post("/post/jobs", params=T, json={**base, "shoot_name": "Whole card"})
check("without days, a job still copies everything, as before", everything.status_code == 200 and asyncio.run(post_db.list_post_job_files(everything.json()["id"], postgres_conn=None)) == [])
check("the real database was never touched", post_db.DB_PATH != REAL_DB)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
