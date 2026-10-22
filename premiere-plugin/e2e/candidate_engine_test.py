"""Tests for the candidate-moment engine (backend/app/post_candidate_moments.py) and the picker options it brings (style role weights, cross-variant
avoidance, first/last-shot roles, learned preferences, pacing curves).

The first part is a REGRESSION GUARD: plans built from deterministic synthetic clips must be exactly what the planner produced before the engine existed
(fixtures/golden_plans.json, captured from the code as it was on 2026-10-22, before any change). Only the new "candidate" field may be added to a shot.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python candidate_engine_test.py
      (with --capture to write the golden file; only ever done once, before the engine was added)"""
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_edit_highlight as hl, post_edit_plan as pe, post_pick, post_steady as sd, post_style as ps  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden_plans.json"
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


# ---- deterministic synthetic clips with real steadiness measurements and described moments --------------------------------------------------------
H, W, F = sd.FRAME_H, sd.FRAME_W, int(sd.SAMPLE_FPS)


def _blur(img, sigma):
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    o = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 1, img)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 0, o)


def _scene(seed):
    img = _blur(np.random.default_rng(seed).random((H + 40, W + 200)).astype(np.float32), 1.4)
    return (img - img.min()) / (img.max() - img.min()) * 255


def _frames(kind, seed, seconds):
    rng = np.random.default_rng(1000 + seed)
    base = _scene(seed)
    n = int(seconds * F)
    out = []
    for i in range(n):
        dx = i if kind == "moving" else (int(6 * abs(np.sin(i / 3.0))) if kind == "burst" and n // 3 <= i <= n // 2 else 0)
        out.append(np.clip(base[20:20 + H, 20 + dx:20 + dx + W] + rng.normal(0, 0.8, (H, W)), 0, 255))
    return out


def make_clips():
    kinds = ["static", "moving", "burst", "static", "moving", "burst", "moving", "static"] * 3
    clips = []
    for i, kind in enumerate(kinds):
        seconds = 6 + (i % 4)
        m = sd.measure(np.stack(_frames(kind, i + 1, seconds)).astype(np.uint8))
        clip = {"file_id": i + 1, "name": f"C{i + 1:04d}.MP4", "path": f"/x/C{i + 1:04d}.MP4", "duration": m["seconds"], "created": "", "picks": [], "steady": m,
                "thumbs": sd.decode_thumbs(m), "scene": ["kitchen", "street", "stage", "beach", "office", "crowd"][i % 6], "people": i % 2 == 0, "fps": 50.0}
        if i % 3 != 2:   # two clips in three were described
            r = random.Random(i)
            clip["events"] = sorted([{"t": round(r.uniform(0.8, m["seconds"] - 0.8), 2), "kind": ["action", "reaction", "camera_move", "reveal", "hero"][(i + j) % 5],
                                      "punch": r.randint(4, 9), "what": f"moment {j} of clip {i + 1}"} for j in range(3)], key=lambda e: -e["punch"])
        clips.append(clip)
    return clips


def beat_hits(seconds, bpm=128, seed=3):
    r = random.Random(seed)
    beat, out, t, i = 60.0 / bpm, [], 0.0, 0
    while t < seconds:
        out.append([round(t, 3), (96 if i % 4 == 0 else 80) + r.random() * 2])
        out.append([round(t + beat / 2, 3), 56 + r.random() * 6])
        t += beat
        i += 1
    return out


def strip(plan):
    """What the golden file compares: every shot without the new 'candidate' field, plus the zooms and repetition report."""
    return {"shots": [{k: v for k, v in s.items() if k != "candidate"} for s in plan["shots"]], "zooms": (plan.get("zooms") or {}).get("items"),
            "repetition": (plan.get("checks") or {}).get("repetition")}


def current_outputs(clips):
    usual = ps.profile_from_references([ps.USUAL_PACE_SLUG])
    calm = ps.profile_from_references(["corporate-highlight-calm"])
    hits = beat_hits(140)
    out = {}
    for label, prof, pace, dur in (("usual_30", usual, 1.0, 30.0), ("calm_40", calm, 1.3, 40.0)):
        sd.clear_series_cache()
        plan = hl.build_highlight_plan(profile=prof, hits=hits, music_in=10.0, duration=dur, fps=25.0, clips=clips, bookend_file_id=None, seed=5, pace=pace, with_opener=False)
        out[label] = strip(plan)
        alts = post_pick.alternatives(plan, clips)
        out[label + "_alternatives"] = {str(k): [{kk: vv for kk, vv in a.items() if kk in ("file_id", "source_in", "seconds", "origin", "tag")} for a in v] for k, v in alts.items()}
    reel = ps.profile_from_references(["jd-sports-moa-draft-01"])
    sd.clear_series_cache()
    rplan = pe.build_plan(profile=reel, hits=hits, music_in=10.0, duration=20.0, fps=25.0, clips=clips, bookend_file_id=None, seed=5)
    out["reel_20"] = strip(rplan)
    return json.loads(json.dumps(out))   # normalise tuples/numpy for comparison


CLIPS = make_clips()
if "--capture" in sys.argv:
    if GOLDEN.exists():
        print(f"{GOLDEN} already exists; delete it by hand if you really mean to re-capture (it must come from the code BEFORE the engine)")
        sys.exit(1)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(current_outputs(CLIPS), indent=1))
    print(f"captured {GOLDEN}")
    sys.exit(0)

