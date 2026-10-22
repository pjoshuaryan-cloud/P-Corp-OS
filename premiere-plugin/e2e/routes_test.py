"""Route-level tests for the new review and variant endpoints (backend/app/main.py), through FastAPI's TestClient. ONLY the boundaries are stubbed: the token check,
the job lookup, the audit log and the job's folder on the drive (a temp folder). The plans, the picker, the review logic, the variant sets and the learning-event
files are all real. No backend process, no drive, no API call, no Premiere.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python routes_test.py"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main, post_edit_plan, post_learning_events as le, post_style, post_variants as pv  # noqa: E402
from app.post_edit_highlight import build_highlight_plan  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
PLAN = build_highlight_plan(profile=post_style.usual_pace_profile(), hits=beat_hits(160), music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, bookend_file_id=None, seed=7)
JOB = {"id": 7, "shoot_name": "Synthetic", "profile": "joshx", "destination_root": "/nowhere", "media_analyzed_at": "2026-10-22", "frame_rate": 25}

with tempfile.TemporaryDirectory() as tmp:
    edit = Path(tmp)
    (edit / "edit_plan_latest.json").write_text(post_edit_plan.plan_to_json(copy.deepcopy(PLAN)))
    audit: list = []

    async def fake_job(job_id, postgres_conn=None):
        return dict(JOB) if job_id == 7 else None

    async def fake_context(job_id, request):
        if job_id != 7:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="no job")
        return dict(JOB), json.loads((edit / "edit_plan_latest.json").read_text()), [dict(c) for c in CLIPS], None

    async def fake_audit(name, payload, result, conn=None):
        audit.append((name, payload, result))

    main.app.dependency_overrides[main.verify_token] = lambda: None
    media = edit / "media"
    media.mkdir()
    on_disk = []
    for c in CLIPS:   # the job's clips as the database lists them, with files that really exist (use checks the drive before replacing the plan)
        f = media / c["name"]
        f.write_bytes(b"x")
        on_disk.append({**c, "path": str(f)})

    async def fake_job_clips(job_id, postgres_conn=None, order_names=None):
        return [dict(c) for c in on_disk]

    saved = (main.get_post_job, main._review_context, main.record_tool_call, post_edit_plan.edit_dir, post_edit_plan.load_job_clips)
    main.get_post_job, main._review_context, main.record_tool_call, post_edit_plan.edit_dir = fake_job, fake_context, fake_audit, (lambda job: edit)
    post_edit_plan.load_job_clips = fake_job_clips
    client = TestClient(main.app)
    try:
        r = client.get("/post/jobs/7/edit-review")
        review = r.json()
        check("the review lists every shot with 'why' and lock state, and says Regenerate is available", r.status_code == 200 and review["can_regenerate"] is True
              and all("why" in s and "locked" in s for s in review["slots"]), r.text[:200])
        body = [s["index"] for s in review["slots"] if s["role"] == "body"]

        r = client.post("/post/jobs/7/edit-review/lock", json={"slot_index": body[1], "locked": True})
        plan = json.loads((edit / "edit_plan_latest.json").read_text())
        check("POST lock saves the lock in the plan file and answers with the locked slot", r.status_code == 200 and r.json()["slot"]["locked"] and body[1] in plan["review"]["locked"], r.text[:200])
        events = le.load_events(edit / le.EVENTS_FILE)
        check("...and writes a 'locked' learning event to the job's file", [e["outcome"] for e in events] == ["locked"] and events[0]["source"] == "review_page")
        check("...and the audit log", audit[-1][0] == "post_job_edit_review_lock_ui")

        before = {s["index"]: (s["file_id"], s["source_in"]) for s in plan["shots"]}
        plan_text_before = (edit / "edit_plan_latest.json").read_text()
        r = client.post("/post/jobs/7/edit-review/regenerate", json={"from_index": body[0], "to_index": body[4]})
        archives = [p.read_text() for p in edit.glob("edit_plan_prev_*.json")]
        check("POST regenerate archives the plan it replaces first (Plan history can bring it back)", len(archives) == 1 and archives[0] == plan_text_before)
        plan = json.loads((edit / "edit_plan_latest.json").read_text())
        after = {s["index"]: (s["file_id"], s["source_in"]) for s in plan["shots"]}
        res = r.json()
        check("POST regenerate re-picks the unlocked shots in the range and saves the plan", r.status_code == 200 and res["regenerated"]
              and all(after[i] != before[i] for i in res["regenerated"]) and after[body[1]] == before[body[1]] and res["locked_kept"] == [body[1]], r.text[:300])
        check("...returns the changed shots for the page to redraw", sorted(s["index"] for s in res["slots"]) == res["regenerated"])
        events = le.load_events(edit / le.EVENTS_FILE)
        check("...and logs one 'regenerated' event per changed shot", sum(e["outcome"] == "regenerated" for e in events) == len(res["regenerated"]))

        check("...answers with the learning event id of every regenerated shot", sorted(int(k) for k in res["event_ids"]) == res["regenerated"], res.get("event_ids"))
        first = str(res["regenerated"][0])
        r = client.post("/post/jobs/7/edit-review/reason", json={"slot_index": res["regenerated"][0], "reasons": ["client_request"], "note": "client", "explains": res["event_ids"][first]})
        check("POST reason after a change records it, and a client's request is not a taste signal", r.status_code == 200 and r.json() == {"recorded": True, "taste_signal": False, "explains": "regenerated"}, r.text)
        reasoned = [e for e in le.load_events(edit / le.EVENTS_FILE) if e["outcome"] == "reasoned"]
        check("...linked to exactly the change the page named", reasoned[-1]["context"]["explains"] == res["event_ids"][first])
        r = client.post("/post/jobs/7/edit-review/reason", json={"slot_index": res["regenerated"][0], "reasons": ["wrong_moment"], "explains": "ffffffffffffffff"})
        check("a reason naming a change that wasn't recorded is a 400", r.status_code == 400 and "wasn't recorded" in r.json()["detail"], r.text)
        sl = next(s for s in client.get("/post/jobs/7/edit-review").json()["slots"] if s["index"] == body[6])
        alt = next(a for a in sl["alternatives"] if a["origin"] == "other_clip")
        r = client.post("/post/jobs/7/edit-review/choice", json={"slot_index": body[6], "file_id": alt["file_id"], "source_in": alt["source_in"], "action": "swap"})
        check("POST choice (unchanged request) now also answers with the swap's learning event id", r.status_code == 200 and isinstance(r.json().get("event_id"), str)
              and {"slot", "approved", "total", "swapped", "slowed"} <= set(r.json()), r.text[:200])
        r = client.post("/post/jobs/7/edit-review/reason", json={"slot_index": body[1], "reasons": ["wrong_moment"]})
        check("a reason for a shot that wasn't changed is refused with a 400 and a plain message", r.status_code == 400 and "first" in r.json()["detail"], r.text)
        r = client.post("/post/jobs/7/edit-review/reason", json={"slot_index": res["regenerated"][0], "reasons": ["made_up"]})
        check("an unknown reason code is refused with a 400", r.status_code == 400, r.text)
        r = client.post("/post/jobs/7/edit-review/regenerate", json={"from_index": body[1], "to_index": body[1]})
        check("regenerating only a locked shot is a 400 that says so", r.status_code == 400 and "locked" in r.json()["detail"], r.text)
        r = client.post("/post/jobs/7/edit-review/lock", json={"slot_index": 999, "locked": True})
        check("locking a shot that doesn't exist is a 400", r.status_code == 400, r.text)

        r = client.get("/post/learning/reason-codes")
        codes = r.json()["reasons"]
        check("the reason codes list has the 12 labels, with only 'client_request' marked as not taste", len(codes) == 12 and [c["code"] for c in codes if not c["taste"]] == ["client_request"])
        r = client.get("/post/jobs/7/learning-events")
        data = r.json()
        check("the job's learning summary counts what was logged and proposes nothing from so little", r.status_code == 200 and data["summary"]["by_outcome"]["regenerated"] >= 1
              and data["proposed_adjustments"] is None and data["reasons"] == {"client_request": 1}, data)

        # ---- variants ------------------------------------------------------------------------------------------------------------------------------
        r = client.get("/post/style-library")
        lib = r.json()
        check("the style library lists 11 directions, the buildable ones and the default set", r.status_code == 200 and len(lib["styles"]) == 11 and lib["min_variants"] == 2
              and lib["max_variants"] == 4 and lib["default_directions"][0] == "music-led-montage")
        r = client.get("/post/jobs/7/edit-variants")
        check("with no sets yet the list is empty, not an error", r.status_code == 200 and r.json()["sets"] == [] and r.json()["latest"] is None, r.text)
        result = pv.build_set(["music-led-montage", "premium-luxury"], profile=post_style.usual_pace_profile(), hits=beat_hits(160), music_in=10.0, duration=30.0, fps=25.0,
                              clips=CLIPS, seed=7, set_id="20261022T130000")
        pv._write_set(pv.variants_dir(edit) / "20261022T130000", result, pv.set_summary(result, song="/x/song.mp3", music_in=10.0, duration=30.0, made_at="2026-10-22T13:00:00"))
        r = client.get("/post/jobs/7/edit-variants")
        check("after a set is saved the list shows it with its full comparison", r.json()["sets"][0]["set_id"] == "20261022T130000" and len(r.json()["latest"]["variants"]) == 2)
        r = client.get("/post/jobs/7/edit-variants/20261022T130000/2")
        check("one variant comes back as a complete plan", r.status_code == 200 and r.json()["style"] == "library:premium-luxury" and r.json()["shots"])
        r = client.get("/post/jobs/7/edit-variants/..%2F..%2Fetc")
        check("a set id with path tricks is a 404", r.status_code == 404, r.status_code)
        r = client.get("/post/jobs/7/edit-variants/20261022T130000/9")
        check("a variant that doesn't exist is a 404", r.status_code == 404)
        plan_before = (edit / "edit_plan_latest.json").read_text()
        v2_clip = json.loads((pv.variants_dir(edit) / "20261022T130000" / "variant_2.json").read_text())["shots"][0]["name"]
        (media / v2_clip).rename(media / (v2_clip + ".away"))
        r = client.post("/post/jobs/7/edit-variants/use", json={"set_id": "20261022T130000", "index": 2})
        check("a variant whose clip is missing from the drive is refused with a 400 naming it, and the current plan is left alone",
              r.status_code == 400 and "missing media" in r.json()["detail"] and (edit / "edit_plan_latest.json").read_text() == plan_before, r.text[:200])
        (media / (v2_clip + ".away")).rename(media / v2_clip)
        r = client.post("/post/jobs/7/edit-variants/use", json={"set_id": "20261022T130000", "index": 2})
        latest = json.loads((edit / "edit_plan_latest.json").read_text())
        archived = [json.loads(p.read_text()) for p in edit.glob("edit_plan_prev_*.json")]
        check("POST use makes the variant the job's plan", r.status_code == 200 and r.json()["style"] == "library:premium-luxury" and latest["style"] == "library:premium-luxury", r.text)
        check("...and the plan it replaced (with his locks and regenerations) is archived, not lost", any(a.get("review", {}).get("locked") == [body[1]] for a in archived)
              and any(json.dumps(a, sort_keys=True) == json.dumps(json.loads(plan_before), sort_keys=True) for a in archived))
        events = le.load_events(edit / le.EVENTS_FILE)
        chosen = [e for e in events if e["outcome"] == "chosen"]
        check("...and logs which direction he chose and what he was offered", len(chosen) == 1 and chosen[0]["context"]["chosen"] == "premium-luxury"
              and chosen[0]["context"]["offered"] == ["music-led-montage", "premium-luxury"])
        check("choosing a variant is not counted as a vote about any kind of moment", le.kind_evidence(chosen) == {})
        r = client.post("/post/jobs/8/edit-variants/use", json={"set_id": "20261022T130000", "index": 1})
        check("another job's id is a 404", r.status_code == 404)
        check("the variants page is served", client.get("/static/edit_variants.html").status_code == 200)
        page = client.get("/static/edit_review.html").text
        check("the review page links to the variants page and has the new controls", "edit_variants.html" in page and "edit-review/lock" in page and "edit-review/regenerate" in page
              and "edit-review/reason" in page)
    finally:
        main.app.dependency_overrides.clear()
        main.get_post_job, main._review_context, main.record_tool_call, post_edit_plan.edit_dir, post_edit_plan.load_job_clips = saved

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
