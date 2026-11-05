"""Several cards in one shoot, and the same-drive check (backend/app/post_ingest.py, post_db.py, main.py). Real files and the real copy and verify code, on temp folders and a temp database. Analysis is a
stand-in here because the files aren't video; real clips went through it separately. Set ON_SET_TEST_PG_DSN to a throwaway Postgres to also run the database part there.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python multi_card_test.py"""
import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, post_db, post_ingest, post_media, post_sources  # noqa: E402

fails = 0
REAL_DB = post_db.DB_PATH
CLIP = "PRIVATE/M4ROOT/CLIP"


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def card(folder, clips):
    """A fake card: {file name: bytes}, laid out as a Sony card is."""
    for name, data in clips.items():
        path = folder / CLIP / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (folder / "PRIVATE/M4ROOT/MEDIAPRO.XML").write_bytes(b"<index>" + os.urandom(40) + b"</index>")   # a camera's index changes every time
    return str(folder)


def blob(seed, size):
    return hashlib.sha256(seed.encode()).digest() * (size // 32 + 1)


async def database(conn, label):
    await post_db.init_post_db(conn)
    job = await post_db.create_post_job("joshx", f"Shoot {label}", "/Volumes/A", "/Volumes/SSD/Shoot", postgres_conn=conn)
    await post_db.create_post_job_files_batch(job, [("a.MP4", "/Volumes/SSD/Shoot/_INGESTED/a.MP4", 100)], postgres_conn=conn)
    check(f"{label}: a card can't join a shoot that hasn't finished copying", not await post_db.add_post_job_card(job, "/Volumes/B", "B", "u2", [("a.MP4", "/x/Card 2/a.MP4", 5)], postgres_conn=conn))
    check(f"{label}: and that refusal adds nothing", len(await post_db.list_post_job_files(job, postgres_conn=conn)) == 1)
    await post_db.update_post_job_status(job, "ingested", postgres_conn=conn)
    check(f"{label}: a copied shoot can take one", await post_db.add_post_job_card(job, "/Volumes/B", "B", "u2", [("a.MP4", "/x/Card 2/a.MP4", 5), ("b.MP4", "/x/Card 2/b.MP4", 7)], postgres_conn=conn))
    row = await post_db.get_post_job(job, conn)
    check(f"{label}: the job now reads from that card and goes back to copying", row["source_path"] == "/Volumes/B" and row["source_volume_uuid"] == "u2" and row["status"] == "ready" and row["media_analyzed_at"] is None, row)
    files = await post_db.list_post_job_files(job, postgres_conn=conn)
    check(f"{label}: both cards' files are in it, with one name twice", len(files) == 3 and [f["relative_path"] for f in files].count("a.MP4") == 2)
    check(f"{label}: stopped with nothing safe, it can't carry on without the rest", not await post_db.skip_unfinished_post_job_files(job, postgres_conn=conn))
    await post_db.update_post_job_status(job, "ingest_failed", postgres_conn=conn)
    check(f"{label}: and still can't with nothing verified", not await post_db.skip_unfinished_post_job_files(job, postgres_conn=conn))
    verified = files[0]["id"]
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE post.job_files SET verified_at = '2026-11-05', status = 'verified' WHERE id = %s", (verified,))
        await conn.commit()
    else:
        import aiosqlite
        async with aiosqlite.connect(post_db.DB_PATH) as db:
            await db.execute("UPDATE post_job_files SET verified_at = '2026-11-05', status = 'verified' WHERE id = ?", (verified,))
            await db.commit()
    check(f"{label}: with a file safe, it can", await post_db.skip_unfinished_post_job_files(job, postgres_conn=conn))
    row = await post_db.get_post_job(job, conn)
    kept = await post_db.list_post_job_files(job, postgres_conn=conn)
    check(f"{label}: only the safe file is left, and the totals say so", [f["id"] for f in kept] == [verified] and row["total_files"] == 1 and row["total_bytes"] == 100 and row["files_failed"] == 0 and row["status"] == "analyzing_media", row)
    check(f"{label}: it can't be done twice", not await post_db.skip_unfinished_post_job_files(job, postgres_conn=conn))
    await post_db.delete_post_job(job, conn)


async def postgres(dsn):
    import psycopg
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await database(conn, "postgres")


def main_tests():
    tmp = Path(tempfile.mkdtemp())
    post_db.DB_PATH = tmp / "post.db"
    main.DATA_BACKEND = "sqlite"   # no real database, whatever this Mac's settings say

    async def no_audit(*a, **kw):
        return None
    main.record_tool_call = no_audit
    asyncio.run(database(None, "sqlite"))
    if os.environ.get("ON_SET_TEST_PG_DSN"):
        asyncio.run(postgres(os.environ["ON_SET_TEST_PG_DSN"]))
    else:
        print("SKIP postgres: ON_SET_TEST_PG_DSN isn't set")
    post_db.DB_PATH = tmp / "post2.db"
    asyncio.run(post_db.init_post_db(None))

    # ---- the same-drive check, with the real device lookup
    here = tmp / "same"
    (here / "footage").mkdir(parents=True)
    check("a folder on a drive counts as being on that drive", post_sources.same_drive(str(here / "footage"), str(tmp)))
    check("two different devices aren't the same drive", not post_sources.same_drive(str(tmp), "/dev"))
    check("a drive that isn't there isn't the same drive", not post_sources.same_drive(str(tmp), "/Volumes/not-a-real-drive"))

    main.AUTH_TOKEN = "made-up"
    T = {"token": "made-up"}
    web = TestClient(main.app)
    plain = {"profile": "joshx", "shoot_name": "Same", "source_path": str(here / "footage"), "destination_volume_path": str(tmp)}
    refused = web.post("/post/jobs", params=T, json=plain)
    check("the source and destination being one drive is refused", refused.status_code == 400 and "same drive" in refused.json()["detail"], refused.text)
    check("a folder there can go anyway, if asked for", web.post("/post/jobs", params=T, json={**plain, "allow_same_drive": True}).status_code == 200)
    whole = web.post("/post/jobs", params=T, json={**plain, "source_path": str(tmp), "allow_same_drive": True})
    check("a whole drive into itself is refused, even if asked for", whole.status_code == 400 and "into itself" in whole.json()["detail"], whole.text)
    assert "made-up" not in refused.text

    # ---- everything else pretends the cards are on other drives, since these temp folders aren't
    real_same = post_sources.same_drive
    post_sources.same_drive = lambda a, b: False
    analysed = []

    async def fake_analysis(job_id, conn=None, only_new=False):
        files = await post_db.list_post_job_files(job_id, postgres_conn=conn)
        done = {m["file_id"] for m in await post_db.list_post_job_file_metadata(job_id, postgres_conn=conn)}
        todo = [f for f in files if f["id"] not in done] if only_new else files
        analysed.append(len(todo))
        await post_db.create_post_job_file_metadata_batch([{"file_id": f["id"], "media_type": "video", "duration_seconds": 8.0} for f in todo], postgres_conn=conn)
        await post_db.update_post_job_media_analyzed(job_id, postgres_conn=conn)
    post_ingest.run_media_analysis = fake_analysis
    post_ingest.notify = lambda *a: None

    def run(job_id):
        asyncio.run(post_ingest.run_ingest_job(asyncio.run(post_db.get_post_job(job_id, None)), None))
        return asyncio.run(post_db.get_post_job(job_id, None))

    MB = 1024 * 1024
    a1, a2, b1, b2 = blob("a1", 6 * MB), blob("a2", 6 * MB), blob("b1", 6 * MB), blob("b2", 7 * MB)
    ssd = tmp / "SSD"
    ssd.mkdir()
    card_a = card(tmp / "cardA", {"C0001.MP4": a1, "C0002.MP4": a2})
    card_b = card(tmp / "cardB", {"C0001.MP4": b1, "C0002.MP4": b2})
    made = web.post("/post/jobs", params=T, json={"profile": "joshx", "shoot_name": "JD", "source_path": card_a, "destination_volume_path": str(ssd), "source_volume_uuid": "uuid-a"})
    jid = made.json()["id"]
    too_early = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_b})
    check("a card can't be added before the first has copied", too_early.status_code == 409, too_early.text)
    web.post(f"/post/jobs/{jid}/start", params=T)
    job = run(jid)
    dest = Path(job["destination_root"]) / "_INGESTED"
    check("the first card copies as it always has, straight into _INGESTED", job["status"] == "ingested" and (dest / CLIP / "C0001.MP4").read_bytes() == a1 and analysed == [3], (job["status"], analysed))

    # ---- the second card
    added = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_b, "source_volume_name": "Untitled", "source_volume_uuid": "uuid-b"})
    check("a second card joins the shoot", added.status_code == 200 and added.json() == {"added": 3, "already": 0, "folder": "Card 2"}, added.text)
    busy = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_a})
    check("no third while it's copying", busy.status_code == 409, busy.text)
    job = run(jid)
    check("it copies, checks and is analysed by itself", job["status"] == "ingested" and job["media_analyzed_at"] is not None, job["status"])
    check("only its own files get analysed", analysed == [3, 3], analysed)
    check("same-named clips sit side by side, each with its own card's bytes", (dest / CLIP / "C0001.MP4").read_bytes() == a1 and (dest / "Card 2" / CLIP / "C0001.MP4").read_bytes() == b1 and (dest / "Card 2" / CLIP / "C0002.MP4").read_bytes() == b2)
    check("the first card's copy wasn't touched", (dest / CLIP / "C0002.MP4").read_bytes() == a2)
    files = web.get(f"/post/jobs/{jid}/files", params=T).json()["files"]
    check("every file is verified, against the original's checksum", all(f["status"] == "verified" and f["source_checksum"] == f["destination_checksum"] for f in files) and len(files) == 6, [f["status"] for f in files])
    check("the totals cover both cards", job["total_files"] == 6 and job["files_copied"] == 6 and job["files_failed"] == 0 and job["total_bytes"] == sum(f["size_bytes"] for f in files) and job["bytes_copied"] == job["total_bytes"], {k: job[k] for k in ("total_files", "files_copied", "total_bytes", "bytes_copied")})
    shown = [f["relative_path"] for f in files]
    check("the file list says which card each is from", f"{CLIP}/C0001.MP4" in shown and f"Card 2/{CLIP}/C0001.MP4" in shown, shown)
    row = next(f for f in asyncio.run(post_db.list_post_job_files(jid, None)) if f["destination_path"].endswith(f"Card 2/{CLIP}/C0001.MP4"))
    check("a proxy of a later card's clip can't overwrite the first card's", post_media.shown_path(row) == f"Card 2/{CLIP}/C0001.MP4")
    check("an old job with no _INGESTED folder keeps its path", post_media.shown_path({"relative_path": "x/a.MP4", "destination_path": "/y/a.MP4"}) == "x/a.MP4")

    # ---- the same card twice
    again = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_b})
    check("the same card again is refused, even though its index file changed", again.status_code == 400 and "already in this shoot" in again.json()["detail"], again.text)
    first_again = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_a})
    check("so is the first card", first_again.status_code == 400 and "already in this shoot" in first_again.json()["detail"], first_again.text)
    check("and nothing changed", asyncio.run(post_db.get_post_job(jid, None))["status"] == "ingested" and len(web.get(f"/post/jobs/{jid}/files", params=T).json()["files"]) == 6)

    # ---- the same card, with more on it
    a3 = blob("a3", 6 * MB)
    card(tmp / "cardA", {"C0003.MP4": a3})
    more = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_a, "source_volume_uuid": "uuid-a"})
    check("a card with new clips copies only what's new", more.status_code == 200 and more.json()["folder"] == "Card 3" and more.json()["already"] == 2 and more.json()["added"] == 2, more.text)
    job = run(jid)
    check("so no clip is on the drive twice", (dest / "Card 3" / CLIP / "C0003.MP4").read_bytes() == a3 and not (dest / "Card 3" / CLIP / "C0001.MP4").exists() and job["status"] == "ingested", job["status"])

    # ---- same name, same size, different clip: the one that must never be skipped
    end_differs = bytearray(a1)
    end_differs[-1] ^= 0xFF
    middle_differs = bytearray(a1)
    middle_differs[len(a1) // 2] ^= 0xFF
    start_differs = bytearray(a1)
    start_differs[0] ^= 0xFF
    card_c = card(tmp / "cardC", {"C0001.MP4": bytes(end_differs)})
    close = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_c})
    check("a clip with the same name and size but different bytes at the end is copied", close.status_code == 200 and close.json()["added"] == 2 and close.json()["already"] == 0, close.text)
    job = run(jid)
    check("into its own folder", (dest / "Card 4" / CLIP / "C0001.MP4").read_bytes() == bytes(end_differs))
    source, copy = tmp / "s.bin", tmp / "d.bin"
    copy.write_bytes(a1)
    for label, data in (("start", start_differs), ("middle", middle_differs)):
        source.write_bytes(bytes(data))
        check(f"different bytes at the {label} count as a different clip", not post_ingest._same_file(str(source), str(copy), len(a1)))
    source.write_bytes(a1)
    check("the same bytes count as the same clip", post_ingest._same_file(str(source), str(copy), len(a1)))
    check("an unreadable copy doesn't count as the same", not post_ingest._same_file(str(source), str(tmp / "missing"), len(a1)))
    small_a, small_b = tmp / "sa", tmp / "sb"
    small_a.write_bytes(b"x" * 10 + b"y")
    small_b.write_bytes(b"x" * 10 + b"z")
    check("a small file is compared whole", not post_ingest._same_file(str(small_a), str(small_b), 11))
    empty_a, empty_b = tmp / "ea", tmp / "eb"
    empty_a.write_bytes(b"")
    empty_b.write_bytes(b"")
    check("two empty files are the same", post_ingest._same_file(str(empty_a), str(empty_b), 0))

    # ---- no room
    keep_usage = post_ingest.shutil.disk_usage
    post_ingest.shutil.disk_usage = lambda p: type("U", (), {"free": 10 * MB})()
    card_d = card(tmp / "cardD", {"C0009.MP4": blob("d", 6 * MB)})
    before = len(web.get(f"/post/jobs/{jid}/files", params=T).json()["files"])
    full = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_d})
    post_ingest.shutil.disk_usage = keep_usage
    check("with no room it's refused up front, saying so", full.status_code == 400 and "Not enough space" in full.json()["detail"] and "add the card again" in full.json()["detail"], full.text)
    check("and the shoot is left as it was", len(web.get(f"/post/jobs/{jid}/files", params=T).json()["files"]) == before and asyncio.run(post_db.get_post_job(jid, None))["status"] == "ingested")

    # ---- refusals
    check("a card that isn't connected is refused", web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": str(tmp / "nope")}).status_code == 400)
    empty = tmp / "emptycard"
    empty.mkdir()
    check("a card with nothing on it is refused", "No files" in web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": str(empty)}).json()["detail"])
    post_sources.same_drive = lambda a, b: True
    on_ssd = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_d})
    post_sources.same_drive = lambda a, b: False
    check("the shoot's own drive can't be added as a card", on_ssd.status_code == 400 and "twice" in on_ssd.json()["detail"], on_ssd.text)
    check("adding a card needs the main token", web.post(f"/post/jobs/{jid}/add-card", params={"token": "wrong"}, json={"source_path": card_d}).status_code == 403)
    check("so does carrying on without files", web.post(f"/post/jobs/{jid}/skip-unfinished", params={"token": "wrong"}).status_code == 403)
    check("a job that doesn't exist says so", web.post("/post/jobs/999999/add-card", params=T, json={"source_path": card_d}).status_code == 404)

    # ---- the card pulled out, or the wrong one put back
    big = blob("e", 9 * MB)
    card_e = card(tmp / "cardE", {"C0001.MP4": big, "C0002.MP4": blob("e2", 8 * MB)})
    fresh = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_e})
    check("another card goes in", fresh.status_code == 200, fresh.text)
    folder = fresh.json()["folder"]
    (tmp / "cardE" / CLIP / "C0001.MP4").write_bytes(blob("other camera", 5 * MB))
    job = run(jid)
    check("a clip that isn't the size it was when scanned isn't copied", job["status"] == "ingest_failed" and not (dest / folder / CLIP / "C0001.MP4").exists(), job["status"])
    failed = [f for f in asyncio.run(post_db.list_post_job_files(jid, None)) if f["status"] == "failed"]
    check("and it says why", len(failed) == 1 and "right card" in failed[0]["error_message"], [f["error_message"] for f in failed])
    check("other cards aren't blocked from being safe", (dest / CLIP / "C0001.MP4").read_bytes() == a1)
    check("a stopped shoot can't take another card yet", web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_d}).status_code == 409)
    (tmp / "cardE" / CLIP / "C0001.MP4").write_bytes(big)
    web.post(f"/post/jobs/{jid}/start", params=T)
    job = run(jid)
    check("with the right card back, Retry finishes only what's left", job["status"] == "ingested" and (dest / folder / CLIP / "C0001.MP4").read_bytes() == big, (job["status"], job["error_message"]))

    # ---- which card is in: a real lookup is tried separately, since it needs a real drive
    real_info = post_ingest._diskutil_info_plist
    async def info_for(uuid):
        async def fake(path):
            fake.asked = path
            return None if uuid is None else {"VolumeUUID": uuid}
        post_ingest._diskutil_info_plist = fake
        return fake
    job_on_card = {"source_path": "/Volumes/Untitled/DCIM", "source_volume_uuid": "right"}
    asyncio.run(info_for("right"))
    check("the right card passes", asyncio.run(post_ingest.source_card_problem(job_on_card)) is None)
    asyncio.run(info_for("other"))
    check("another card under the same name doesn't", "different card" in (asyncio.run(post_ingest.source_card_problem(job_on_card)) or ""))
    asyncio.run(info_for(None))
    check("no card says to put it back", "isn't connected" in (asyncio.run(post_ingest.source_card_problem(job_on_card)) or ""))
    fake_probe = asyncio.run(info_for("right"))
    asyncio.run(post_ingest.source_card_problem(job_on_card))
    check("it asks about the drive, even when the source is a folder on it", fake_probe.asked == "/Volumes/Untitled")
    check("a job with no recorded id isn't blocked", asyncio.run(post_ingest.source_card_problem({"source_path": "/Volumes/Untitled"})) is None)
    check("nor one whose source isn't a drive", asyncio.run(post_ingest.source_card_problem({"source_path": "/tmp/x", "source_volume_uuid": "right"})) is None)
    post_ingest._diskutil_info_plist = real_info

    # ---- carrying on without a bad card
    card_f = card(tmp / "cardF", {"C0001.MP4": blob("f", 6 * MB)})
    bad = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_f})
    folder = bad.json()["folder"]
    (tmp / "cardF" / CLIP / "C0001.MP4").unlink()
    job = run(jid)
    check("a card that fails stops the shoot", job["status"] == "ingest_failed", job["status"])
    count = job["total_files"]
    skipped = web.post(f"/post/jobs/{jid}/skip-unfinished", params=T)
    job = asyncio.run(post_db.get_post_job(jid, None))
    check("it can carry on without what didn't copy", skipped.status_code == 200 and job["status"] == "analyzing_media" and job["total_files"] < count and job["files_failed"] == 0, job["status"])
    still = [f for f in web.get(f"/post/jobs/{jid}/files", params=T).json()["files"]]
    check("what's already safe stays", any(f["relative_path"] == f"{CLIP}/C0001.MP4" for f in still) and all(f["status"] == "verified" or f["relative_path"].startswith(folder) for f in still))
    job = run(jid)
    check("and it comes back ready", job["status"] == "ingested" and job["media_analyzed_at"] is not None, job["status"])

    # ---- the project
    check("the project gets made", asyncio.run(post_db.update_post_job_premiere_project(jid, "/x/JD.prproj", None)))
    late = web.post(f"/post/jobs/{jid}/add-card", params=T, json={"source_path": card_d})
    check("once the Premiere project exists, a card is refused, saying why", late.status_code == 409 and "Prepare POST Project" in late.json()["detail"], late.text)

    post_sources.same_drive = real_same
    check("nothing landed in the real database", post_db.DB_PATH != REAL_DB)


main_tests()
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
