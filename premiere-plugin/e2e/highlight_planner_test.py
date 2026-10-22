"""Corporate highlight cut to music (Josh, 2026-10-14): cuts on the music's hits at a calm pace, steadiest windows, slow zooms only on static shots,
opening and closing cards, hard cuts only. Unit tests with synthetic hits and clips of KNOWN content, then plan_for_job end to end with a fake job,
real fixture clips and a real song."""
import asyncio, json, os, random, shutil, subprocess, sys, tempfile
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
import numpy as np
from app import post_brand_graphics as bg, post_edit_highlight as hl, post_edit_plan as pe, post_edit_story as st, post_edit_types as pet, post_reference as pr, post_steady as sd, post_style as ps

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else "")); fails += (not cond)

prof = ps.profile_from_references(["corporate-highlight-calm"]); FPS = 24.0

# ---------------------------------------------------------------- the style itself
check("the corporate highlight style loads as a highlight profile", prof.highlight and prof.edit_type == "corporate_highlight" and prof.inferred and prof.accents is None and prof.story is not None)
check("its target is 40 s (Josh's 35-45 s)", prof.target_duration_seconds == 40.0, prof.target_duration_seconds)
check("it takes the corporate reference's shot rhythm (opener ~1.9 s)", len(prof.story.body_lengths) > 50 and 1.5 < prof.story.opener_seconds < 2.3, (len(prof.story.body_lengths), prof.story.opener_seconds))
try: ps.profile_from_references(["corporate-highlight-calm", "fashion-event-converse-kenzo"]); check("it can't be pooled with another reference", False)
except ValueError as e: check("it can't be pooled with another reference (plain message)", "complete style of its own" in str(e), str(e)[:100])
listed = {s["slug"]: s for s in ps.available_styles()}
check("it is listed among the buildable styles", "corporate-highlight-calm" in listed and listed["corporate-highlight-calm"]["tags"]["edit_type"] == "corporate_highlight")
card = pe._style_card({**listed["corporate-highlight-calm"]})
check("its card says corporate_highlight, 40 s, no accents and CALM shot lengths (~2.1 s median, not the reference's 1.6)", card["edit_type"] == "corporate_highlight" and card["seconds"] == 40 and not card["has_accents"] and 1.8 <= card["median_shot_seconds"] <= 2.5, card)
path = pr.REFERENCE_DIR / "corporate-highlight-calm.json"; saved = path.read_text(); path.unlink()
ps.profile_from_references(["corporate-highlight-calm"])
check("the style record heals itself if the (git-ignored) data folder loses it", path.exists() and json.loads(path.read_text())["tags"]["edit_type"] == "corporate_highlight")
check("the corporate story style is untouched by all this", not ps.profile_from_references(["corporate-distribution-company"]).highlight and ps.profile_from_references(["corporate-distribution-company"]).edit_type == "narrated_broll")

# ---------------------------------------------------------------- cut times
rng = random.Random(3)
def beat_hits(seconds, bpm=120, seed=3):
    r = random.Random(seed); beat = 60.0 / bpm; out = []; t = 0.0; i = 0
    while t < seconds:
        pct = 96 if i % 4 == 0 else (82 if i % 2 == 0 else 68)
        out.append([round(t, 3), pct + r.random() * 2]); out.append([round(t + beat / 2, 3), 56 + r.random() * 6]); t += beat; i += 1
    return out
