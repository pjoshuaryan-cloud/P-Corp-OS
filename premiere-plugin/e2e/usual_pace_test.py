"""Tests for the default style "Your usual pace" (2026-10-21): his own shot rhythm (backend/app/post_usual_pace.json, written by learning.rhythm --export-usual-pace)
run through the highlight planner, listed first, with the calm corporate highlight kept as an opt-in.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python usual_pace_test.py"""
import asyncio
import json
import random
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_edit_highlight as hl, post_edit_plan as pe, post_edit_types as pet, post_reference as pr, post_style as ps  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


# ---- the measured file ----------------------------------------------------------------------------------------------------------------------
data = ps.load_usual_pace()
check("the measured rhythm file is in the repo and has what the planner needs", all(k in data for k in ("body_lengths", "opener_seconds", "closing_hold_seconds", "typical_seconds", "min_shot_seconds", "max_shot_seconds", "from_edits", "made")))
lengths = data["body_lengths"]
check("it holds 100 sorted shot lengths between the floor and the cap", len(lengths) == 100 and lengths == sorted(lengths) and min(lengths) >= data["min_shot_seconds"] and max(lengths) <= data["max_shot_seconds"], (len(lengths), min(lengths), max(lengths)))
check("it is his pace: a median shot of 0.4-0.8 s, learned from at least 50 edits", 0.4 <= statistics.median(lengths) <= 0.8 and data["from_edits"] >= 50, (statistics.median(lengths), data["from_edits"]))

# ---- the style ------------------------------------------------------------------------------------------------------------------------------
usual = ps.profile_from_references([ps.USUAL_PACE_SLUG])
calm = ps.profile_from_references(["corporate-highlight-calm"])
check("it loads as a highlight style with hard cuts only and no narration", usual.highlight and usual.edit_type == "corporate_highlight" and usual.accents is None and usual.story is not None and usual.story.words_per_second == 0.0)
check("its pace multiplier is 1.0 (his own), the calm style's is still the planner's 1.3", pe.default_pace(usual) == 1.0 and pe.default_pace(calm) == 1.3 and calm.default_pace is None)
check("its shot rhythm is his measured one, and its default length is his typical edit", usual.story.body_lengths == lengths and usual.target_duration_seconds == float(round(data["typical_seconds"])), (usual.target_duration_seconds, data["typical_seconds"]))
check("it may cut shorter than the calm style's one-second floor; the calm style may not", usual.highlight_min_shot_seconds == data["min_shot_seconds"] < 1.0 and calm.highlight_min_shot_seconds is None)
try:
    ps.profile_from_references([ps.USUAL_PACE_SLUG, "corporate-highlight-calm"])
    check("it can't be pooled with another reference", False)
except ValueError as exc:
    check("it can't be pooled with another reference (plain message)", "complete style of its own" in str(exc), str(exc))
check("the calm style is untouched (same rhythm source, still a highlight)", calm.highlight and calm.story is not None and calm.rhythm_note is None and 1.4 < statistics.median(calm.story.body_lengths) < 1.9, statistics.median(calm.story.body_lengths))
check("the corporate story style is untouched", not ps.profile_from_references(["corporate-distribution-company"]).highlight)

# ---- being the default ----------------------------------------------------------------------------------------------------------------------
styles = ps.available_styles()
slugs = [s["slug"] for s in styles]
check("it is listed FIRST, which is what the planning screen preselects", slugs[0] == ps.USUAL_PACE_SLUG, slugs)
check("the calm corporate highlight is still offered", "corporate-highlight-calm" in slugs)
check("it is first in the full list too (including reference-only styles)", ps.available_styles(buildable_only=False)[0]["slug"] == ps.USUAL_PACE_SLUG)
card = pe._style_card(styles[0])
check("its card says what it is, in plain words, with the corporate-highlight flags the screen already understands", card["friendly_title"] == "Your usual pace" and card["edit_type"] == "corporate_highlight" and not card["has_accents"] and not card["inferred"], card)
check("its card shows his measured median shot and typical length", 0.4 <= card["median_shot_seconds"] <= 0.8 and card["seconds"] == float(round(data["typical_seconds"])), card)
calm_card = pe._style_card(next(s for s in styles if s["slug"] == "corporate-highlight-calm"))
check("the calm style's card now says how slow it is, and still has its 40 s and calm median", "two seconds" in calm_card["blurb"] and calm_card["seconds"] == 40 and calm_card["median_shot_seconds"] >= 1.8, calm_card)
check("the edit type's description no longer calls every highlight calm", "Your usual pace" in pet.EDIT_TYPES["corporate_highlight"]["how"])

