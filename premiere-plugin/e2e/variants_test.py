"""Tests for multi-variant edit plans (backend/app/post_variants.py): the plans are complete and valid, meaningfully different, built from ONE analysis with no API
call, honest about what is executed, and the job-level flow saves a set without touching the current plan and can make a variant the job's plan.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python variants_test.py"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from synthetic_clips import beat_hits, make_clips  # noqa: E402
from app import post_style, post_style_library as lib, post_variants as pv  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


CLIPS = make_clips()
HITS = beat_hits(160)
PROFILE = post_style.usual_pace_profile()
DIRS = ["music-led-montage", "high-energy-commercial", "premium-luxury"]


def build(directions=DIRS, clips=CLIPS, seed=7, duration=30.0):
    return pv.build_set(list(directions), profile=PROFILE, hits=HITS, music_in=10.0, duration=duration, fps=25.0, clips=clips, seed=seed, with_cards=False, set_id="20261022T120000")


res = build()
plans = res["plans"]
check("three directions give three complete plans", len(plans) == 3 and all(p["shots"] for p in plans))
ok = True
for p in plans:
    frames = 0
    for s in p["shots"]:
        ok &= s["start_frame"] == frames and s["duration_frames"] > 0
        frames += s["duration_frames"]
        clip = next(c for c in CLIPS if c["file_id"] == s["file_id"])
        ok &= 0 <= s["source_in"] and s["source_out"] <= clip["duration"] + 0.05
    ok &= frames == p["duration_frames"]
check("every variant is a valid timeline: shots back to back, the right total length, every stretch inside its clip", ok)
check("every body shot of every variant is free of hard cuts (measured)", all(not (s["candidate"]["technical"] or {}).get("cut_inside") for p in plans for s in p["shots"] if s["role"] == "body"))
check("each plan names its library style and carries a variant block", [p["style"] for p in plans] == [f"library:{d}" for d in DIRS] and all(p["variant"]["index"] == k for k, p in enumerate(plans, 1)))
mean = {p["variant"]["style"]: p["variant"]["metrics"]["mean_shot"] for p in plans}
# means, not medians: at 128 BPM half of every variant's shots are exactly one beat (0.48 s), so the montage's and high-energy's medians tie
check("the directions really differ in pace: premium's shots are longer than the montage's, which are longer than high-energy's", mean["premium-luxury"] > mean["music-led-montage"] > mean["high-energy-commercial"], mean)
check("premium cuts about half as often as the montage", 0.4 <= plans[2]["variant"]["metrics"]["body_shots"] / plans[0]["variant"]["metrics"]["body_shots"] <= 0.7,
      [p["variant"]["metrics"]["body_shots"] for p in plans])
pairs = res["comparison"]["pairs"]
check("no two variants share more than a third of their stretches (they show different footage)", all(x["shared_stretches"] <= pv.TOO_SIMILAR_SHARE for x in pairs), pairs)
alone = [pv.build_variant(d, profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, avoid={}, seed=7 + k, with_cards=False, index=k + 1, set_id="x")
         for k, d in enumerate(DIRS)]
alone_share = max(pv.compare(alone)["pairs"], key=lambda x: x["shared_stretches"])["shared_stretches"]
set_share = max(x["shared_stretches"] for x in pairs)
check("telling each variant what the earlier ones used is what keeps them apart (planned independently they overlap far more)", alone_share >= 3 * max(set_share, 0.05),
      (alone_share, set_share))
mix = [p["variant"]["metrics"]["role_mix"] for p in plans]
check("the shot mixes differ between directions", mix[0] != mix[1] and mix[1] != mix[2] and mix[0] != mix[2], mix)

# the 'build' curve, measured as an average: every cut snaps to a hit, so one plan can come out flat, but across seeds a build shortens the second half
from app.post_edit_highlight import build_highlight_plan  # noqa: E402
build_curve = lib.planner_config(lib.get_style("high-energy-commercial"))["pacing_curve"]


def half_ratio(curve, seed):
    p = build_highlight_plan(profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, bookend_file_id=None, seed=seed, pace=0.85, slow_zooms=False,
                             with_opener=False, pacing_curve=curve)
    m = pv.metrics(p)
    return m["second_half_mean"] / m["first_half_mean"]


flat_r = sum(half_ratio(None, s) for s in range(8)) / 8
build_r = sum(half_ratio(build_curve, s) for s in range(8)) / 8
check("averaged over 8 seeds, a 'build' curve makes the second half's shots clearly shorter than an even rhythm does", build_r < flat_r - 0.1, (round(build_r, 3), round(flat_r, 3)))
hi = plans[1]["variant"]
check("a build variant states what it measured (first-half and second-half shot length), not just what it intended",
      f"{hi['metrics']['first_half_mean']:.2f} s in the first half and {hi['metrics']['second_half_mean']:.2f} s in the second" in hi["approach"], hi["approach"])
check("a breathe variant states its measured opening/closing and middle shot lengths", "the opening and closing quarters average" in plans[2]["variant"]["approach"], plans[2]["variant"]["approach"])
check("an even-rhythm variant claims no shape at all", "Measured:" not in plans[0]["variant"]["approach"], plans[0]["variant"]["approach"])
check("a variant set makes no API call (it reuses descriptions already made)", all(p["variant"]["api_calls"] == 0 for p in plans))
for p, d in zip(plans, DIRS):   # this set has no logo: a brand-card line the library lists as executed moves to the proposals, saying why
    rep = lib.execution_report(lib.get_style(d))
    cards = [x for x in rep["executed"] if "brand card" in x]
    if not (p["variant"]["executed"] == [x for x in rep["executed"] if x not in cards]
            and p["variant"]["proposed_only"] == rep["proposed_only"] + [f"{x} -- not made: the job has no logo or no standard frame size" for x in cards]):
        check(f"variant '{d}' lists exactly what the library executes, with an unmade brand card moved to the proposals", False, (p["variant"]["executed"], p["variant"]["proposed_only"]))
        break
else:
    check("every variant lists exactly what the library executes, and a brand card that wasn't made is listed as not made, never as done", True)
check("...the high-energy direction (which ends on a brand card) shows that move", any("brand card" in x and "not made" in x for x in plans[1]["variant"]["proposed_only"])
      and not any("brand card" in x for x in plans[1]["variant"]["executed"]))
check("the confidence line says only the base rhythm is measured; the direction's own pace multiplier is guidance",
      all(f"the {p['variant']['pacing']['pace']:g}x pace on it" in p["variant"]["confidence"]["basis"] and "guidance" in p["variant"]["confidence"]["basis"] for p in plans))
check("every variant in a set has the same length, so one music cut serves them all", len({p["duration_frames"] for p in plans}) == 1, [p["duration_frames"] for p in plans])
check("a premium variant lists treatments it cannot execute as proposals (e.g. dissolves), never as executed", any("dissolve" in x for x in plans[2]["variant"]["proposed_only"]) and not any("dissolve" in x for x in plans[2]["variant"]["executed"]))
check("every variant says its moments are Claude's judgement, not checked against Josh's taste", all(any("not checked against your taste" in x for x in p["variant"]["confidence"]["limitations"]) for p in plans))
check("the approach text reports the opening and closing it actually got, not just what it wanted", all(("it opened on" in p["variant"]["approach"]) == bool(lib.planner_config(lib.get_style(d))["first_role"]) for p, d in zip(plans, DIRS)))
again = build()
check("the same footage, song and seed give the same variants (repeatable)", [[(s["file_id"], s["source_in"], s["duration_frames"]) for s in p["shots"]] for p in again["plans"]]
      == [[(s["file_id"], s["source_in"], s["duration_frames"]) for s in p["shots"]] for p in plans])
first_alone = build(["music-led-montage", "premium-luxury"])["plans"][0]
check("the first variant is exactly what that style plans on its own (later variants avoid it, not the other way round)", [(s["file_id"], s["source_in"]) for s in first_alone["shots"]] == [(s["file_id"], s["source_in"]) for s in plans[0]["shots"]])

for label, dirs, expect in (("one variant", ["music-led-montage"], "2 to 4"), ("five variants", list(lib.LIBRARY)[:5], "2 to 4"), ("the same style twice", ["premium-luxury", "premium-luxury"], "different style"),
                            ("the interview profile", ["music-led-montage", "dialogue-interview"], "can't be built"), ("an unknown style", ["music-led-montage", "no-such-style"], "can't be built")):
    try:
        build(dirs)
        check(f"refuses {label} with a plain reason", False)
    except pv.VariantError as exc:
        check(f"refuses {label} with a plain reason", expect in str(exc), str(exc))
check("the synthetic set cuts at the speeds it promises, so it carries no pace warning", not any("meant to cut faster" in n for n in res["notes"]), res["notes"])
fake = [{"variant": {"index": 1, "name": "Montage", "pacing": {"pace": 1.0}, "metrics": {"mean_shot": 0.55}}},
        {"variant": {"index": 2, "name": "High-energy", "pacing": {"pace": 0.85}, "metrics": {"mean_shot": 0.58}}},
        {"variant": {"index": 3, "name": "Premium", "pacing": {"pace": 1.6}, "metrics": {"mean_shot": 1.0}}}]
notes = pv.pace_notes(fake)
check("a direction meant to be faster that came out slower is pointed out, with both numbers (seen for real on GWM)", len(notes) == 1 and "0.58 s against 0.55 s" in notes[0]
      and notes[0].startswith("Variant 2 (High-energy)"), notes)
fake[1]["variant"]["metrics"]["mean_shot"] = 0.50
check("...and not when it really is at least 5% faster", pv.pace_notes(fake) == [])
few = build(clips=CLIPS[:5], duration=20.0)
check("from a shoot with too few clips the set still builds, and says which variants are too alike", few["notes"] and all("too few different clips" in n for n in few["notes"]), few["notes"])
hybrid = build(["music-led-montage", "hybrid:sports-action+fashion-beauty:70"])
check("a custom hybrid style builds as a variant too", hybrid["plans"][1]["style"] == "library:hybrid:sports-action+fashion-beauty:70")

# ---- plan validation: missing media, impossible timecodes, gaps ------------------------------------------------------------------------------------------
import copy  # noqa: E402
good = plans[0]
check("every variant the planner made is valid against the job's clips", all(pv.validate_plan(p, CLIPS) == [] for p in plans), [pv.validate_plan(p, CLIPS)[:2] for p in plans])
bad_cases = {
    "a gap on the timeline": lambda p: p["shots"][3].__setitem__("start_frame", p["shots"][3]["start_frame"] + 2),
    "a negative source in point": lambda p: p["shots"][2].update({"source_in": -0.5, "source_out": -0.5 + (p["shots"][2]["source_out"] - p["shots"][2]["source_in"])}),
    "a window running past the end of its clip": lambda p: p["shots"][1].update({"source_in": 99.0, "source_out": 99.0 + p["shots"][1]["duration_frames"] / 25.0}),
    "a window that doesn't fill its slot": lambda p: p["shots"][4].__setitem__("source_out", p["shots"][4]["source_in"] + 0.1),
    "a total length that doesn't add up": lambda p: p.__setitem__("duration_frames", p["duration_frames"] + 5),
    "a clip that is no longer the job's": lambda p: p["shots"][5].__setitem__("file_id", 999),
    "a shot with no length": lambda p: p["shots"][6].__setitem__("duration_frames", 0),
}
for label, damage in bad_cases.items():
    p = copy.deepcopy(good)
    damage(p)
    probs = pv.validate_plan(p, CLIPS)
    check(f"validate_plan catches {label}, in plain words", bool(probs), probs[:2])
slow = copy.deepcopy(good)
s0 = next(s for s in slow["shots"] if s["role"] == "body")
s0.update({"speed": 0.5, "source_out": round(s0["source_in"] + (s0["source_out"] - s0["source_in"]) * 0.5, 3)})
check("a slowed shot (half the source window at half speed) is valid", pv.validate_plan(slow, CLIPS) == [], pv.validate_plan(slow, CLIPS))
gone = next(c for c in CLIPS if c["file_id"] == good["shots"][0]["file_id"])["path"]
missing = pv.validate_plan(good, CLIPS, existing={c["path"] for c in CLIPS if c["path"] != gone})
check("missing media: a used clip whose file isn't on the drive is named", any("missing media" in x and gone in x for x in missing), missing[:2])
check("without the job's clips it still checks the timeline itself", pv.validate_plan(good) == [] and pv.validate_plan({"fps": 25.0, "shots": []}) == ["The plan has no shots."])

# ---- brand cards: only the card a direction asks for ------------------------------------------------------------------------------------------------------
from PIL import Image  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    logo = Path(tmp) / "logo.png"
    Image.new("RGBA", (400, 160), (230, 40, 40, 255)).save(logo)
    carded = pv.build_set(["high-energy-commercial", "music-led-montage"], profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, seed=7,
                          with_cards=True, set_id="20261022T120000")["plans"]
    job_ = {"id": 5, "shoot_name": "Synthetic", "deliverable_format": "16:9", "resolution": "4k_uhd"}
    for p in carded:
        pv.add_cards(p, job_, str(logo), (3840, 2160), Path(tmp) / "gfx")
    hi_cards = (carded[0].get("graphics") or {}).get("cards") or []
    closing = carded[0]["shots"][-1]
    check("a direction that ends on a brand card gets exactly one closing card, over its closing hold", [c["role"] for c in hi_cards] == ["closer"]
          and hi_cards[0]["start_frame"] == closing["start_frame"] and hi_cards[0]["frames"] == closing["duration_frames"] and Path(hi_cards[0]["file"]).exists(), hi_cards)
    check("...and no logo bug or captions (a highlight asks only for its cards)", carded[0]["graphics"]["logo_bug"] is None and carded[0]["graphics"]["captions"] is None)
    check("a direction that ends on a held hero moment gets no card at all", "graphics" not in carded[1], carded[1].get("graphics"))
    check("the card's variant says nothing about a missing logo once it has one", not any("no logo" in x for x in carded[0]["variant"]["confidence"]["limitations"]))
    check("...and lists the card it made as done", any("brand card" in x for x in carded[0]["variant"]["executed"]))
    broken = pv.build_set(["high-energy-commercial", "music-led-montage"], profile=PROFILE, hits=HITS, music_in=10.0, duration=30.0, fps=25.0, clips=CLIPS, seed=7,
                          with_cards=True, set_id="20261022T120000")["plans"][0]
    pv.add_cards(broken, job_, str(Path(tmp) / "missing_logo.png"), (3840, 2160), Path(tmp) / "gfx")
    check("if the card can't be drawn (unreadable logo), the plan has no card and the card line moves to 'not made', with the reason",
          "graphics" not in broken and not any("brand card" in x for x in broken["variant"]["executed"])
          and any("brand card" in x and "not made" in x for x in broken["variant"]["proposed_only"]), broken["variant"]["proposed_only"][-1:])

# ---- the job-level flow: one analysis, files saved beside the plan, the current plan untouched, a variant chosen ----------------------------------------------
from app import post_db, post_edit_plan, post_music, post_steady, post_brand_graphics  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    job = {"id": 5, "shoot_name": "Synthetic", "profile": "joshx", "destination_root": str(root), "media_analyzed_at": "2026-10-22", "frame_rate": 25}
    edit = root / "09_PROJECT FILES" / "edit_plans"
    edit.mkdir(parents=True)
    (root / "04_MUSIC").mkdir()
    song = root / "04_MUSIC" / "song.mp3"
    song.write_bytes(b"not really audio")
    current = {"style": "your-usual-pace", "fps": 25.0, "shots": [], "music": {"cut_path": str(root / "04_MUSIC" / "song_reelcut.wav")}, "duration_frames": 0}
    (edit / "edit_plan_latest.json").write_text(json.dumps(current))
    before = (edit / "edit_plan_latest.json").read_bytes()
    calls = {"analyze_music": 0, "analyse_clips": 0, "render": []}

    async def fake_job(job_id, postgres_conn=None):
        return dict(job) if job_id == 5 else None

    async def fake_clips(job_id, postgres_conn=None, order_names=None):
        return [dict(c) for c in CLIPS]

    async def fake_analyse(clips, job_, *, concurrency=5, only_cached=False, always=None):
        calls["analyse_clips"] += 1
        return {"analysed": 0, "cached": len(clips), "unreadable": 0}

    async def fake_music(path):
        calls["analyze_music"] += 1
        return {"hits": HITS, "duration": 160.0, "tempo_bpm": 128.0}

    async def fake_render(src, out, music_in, seconds, fade=1.5):
        if calls.get("render_fails"):
            raise post_music.MusicAnalysisError("ffmpeg couldn't read the song")
        calls["render"].append(out)
        calls["render_args"] = (seconds, fade)
        Path(out).write_bytes(b"wav")

    saved = (post_db.get_post_job, post_edit_plan.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, post_edit_plan.find_logo,
             post_edit_plan.bring_song_into_project, post_music.find_music_file)
    post_db.get_post_job, post_edit_plan.load_job_clips, post_steady.analyse_clips = fake_job, fake_clips, fake_analyse
    post_music.analyze_music, post_music.render_music_cut = fake_music, fake_render
    post_edit_plan.find_logo, post_edit_plan.bring_song_into_project, post_music.find_music_file = (lambda j: None), (lambda s, d: str(s)), (lambda folder: str(song))
    from app import post_learning_events as _le
    real_adopted, _le.ADOPTED_PREFERENCES = _le.ADOPTED_PREFERENCES, root / "no_adopted_preferences.json"   # never his real file
    try:
        summary = asyncio.run(pv.plan_variants_for_job(5, count=3, target_seconds=24.0))
        first_run = {k: (list(v) if isinstance(v, list) else v) for k, v in calls.items()}
        calls["render_fails"] = True
        try:
            asyncio.run(pv.plan_variants_for_job(5, count=2, target_seconds=24.0))
            check("a music cut that fails to render is a plain VariantError (a 400 with a reason, not a crash)", False)
        except pv.VariantError as exc:
            check("a music cut that fails to render is a plain VariantError (a 400 with a reason, not a crash)", "music couldn't be cut" in str(exc), str(exc))
        calls["render_fails"] = False
        try:
            asyncio.run(pv.plan_variants_for_job(5, count=2, target_seconds=200.0))
            check("a song shorter than the edit is a plain VariantError naming the track's length (it was a 500 on GWM)", False)
        except pv.VariantError as exc:
            check("a song shorter than the edit is a plain VariantError naming the track's length (it was a 500 on GWM)", "track is" in str(exc), str(exc))
    finally:
        (post_db.get_post_job, post_edit_plan.load_job_clips, post_steady.analyse_clips, post_music.analyze_music, post_music.render_music_cut, post_edit_plan.find_logo,
         post_edit_plan.bring_song_into_project, post_music.find_music_file) = saved
        _le.ADOPTED_PREFERENCES = real_adopted
    set_id = summary["set_id"]
    folder = edit / "variants" / set_id
    # found live on GWM: the set's music cut became the newest file in the music folder, and the next plan picked it as "the song"
    check("after a set is made, the job's song is still the song (the set's own music cut is never picked as one)",
          post_music.find_music_file(str(root / "04_MUSIC")) == str(song) and [f["name"] for f in post_edit_plan.list_music_files(job)] == ["song.mp3"],
          (post_music.find_music_file(str(root / "04_MUSIC")), [f["name"] for f in post_edit_plan.list_music_files(job)]))
    check("the job-level flow builds the default three directions", [v["style"] for v in summary["variants"]] == list(pv.DEFAULT_DIRECTIONS[:3]), [v["style"] for v in summary["variants"]])
    check("it reads the song and the clips' analysis ONCE for the whole set", first_run["analyze_music"] == 1 and first_run["analyse_clips"] == 1, first_run)
    check("...and a set whose music cut failed saved nothing", sorted(p.name for p in (edit / "variants").iterdir()) == [set_id])
    check("it saves every variant and the comparison beside the plan", (folder / "set.json").exists() and all((folder / f"variant_{k}.json").exists() for k in (1, 2, 3)))
    check("the job's current plan is untouched", (edit / "edit_plan_latest.json").read_bytes() == before)
    check("the set gets its own music cut, so the current plan's music file is never overwritten", len(calls["render"]) == 1 and calls["render"][0].endswith(f"_variants_{set_id}.wav")
          and "reelcut" not in calls["render"][0], calls["render"])
    v2 = json.loads((folder / "variant_2.json").read_text())
    check("each saved variant points at that music cut and knows its job", v2["music"]["cut_path"] == calls["render"][0] and v2["job_id"] == 5 and v2["shoot_name"] == "Synthetic")
    check("the music cut is as long as the variants and fades out the way the plan says (not a fixed 1.5 s)",
          abs(calls["render_args"][0] - v2["duration_frames"] / 25.0) < 1e-6 and calls["render_args"][1] == v2["music"]["fade_out_seconds"] and v2["music"]["fade_out_seconds"] != 1.5,
          (calls["render_args"], v2["music"].get("fade_out_seconds")))
    check("every variant of the set says the fade the shared cut really has", all(json.loads((folder / f"variant_{k}.json").read_text())["music"]["fade_out_seconds"] == calls["render_args"][1] for k in (1, 2, 3)))
    check("only the app's own cuts are hidden from the song list: a song of his called '..._variants_mix' still counts",
          post_music.is_own_cut(Path("a_variants_20261022T094507.wav")) and post_music.is_own_cut(Path("a_reelcut.wav")) and not post_music.is_own_cut(Path("club_variants_mix.wav")))
    check("no logo on the job: a direction that wants brand cards says none were made", any("no logo" in x for v in summary["variants"] if v["style"] == "high-energy-commercial" for x in v["confidence"]["limitations"]))
    check("the set lists itself, newest first", pv.list_sets(edit)[0]["set_id"] == set_id and pv.list_sets(edit)[0]["variants"] == [v["name"] for v in summary["variants"]])
    check("a variant can be loaded back exactly as saved", pv.load_variant(edit, set_id, 2) == v2)
    for bad in ("../../etc", "nope", set_id + "/.."):
        try:
            pv.load_set(edit, bad)
            check(f"a set id like '{bad}' is refused (no path tricks)", False)
        except pv.VariantError:
            check(f"a set id like '{bad}' is refused (no path tricks)", True)
    chosen = pv.use_variant(edit, set_id, 2)
    latest = json.loads((edit / "edit_plan_latest.json").read_text())
    archived = sorted(edit.glob("edit_plan_prev_*.json"))
    check("choosing a variant makes it the job's plan (what Build My Edit builds)", latest["style"] == "library:high-energy-commercial" and latest["variant"]["chosen_at"] and chosen["shots"] == latest["shots"])
    check("...and the plan it replaced is archived, not lost", len(archived) == 1 and json.loads(archived[0].read_text())["style"] == "your-usual-pace")
    check("...with a named copy for plan history", (edit / f"edit_plan_variant_{set_id}_2.json").exists())

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