HITS = beat_hits(160)
cp = hl.cut_profile(prof, 40.0, st.CALM_PACE)
check("cut_profile: calm lengths (median x1.3), nothing under a second, closing hold sized to the edit, no accents", min(cp.shot_lengths) >= 1.0 and 1.8 <= float(np.median(cp.shot_lengths)) <= 2.5 and 2.5 <= cp.end_card_seconds <= 4.5 and cp.accents is None and abs(cp.end_card_seconds - 4.4) < 0.05, (float(np.median(cp.shot_lengths)), cp.end_card_seconds))
cuts = pe.plan_cut_times([[h[0] - 10.0, h[1]] for h in HITS if 10 <= h[0] <= 50.05], 40.0, cp, random.Random(5), opener_seconds=prof.story.opener_seconds)
check("plan_cut_times with an opener: first cut at 0, second within 0.6 s of the opener length and on a hit", cuts[0]["t"] == 0 and abs(cuts[1]["t"] - prof.story.opener_seconds) <= 0.62 and cuts[1]["on_hit"], cuts[:3])
none_op = pe.plan_cut_times([[h[0] - 10.0, h[1]] for h in HITS if 10 <= h[0] <= 50.05], 40.0, cp, random.Random(5))
check("plan_cut_times without an opener behaves as before (no extra early cut)", len(none_op) >= 3 and none_op[1]["t"] > 0.9, none_op[:3])
sparse = pe.plan_cut_times([[7.0, 90.0], [15.0, 90.0], [25.0, 90.0], [34.0, 90.0]], 40.0, cp, random.Random(5), opener_seconds=1.87)
check("an opener with no hit near it falls back to cutting at exactly its length, off the beat", abs(sparse[1]["t"] - 1.87) < 1e-6 and not sparse[1]["on_hit"], sparse[:3])

# ---------------------------------------------------------------- clips with known content (static / moving / with cuts)
H, W, F = sd.FRAME_H, sd.FRAME_W, int(sd.SAMPLE_FPS)
def gf(img, sigma):
    r = int(3 * sigma) + 1; k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    o = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 1, img)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, mode="valid"), 0, o)
def scene(seed):
    img = gf(np.random.default_rng(seed).random((H + 40, W + 200)).astype(np.float32), 1.4); return (img - img.min()) / (img.max() - img.min()) * 255
nz = np.random.default_rng(9)
def seg(kind, seed, sec):
    base = scene(seed); n = int(sec * F); crop = lambda dx=0: np.clip(base[20:20 + H, 20 + dx:20 + dx + W], 0, 255)
    return [np.clip(crop(int(i * (1.0 if kind == "moving" else 0))) + nz.normal(0, 0.8, (H, W)), 0, 255) for i in range(n)]
def clip_of(*segs): return np.stack([f for s in segs for f in s]).astype(np.uint8)
def steady_clip(i, kind, sec=9):
    parts = {"static": [seg("static", i, sec)], "moving": [seg("moving", i, sec)], "cuts": [seg("static", i, 3), seg("static", i + 500, 3), seg("static", i + 900, 3)]}[kind]
    m = sd.measure(clip_of(*parts)); return {"file_id": i, "name": f"C{i:04d}.MP4", "path": f"/x/C{i:04d}.MP4", "duration": m["seconds"], "created": "", "picks": [], "steady": m, "_kind": kind}
kinds = ["static", "moving", "cuts", "static", "moving", "moving", "static", "cuts"] * 4
CLIPS = [steady_clip(i + 1, k) for i, k in enumerate(kinds)]
by_id = {c["file_id"]: c for c in CLIPS}

def plan_for(**kw):
    a = dict(profile=prof, hits=HITS, music_in=10.0, duration=40.0, fps=FPS, clips=CLIPS, bookend_file_id=None, seed=5); a.update(kw)
    return hl.build_highlight_plan(**a)
