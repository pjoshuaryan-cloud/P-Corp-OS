"""Tests for the review page's new controls (backend/app/post_review.py): earlier / later timing, locking a shot, regenerating a section, the reason chips, "why this
shot", and the learning events they write (post_learning_events). Synthetic footage with real steadiness measurements; no drive, no API, no Premiere.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python review_additions_test.py"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from app import post_learning_events as le, post_review as pr, post_style  # noqa: E402
from app.post_edit_highlight import build_highlight_plan  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
BY_ID = {c["file_id"]: c for c in CLIPS}
PLAN0 = build_highlight_plan(profile=post_style.usual_pace_profile(), hits=beat_hits(160), music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, bookend_file_id=None, seed=7)
FPS = PLAN0["fps"]


def fresh():
    return copy.deepcopy(PLAN0)


def timing(plan):
    return [(s["index"], s["start_frame"], s["duration_frames"]) for s in plan["shots"]]


def no_cut(plan, shot):
    w = pr.post_pick.valid_alternative(plan, CLIPS, shot["index"], shot["file_id"], shot["source_in"])
    return w is not None


# ---- earlier / later -----------------------------------------------------------------------------------------------------------------------------
plan = fresh()
review = pr.build_review(plan, CLIPS)
body = [s for s in review["slots"] if s["role"] == "body"]
with_nudge = [s for s in body if any(a["origin"] in ("earlier", "later") for a in s["alternatives"])]
check("most body shots offer the same moment earlier and/or later", len(with_nudge) >= 0.7 * len(body), (len(with_nudge), len(body)))
ok = True
for s in with_nudge:
    shot = next(x for x in plan["shots"] if x["index"] == s["index"])
    clip = BY_ID[shot["file_id"]]
    for a in s["alternatives"]:
        if a["origin"] not in ("earlier", "later"):
            continue
        step = abs(a["source_in"] - shot["source_in"])
        ok &= a["file_id"] == shot["file_id"] and pr.NUDGE_MIN_SECONDS - 1e-6 <= step <= pr.NUDGE_MAX_SECONDS + 1e-6 and (a["source_in"] < shot["source_in"]) == (a["origin"] == "earlier")
        ok &= 0 <= a["source_in"] and a["source_in"] + a["seconds"] <= clip["duration"] - 0.04 + 1e-6
        ok &= pr.post_pick.valid_alternative(plan, CLIPS, s["index"], a["file_id"], a["source_in"]) is not None
check("every earlier/later option is the same clip, moved 0.2-1 s the right way, inside the clip, with no cut inside", ok)
check("opening and closing shots are never offered a timing nudge", all(not any(a["origin"] in ("earlier", "later") for a in s["alternatives"]) for s in review["slots"] if s["role"] != "body"))
check("every planned shot says why it was chosen", all(s["why"] for s in review["slots"]), [s["why"] for s in review["slots"]][:3])
check("...and the reason is honest about where the moment came from", all(("Claude" in s["why"]) or ("measured" in s["why"]) or ("little analysis" in s["why"]) for s in review["slots"]))

target = with_nudge[0]
nudge = next(a for a in target["alternatives"] if a["origin"] in ("earlier", "later"))
before_timing = timing(plan)
out = pr.apply_choice(plan, CLIPS, target["index"], nudge["file_id"], nudge["source_in"], "swap")
shot = next(x for x in plan["shots"] if x["index"] == target["index"])
check("choosing 'earlier'/'later' moves the stretch and nothing else (cut timing unchanged)", shot["source_in"] == nudge["source_in"] and timing(plan) == before_timing)
check("...the shot's candidate record now describes the stretch it really shows", shot["candidate"]["source_in"] == round(shot["source_in"], 3)
      and shot["candidate"]["source_out"] == round(shot["source_out"], 3) and shot["candidate"]["origin"] == "picked_in_review", shot["candidate"])
check("...and its moment says it was moved in review", shot["moment_source"].startswith(f"picked in review -- moved {nudge['origin']}"), shot["moment_source"])

with tempfile.TemporaryDirectory() as tmp:
    edit = Path(tmp)
    pr.log_record(edit, 9, plan, "swap", out)
    events = le.load_events(edit / le.EVENTS_FILE)
    check("a nudge is logged as a 'moved' event, not a 'swapped' one", [e["outcome"] for e in events] == ["moved"], [e["outcome"] for e in events])
    check("...so it is not a vote against that kind of moment", le.kind_evidence(events) == {}, le.kind_evidence(events))
    check("the review log line is still written exactly as before (the taste tools read it)", json.loads((edit / "review_log.jsonl").read_text().splitlines()[0])["action"] == "swap")

# ---- a real swap, then reasons --------------------------------------------------------------------------------------------------------------------
plan = fresh()
review = pr.build_review(plan, CLIPS)
slot = next(s for s in review["slots"] if s["role"] == "body" and any(a["origin"] == "other_clip" for a in s["alternatives"]) and s["current"].get("kind") is None)
# give the current moment a known kind so the swap is a vote (synthetic plans pick steady windows; the kind lives on the shot's candidate)
alt = next(a for a in slot["alternatives"] if a["origin"] == "other_clip")
with tempfile.TemporaryDirectory() as tmp:
    edit = Path(tmp)
    try:
        pr.reason_event(edit, 9, plan, slot["index"], ["client_request"], None)
        check("a reason for a shot that was never changed is refused", False)
    except pr.ReviewError as exc:
        check("a reason for a shot that was never changed is refused", "first" in str(exc), str(exc))
    out = pr.apply_choice(plan, CLIPS, slot["index"], alt["file_id"], alt["source_in"], "swap")
    rec = {"ts": "2026-10-22T10:00:00", "job_id": 9, "style": plan.get("style"), "action": "swap", "slot": out["slot"], "chosen": out["chosen"],
           "passed_over": [dict(c, kind="hero") if c["origin"] == "current" else c for c in out["shown"] if c["id"] != out["chosen"]["id"]], "kept_current": False}
    le.record_for_job(edit, le.from_review_record(rec))
    events = le.load_events(edit / le.EVENTS_FILE)
    check("a swap away from a hero moment counts as one vote against heroes", le.kind_evidence(events).get("hero", {}).get("changed") == 1, le.kind_evidence(events))
    for bad in ([], ["not_a_reason"]):
        try:
            pr.reason_event(edit, 9, plan, slot["index"], bad, None)
            check(f"reasons {bad!r} are refused", False)
        except pr.ReviewError:
            check(f"reasons {bad!r} are refused", True)
    reason = pr.reason_event(edit, 9, plan, slot["index"], ["client_request"], "  the client wanted the logo  ")
    check("a reason names the change it explains", reason["context"]["explains"] == events[-1]["id"] and reason["outcome"] == "reasoned" and reason["note"] == "the client wanted the logo")
    check("a client's request is never a taste signal", reason["taste_signal"] is False)
    le.record_for_job(edit, [reason])
    events = le.load_events(edit / le.EVENTS_FILE)
    check("once he says the client asked for it, that swap no longer counts against heroes", le.kind_evidence(events) == {}, le.kind_evidence(events))
    check("...and it is no longer counted as a taste signal at all", le.summarize(events)["taste_signals"] == 0, le.summarize(events))
    taste_reason = pr.reason_event(edit, 9, plan, slot["index"], ["wrong_moment"], None)
    le.record_for_job(edit, [taste_reason])
    events = le.load_events(edit / le.EVENTS_FILE)
    check("a taste reason (wrong moment) given later does not bring a client-requested swap back", le.kind_evidence(events) == {}, le.kind_evidence(events))
    check("the reason counts are kept for him to see", le.reason_counts(events) == {"client_request": 1, "wrong_moment": 1}, le.reason_counts(events))

# ---- lock ----------------------------------------------------------------------------------------------------------------------------------------------
plan = fresh()
body_idx = [s["index"] for s in plan["shots"] if s["role"] == "body"]
out = pr.set_lock(plan, body_idx[3], True)
review = pr.build_review(plan, CLIPS)
check("a locked shot shows as locked and as reviewed", next(s for s in review["slots"] if s["index"] == body_idx[3])["locked"] and body_idx[3] in plan["review"]["approved"]
      and review["locked"] == 1)
ev = pr.review_events(9, plan, "locked", out)
check("locking writes one confirmed 'locked' event that is not a vote", len(ev) == 1 and ev[0]["outcome"] == "locked" and ev[0]["confidence"] == "confirmed" and le.kind_evidence(ev) == {})
try:
    pr.set_lock(plan, 999, True)
    check("locking a shot that doesn't exist is refused", False)
except pr.ReviewError:
    check("locking a shot that doesn't exist is refused", True)

# ---- regenerate ------------------------------------------------------------------------------------------------------------------------------------------
lo, hi = body_idx[2], body_idx[7]
before = {s["index"]: (s["file_id"], s["source_in"]) for s in plan["shots"]}
before_timing = timing(plan)
res = pr.regenerate_section(plan, CLIPS, lo, hi)
after = {s["index"]: (s["file_id"], s["source_in"]) for s in plan["shots"]}
changed = {c["index"] for c in res["regenerated"]}
check("regenerate changes the unlocked shots in the range", changed and changed <= set(range(lo, hi + 1)) - {body_idx[3]} and all(after[i] != before[i] for i in changed), res)
check("...leaves the locked shot inside the range exactly as it was", after[body_idx[3]] == before[body_idx[3]] and res["locked_kept"] == [body_idx[3]])
check("...leaves every shot outside the range exactly as it was", all(after[i] == before[i] for i in before if not lo <= i <= hi))
check("...and never touches cut timing", timing(plan) == before_timing)
shots = {s["index"]: s for s in plan["shots"]}
check("every regenerated shot is a clean stretch (no cut inside), inside its clip", all(no_cut(plan, shots[i]) and shots[i]["source_out"] <= BY_ID[shots[i]["file_id"]]["duration"] + 0.05 for i in changed))
check("...with a candidate record describing it", all(shots[i]["candidate"]["source_in"] == round(shots[i]["source_in"], 3) for i in changed))
check("...and keeps its planned moment as 'the original' so one click undoes it", all(plan["review"]["original"][str(i)]["source_in"] == before[i][1] for i in changed))
review = pr.build_review(plan, CLIPS)
check("the original is offered back as an alternative", all(any(a["origin"] == "original" for a in next(s for s in review["slots"] if s["index"] == i)["alternatives"]) for i in changed))
check("a regenerated shot has to be reviewed again", not any(i in plan["review"]["approved"] for i in changed))
res2 = pr.regenerate_section(plan, CLIPS, lo, hi)
third = {s["index"]: (s["file_id"], s["source_in"]) for s in plan["shots"]}
moved_on = {c["index"] for c in res2["regenerated"]}
check("pressing Regenerate again moves every shot on (this footage has fresh stretches left)", moved_on == changed and not res2["unchanged"], res2["unchanged"])
check("...and no shot swings back to a stretch it already showed", all(third[i] != before[i] and third[i] != after[i] for i in moved_on), (before, after, third))
ev = pr.review_events(9, plan, "regenerated", res)
check("each regenerated shot writes a confirmed 'regenerated' event, none of them a vote", len(ev) == len(res["regenerated"]) and all(e["outcome"] == "regenerated" for e in ev)
      and le.kind_evidence(ev) == {})
pr.set_lock(plan, body_idx[0], True)
try:
    pr.regenerate_section(plan, CLIPS, body_idx[0], body_idx[0])
    check("regenerating a locked shot alone is refused", False)
except pr.ReviewError as exc:
    check("regenerating a locked shot alone is refused", "locked" in str(exc), str(exc))
reel = fresh()
reel["mode"] = "reel"
try:
    pr.regenerate_section(reel, CLIPS, lo, hi)
    check("a plan whose moments come from Claude's descriptions (a reel) refuses to regenerate, and says why", False)
except pr.ReviewError as exc:
    check("a plan whose moments come from Claude's descriptions (a reel) refuses to regenerate, and says why", "one at a time" in str(exc), str(exc))
check("the review says whether Regenerate is available", pr.build_review(fresh(), CLIPS)["can_regenerate"] is True)

# ---- Regenerate never touches a shot he decided on (found by the independent review: it used to throw his swaps away) ---------------------------------
rp = fresh()
bi = [s["index"] for s in rp["shots"] if s["role"] == "body"]
by = {s["index"]: s for s in rp["shots"]}
slot_s = next(x for x in pr.build_review(rp, CLIPS)["slots"] if x["index"] == bi[1])
alt_s = next(a for a in slot_s["alternatives"] if a["origin"] == "other_clip")
pr.apply_choice(rp, CLIPS, bi[1], alt_s["file_id"], alt_s["source_in"], "swap")            # picked by him
pr.apply_choice(rp, CLIPS, bi[2], by[bi[2]]["file_id"], by[bi[2]]["source_in"], "approve")  # kept by him
slow_i = next(i for i in bi[3:7] if pr.slow_check(rp, BY_ID[by[i]["file_id"]], by[i])[0])
pr.set_speed(rp, CLIPS, slow_i, 0.5)                                                         # slowed by him (also counts as reviewed)
mine = {i: (by[i]["file_id"], by[i]["source_in"], by[i].get("speed")) for i in (bi[1], bi[2], slow_i)}
res_r = pr.regenerate_section(rp, CLIPS, bi[0], bi[8])
check("Regenerate leaves the shot he picked, the one he kept and the one he slowed exactly as they are",
      all((by[i]["file_id"], by[i]["source_in"], by[i].get("speed")) == mine[i] for i in mine), (mine, {i: (by[i]["file_id"], by[i]["source_in"]) for i in mine}))
check("...says which of his it kept, and why", {k["index"]: k["why"] for k in res_r["kept_yours"]} == {bi[1]: "picked by you", bi[2]: "kept by you", slow_i: "slowed by you"},
      res_r["kept_yours"])
check("...and re-picks only the others", {c["index"] for c in res_r["regenerated"]} <= set(bi[0:9]) - set(mine) and res_r["regenerated"])
first_regen = {c["index"]: (c["after"]["file_id"], c["after"]["source_in"]) for c in res_r["regenerated"]}
res_r2 = pr.regenerate_section(rp, CLIPS, bi[0], bi[8])
again = next(c for c in res_r2["regenerated"] if c["index"] in first_regen)
slot_g = next(x for x in pr.build_review(rp, CLIPS)["slots"] if x["index"] == again["index"])
prev = [a for a in slot_g["alternatives"] if a["origin"] == "previous"]
check("after a second Regenerate, the moment it showed just before is offered back ('before regenerate'), as well as the planner's original",
      prev and (prev[0]["file_id"], prev[0]["source_in"]) == first_regen[again["index"]] and any(a["origin"] == "original" for a in slot_g["alternatives"]), slot_g["alternatives"][:3])
try:
    pr.regenerate_section(rp, CLIPS, bi[1], bi[2])
    check("a range holding only his own decisions is refused, and says why", False)
except pr.ReviewError as exc:
    check("a range holding only his own decisions is refused, and says why", "decided on" in str(exc), str(exc))

# a regeneration can set the shot's kind of moment (event_kind); a later swap must not keep it
k_shot = next(s for s in rp["shots"] if s["index"] == again["index"])
k_shot["event_kind"] = "hero"
slot_k = next(x for x in pr.build_review(rp, CLIPS)["slots"] if x["index"] == k_shot["index"])
alt_k = next(a for a in slot_k["alternatives"] if a["origin"] == "other_clip")
pr.apply_choice(rp, CLIPS, k_shot["index"], alt_k["file_id"], alt_k["source_in"], "swap")
ev_k = k_shot["candidate"].get("event") or {}
check("a swap drops the old shot's kind of moment: the record's role is the NEW stretch's own", "event_kind" not in k_shot
      and k_shot["candidate"]["role"] == (ev_k.get("kind") or "hold"), (k_shot.get("event_kind"), k_shot["candidate"]["role"], ev_k.get("kind")))

with tempfile.TemporaryDirectory() as tmp:
    edit = Path(tmp)
    lp = fresh()
    li = [s["index"] for s in lp["shots"] if s["role"] == "body"][0]
    for state in (True, False, True):
        le.record_for_job(edit, pr.review_events(9, lp, "locked" if state else "unlocked", pr.set_lock(lp, li, state)))
    check("lock, unlock, lock moments apart are three events, not one (live events are timed to the microsecond)",
          [e["outcome"] for e in le.load_events(edit / le.EVENTS_FILE)] == ["locked", "unlocked", "locked"])
    # an explicit link: the reason names exactly the change the page swapped
    sl = next(x for x in pr.build_review(lp, CLIPS)["slots"] if x["role"] == "body" and x["index"] != li)
    a1 = next(a for a in sl["alternatives"] if a["origin"] == "other_clip")
    id1 = pr.log_record(edit, 9, lp, "swap", pr.apply_choice(lp, CLIPS, sl["index"], a1["file_id"], a1["source_in"], "swap"))
    sl2 = next(x for x in pr.build_review(lp, CLIPS)["slots"] if x["index"] == sl["index"])
    a2 = next(a for a in sl2["alternatives"] if a["origin"] == "other_clip")
    id2 = pr.log_record(edit, 9, lp, "swap", pr.apply_choice(lp, CLIPS, sl["index"], a2["file_id"], a2["source_in"], "swap"))
    check("log_record hands back the id of the learning event it wrote", isinstance(id1, str) and isinstance(id2, str) and id1 != id2)
    r1 = pr.reason_event(edit, 9, lp, sl["index"], ["client_request"], None, explains=id1)
    check("a reason sent with a change's id explains THAT change, even when a later one exists", r1["context"]["explains"] == id1)
    try:
        pr.reason_event(edit, 9, lp, sl["index"], ["client_request"], None, explains="0000000000000000")
        check("a reason naming a change that wasn't recorded is refused (it never falls back to another change)", False)
    except pr.ReviewError as exc:
        check("a reason naming a change that wasn't recorded is refused (it never falls back to another change)", "wasn't recorded" in str(exc), str(exc))
    # a nudge accepted from a page that is out of date (the review no longer lists it) is still a re-timing
    np_ = fresh()
    ns = next(x for x in pr.build_review(np_, CLIPS)["slots"] if any(a["origin"] == "later" for a in x["alternatives"]))
    nudge_l = next(a for a in ns["alternatives"] if a["origin"] == "later")
    real_nudges = pr._nudges
    pr._nudges = lambda *a, **k: []
    try:
        out_n = pr.apply_choice(np_, CLIPS, ns["index"], nudge_l["file_id"], nudge_l["source_in"], "swap")
    finally:
        pr._nudges = real_nudges
    check("a nudge from an out-of-date page is still labelled 'later'", out_n["chosen"]["origin"] == "later", out_n["chosen"]["origin"])
    nid = pr.log_record(edit, 9, np_, "swap", out_n)
    check("...so it is logged as 'moved', not as a vote against the moment", next(e for e in le.load_events(edit / le.EVENTS_FILE) if e["id"] == nid)["outcome"] == "moved")

# ---- final review's findings: unlock, repeated keeps, his own picks, the reason fallback ------------------------------------------------------------------
up = fresh()
ub = [s["index"] for s in up["shots"] if s["role"] == "body"]
ush = {s["index"]: s for s in up["shots"]}
pr.set_lock(up, ub[0], True)
pr.set_lock(up, ub[0], False)
check("lock then unlock: the shot is no longer 'decided', so Regenerate may replace it again (as the Unlock button says)",
      pr.decided(ush[ub[0]], up["review"]) is None and ub[0] not in up["review"]["approved"], (pr.decided(ush[ub[0]], up["review"]), up["review"]["approved"]))
pr.set_lock(up, ub[1], True)
pr.apply_choice(up, CLIPS, ub[1], ush[ub[1]]["file_id"], ush[ub[1]]["source_in"], "approve")
pr.set_lock(up, ub[1], False)
check("lock, Keep this, unlock: his Keep stands (only a lock's own approval is taken back)", pr.decided(ush[ub[1]], up["review"]) == "kept by you")

with tempfile.TemporaryDirectory() as tmp:
    edit = Path(tmp)
    vp = fresh()
    vb = [s["index"] for s in vp["shots"] if s["role"] == "body"]
    vsh = {s["index"]: s for s in vp["shots"]}
    for i in range(3):   # "Keep this", "Keep this (again)", "Keep this (again)" on a shot with a known kind
        rec_out = pr.apply_choice(vp, CLIPS, vb[0], vsh[vb[0]]["file_id"], vsh[vb[0]]["source_in"], "approve")
        rec_out["chosen"] = {**rec_out["chosen"], "kind": "hero"}
        pr.log_record(edit, 9, vp, "approve", rec_out)
    ev3 = le.load_events(edit / le.EVENTS_FILE)
    check("three 'Keep this' clicks on one shot are three records but ONE vote", len(ev3) >= 1 and le.kind_evidence(ev3).get("hero", {}).get("n") == 1, le.kind_evidence(ev3))
    sl_o = next(x for x in pr.build_review(vp, CLIPS)["slots"] if x["index"] == vb[1])
    al_o = next(a for a in sl_o["alternatives"] if a["origin"] == "other_clip")
    pr.apply_choice(vp, CLIPS, vb[1], al_o["file_id"], al_o["source_in"], "swap")          # now the shot holds HIS pick
    own = pr.apply_choice(vp, CLIPS, vb[1], vsh[vb[1]]["file_id"], vsh[vb[1]]["source_in"], "approve")
    own["chosen"] = {**own["chosen"], "kind": "reveal"}
    pr.log_record(edit, 9, vp, "approve", own)
    check("keeping a moment he picked himself is recorded but is not a vote on the planner's kinds", "reveal" not in le.kind_evidence(le.load_events(edit / le.EVENTS_FILE)),
          le.kind_evidence(le.load_events(edit / le.EVENTS_FILE)))
    observed_move = le.make_event(category="observed_edit", confidence="observed", outcome="moved", source="learn_button", job_id=9, ts="2026-10-22T23:00:00",
                                  slot={"index": vb[2], "role": None, "seconds": None, "cut_at": None}, plan_ref={"file": None, "made_at": None, "basis": "matched"})
    le.record_for_job(edit, [observed_move])
    try:
        pr.reason_event(edit, 9, vp, vb[2], ["client_request"], None)
        check("a reason never attaches to a 'moved' seen in his finished timeline (only to his own changes on the review page)", False)
    except pr.ReviewError:
        check("a reason never attaches to a 'moved' seen in his finished timeline (only to his own changes on the review page)", True)

# ---- slow motion keeps the candidate record honest -------------------------------------------------------------------------------------------------------
sp = fresh()
s = next(x for x in sp["shots"] if x["role"] == "body" and pr.slow_check(sp, BY_ID[x["file_id"]], x)[0])
orig = copy.deepcopy(s)
pr.set_speed(sp, CLIPS, s["index"], 0.5)
check("slowing a shot re-describes the half-length stretch it now shows", s["candidate"]["source_in"] == round(s["source_in"], 3)
      and abs(s["candidate"]["duration"] - (s["source_out"] - s["source_in"])) < 0.002, s["candidate"])
pr.set_speed(sp, CLIPS, s["index"], 1.0)
check("slow motion off gives back the identical shot, its planner record (with the score) included", s == orig,
      {k: (orig.get(k), s.get(k)) for k in set(orig) | set(s) if orig.get(k) != s.get(k)})
pr.set_speed(sp, CLIPS, s["index"], 0.5)
slot = next(x for x in pr.build_review(sp, CLIPS)["slots"] if x["index"] == s["index"])
alt = next(a for a in slot["alternatives"] if a["origin"] == "other_clip")
pr.apply_choice(sp, CLIPS, s["index"], alt["file_id"], alt["source_in"], "swap")
pr.set_speed(sp, CLIPS, s["index"], 1.0)
check("slow, then swap, then normal speed: the record describes the NEW clip's real-time stretch, never the swapped-out one", s["candidate"]["media"]["file_id"] == s["file_id"] == alt["file_id"]
      and s["candidate"]["source_in"] == round(s["source_in"], 3) and "candidate_real_time" not in s, s["candidate"])

# ---- the plan stays a valid plan for the plugin ----------------------------------------------------------------------------------------------------------
frames = 0
ok = True
for s in plan["shots"]:
    ok &= s["start_frame"] == frames
    frames += s["duration_frames"]
    ok &= abs((s["source_out"] - s["source_in"]) * (s.get("speed") or 1.0) ** -1 - s["duration_frames"] / FPS) < 0.05 if s.get("speed") else abs((s["source_out"] - s["source_in"]) - s["duration_frames"] / FPS) < 0.05
check("after nudges, locks and regenerations every shot still fills its slot exactly, back to back", ok and frames == plan["duration_frames"])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