golden = json.loads(GOLDEN.read_text())
now = current_outputs(CLIPS)
for key in golden:
    check(f"regression: '{key}' is exactly what the planner produced before the engine existed", now.get(key) == golden[key],
          next((f"first difference at shot {i}: {a} vs {b}" for i, (a, b) in enumerate(zip(now.get(key, {}).get('shots', []) if isinstance(now.get(key), dict) and 'shots' in now.get(key, {}) else [], golden[key].get('shots', []) if isinstance(golden[key], dict) and 'shots' in golden[key] else [])) if a != b), "differs"))

# ---- the other paths through the same shared code (opening-card slot, bookend clip, narrated story) --------------------------------------------------
# Captured 2026-10-22 from the COMMITTED planner (a git worktree at 65392a4, before this upgrade) with the same synthetic clips; added after the independent
# review pointed out the first golden file covered neither the story planner nor the opener / bookend branches of assign_clips_to_slots.
GOLDEN_PATHS = GOLDEN.with_name("golden_plans_paths.json")


def path_outputs(clips):
    from app import post_edit_story as st
    usual = ps.profile_from_references([ps.USUAL_PACE_SLUG])
    calm = ps.profile_from_references(["corporate-highlight-calm"])
    hits = beat_hits(140)
    out = {}
    sd.clear_series_cache()
    out["usual_30_opener"] = strip(hl.build_highlight_plan(profile=usual, hits=hits, music_in=10.0, duration=30.0, fps=25.0, clips=clips, bookend_file_id=None, seed=5, pace=1.0, with_opener=True))
    sd.clear_series_cache()
    out["calm_40_bookend"] = strip(hl.build_highlight_plan(profile=calm, hits=hits, music_in=10.0, duration=40.0, fps=25.0, clips=clips, bookend_file_id=4, seed=5, pace=1.3, with_opener=True))
    story = ps.profile_from_references(["corporate-distribution-company"])
    for label, bookend in (("story_40", None), ("story_40_bookend", 4)):
        sd.clear_series_cache()
        tl = st.story_timeline(story.story, fps=25.0, script=None, target_seconds=40.0, seed=5, has_bookend=bookend is not None, with_opener=True, pace=1.3)
        out[label] = strip(st.build_story_plan(profile=story, timeline=tl, music_in=10.0, fps=25.0, clips=clips, bookend_file_id=bookend, seed=5))
    return json.loads(json.dumps(out))


golden_paths = json.loads(GOLDEN_PATHS.read_text())
now_paths = path_outputs(CLIPS)
for key in golden_paths:
    a_, b_ = now_paths.get(key, {}).get("shots", []), golden_paths[key]["shots"]
    check(f"regression: '{key}' is exactly what the committed planner produced", now_paths.get(key) == golden_paths[key],
          next((f"first difference at shot {i}: {x} vs {y}" for i, (x, y) in enumerate(zip(a_, b_)) if x != y), f"{len(a_)} vs {len(b_)} shots / zooms / repetition differ"))

# ---- candidate records on every planned shot ------------------------------------------------------------------------------------------------------
from app import post_candidate_moments as cm  # noqa: E402

usual = ps.profile_from_references([ps.USUAL_PACE_SLUG])
hits = beat_hits(140)


def plan_with(**kw):
    sd.clear_series_cache()
    args = dict(profile=usual, hits=hits, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, bookend_file_id=None, seed=5, pace=1.0, with_opener=False)
    args.update(kw)
    return hl.build_highlight_plan(**args)