plan = plan_for()
shots = plan["shots"]; body = [s for s in shots if s["role"] == "body"]
check("plan: it is a highlight plan lasting exactly 40 s on the frame grid", plan["mode"] == "highlight" and plan["duration_frames"] == 960 and plan["duration_seconds"] == 40.0, (plan["mode"], plan["duration_frames"]))
check("plan: slots are contiguous from frame 0 to the end, every shot at least 3 frames", shots[0]["start_frame"] == 0 and all(b["start_frame"] == a["start_frame"] + a["duration_frames"] for a, b in zip(shots, shots[1:])) and shots[-1]["start_frame"] + shots[-1]["duration_frames"] == 960 and min(s["duration_frames"] for s in shots) >= 3)
check("plan: opens on the opening-card slot, closes on the closing hold, body in between", shots[0]["role"] == "opener" and shots[-1]["role"] == "end_card" and all(s["role"] == "body" for s in shots[1:-1]) and len(body) >= 8, [s["role"] for s in shots])
check("plan: the opener is about 1.9 s and the closing hold about 4.4 s", 1.3 <= shots[0]["duration_frames"] / FPS <= 2.5 and 3.9 <= shots[-1]["duration_frames"] / FPS <= 5.2, (shots[0]["duration_frames"] / FPS, shots[-1]["duration_frames"] / FPS))
med = float(np.median([s["duration_frames"] / FPS for s in body]))
check("plan: calm pacing -- body shots run about 2 s (median 1.6-2.8 s), nothing under a second", 1.6 <= med <= 2.8 and min(s["duration_frames"] for s in body) >= 24 - 1, med)
check("plan: cuts land on the music's hits (>= 80%) and say which hit", plan["checks"]["cuts_on_hits"] >= 0.8 and all(s["cut_hit_percentile"] is not None for s in shots if s["cut_on_hit"]), plan["checks"]["cuts_on_hits"])
hit_times = sorted(h[0] - 10.0 for h in HITS)
off = [s for s in shots if s["cut_on_hit"] and min(abs(s["start_frame"] / FPS - h) for h in hit_times) > 0.03]
check("plan: every cut flagged 'on a hit' really is within 30 ms of a hit in the song", not off, [(s["index"], s["start_frame"] / FPS) for s in off][:4])
check("plan: no shot has a hard cut inside it", all((s.get("steady") or {}).get("cuts", 0) == 0 for s in shots), [(s["index"], by_id[s["file_id"]]["_kind"]) for s in shots if (s.get("steady") or {}).get("cuts")])
check("plan: shot windows stay inside their clips", all(0 <= s["source_in"] and s["source_out"] <= by_id[s["file_id"]]["duration"] + 1e-6 for s in shots))
zs = {z["shot_index"] for z in plan["zooms"]["items"]}; static_idx = {s["index"] for s in body if s["steady"]["static"]}
check("plan: slow zooms are on exactly the static body shots, never on the cards or a moving shot", zs == static_idx and len(zs) > 0 and not any(by_id[s["file_id"]]["_kind"] == "moving" for s in body if s["index"] in zs), (sorted(zs), sorted(static_idx)))
check("plan: zooms are push-ins AND pull-outs, each 2.5-5%", {z["direction"] for z in plan["zooms"]["items"]} == {"in", "out"} and all(2.5 <= z["percent"] <= 5.0 for z in plan["zooms"]["items"]), [(z["direction"], z["percent"]) for z in plan["zooms"]["items"]])
check("plan: hard cuts only -- no accents, no narration, no captions", "accents" not in plan and "narration" not in plan and not any("phrase" in s for s in shots))
check("plan: asks Premiere to fill the frame by default, and says so; fill_frame=False leaves it out", plan.get("fit") == "fill" and any("fill the frame" in n for n in plan["notes"]) and "fit" not in plan_for(fill_frame=False))
check("plan: music starts where asked and fades out over the closing hold", plan["music"]["in_seconds"] == 10.0 and 1.5 <= plan["music"]["fade_out_seconds"] <= 4.0, plan["music"])
check("plan: notes say hard cuts, steadiest windows, pace 1.3 and that the rhythm is adapted", any("Hard cuts only" in n for n in plan["notes"]) and any("1.3x" in n for n in plan["notes"]) and any("adapted" in n for n in plan["notes"]) and any("slow zoom" in n for n in plan["notes"]))
check("plan: checks report the steady and zoom counts", plan["checks"]["steady"]["slow_zooms"] == len(plan["zooms"]["items"]) and plan["checks"]["steady"]["shots_with_a_cut_inside"] == 0 and plan["checks"]["opener_slot"], plan["checks"]["steady"])

# options
p_fast = plan_for(pace=1.0); p_slow = plan_for(pace=1.8)
check("pace: slower pace = fewer, longer shots", len(p_slow["shots"]) < len(plan["shots"]) < len(p_fast["shots"]), (len(p_fast["shots"]), len(plan["shots"]), len(p_slow["shots"])))
for bad in (0.5, 3.0):
    try: plan_for(pace=bad); check(f"pace {bad} refused", False)
    except pe.EditPlanError as e: check(f"pace {bad} refused with the allowed range", "between" in str(e), str(e)[:90])