# ---- the style record heals and tracks the measured file ---------------------------------------------------------------------------------------
real_dir = pr.REFERENCE_DIR
with tempfile.TemporaryDirectory() as tmp:
    pr.REFERENCE_DIR = Path(tmp)
    try:
        pet.ensure_inferred_styles([ps.USUAL_PACE_SLUG])
        path = Path(tmp) / f"{ps.USUAL_PACE_SLUG}.json"
        rec = json.loads(path.read_text()) if path.exists() else {}
        check("a missing style record is written again from the measured file", rec.get("learned_pace") is True and rec["tags"]["edit_type"] == "corporate_highlight" and rec["tags"]["learned_from"] == data["made"], rec.get("tags"))
        first = path.stat().st_mtime_ns
        pet.ensure_inferred_styles([ps.USUAL_PACE_SLUG])
        check("a current record is left alone", path.stat().st_mtime_ns == first)
        rec["tags"]["learned_from"] = "2000-01-01T00:00:00"
        path.write_text(json.dumps(rec))
        pet.ensure_inferred_styles([ps.USUAL_PACE_SLUG])
        check("a record made from an older measurement is rewritten when the file is re-exported", json.loads(path.read_text())["tags"]["learned_from"] == data["made"])
        saved_file = ps.USUAL_PACE_FILE
        ps.USUAL_PACE_FILE = Path(tmp) / "nope.json"
        path.unlink()
        try:
            written = pet.write_inferred_styles(only=[ps.USUAL_PACE_SLUG])
            check("with the measured file missing the style is simply not offered, and nothing raises (a card must never break the list of styles)", written == [] and not path.exists(), written)
            try:
                ps.profile_from_references([ps.USUAL_PACE_SLUG])
                check("planning with it then says plainly how to measure it", False)
            except ValueError as exc:
                check("planning with it then says plainly how to measure it", "rhythm --export-usual-pace" in str(exc), str(exc))
        finally:
            ps.USUAL_PACE_FILE = saved_file
    finally:
        pr.REFERENCE_DIR = real_dir

# ---- planning with it: same clips, same song, same seed ---------------------------------------------------------------------------------------
FPS = 25.0


def beat_hits(seconds, bpm=140, seed=3):
    r = random.Random(seed)
    beat, out, t, i = 60.0 / bpm, [], 0.0, 0
    while t < seconds:
        pct = 96 if i % 4 == 0 else (82 if i % 2 == 0 else 68)
        out.append([round(t, 3), pct + r.random() * 2])
        out.append([round(t + beat / 2, 3), 56 + r.random() * 6])
        t += beat
        i += 1
    return out


HITS = beat_hits(120)
CLIPS = [{"file_id": i + 1, "name": f"C{i + 1:04d}.MP4", "path": f"/x/C{i + 1:04d}.MP4", "duration": 12.0 + (i % 5), "created": "", "picks": []} for i in range(60)]


def plan(profile, duration=30.0, pace=None, with_opener=False):
    return hl.build_highlight_plan(profile=profile, hits=HITS, music_in=10.0, duration=duration, fps=FPS, clips=CLIPS, bookend_file_id=None, seed=5,
                                   pace=pe.default_pace(profile) if pace is None else pace, with_opener=with_opener)


def body(p):
    return [s["duration_frames"] / FPS for s in p["shots"] if s["role"] == "body"]


pu, pc = plan(usual), plan(calm)
bu, bc = body(pu), body(pc)
check("at the same length and song, 'your usual pace' cuts at HIS pace: median body shot under a second", statistics.median(bu) <= 0.9, statistics.median(bu))
check("while the calm style still cuts at its own (median 1.3 s or longer)", statistics.median(bc) >= 1.3, statistics.median(bc))
check("so it uses at least twice as many shots as the calm style (about 2.3x on this 140 BPM song, nearly 5x on his 179 BPM GWM song)", len(pu["shots"]) >= 2.0 * len(pc["shots"]), (len(pu["shots"]), len(pc["shots"])))
check("no shot but the last before the closing card is shorter than the style's floor (give or take a frame); the last can be, as it always could: the cut planner doesn't enforce the floor on it", min(bu[:-1]) >= data["min_shot_seconds"] - 1.0 / FPS - 1e-9, min(bu[:-1]))
check("the calm style still never goes under a second, apart from that same last shot", min(bc[:-1]) >= 1.0 - 1.0 / FPS - 1e-9, min(bc[:-1]))
target = statistics.median(lengths)
realised = {}
for bpm in (100, 140, 180):
    meds = []
    for seed in range(4):
        hits = beat_hits(120, bpm, seed=seed + 1)
        p = hl.build_highlight_plan(profile=usual, hits=hits, music_in=10.0, duration=30.0, fps=FPS, clips=CLIPS, bookend_file_id=None, seed=seed + 11, pace=1.0, with_opener=False)
        meds.append(statistics.median(body(p)))
    realised[bpm] = statistics.mean(meds)
