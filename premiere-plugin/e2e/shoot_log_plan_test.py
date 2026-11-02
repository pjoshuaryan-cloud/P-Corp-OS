"""Clips rejected in the Shoot Log stay out of Plan Edit: new plans, variant sets, Describe and the opening-clip list leave them out, review never offers them, and a shoot with no log plans
exactly as it did. Real planners, real review logic and the real log files, on synthetic clips in a temp folder. No drive, no API call, and nothing under backend/data is touched. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python shoot_log_plan_test.py"""
import asyncio
import copy
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient  # noqa: E402
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from app import main, post_db, post_edit_plan as pe, post_moments, post_music, post_pick, post_review, post_shoot_log as sl, post_steady, post_style, post_variants as pv  # noqa: E402
from app.post_edit_highlight import build_highlight_plan  # noqa: E402
from learning import transfer_cut  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
HITS = beat_hits(160)
REAL_DATA = sl.DATA


def write_log(ctx, statuses=None, auto_reject=()):
    """A shoot log for the synthetic clips: `statuses` are his choices, `auto_reject` are clips the checks refused."""
    log = {"version": 1, "project_path": ctx["project_path"], "name": ctx["name"], "clips": {}, "order": []}
    for c in CLIPS:
        cid = str(c["file_id"])
        log["clips"][cid] = {"id": cid, "file_id": c["file_id"], "name": c["name"], "path": c["path"], "duration": c["duration"], "checks": {"result": "reject" if c["name"] in auto_reject else "pass", "flags": []}}
        log["order"].append(cid)
    sl._save_log(ctx, log)
    (Path(ctx["folder"]) / "overrides.jsonl").unlink(missing_ok=True)
    for name, status in (statuses or {}).items():
        sl.add_override(ctx, str(next(c["file_id"] for c in CLIPS if c["name"] == name)), "status", status)