try: plan_for(duration=8.0); check("an 8 s highlight is refused", False)
except pe.EditPlanError as e: check("an 8 s highlight is refused plainly", "at least 12" in str(e), str(e)[:90])
check("slow_zooms=False plans none but the same shots", "zooms" not in plan_for(slow_zooms=False) and [s["source_in"] for s in plan_for(slow_zooms=False)["shots"]] == [s["source_in"] for s in plan["shots"]])
no_op = plan_for(with_opener=False)
check("with_opener=False: no opening-card slot, the edit starts straight on a body shot", no_op["shots"][0]["role"] == "body" and no_op["shots"][-1]["role"] == "end_card" and not no_op["checks"]["opener_slot"])
bk = plan_for(bookend_file_id=CLIPS[0]["file_id"])
check("an establishing clip opens the edit and comes back under the closing card", bk["shots"][0]["file_id"] == CLIPS[0]["file_id"] and bk["shots"][-1]["file_id"] == CLIPS[0]["file_id"] and all(s["file_id"] != CLIPS[0]["file_id"] for s in bk["shots"][1:-1]) and bk["checks"]["bookend"])
for L in (35.0, 45.0):
    pl = plan_for(duration=L); check(f"{L:.0f} s lands exactly on the requested length", pl["duration_seconds"] == L and pl["shots"][-1]["start_frame"] + pl["shots"][-1]["duration_frames"] == round(L * FPS), pl["duration_seconds"])
check("deterministic: same seed, same plan; another seed, another plan", json.dumps(plan_for(), sort_keys=True) == json.dumps(plan_for(), sort_keys=True) and json.dumps(plan_for(seed=6)["shots"], sort_keys=True) != json.dumps(plan["shots"], sort_keys=True))
allmoving = [steady_clip(100 + i, "moving") for i in range(30)]
check("all-moving footage: no zooms at all", "zooms" not in plan_for(clips=allmoving))
unread = [{k: v for k, v in c.items() if k not in ("steady", "_kind")} for c in CLIPS]
p_un = plan_for(clips=unread)
check("clips that couldn't be analysed fall back to the old window choice, with no zooms", "zooms" not in p_un and all(not s.get("steady") for s in p_un["shots"]) and p_un["checks"]["moment_sources"]["middle"] > 0)

# the review step on a highlight plan
import app.post_review as prv
clips_ev = [{**c, "events": [{"t": 1.5, "punch": 6.0, "kind": "action", "what": "a"}, {"t": 4.5, "punch": 5.0, "kind": "reaction", "what": "b"}, {"t": 7.5, "punch": 4.0, "kind": "hero", "what": "c"}], "scene": f"scene {c['file_id']}"} for c in CLIPS]
try:
    pr_ = json.loads(json.dumps(plan)); zshot = next(s for s in pr_["shots"] if s["index"] in zs)
    slot = next(s for s in prv.build_review(pr_, clips_ev)["slots"] if s["index"] == zshot["index"]); alt = slot["alternatives"][0]
    prv.apply_choice(pr_, clips_ev, zshot["index"], alt["file_id"], alt["source_in"], "swap")
    check("review: swapping a shot's moment drops its zoom", all(z["shot_index"] != zshot["index"] for z in pr_["zooms"]["items"]) and len(pr_["zooms"]["items"]) == len(zs) - 1)
except Exception as exc:
    check("review step works on a highlight plan", False, repr(exc))

