"""The Shoot Log (backend/app/post_shoot_log.py and its routes): its rules, his choices winning over Claude's, what goes to Premiere, and a whole run on tiny real clips made here with
ffmpeg, with a stand-in for Claude. No drive, no API call, no Premiere, and nothing under backend/data is touched. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python shoot_log_test.py"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, post_media, post_moments, post_shoot_log as sl, post_steady  # noqa: E402
from learning import transfer_cut  # noqa: E402

fails = 0
REAL_DATA = sl.DATA


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def series(luma=0.4, sharp=0.008, jerk=0.0, seconds=8, seed=0, levels=None):
    n = seconds * 8
    pic = (np.random.default_rng(seed).random((post_steady.THUMB_H, post_steady.THUMB_W)) * 0.3 + luma - 0.15).clip(0, 1)
    thumbs = np.repeat((pic * 255).astype(np.uint8)[None], seconds, axis=0)
    m = {"fps": 8.0, "luma": [luma] * n, "sharp": [sharp] * n, "motion": [0.02 + (jerk if i % 2 else 0.0) for i in range(n)], "hi": [0.0] * n, "spikes": [], "seconds": float(seconds),
         "thumbs": base64.b64encode(thumbs.tobytes()).decode("ascii"), "thumb_n": seconds}
    if levels:
        m["levels"] = levels
    return m


def good_tags(**kw):
    return {"shot_size": "wide", "subjects": ["product", "talent"], "energy": "peak", "camera_move": "handheld", "vertical_crop_ok": True, "description": "Bottle held up", "quality_note": "", **kw}


# ---- words in Premiere ----------------------------------------------------------------------------------------------------------------------------------------
tokens = [sl.token_for("shot_size", v) for v in sl.VOCAB["shot_size"]] + [sl.token_for("subjects", v) for v in sl.VOCAB["subjects"]] + [sl.token_for("energy", v) for v in sl.VOCAB["energy"]] + [sl.token_for("camera_move", v) for v in sl.VOCAB["camera_move"]]
check("no tag word sits inside another, because Premiere's search matches parts of words", not [(a, b) for a in tokens for b in tokens if a != b and a in b])
check("every tag is one unbroken word, because real Premiere splits a search at an underscore", all(t.isalnum() and t.islower() for t in tokens), tokens)
check("the vocabulary is the spec's", sl.VOCAB["shot_size"] == ["extreme_wide", "wide", "medium", "close", "detail"] and "branding_signage" in sl.VOCAB["subjects"] and "drone" in sl.VOCAB["camera_move"])

# ---- camera data ----------------------------------------------------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    clip = Path(tmp) / "C0001.MP4"
    clip.write_bytes(b"x")
    (Path(tmp) / "C0001M01.XML").write_text('<Device manufacturer="Sony" modelName="ILCE-7SM3" serialNo="1"/><Lens modelName="E 28-75mm"/><VideoFrame videoCodec="AVC200" captureFps="50.00p"/><Item name="CaptureGammaEquation" value="s-log3-cine"/>')
    side = sl.read_sidecar(str(clip))
    check("the sidecar gives the real gamma, camera, lens and frame rate", (side["gamma"], side["camera"], side["lens"], side["capture_fps"]) == ("s-log3-cine", "ILCE-7SM3", "E 28-75mm", "50.00p"), side)
    check("no sidecar is fine", sl.read_sidecar(str(Path(tmp) / "C0002.MP4")) == {})
check("gamma decides the limits", (sl.gamma_profile("s-log3-cine"), sl.gamma_profile("rec709"), sl.gamma_profile(None)) == ("slog3", "rec709", "unknown"))
check("only Log gets the viewing curve", "curves" in sl.viewing_filter("slog3", 480) and "curves" not in sl.viewing_filter("rec709", 480) and "curves" not in sl.viewing_filter("unknown", 480))

# ---- the checks -----------------------------------------------------------------------------------------------------------------------------------------------
check("S-Log3 black is rejected; the same level in Rec.709 is only dark", sl.rejected(sl.clip_stats(series(luma=0.095), "slog3")) and not sl.rejected(sl.clip_stats(series(luma=0.095), "rec709")))
half = series(luma=0.095)
half["luma"][:32] = [0.4] * 32
check("a clip black for half its length is not rejected", not sl.rejected(sl.clip_stats(half, "slog3")))
check("measured shares win over the small-thumbnail estimate", sl.clip_stats(series(levels={"hi84": [0.5, 0.5], "lo12": [0.1, 0.3]}), "slog3")["blown"] == 0.5 and sl.clip_stats(series(levels={"hi84": [0.5, 0.5], "lo12": [0.1, 0.3]}), "slog3")["crushed"] == 0.2)
check("reads made before the measured shares still work, from thumbnails", sl.clip_stats(series(luma=0.4), "slog3")["blown"] == 0.0)
m = post_steady.measure(np.full((24, post_steady.FRAME_H, post_steady.FRAME_W), 230, dtype=np.uint8))
check("the clip reader measures what S-Log3 needs: 230/255 is above S-Log3's clip and Rec.709's", m["levels"]["hi84"] == [1.0] * 3 and m["levels"]["hi90"] == [1.0] * 3 and m["levels"]["lo12"] == [0.0] * 3, m.get("levels"))
ordinary = [{"id": f"c{i}", "name": f"C{i}.MP4", "duration": 8.0, "profile": "slog3", "m": series(seed=i + 1)} for i in range(20)]
mk = lambda cid, duration=8.0, **kw: {"id": cid, "name": f"{cid}.MP4", "duration": duration, "profile": "slog3", "m": series(seed=sum(map(ord, cid)), **kw)}
results = sl.check_results(ordinary + [mk("soft", sharp=0.001), mk("dark", luma=0.15), mk("bright", luma=0.7), mk("shaky", jerk=0.2), mk("short", duration=1.5), mk("black", luma=0.09), {"id": "gone", "name": "gone.MP4", "duration": 8.0, "profile": "slog3", "m": None}])
types = lambda cid: [f["type"] for f in results[cid]["flags"]]
check("each check fires on the clip built for it", "soft" in types("soft") and "under" in types("dark") and "over" in types("bright") and "shaky" in types("shaky") and "short" in types("short"), {k: types(k) for k in ("soft", "dark", "bright", "shaky", "short")})
check("a flag says check, never reject", all(results[c]["result"] == "check" for c in ("soft", "dark", "bright", "shaky", "short")))
check("ordinary clips pass", all(results[c["id"]]["result"] == "pass" for c in ordinary), [results[c["id"]] for c in ordinary if results[c["id"]]["result"] != "pass"][:2])
check("a black clip is the one automatic reject, with a reason", results["black"]["result"] == "reject" and "Black" in results["black"]["reject_reason"])
check("a clip not read yet gets no verdict", "gone" not in results)
check("every flag says why in words", all(f["reason"] for r in results.values() for f in r["flags"]))
few = sl.check_results([mk("a"), mk("b"), mk("c", jerk=0.5)])
check("in a tiny shoot nothing is called the shakiest tenth", not any(f["type"] == "shaky" for r in few.values() for f in r["flags"]))
log709 = sl.check_results([{"id": "l", "name": "l", "duration": 8.0, "profile": "slog3", "m": series(sharp=0.002, seed=3)}, {"id": "l2", "name": "l2", "duration": 8.0, "profile": "slog3", "m": series(sharp=0.002, seed=4)}, {"id": "r", "name": "r", "duration": 8.0, "profile": "rec709", "m": series(sharp=0.05, seed=5)}, {"id": "r2", "name": "r2", "duration": 8.0, "profile": "rec709", "m": series(sharp=0.05, seed=6)}])
check("flat Log isn't called soft for being flatter than Rec.709 in the same shoot", not any(f["type"] == "soft" for r in log709.values() for f in r["flags"]), log709)
twin = {"id": "again", "name": "again.MP4", "duration": 8.0, "profile": "slog3", "m": ordinary[3]["m"]}
dup = sl.check_results(ordinary + [twin])
check("a repeat says which clip it looks like, and both share a group", "C3.MP4" in dup["again"]["flags"][0]["reason"] and dup["again"]["group"] == dup["c3"]["group"] == "c3" and dup["c3"]["result"] == "pass", dup["again"])
long_clip = sl.check_results([{"id": "L", "name": "L", "duration": 400.0, "profile": "slog3", "m": series(seed=9)}])
check("a clip past the reader's limit says only part was checked, without being called a problem", long_clip["L"]["flags"][0]["type"] == "long" and long_clip["L"]["result"] == "pass", long_clip)

# ---- Claude's answer ------------------------------------------------------------------------------------------------------------------------------------------
reply = lambda **kw: json.dumps({**good_tags(), "scene": "product", "people": True, "events": [{"t": 1.0, "kind": "hero", "punch": 8, "what": "Bottle lifted"}], **kw})
parsed = sl.parse_tag_reply("sure: " + reply(), 5.0)
check("a good answer gives tags and moments", parsed["tags"]["shot_size"] == "wide" and parsed["moments"]["events"][0]["what"] == "Bottle lifted", parsed)
check("no moments is still a good answer", sl.parse_tag_reply(reply(events=[]), 5.0)["moments"]["events"] == [])
for bad, why in ((reply(shot_size="tight"), "a word outside the vocabulary"), (reply(subjects=["product", "dog"]), "an unknown subject"), (reply(subjects=[]), "no subjects"), (reply(description=""), "no description"), (reply(vertical_crop_ok="yes"), "a non-true/false crop answer"), ("not json", "no JSON")):
    check(f"{why} is refused", sl.parse_tag_reply(bad, 5.0) is None)

# ---- his choices ----------------------------------------------------------------------------------------------------------------------------------------------
clip = {"id": "1", "name": "C1.MP4", "path": "/x/C1.MP4", "tags": good_tags(), "checks": {"result": "pass", "flags": []}}
e = sl.effective_clip(clip, {"shot_size": "close", "status": "select"})
check("his choice wins and Claude's answer is kept beside it", e["tags"]["shot_size"] == "close" and e["ai_tags"]["shot_size"] == "wide" and clip["tags"]["shot_size"] == "wide" and e["status"] == "select" and e["yours"] == ["shot_size", "status"])
auto = {**clip, "checks": {"result": "reject", "flags": []}}
check("an unusable clip starts rejected, and he can bring it back", sl.effective_clip(auto, {})["status"] == "reject" and sl.effective_clip(auto, {"status": "none"})["status"] == "none")
for field, value in (("status", "maybe"), ("shot_size", "tight"), ("subjects", ["dog"]), ("subjects", "product"), ("vertical_crop_ok", "yes"), ("description", 5), ("nonsense", "x")):
    try:
        sl.validate_override(field, value)
        check(f"a bad {field} is refused", False)
    except sl.ShootLogError:
        check(f"a bad {field} is refused", True)
check("subjects are de-duplicated, in his order", sl.validate_override("subjects", ["talent", "product", "talent"]) == ["talent", "product"])
kept = sl.tags_kept([{"id": "1", "tags": good_tags()}, {"id": "2", "tags": good_tags()}, {"id": "3", "tags": good_tags()}], {"1": {"status": "select"}, "2": {"shot_size": "close", "subjects": ["talent", "product"]}})
check("tags kept counts only clips he reviewed, and reordering subjects isn't a change", kept["total"] == 10 and kept["kept"] == 9 and kept["per_field"]["shot_size"]["kept"] == 1 and kept["per_field"]["subjects"]["kept"] == 2, kept)
check("no reviews, no share", sl.tags_kept([{"id": "1", "tags": good_tags()}], {})["share"] is None)
check("review time leaves out breaks", sl.review_minutes([{"at": "2026-11-02T10:00:00"}, {"at": "2026-11-02T10:02:00"}, {"at": "2026-11-02T11:00:00"}, {"at": "2026-11-02T11:01:00"}]) == 3.0)

# ---- out to Premiere ------------------------------------------------------------------------------------------------------------------------------------------
live = sl.effective_clip(clip, {})
check("Log Note holds the words the search bins look for", sl.log_note_words(live) == "shotwide subjectproduct subjecttalent energypeak movehandheld", sl.log_note_words(live))
gone = sl.effective_clip(clip, {"status": "reject"})
check("a rejected clip carries no search words, so it can't show in a search bin", sl.log_note_words(gone) == "rejected")
flagged = sl.effective_clip({**clip, "checks": {"result": "check", "flags": [{"type": "soft", "reason": "x"}, {"type": "long", "reason": "y"}]}}, {})
check("flags are searchable too, apart from the note about long clips", "checksoft" in sl.log_note_words(flagged) and "checklong" not in sl.log_note_words(flagged))
groups = sl.search_bin_groups([live, sl.effective_clip({**clip, "tags": good_tags(shot_size="detail", subjects=["venue"])}, {"status": "reject"})])
check("search bins only for what the shoot has, and not for what's only on rejected clips", [s["name"] for s in groups[0]["search"]] == ["Talent", "Product"] and [s["query"] for s in groups[1]["search"]] == ["shotwide"], groups)

# ---- a whole run on real tiny clips, with a stand-in for Claude -----------------------------------------------------------------------------------------------
class Block:
    type = "text"
    def __init__(self, text): self.text = text


class FakeMessages:
    def __init__(self): self.calls = []; self.script = {}; self.boom = None
    async def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom
        text = self.script.pop(len(self.calls), reply())
        return type("R", (), {"content": [Block(text)], "usage": type("U", (), {"input_tokens": 3000, "output_tokens": 300})()})()


class FakeClient:
    def __init__(self): self.messages = FakeMessages()


class APIConnectionError(Exception):
    pass


def make(path, source):
    subprocess.run([post_media.FFMPEG_PATH, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", source, "-t", "2.4", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)], check=True)


async def finish(key):
    while sl._RUNS[key]["state"] == "running":
        await asyncio.sleep(0.05)
    return sl.run_state(key)


async def previews_done(key):
    job = sl._PREVIEW_JOBS.get(key)
    while job and job["state"] == "running":
        await asyncio.sleep(0.05)
    return job


async def whole_run(tmp):
    media = Path(tmp) / "media"
    media.mkdir()
    for i, src in enumerate(("testsrc=s=320x180:r=25", "testsrc2=s=320x180:r=25", "smptebars=s=320x180:r=25", "rgbtestsrc=s=320x180:r=25")):
        make(media / f"C{i}.MP4", src)
    make(media / "BLACK.MP4", "color=c=black:s=320x180:r=25")
    (media / "BROKEN.MP4").write_bytes(b"not a video")
    (media / "NOTE.WAV").write_bytes(b"x")
    (media / "C0M01.XML").write_text('<Device modelName="ILCE-7SM3"/><Item name="CaptureGammaEquation" value="rec709"/>')
    (media / "BLACKM01.XML").write_text('<Item name="CaptureGammaEquation" value="rec709"/>')
    project = str(Path(tmp) / "Shoot.prproj")
    ctx = sl.new_context(project, None)
    check("a project of his gets its own folder, not one on a drive, and the same id each time", ctx["key"].startswith("p") and str(Path(tmp)) in ctx["folder"] and sl.context_for_project(project)["key"] == ctx["key"], ctx)
    incoming = [{"name": p.name, "path": str(p)} for p in sorted(media.iterdir()) if p.suffix != ".XML"]
    started = sl.start_logging(ctx, incoming)
    check("files that aren't video are left out and named", started["skipped"] == ["NOTE.WAV"] and started["clips"] == 6, started)
    try:
        sl.start_logging(ctx, incoming)
        check("a second start while running is refused", False)
    except sl.ShootLogError:
        check("a second start while running is refused", True)
    state = await finish(ctx["key"])
    check("the free part finishes", state["state"] == "done", state)
    await previews_done(ctx["key"])
    data = sl.view(ctx)
    by = {c["name"]: c for c in data["clips"]}
    check("previews are made in the background once the checks finish, without being asked", data["previews"]["total"] == 4 and data["previews"]["ready"] == 4 and all(by[f"C{i}.MP4"]["preview_ready"] for i in range(4)), data["previews"])
    check("no preview for a broken or black clip", not by["BROKEN.MP4"]["preview_ready"] and not by["BLACK.MP4"]["preview_ready"])
    check("nothing half-made is left behind", not list((Path(ctx["folder"]) / "previews").glob("*.part.mp4")))
    check("camera data comes from the sidecar when there is one", by["C0.MP4"]["gamma"] == "rec709" and by["C0.MP4"]["camera"] == "ILCE-7SM3" and by["C1.MP4"]["gamma"] is None and by["C1.MP4"]["profile"] == "unknown", by["C0.MP4"])
    check("the clip's facts are read", by["C0.MP4"]["width"] == 320 and by["C0.MP4"]["fps"] == 25.0 and abs(by["C0.MP4"]["duration"] - 2.4) < 0.1 and by["C0.MP4"]["vertical"] is False, by["C0.MP4"])
    check("a broken file is rejected, saying why, and doesn't stop the run", by["BROKEN.MP4"]["status"] == "reject" and "Couldn't be read" in by["BROKEN.MP4"]["checks"]["reject_reason"], by["BROKEN.MP4"])
    check("a black clip is rejected", by["BLACK.MP4"]["status"] == "reject", by["BLACK.MP4"].get("checks"))
    check("real clips aren't rejected", all(by[f"C{i}.MP4"]["status"] == "none" and by[f"C{i}.MP4"]["checks"]["result"] in ("pass", "check") for i in range(4)), [by[f"C{i}.MP4"]["checks"] for i in range(4)])
    check("four viewing frames per clip", all(sl.thumb_path(ctx, by[f"C{i}.MP4"]["id"], k).exists() for i in range(4) for k in range(4)))
    check("the estimate counts only clips worth tagging", data["estimate"]["clips"] == 4 and data["estimate"]["usd"] > 0 and data["estimate"]["cap_usd"] >= data["estimate"]["usd"], data["estimate"])
    steady_before = (Path(ctx["folder"]).parent / "steadiness.json").stat().st_mtime
    made_before = {p.name: p.stat().st_mtime for p in (Path(ctx["folder"]) / "previews").iterdir()}
    sl.start_logging(ctx, incoming)
    state = await finish(ctx["key"])
    await previews_done(ctx["key"])
    check("running it again remakes no previews", {p.name: p.stat().st_mtime for p in (Path(ctx["folder"]) / "previews").iterdir()} == made_before)

    # Pausing, resuming, a click while the job is busy, and a card pulled out.
    pv = Path(ctx["folder"]) / "previews"
    ids_now = {c["name"]: c["id"] for c in sl.view(ctx)["clips"]}
    for f in pv.iterdir():
        f.unlink()
    sl.start_previews(ctx)
    paused = sl.pause_previews(ctx)
    check("a pause says so at once", paused["state"] == "pausing", paused)
    await previews_done(ctx["key"])
    check("a pause holds: the job stops short of the end", sl.preview_state(ctx)["state"] == "paused" and sl.preview_state(ctx)["ready"] < 4, sl.preview_state(ctx))
    clicked = sl.load_log(ctx)["clips"][ids_now["C3.MP4"]]
    already = (await sl.render_preview(ctx, clicked)).exists()
    check("a clicked clip is still made while paused", already)
    resumed = sl.start_previews(ctx)
    again_start = sl.start_previews(ctx)
    check("starting twice doesn't start a second job", resumed["state"] == "running" and again_start["state"] == "running")
    await previews_done(ctx["key"])
    check("resuming finishes the rest", sl.preview_state(ctx)["ready"] == 4, sl.preview_state(ctx))
    for f in pv.iterdir():
        f.unlink()
    target = sl.load_log(ctx)["clips"][ids_now["C0.MP4"]]
    both = await asyncio.gather(sl.render_preview(ctx, target), sl.render_preview(ctx, target))
    check("two requests for the same clip make one file, not a corrupt one", both[0] == both[1] and both[0].stat().st_size > 0 and not list(pv.glob("*.part.mp4")))
    sl.add_override(ctx, ids_now["C1.MP4"], "status", "reject")
    sl.start_previews(ctx)
    await previews_done(ctx["key"])
    check("a clip he has rejected gets no preview", not sl.preview_path(ctx, ids_now["C1.MP4"]).exists() and sl.preview_state(ctx)["total"] == 3 and sl.preview_state(ctx)["ready"] == 3, sl.preview_state(ctx))
    sl.add_override(ctx, ids_now["C1.MP4"], "status", "none")
    real_disk = sl.shutil.disk_usage
    sl.shutil.disk_usage = lambda p: type("D", (), {"free": 1_000_000})()
    sl.start_previews(ctx)
    await previews_done(ctx["key"])
    low = sl.preview_state(ctx)
    check("a nearly full drive pauses it and says why", low["state"] == "paused" and "GB free" in low["message"], low)
    sl.shutil.disk_usage = real_disk
    for f in pv.iterdir():
        f.unlink()
    log_gone = sl.load_log(ctx)
    for c in log_gone["clips"].values():
        c["path"] = "/nowhere/" + c["name"]
    sl._save_log(ctx, log_gone)
    sl.start_previews(ctx)
    await previews_done(ctx["key"])
    gone = sl.preview_state(ctx)
    check("a card pulled out pauses it and says what to check, instead of failing clip after clip", gone["state"] == "paused" and "connected" in gone["message"], gone)
    log_back = sl.load_log(ctx)
    for cid, c in log_back["clips"].items():
        c["path"] = str(media / c["name"])
    sl._save_log(ctx, log_back)
    sl.start_previews(ctx)
    await previews_done(ctx["key"])
    check("with the card back, it carries on", sl.preview_state(ctx)["ready"] == sl.preview_state(ctx)["total"], sl.preview_state(ctx))
    check("running it again reads nothing new", "0 read now" in state["message"] and (Path(ctx["folder"]).parent / "steadiness.json").stat().st_mtime == steady_before, state["message"])

    client = FakeClient()
    client.messages.script[2] = "no json here"   # the second call's answer is bad, so that clip has to try again
    sl.start_tagging(ctx, client)
    state = await finish(ctx["key"])
    data = sl.view(ctx)
    by = {c["name"]: c for c in data["clips"]}
    check("every usable clip gets tagged, a bad answer is tried once more", state["state"] == "done" and data["counts"]["tagged"] == 4 and len(client.messages.calls) == 5, (state, len(client.messages.calls)))
    check("rejected clips aren't sent to Claude", not by["BLACK.MP4"]["ai_tags"] and not by["BROKEN.MP4"]["ai_tags"])
    sent = client.messages.calls[0]
    check("Claude gets labelled frames and the fixed vocabulary", any(b["type"] == "image" for b in sent["messages"][0]["content"]) and "branding_signage" in sent["system"] and sent["model"] == sl.MODEL)
    check("what it really cost goes in the ledger", any(row for row in (Path(ctx["folder"]) / post_moments.USAGE_FILE).read_text().splitlines() if "shoot_log_tags" in row), state)
    check("tagged clips carry what made them", by["C1.MP4"]["tag_provenance"]["prompt"] == sl.TAG_PROMPT_VERSION)
    calls = len(client.messages.calls)
    check("nothing is left to tag, so a second click spends nothing", sl.start_tagging(ctx, client)["started"] is False and len(client.messages.calls) == calls)

    # A clip Claude can't answer for doesn't stop the others; no signal stops the run and the same click carries on; the money limit holds.
    log = sl.load_log(ctx)
    for c in log["clips"].values():
        c.pop("tags", None); c.pop("tag_provenance", None)
    sl._save_log(ctx, log)
    client = FakeClient()
    client.messages.script.update({1: "bad", 2: "bad"})
    sl.start_tagging(ctx, client)
    state = await finish(ctx["key"])
    check("a clip with no good answer is named and the rest go on", len(state["failed"]) == 1 and sl.view(ctx)["counts"]["tagged"] == 3 and state["state"] == "done", state)
    log = sl.load_log(ctx)
    for c in log["clips"].values():
        c.pop("tags", None); c.pop("tag_provenance", None)
    sl._save_log(ctx, log)
    client = FakeClient()
    client.messages.boom = APIConnectionError("no signal")
    sl.start_tagging(ctx, client)
    state = await finish(ctx["key"])
    check("no signal stops the run and says to click again", state["state"] == "stopped" and "signal" in state["message"], state)
    client = FakeClient()
    sl.start_tagging(ctx, client, cap_usd=0.015)
    state = await finish(ctx["key"])
    done = sl.view(ctx)["counts"]["tagged"]
    check("the money limit stops it with the work kept", state["state"] == "stopped" and "limit" in state["message"] and 0 < done < 4, (state, done))
    client = FakeClient()
    sl.start_tagging(ctx, client)
    await finish(ctx["key"])
    check("the same click finishes the rest", sl.view(ctx)["counts"]["tagged"] == 4 and len(client.messages.calls) == 4 - done)

    # His choices, the plan for Premiere, the export.
    ids = {c["name"]: c["id"] for c in sl.view(ctx)["clips"]}
    sl.add_override(ctx, ids["C0.MP4"], "status", "select")
    sl.add_override(ctx, ids["C0.MP4"], "shot_size", "close")
    sl.add_override(ctx, ids["C1.MP4"], "status", "reject")
    sl.add_override(ctx, ids["C2.MP4"], "description", "=SUM(A1)")
    try:
        sl.add_override(ctx, "999", "status", "select")
        check("a choice on an unknown clip is refused", False)
    except sl.ShootLogError:
        check("a choice on an unknown clip is refused", True)
    lines = (Path(ctx["folder"]) / "overrides.jsonl").read_text().splitlines()
    log_ai = sl.load_log(ctx)["clips"][ids["C0.MP4"]]["tags"]["shot_size"]
    check("his choices are in their own file and Claude's answer is untouched", [json.loads(l)["value"] for l in lines[-4:]][:2] == ["select", "close"] and log_ai == "wide", lines[-4:])
    data = sl.view(ctx)
    check("the counts follow his choices", data["counts"]["selects"] == 1 and data["counts"]["rejects"] == 3 and data["counts"]["reviewed"] == 3, data["counts"])
    plan = sl.apply_plan(ctx)
    p = {c["name"]: c for c in plan["clips"]}
    check("the plan carries his choice, not Claude's", p["C0.MP4"]["status"] == "select" and "shotclose" in p["C0.MP4"]["note"] and "shotwide" not in p["C0.MP4"]["note"], p["C0.MP4"])
    check("a rejected clip gets no markers and no search words", p["C1.MP4"]["note"] == "rejected" and not p["C1.MP4"]["markers"])
    check("markers come from the described moments", p["C0.MP4"]["markers"][0]["comment"] == "Bottle lifted" and p["C0.MP4"]["markers"][0]["t"] == 1.0)
    check("nothing has been applied yet", p["C0.MP4"]["previous"] == {})
    sl.record_applied(ctx, {"moved": 2})
    again = {c["name"]: c for c in sl.apply_plan(ctx)["clips"]}
    check("after applying, the plan remembers what it wrote", again["C0.MP4"]["previous"] == {"status": "select", "description": "Bottle held up"} and sl.view(ctx)["applied_at"], again["C0.MP4"])
    text = sl.to_csv(ctx)
    check("the CSV has every clip with his choices, and a cell can't run as a formula", len(text.strip().splitlines()) == 7 and ",close," in text and "'=SUM(A1)" in text and "=SUM(A1)" not in text.replace("'=SUM(A1)", ""), text[:300])
    preview = await sl.render_preview(ctx, sl.load_log(ctx)["clips"][ids["C0.MP4"]])
    check("a preview can be made and is reused", preview.exists() and preview.stat().st_size > 0 and (await sl.render_preview(ctx, sl.load_log(ctx)["clips"][ids["C0.MP4"]])) == preview)
    merged = sl.load_log(ctx)
    sl.merge_clips(merged, [i for i in incoming if i["name"] in ("C0.MP4", "C1.MP4")])
    check("if clips leave the project they leave the log, and the rest keep their tags", len(merged["clips"]) == 2 and any(c.get("tags") for c in merged["clips"].values()))
    return ctx, ids


with tempfile.TemporaryDirectory() as tmp:
    sl.DATA = Path(tmp) / "shoot_logs"
    transfer_cut.DATA = Path(tmp) / "projects"
    ctx, ids = asyncio.run(whole_run(tmp))

    # ---- routes -----------------------------------------------------------------------------------------------------------------------------------------------
    main.AUTH_TOKEN = "t"
    async def no_job(_): return None, {}
    async def no_audit(*a, **k): return None
    main._shoot_log_job_lookup, main._shoot_log_audit = no_job, no_audit
    web = TestClient(main.app)
    key = ctx["key"]
    check("no token, no log", web.get(f"/post/shoot-log/{key}").status_code == 422 and web.get(f"/post/shoot-log/{key}?token=wrong").status_code == 403)
    got = web.get(f"/post/shoot-log/{key}?token=t")
    check("the page's data comes back", got.status_code == 200 and got.json()["counts"]["clips"] == 6 and "vocabulary" in got.json(), got.text[:200])
    check("an unknown shoot is a 404, and a request can't name a folder", web.get("/post/shoot-log/nope?token=t").status_code == 404 and web.get("/post/shoot-log/..%2F..%2Fetc?token=t").status_code == 404)
    check("the page itself is served", web.get("/static/shoot_log.html").status_code == 200)
    r = web.post(f"/post/shoot-log/{key}/override?token=t", json={"clip": ids["C3.MP4"], "field": "shot_size", "value": "tight"})
    check("a bad choice is a 400 that says why", r.status_code == 400 and "shot_size" in r.json()["detail"], r.text)
    r = web.post(f"/post/shoot-log/{key}/override?token=t", json={"clip": ids["C3.MP4"], "field": "status", "value": "select"})
    check("a good choice is kept", r.status_code == 200 and web.get(f"/post/shoot-log/{key}?token=t").json()["counts"]["selects"] == 2, r.text)
    check("a viewing frame comes back as an image", web.get(f"/post/shoot-log/{key}/thumb/{ids['C3.MP4']}/0?token=t").headers["content-type"] == "image/jpeg")
    check("a frame that doesn't exist is a 404", web.get(f"/post/shoot-log/{key}/thumb/1/0?token=t").status_code == 404)
    check("a clip id has to be a number, so a path can't get through", web.get(f"/post/shoot-log/{key}/thumb/..%2F..%2Fx/0?token=t").status_code in (404, 422))
    r = web.get(f"/post/shoot-log/{key}/previews?token=t")
    check("the preview state has its own light route, so reviewing isn't disturbed by polling", r.status_code == 200 and "ready_ids" in r.json() and "clips" not in r.json(), r.text[:200])
    check("preview routes need the token", web.post(f"/post/shoot-log/{key}/previews/start?token=wrong").status_code == 403 and web.post(f"/post/shoot-log/{key}/previews/pause?token=wrong").status_code == 403)
    check("pausing with nothing running is harmless", web.post(f"/post/shoot-log/{key}/previews/pause?token=t").status_code == 200)
    check("a preview comes back as video", web.get(f"/post/shoot-log/{key}/preview/{ids['C0.MP4']}?token=t").headers["content-type"] == "video/mp4")
    check("a preview only for clips in the log", web.get(f"/post/shoot-log/{key}/preview/5?token=t").status_code == 404)
    r = web.get(f"/post/shoot-log/{key}/export.csv?token=t")
    check("the CSV downloads", r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.text.startswith("name,status"))
    r = web.post("/post/shoot-log/apply-plan?token=t", json={"project_path": ctx["project_path"]})
    check("Apply gets its plan by project", r.status_code == 200 and r.json()["key"] == key and r.json()["bins"]["parent"] == "Shoot Log", r.text[:200])
    r = web.post("/post/shoot-log/apply-plan?token=t", json={"project_path": "/not/logged.prproj"})
    check("a project that was never logged says what to do", r.status_code == 404 and "Log This Shoot" in r.json()["detail"])
    r = web.post(f"/post/shoot-log/{key}/applied?token=t", json={"report": {"moved": 1}})
    check("Apply reports back", r.status_code == 200 and json.loads((Path(ctx["folder"]) / "applied.json").read_text())["report"] == {"moved": 1})
    stubbed = {}
    def fake_start(c, clips, file_ids=None):
        stubbed.update(clips=clips, ctx=c)
        return {"clips": len(clips), "skipped": [], "run": None}
    real_start, sl.start_logging = sl.start_logging, fake_start
    r = web.post("/post/shoot-log/start?token=t", json={"project_path": ctx["project_path"], "clips": [{"name": "C0.MP4", "path": "/a/C0.MP4"}]})
    check("starting returns the review page", r.status_code == 200 and r.json()["key"] == key and r.json()["review_path"] == f"/static/shoot_log.html?log={key}" and stubbed["clips"] == [{"name": "C0.MP4", "path": "/a/C0.MP4"}], r.text[:200])
    other = web.post("/post/shoot-log/start?token=t", json={"project_path": str(Path(tmp) / "Other.prproj"), "clips": []})
    check("a new project is registered once with its own id", other.status_code == 200 and other.json()["key"] != key and other.json()["key"] in sl.load_index())
    sl.start_logging = real_start
    async def fine(client, model): return None
    real_credit, post_moments.check_credit = post_moments.check_credit, fine
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    real_tag, sl.start_tagging = sl.start_tagging, lambda c, client, cap=None: {"started": True, "estimate": {"clips": 1}, "run": None, "cap": cap}
    r = web.post(f"/post/shoot-log/{key}/tag?token=t", json={"max_usd": 0.5})
    check("tagging is its own explicit request with a limit", r.status_code == 200 and r.json()["cap"] == 0.5, r.text[:200])
    sl.start_tagging, post_moments.check_credit = real_tag, real_credit
    check("Shoot Log pages hold no database connection, so a page of thumbnails can't tie up the pool", main._is_slow_route("GET", f"/post/shoot-log/{key}/thumb/1/0") and main._is_slow_route("GET", "/static/shoot_log.html") and main._is_slow_route("POST", "/post/shoot-log/start"))
    check("other routes are as they were", not main._is_slow_route("GET", "/post/jobs") and main._is_slow_route("POST", "/ventures/1/validate") and not main._is_slow_route("GET", "/ventures/1/marketing-content"))

check("nothing landed in the real data folder", not (REAL_DATA / "index.json").exists() or "Shoot.prproj" not in (REAL_DATA / "index.json").read_text())

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