check("the planner reproduces his rhythm at any tempo: the median body shot lands within 25% of the style's own, at 100, 140 and 180 BPM", all(0.75 * target <= v <= 1.25 * target for v in realised.values()), (target, realised))
check("its cuts still land on the music's hits", pu["checks"]["cuts_on_hits"] >= 0.8, pu["checks"]["cuts_on_hits"])
check("it still ends on a closing hold of 2.5-4.5 s, hard cuts only, no accents", 2.5 <= pu["checks"]["closing_hold_seconds"] <= 4.5 and "accents" not in pu and pu["mode"] == "highlight", pu["checks"]["closing_hold_seconds"])
po = plan(usual, duration=30.0, with_opener=True)
check("with a logo the first slot is the opening card at the card timing, then his rhythm", po["shots"][0]["role"] == "opener" and abs(po["shots"][0]["duration_frames"] / FPS - data["opener_seconds"]) <= 0.7 and statistics.median(body(po)) <= 0.9, (po["shots"][0]["duration_frames"] / FPS, statistics.median(body(po))))
notes_u, notes_c = " ".join(pu["notes"]), " ".join(pc["notes"])
check("the plan says where its rhythm comes from: his own edits, not the narrated corporate reference", "your usual pace" in notes_u and "of your edits" in notes_u and "narrated reference" not in notes_u and "x the reference" not in notes_u, notes_u[:300])
check("and the calm plan's notes are word for word what they were", "narrated reference's" in notes_c and "Pace is 1.3x the reference's" in notes_c and "your usual" not in notes_c, notes_c[:300])
check("the pace is shown as a multiple of HIS usual", "Pace is 1x your usual" in notes_u, notes_u)
slow = plan(usual, pace=2.0)
check("a higher pace makes it calmer (the pace dial still works on this style)", statistics.median(body(slow)) > statistics.median(bu) * 1.4, (statistics.median(body(slow)), statistics.median(bu)))
try:
    plan(usual, pace=0.5)
    check("a pace outside 0.8-2.0 is still refused", False)
except pe.EditPlanError:
    check("a pace outside 0.8-2.0 is still refused", True)
check("the same input gives the same plan (seeded), so a re-plan is repeatable", [s["duration_frames"] for s in plan(usual)["shots"]] == [s["duration_frames"] for s in pu["shots"]])

# ---- on his real GWM clips and the real song (read-only; skipped when the drive isn't mounted) --------------------------------------------------
folder = Path("/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video/10_PREMIERE/edit_plans")
song = Path("/Volumes/Joshx SSD/Two Tone/GWM - Highlight Video/07_MUSIC/sero - Moon Road.mp3")
if (folder / "steadiness.json").exists() and (folder / "moments.json").exists() and song.exists():
    from app import post_music, post_steady
    from learning.planner_ab import load_clips
    real = load_clips(folder)
    analysis = asyncio.run(post_music.analyze_music(str(song)))
    out = {}
    for label, prof in (("usual", usual), ("calm", calm)):
        post_steady.clear_series_cache()
        music_in = pe.choose_music_window(analysis["hits"], analysis["duration"], 22.0, None)
        out[label] = hl.build_highlight_plan(profile=prof, hits=analysis["hits"], music_in=music_in, duration=22.0, fps=FPS, clips=real, bookend_file_id=None, seed=7,
                                             pace=pe.default_pace(prof), with_opener=False)
    n_usual, n_calm = len(out["usual"]["shots"]), len(out["calm"]["shots"])
    check("his real GWM clips, 22 s: 'your usual pace' plans a shot count in the range of his own cut of it (he made 46 shots in 21.9 s)", 30 <= n_usual <= 55, n_usual)
    check("while the calm style planned a handful (it gave 16 shots for 40 s, and he rebuilt it into 46 for 22 s)", n_calm <= 12, n_calm)
    check("with every shot on a different clip's best moment and cuts on the beat", out["usual"]["checks"]["distinct_clips"] >= 0.9 * n_usual and out["usual"]["checks"]["cuts_on_hits"] >= 0.9, out["usual"]["checks"]["cuts_on_hits"])
else:
    print("SKIP his real GWM clips (the drive isn't mounted)")

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