# ---------------------------------------------------------------- the brand graphics on a vertical frame
tmp = tempfile.mkdtemp(prefix="hl_gfx_")
# (2026-10-22) the logo this test used, gfx/test_logo.png, was never committed, so the test failed on any other checkout: it draws its own now
from PIL import Image as _Image  # noqa: E402
LOGO = f"{tempfile.mkdtemp(prefix='hl_logo_')}/test_logo.png"
_Image.new("RGBA", (600, 240), (230, 40, 40, 255)).save(LOGO)
try:
    from pathlib import Path
    gfx, notes = bg.build_graphics(plan, job={"deliverable_format": "9:16", "resolution": "4k_uhd"}, logo_path=LOGO, size=(2160, 3840), out_dir=Path(tmp), tagline="Moving forward", contact_lines=["a.co.za", "b@a.co.za"], logo_bug=False)
    check("graphics: opening and closing cards only (no logo bug, no captions) on a 2160 x 3840 frame", gfx["frame_size"] == [2160, 3840] and [c["role"] for c in gfx["cards"]] == ["opener", "closer"] and gfx["logo_bug"] is None and gfx["captions"] is None, {k: gfx[k] for k in ("frame_size", "logo_bug", "captions")})
    check("graphics: each card sits exactly on its slot", gfx["cards"][0]["start_frame"] == shots[0]["start_frame"] and gfx["cards"][0]["frames"] == shots[0]["duration_frames"] and gfx["cards"][1]["start_frame"] == shots[-1]["start_frame"] and gfx["cards"][1]["frames"] == shots[-1]["duration_frames"])
    check("graphics: the card images are full-frame 2160 x 3840", all(__import__("PIL.Image", fromlist=["Image"]).open(c["file"]).size == (2160, 3840) for c in gfx["cards"]))
    g2, _ = bg.build_graphics(plan, job={}, logo_path=LOGO, size=(2160, 3840), out_dir=Path(tmp), tagline=None, contact_lines=None, logo_bug=True)
    box = g2["logo_bug"]["box"]
    check("graphics: with the logo bug on, the vertical plate keeps the reference's shape (about 2.1:1), 24% of the width, in the top-right", abs((box[2] - box[0]) / (box[3] - box[1]) - 2.14) < 0.15 and abs((box[2] - box[0]) / 2160 - 0.24) < 0.01 and box[2] < 2160 and box[1] > 100, box)
    land, _ = bg.build_graphics({**plan}, job={}, logo_path=LOGO, size=(3840, 2160), out_dir=Path(tmp), tagline=None, contact_lines=None, logo_bug=True)
    check("graphics: a 16:9 frame still uses the reference's own plate box (unchanged)", land["logo_bug"]["box"] == [round(0.796 * 3840), round(0.051 * 2160), round(0.949 * 3840), round(0.178 * 2160)], land["logo_bug"]["box"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- end to end: plan_for_job, fake job, REAL fixture clips + a real song, vertical 4K
SONG = "/Users/joshuapeters/Downloads/Channel 13 - Do You Remember - Instrumental Version.mp3"; SRC = "e2e/src_corporate_4k"
def probe_seconds(p): return float(subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.split()[0])
# (2026-10-22) this section needs 4K fixture footage and a song that live outside the repo; when they are missing it says so and is skipped instead of crashing
HAVE_FIXTURES = os.path.isdir(SRC) and os.path.exists(SONG)
REAL = [{"file_id": i + 1, "name": f, "path": os.path.abspath(f"{SRC}/{f}"), "duration": probe_seconds(f"{SRC}/{f}"), "created": "", "picks": []} for i, f in enumerate(sorted(os.listdir(SRC))) if f.endswith(".MP4")] if HAVE_FIXTURES else []
async def e2e():
    from app import post_db
    tmp = tempfile.mkdtemp(prefix="hl_e2e_")
    job = {"id": 9101, "shoot_name": "HLTEST", "profile": "alpha_mode", "destination_root": tmp, "media_analyzed_at": "2026-10-14", "frame_rate": "24", "deliverable_format": "9:16", "resolution": "4k_uhd"}
    async def fake_job(job_id, postgres_conn=None): return dict(job)
    async def fake_clips(job_id, postgres_conn=None, order_names=None): return [dict(c) for c in REAL]
    real_get, real_load = post_db.get_post_job, pe.load_job_clips
    post_db.get_post_job, pe.load_job_clips = fake_job, fake_clips
    try:
        os.makedirs(f"{tmp}/07_MUSIC"); os.makedirs(f"{tmp}/06_GRAPHICS"); shutil.copyfile(SONG, f"{tmp}/07_MUSIC/bed.mp3"); shutil.copyfile(LOGO, f"{tmp}/06_GRAPHICS/logo.png")
        plan = await pe.plan_for_job(9101, style=["corporate-highlight-calm"], music_path=f"{tmp}/07_MUSIC/bed.mp3", seed=4, card_tagline="Moving forward", card_contact=["a.co.za"])
        out = f"{tmp}/10_PREMIERE/edit_plans"
        check("e2e: a highlight plan, saved, 40 s by default, with the cut-to-music checks", plan["mode"] == "highlight" and os.path.exists(f"{out}/edit_plan_latest.json") and plan["duration_seconds"] == 40.0 and plan["checks"]["cuts_on_hits"] >= 0.75, (plan["mode"], plan["duration_seconds"], plan["checks"]["cuts_on_hits"]))
        check("e2e: steadiness analysed the real clips (every shot has a steady window) and the cache file exists", plan["checks"]["steady"]["shots_with_a_steady_window"] == len(plan["shots"]) and os.path.exists(f"{out}/steadiness.json"), plan["checks"]["steady"])
        check("e2e: no shot has a cut inside and the zooms are only on static footage", plan["checks"]["steady"]["shots_with_a_cut_inside"] == 0 and all(next(s for s in plan["shots"] if s["index"] == z["shot_index"])["steady"]["static"] for z in (plan.get("zooms") or {}).get("items", [])))
        g = plan.get("graphics")
        check("e2e: opening and closing cards for a 2160 x 3840 sequence, no logo bug, no captions, files exist", g and g["frame_size"] == [2160, 3840] and [c["role"] for c in g["cards"]] == ["opener", "closer"] and g["logo_bug"] is None and g["captions"] is None and all(os.path.exists(c["file"]) for c in g["cards"]), g and {k: g[k] for k in ("frame_size", "logo_bug")})
        cut = plan["music"]["cut_path"]; dur = float(subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", cut], capture_output=True, text=True).stdout.split()[0])
        check("e2e: the music is cut to the picture's length, with no lead shift (cuts sit exactly on the hits)", abs(dur - plan["duration_seconds"]) < 0.15 and "cut_lead_seconds" not in plan["music"], (dur, plan["music"]))
        p2 = await pe.plan_for_job(9101, style=["corporate-highlight-calm"], music_path=f"{tmp}/07_MUSIC/bed.mp3", target_seconds=36, seed=4, logo_bug=True, slow_zooms=False, pace=1.6)
        check("e2e: 36 s, logo bug switched on, zooms off, pace 1.6 all honoured", abs(p2["duration_seconds"] - 36) < 0.1 and p2["graphics"]["logo_bug"] is not None and "zooms" not in p2 and p2["checks"]["steady"]["pace"] == 1.6, (p2["duration_seconds"], p2["checks"]["steady"]))
        p3 = await pe.plan_for_job(9101, style=["corporate-highlight-calm"], music_path=f"{tmp}/07_MUSIC/bed.mp3", target_seconds=40, seed=4, brand_graphics=False)
        check("e2e: brand graphics off -> no graphics block and no card slot needed", "graphics" not in p3 and p3["shots"][0]["role"] in ("opener", "body"))
        os.remove(f"{tmp}/06_GRAPHICS/logo.png")
        p4 = await pe.plan_for_job(9101, style=["corporate-highlight-calm"], music_path=f"{tmp}/07_MUSIC/bed.mp3", target_seconds=40, seed=4)
        check("e2e: no logo in the job -> the plan still builds and says why there are no cards", "graphics" not in p4 and p4["shots"][0]["role"] == "body" and any("No logo found" in n for n in p4["notes"]), [n[:60] for n in p4["notes"]])
        # regressions: the other styles are untouched
        s1 = await pe.plan_for_job(9101, style=["corporate-distribution-company"], music_path=f"{tmp}/07_MUSIC/bed.mp3", target_seconds=40, seed=4)
        s2 = await pe.plan_for_job(9101, style=["fashion-event-converse-kenzo"], music_path=f"{tmp}/07_MUSIC/bed.mp3", seed=4)
        check("e2e regression: the narrated story is still a story plan and a music reel is still a hit-synced reel", s1["mode"] == "story" and s2.get("mode") != "highlight" and s2["checks"]["cuts_on_hits"] is not None and s2["music"].get("cut_lead_seconds") == 0.025, (s1["mode"], s2.get("mode")))
        try: await pe.plan_for_job(9101, style=["corporate-highlight-calm"], music_path=f"{tmp}/07_MUSIC/bed.mp3", target_seconds=400)
        except pe.EditPlanError as e: check("e2e: a 400 s highlight with a 194 s song is refused with the track length stated", "track is" in str(e), str(e)[:100])
    finally:
        post_db.get_post_job, pe.load_job_clips = real_get, real_load; shutil.rmtree(tmp, ignore_errors=True)
if HAVE_FIXTURES:
    asyncio.run(e2e())
else:
    print(f"SKIP e2e section: fixture footage ({SRC}) or song ({SONG}) not on this machine -- 0 of its checks ran")
print("\nFAILS:", fails); sys.exit(1 if fails else 0)