with tempfile.TemporaryDirectory() as tmp:
    sl.DATA = Path(tmp) / "shoot_logs"
    transfer_cut.DATA = Path(tmp) / "projects"
    root = Path(tmp) / "Shoot"
    (root / "09_PROJECT FILES" / "edit_plans").mkdir(parents=True)
    (root / "04_MUSIC").mkdir()
    song = root / "04_MUSIC" / "song.wav"
    song.write_bytes(b"x")
    project = str(root / "Shoot.prproj")
    JOB = {"id": 9, "shoot_name": "Synthetic", "profile": "joshx", "destination_root": str(root), "media_analyzed_at": "2026-11-02", "frame_rate": "25", "premiere_project_path": project}

    # ---- which clips count as rejected ------------------------------------------------------------------------------------------------------------------------
    check("a shoot with no log has no rejects, and its clips come back as they were", sl.rejected_paths(JOB) == set() and pe.split_rejected(CLIPS, JOB) == (CLIPS, []))
    ctx = sl.new_context(project, JOB)
    check("a POST shoot's log sits beside its plans", ctx["key"] == "j9" and str(root) in ctx["folder"], ctx)
    write_log(ctx)
    check("a log with nothing rejected changes nothing", pe.split_rejected(CLIPS, JOB)[1] == [])
    write_log(ctx, {"C0002.MP4": "reject", "C0003.MP4": "select", "C0004.MP4": "reject"}, auto_reject=("C0005.MP4",))
    kept, left = pe.split_rejected(CLIPS, JOB)
    check("his rejects and clips the checks refused are left out; selects and undecided stay", sorted(c["name"] for c in left) == ["C0002.MP4", "C0004.MP4", "C0005.MP4"] and len(kept) == len(CLIPS) - 3, [c["name"] for c in left])
    sl.add_override(ctx, "4", "status", "none")
    check("the last choice wins: a clip he brought back is back", "C0004.MP4" not in [c["name"] for c in pe.split_rejected(CLIPS, JOB)[1]])
    sl.add_override(ctx, "5", "status", "none")
    check("he can overrule the checks too", "C0005.MP4" not in [c["name"] for c in pe.split_rejected(CLIPS, JOB)[1]])
    write_log(ctx, {"C0002.MP4": "reject"})
    accented = [{**CLIPS[1], "path": unicodedata.normalize("NFD", "/x/é.MP4")}]
    log = sl.load_log(ctx)
    log["clips"]["2"]["path"] = unicodedata.normalize("NFC", "/x/é.MP4")
    sl._save_log(ctx, log)
    check("the same file name spelled two ways still matches", pe.split_rejected(accented, JOB)[1] == accented)
    write_log(ctx, {"C0002.MP4": "reject"})

    # A log started with no signal is filed under the project, with its own clip ids, so paths have to do the matching.
    JOB2 = {**JOB, "id": 10, "premiere_project_path": str(root / "Other.prproj")}
    ctx2 = sl.new_context(JOB2["premiere_project_path"], None)
    write_log(ctx2, {"C0007.MP4": "reject"})
    log2 = sl.load_log(ctx2)
    log2["clips"] = {str(90000 + int(k)): {**v, "id": str(90000 + int(k))} for k, v in log2["clips"].items()}
    log2["order"] = list(log2["clips"])
    (Path(ctx2["folder"]) / "overrides.jsonl").unlink()
    sl._save_log(ctx2, log2)
    sl.add_override(ctx2, "90007", "status", "reject")
    check("a log filed under the project still counts for its shoot", [c["name"] for c in pe.split_rejected(CLIPS, JOB2)[1]] == ["C0007.MP4"])

    # ---- real planners ----------------------------------------------------------------------------------------------------------------------------------------
    async def fake_job(job_id, postgres_conn=None):
        return dict(JOB)

    async def fake_clips(job_id, postgres_conn=None, order_names=None):
        return [copy.deepcopy(c) for c in CLIPS]

    async def fake_analyse(clips, job_, **kw):
        return {"analysed": 0, "cached": len(clips), "unreadable": 0, "not_read": 0}

    async def fake_music(path):
        return {"hits": HITS, "duration": 160.0, "tempo_bpm": 128.0}

    async def fake_render(src, out, music_in, seconds, *a, **k):
        Path(out).write_bytes(b"wav")

    saved = (post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, pe.find_logo, pe.bring_song_into_project, pe.attach_moments)
    post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut = fake_job, fake_clips, fake_analyse, fake_music, fake_render
    pe.find_logo, pe.bring_song_into_project, pe.attach_moments = (lambda j: None), (lambda s, d: str(s)), (lambda clips, job: clips)

    def plan_with(style, **kw):
        return asyncio.run(pe.plan_for_job(9, style=[style], music_path=str(song), target_seconds=24.0, seed=3, **kw))

    def stable(plan):
        return {k: v for k, v in plan.items() if k not in ("plan_path", "planned_at", "notes", "checks")}

    def used(plan):
        return {s["name"] for s in plan["shots"]}

    # Rejecting a clip the plan actually uses, so the test can't pass by luck.
    (Path(ctx["folder"]) / "overrides.jsonl").unlink(missing_ok=True)
    sl._save_log(ctx, {"version": 1, "project_path": project, "name": "x", "clips": {}, "order": []})
    baseline = plan_with(post_style.USUAL_PACE_SLUG)
    write_log(ctx)
    with_log = plan_with(post_style.USUAL_PACE_SLUG)
    check("a log with nothing rejected plans exactly what no log plans", stable(baseline) == stable(with_log) and "left_out_rejected" not in with_log["checks"])
    targets = sorted(used(baseline))[:6]
    check("the test is real: the plan uses those clips before they're rejected", len(targets) == 6)
    write_log(ctx, {n: "reject" for n in targets})
    after = plan_with(post_style.USUAL_PACE_SLUG)
    check("a new plan never uses a rejected clip", not used(after) & set(targets), used(after) & set(targets))
    check("the plan still fills its length", abs(after["duration_frames"] - baseline["duration_frames"]) <= 2 and after["checks"]["shot_count"] > 0, (after["duration_frames"], baseline["duration_frames"]))
    check("it says what it left out, in the notes Plan Edit shows", any("Left out 6 clip(s) rejected in the Shoot Log" in n and targets[0] in n for n in after["notes"]) and after["checks"]["left_out_rejected"] == targets, after["notes"][-2:])
    write_log(ctx)
    check("bringing them back brings back the same plan", stable(plan_with(post_style.USUAL_PACE_SLUG)) == stable(baseline))

    families = [("furniture-expo-decorex", "a plain music montage"), ("corporate-distribution-company", "a narrated story"), ("corporate-highlight-calm", "a calm highlight")]
    known = {s["slug"] for s in post_style.available_styles()}
    for slug, what in families:
        if slug not in known:
            print(f"SKIP  {what}: the {slug} reference isn't on this machine")
            continue
        write_log(ctx)
        plain = plan_with(slug)
        names = sorted(used(plain))[:5]
        write_log(ctx, {n: "reject" for n in names})
        other = plan_with(slug)
        check(f"{what} leaves them out too", names and not used(other) & set(names), used(other) & set(names))

    write_log(ctx, {c["name"]: "reject" for c in CLIPS})
    try:
        plan_with(post_style.USUAL_PACE_SLUG)
        check("all rejected is refused", False)
    except pe.EditPlanError as exc:
        check("if everything is rejected it says so, rather than failing somewhere odd", "rejected in the Shoot Log" in str(exc), str(exc))
    write_log(ctx, {"C0003.MP4": "reject"})
    try:
        plan_with(post_style.USUAL_PACE_SLUG, bookend_file_id=3)
        check("a rejected opener is refused", False)
    except pe.EditPlanError as exc:
        check("a rejected opening clip says what to do", "opening clip is rejected" in str(exc), str(exc))
    check("an opener that isn't rejected still works", plan_with(post_style.USUAL_PACE_SLUG, bookend_file_id=8)["shots"][0]["name"] == "C0008.MP4")

    # An interview's cameras are chosen by hand: that choice stands.
    import app.post_edit_dialogue as dialogue
    seen = {}
    async def fake_dialogue(job, profile, clips, **kw):
        seen["clips"] = [c["name"] for c in clips]
        return {"stub": True}
    real_dialogue, dialogue.plan_dialogue_for_job = dialogue.plan_dialogue_for_job, fake_dialogue
    real_profile, post_style.profile_from_references = post_style.profile_from_references, lambda style: type("P", (), {"dialogue": object(), "target_duration_seconds": 30.0})()
    try:
        write_log(ctx, {"C0001.MP4": "reject"})
        asyncio.run(pe.plan_for_job(9, style=["talking"], music_path=str(song), target_seconds=24.0))
    finally:
        dialogue.plan_dialogue_for_job, post_style.profile_from_references = real_dialogue, real_profile
    check("an interview's cameras aren't filtered", "C0001.MP4" in seen["clips"])

    # ---- the planning screen and Describe ---------------------------------------------------------------------------------------------------------------------
    write_log(ctx, {"C0002.MP4": "reject"})
    pe.attach_moments = lambda clips, job: clips
    options = pe._options_from_drive(dict(JOB), [copy.deepcopy(c) for c in CLIPS])
    check("the opening-clip list leaves out rejected clips", "C0002.MP4" not in [c["name"] for c in options["clips"]] and len(options["clips"]) == len(CLIPS) - 1)
    check("the Describe count and cost leave them out too", options["describe"]["total"] == len(CLIPS) - 1, options["describe"]["total"])

    # ---- variants ---------------------------------------------------------------------------------------------------------------------------------------------
    seen_variants = {}
    class Stop(Exception):
        pass
    async def stop_analyse(clips, job_, **kw):
        seen_variants["names"] = [c["name"] for c in clips]
        raise Stop()
    real_an = post_steady.analyse_clips
    post_steady.analyse_clips = stop_analyse
    try:
        asyncio.run(pv.plan_variants_for_job(9, count=3))
    except Stop:
        pass
    check("variant sets leave them out", "C0002.MP4" not in seen_variants["names"] and len(seen_variants["names"]) == len(CLIPS) - 1, seen_variants)
    post_steady.analyse_clips = real_an
    write_log(ctx, {c["name"]: "reject" for c in CLIPS})
    try:
        asyncio.run(pv.plan_variants_for_job(9, count=3))
        check("variants with everything rejected are refused", False)
    except pv.VariantError as exc:
        check("variants with everything rejected say so", "rejected in the Shoot Log" in str(exc), str(exc))

    (post_db.get_post_job, pe.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, pe.find_logo, pe.bring_song_into_project, pe.attach_moments) = saved

    # ---- review of a plan made before the clip was rejected ---------------------------------------------------------------------------------------------------
    plan = build_highlight_plan(profile=post_style.usual_pace_profile(), hits=HITS, music_in=10.0, duration=24.0, fps=25.0, clips=[copy.deepcopy(c) for c in CLIPS], bookend_file_id=None, seed=3)
    planned = [s["name"] for s in plan["shots"] if s["role"] == "body"]
    victim, bystander, other = planned[0], planned[2], planned[4]
    write_log(ctx, {victim: "reject", bystander: "reject"})
    clips = pe.mark_rejected([copy.deepcopy(c) for c in CLIPS], JOB)
    check("for review, rejected clips are flagged and stay findable", len(clips) == len(CLIPS) and sum(bool(c.get("rejected")) for c in clips) == 2)
    review = post_review.build_review(copy.deepcopy(plan), clips)
    slot = next(s for s in review["slots"] if s["current"]["name"] == victim)
    check("an older plan's shot still shows, marked as rejected, rather than breaking", slot["rejected"] is True and slot["current"]["name"] == victim)
    check("only shots using a rejected clip are marked", all(s["rejected"] == (s["current"]["name"] in (victim, bystander)) for s in review["slots"]), [(s["current"]["name"], s["rejected"]) for s in review["slots"]][:6])
    offered = {a["name"] for s in review["slots"] for a in s["alternatives"] if a["name"] != s["current"]["name"]}
    check("a rejected clip is never offered as a swap", bystander not in offered and victim not in offered, offered & {bystander, victim})
    check("the test is real: swaps were on offer", len(offered) > 3, offered)
    unmarked = post_review.build_review(copy.deepcopy(plan), [copy.deepcopy(c) for c in CLIPS])
    check("with no rejects, a slot isn't marked", not any(s["rejected"] for s in unmarked["slots"]))
    by_name = {c["name"]: c for c in clips}
    check("a page left open can't swap a rejected clip in", post_pick.valid_alternative(plan, clips, slot["index"], by_name[bystander]["file_id"], 0.5) is None)
    check("the same swap on a clip that isn't rejected is still fine", post_pick.valid_alternative(plan, clips, slot["index"], by_name[other]["file_id"], 0.5) is not None)
    regen = copy.deepcopy(plan)
    idx = [s["index"] for s in regen["shots"] if s["role"] == "body"]
    swap = next(a for s in review["slots"] for a in s["alternatives"] if a["name"] not in (victim, bystander, s["current"]["name"]))
    slot_of = next(s for s in review["slots"] if swap in s["alternatives"])
    swapped = copy.deepcopy(plan)
    post_review.apply_choice(swapped, clips, slot_of["index"], swap["file_id"], swap["source_in"], "swap")
    check("swapping to a clip that isn't rejected still works", next(s for s in swapped["shots"] if s["index"] == slot_of["index"])["name"] == swap["name"])
    try:
        post_review.apply_choice(copy.deepcopy(plan), clips, slot["index"], by_name[bystander]["file_id"], 0.5, "swap")
        check("swapping a rejected clip in is refused", False)
    except post_review.ReviewError:
        check("swapping a rejected clip in is refused", True)
    post_review.regenerate_section(regen, clips, idx[0], idx[-1])
    now = [s["name"] for s in regen["shots"] if s["role"] == "body"]
    check("Regenerate replaces rejected clips and never picks one", victim not in now and bystander not in now, [n for n in now if n in (victim, bystander)])
    problems = pv.validate_plan(copy.deepcopy(plan), [copy.deepcopy(c) for c in CLIPS])
    check("a plan that uses a clip rejected later is still sound to build", problems == [], problems)

    # ---- routes -----------------------------------------------------------------------------------------------------------------------------------------------
    main.app.dependency_overrides[main.verify_token] = lambda: None
    async def main_job(job_id, postgres_conn=None):
        return dict(JOB) if job_id == 9 else None
    real_job, main.get_post_job = main.get_post_job, main_job
    real_status_load = pe.load_job_clips
    pe.load_job_clips = fake_clips
    web = TestClient(main.app)
    write_log(ctx, {"C0002.MP4": "reject", "C0003.MP4": "reject"})
    r = web.get("/post/jobs/9/moments-status")
    check("the Describe status route counts without rejected clips", r.status_code == 200 and r.json()["total"] == len(CLIPS) - 2, r.text[:200])
    started = {}
    def fake_start(job_id, client, model, clips_, folder, max_calls, planned_total=None):
        started["names"] = [c["name"] for c in clips_]
        return {"state": "running"}
    async def fine(client, model):
        return None
    real_credit, real_start, real_key = post_moments.check_credit, post_moments.start_run, main._require_api_key
    post_moments.check_credit, post_moments.start_run, main._require_api_key = fine, fake_start, lambda: "test"
    r = web.post("/post/jobs/9/find-moments", json={})
    check("Describe doesn't pay for rejected clips", r.status_code == 200 and "C0002.MP4" not in started.get("names", ["C0002.MP4"]) and len(started["names"]) == len(CLIPS) - 2, (r.status_code, r.text[:200]))
    post_moments.check_credit, post_moments.start_run, main._require_api_key = real_credit, real_start, real_key
    pe.load_job_clips = real_status_load
    main.get_post_job = real_job
    main.app.dependency_overrides.pop(main.verify_token, None)

check("nothing landed in the real data folder", not (REAL_DATA / "index.json").exists() or '"j9"' not in (REAL_DATA / "index.json").read_text())

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