base = plan_with()
cands = [s.get("candidate") for s in base["shots"]]
check("every planned shot carries a candidate record of the current schema", all(c and c["schema"] == cm.CANDIDATE_SCHEMA_VERSION and c["engine"] == cm.ENGINE_VERSION for c in cands))
check("the record's time range is exactly the shot's source range", all(abs(c["source_in"] - s["source_in"]) < 1e-6 and abs(c["duration"] - s["duration_frames"] / 25.0) < 0.002 for c, s in zip(cands, base["shots"])))
check("a 50 fps clip's range is also given in its own frames", all(c["timebase"]["fps"] == 50.0 and c["timebase"]["in_frame"] == round(c["source_in"] * 50) for c in cands))
check("ids are stable: the same plan again gives the same ids", [c["id"] for c in cands] == [s["candidate"]["id"] for s in plan_with()["shots"]])
check("ids differ between different stretches", len({c["id"] for c in cands}) == len(cands))
ev = [c for c in cands if c["origin"] == "described_moment"]
st = [c for c in cands if c["origin"] == "steadiest_stretch"]
check("both kinds of origin appear in this plan (described moments and steadiest stretches)", ev and st, (len(ev), len(st)))
check("a described moment's role is the kind Claude gave it, with the event recorded", all(c["role"] == c["event"]["kind"] and c["event"]["what"] for c in ev))
check("a steadiest stretch is a 'hold' with no event", all(c["role"] == "hold" and c["event"] is None for c in st))
check("judgement and measurement are kept apart: described moments say judgement from stills, steadiest stretches say measured",
      all(c["confidence"]["basis"].startswith("judgement") for c in ev) and all(c["confidence"]["basis"] == "measured" for c in st))
check("nothing claims to be checked against Josh's taste", not any(c["confidence"]["checked_against_your_taste"] for c in cands))
check("a described moment says its time can be off and quotes the measured first-pick rate", all(any("half a second" in u for u in c["confidence"]["uncertain"]) and any("9%" in u for u in c["confidence"]["uncertain"]) for c in ev))
check("every record has evidence in plain words, including the measured cut check", all(c["evidence"] and any("hard cut" in e for e in c["evidence"]) for c in cands))
check("every record from the picker has its score breakdown, labelled as a relative ranking", all(c.get("score") and "role" in c["score"]["parts"] and "relative" in c["score"]["note"] for c in cands))
check("legacy descriptions are labelled as such (no version recorded)", all(c["provenance"]["describe"] == "legacy description (no version recorded)" for c in ev))
check("without a verified checksum the media key is name + duration and marked not stable", all(c["media"]["key"].startswith("name:") and c["media"]["stable"] is False for c in cands))
check("with a checksum the key is the checksum and stable", cm.media_key({"checksum": "abc", "name": "x", "duration": 3})[0] == "sha256:abc" and cm.media_key({"checksum": "abc"})[1])
check("explain_choice gives one plain sentence for each shot", all(cm.explain_choice(c).endswith(").") and len(cm.explain_choice(c)) < 260 for c in cands))
reel = pe.build_plan(profile=ps.profile_from_references(["jd-sports-moa-draft-01"]), hits=hits, music_in=10.0, duration=20.0, fps=25.0, clips=[{k: v for k, v in c.items() if k not in ("steady", "thumbs")} for c in CLIPS], bookend_file_id=None, seed=5)
rc = [s["candidate"] for s in reel["shots"]]
check("music-reel shots carry records too, saying their footage was not read for steadiness", all(r and any("not read" in u for u in r["confidence"]["uncertain"]) and r["technical"]["cut_inside"] is None for r in rc))

clip = next(c for c in CLIPS if c.get("events"))
cl = cm.clip_candidates(clip, 0.6, limit=5)
check("clip_candidates lists the clip's described moments (strongest first) then its steadiest stretch", cl and cl[-1]["origin"] == "steadiest_stretch" and all(c["origin"] == "described_moment" for c in cl[:-1])
      and [c["event"]["punch"] for c in cl[:-1]] == sorted([c["event"]["punch"] for c in cl[:-1]], reverse=True), [(c["origin"], (c["event"] or {}).get("punch")) for c in cl])
check("each listed candidate keeps the planner-shaped window", all("window" in c and c["window"]["start"] == c["source_in"] for c in cl))
check("a clip with no steadiness reading has no candidates (nothing measured to stand on)", cm.clip_candidates({**clip, "steady": None}, 0.6) == [])
check("a window with a cut inside is marked invalid with the reason", cm.describe(clip, {"start": 1.0, "duration": 0.5, "source": "steadiest window", "steady": {"cuts": 1, "luma": 0.5}})["valid"] is False)

# ---- the optional picker terms do what they say ------------------------------------------------------------------------------------------------------
def share(plan, role):
    body = [s for s in plan["shots"] if s["role"] == "body"]
    return sum(1 for s in body if s["candidate"]["role"] == role) / len(body)


hero = plan_with(picker_options={"role_weights": {"hero": 1.0, "hold": -1.0}})
check("a style that wants hero shots gets more of them than the default", share(hero, "hero") > share(base, "hero"), (share(base, "hero"), share(hero, "hero")))
check("...and fewer plain holds", share(hero, "hold") < share(base, "hold"), (share(base, "hold"), share(hero, "hold")))
avoid = {}
for s_ in base["shots"]:
    avoid.setdefault(s_["file_id"], []).append((s_["source_in"], s_["source_out"]))
second = plan_with(picker_options={"avoid": avoid})
same = sum(1 for a, b in zip(base["shots"], second["shots"]) if a["file_id"] == b["file_id"] and abs(a["source_in"] - b["source_in"]) < 0.3)
overlap_any = sum(1 for s_ in second["shots"] if any(s_["source_in"] < b and s_["source_out"] > a for a, b in avoid.get(s_["file_id"], [])))
check("a second variant told to avoid the first one's footage reuses far less of it", overlap_any <= len(second["shots"]) // 4, (overlap_any, len(second["shots"])))
def expected_penalty(s_):
    spans = avoid.get(s_["file_id"])
    if not spans:
        return 0.0
    return post_pick.VARIANT_OVERLAP_PENALTY if any(s_["source_in"] < b and s_["source_in"] + s_["candidate"]["duration"] > a for a, b in spans) else post_pick.VARIANT_SAME_CLIP_PENALTY


scored = [s_ for s_ in second["shots"] if (s_["candidate"].get("score") or {}).get("parts")]
check("...and every picked shot's score breakdown carries exactly the penalty it earned (overlap 1.5, same clip 0.35, else 0), and some shots earned one",
      scored and all(abs(s_["candidate"]["score"]["parts"]["other_variant_penalty"] - expected_penalty(s_)) < 1e-6 for s_ in scored)
      and any(s_["candidate"]["score"]["parts"]["other_variant_penalty"] > 0 for s_ in scored),
      [(s_["candidate"]["score"]["parts"]["other_variant_penalty"], expected_penalty(s_)) for s_ in scored][:6])
opens = plan_with(slot_roles={"first": "hero", "last": "hero"}, picker_options={})
check("a style that opens on a hero gets a hero as its first shot (the default plan opened on a different kind)", opens["shots"][0]["candidate"]["role"] == "hero" and base["shots"][0]["candidate"]["role"] != "hero",
      (opens["shots"][0]["candidate"]["role"], base["shots"][0]["candidate"]["role"]))
check("...and one that ends on a hero gets a hero as its closing hold (the last shot of the edit)", opens["shots"][-1]["candidate"]["role"] == "hero",
      (opens["shots"][-1]["role"], opens["shots"][-1]["candidate"]["role"], base["shots"][-1]["candidate"]["role"]))
pref = plan_with(picker_options={"preferences": {"reveal": 0.15, "action": -0.15}})
check("learned preferences never move the mix against their direction", share(pref, "reveal") >= share(base, "reveal") and share(pref, "action") <= share(base, "action"),
      ((share(base, "reveal"), share(pref, "reveal")), (share(base, "action"), share(pref, "action"))))
want = {"reveal": 0.15 * post_pick.PREFERENCE_WEIGHT, "action": -0.15 * post_pick.PREFERENCE_WEIGHT}
pscored = [s_ for s_ in pref["shots"] if (s_["candidate"].get("score") or {}).get("parts")]
check("...and every picked shot's score carries the learned term for its kind (+0.15 reveal, -0.15 action, 0 otherwise), so the term is really applied",
      any(p_["candidate"]["role"] in want for p_ in pscored)
      and all(abs(p_["candidate"]["score"]["parts"]["learned_preference"] - want.get(p_["candidate"]["score"]["parts"]["role"], 0.0)) < 1e-6 for p_ in pscored),
      [(p_["candidate"]["score"]["parts"]["role"], p_["candidate"]["score"]["parts"]["learned_preference"]) for p_ in pscored][:6])
check("the default plan carries no learned term at all", all(s_["candidate"]["score"]["parts"]["learned_preference"] == 0 for s_ in base["shots"] if (s_["candidate"].get("score") or {}).get("parts")))
build = plan_with(pacing_curve=[1.3, 1.25, 1.15, 1.05, 1.0, 0.95, 0.9, 0.85, 0.8, 0.75])
b = [s["duration_frames"] for s in build["shots"] if s["role"] == "body"]
half = len(b) // 2
check("a 'build' pacing curve makes the second half's shots shorter than the first half's", np.median(b[half:]) < np.median(b[:half]), (np.median(b[:half]), np.median(b[half:])))
try:
    plan_with(pacing_curve=[1.0] * 9)
    check("a malformed pacing curve is refused", False)
except pe.EditPlanError:
    check("a malformed pacing curve is refused", True)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
