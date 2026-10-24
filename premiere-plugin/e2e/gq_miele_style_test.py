"""The blended "GQ x Miele event reel" style (2026-10-24): the shot rhythm and shape of the Moet x Don C reel (his priority reference, counted double) with his
Miele Decorex edit, cuts on the music's hits like the Decorex edit, each shot starting just before the moment Claude described (on the action). Reads the two
saved reference records (backend/data/post_references); runs the real music-montage planner on synthetic music and clips. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python gq_miele_style_test.py"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_clips import make_clips  # noqa: E402
from app import post_edit_plan as pe, post_reference as pr, post_style as ps  # noqa: E402

fails = 0


def beat_hits(seconds, bpm=120, seed=3):
    """A steady synthetic song: strong hits on the beat (downbeats strongest), weak ones between (same shape as candidate_engine_test's)."""
    import random
    r = random.Random(seed)
    beat, out, t, i = 60.0 / bpm, [], 0.0, 0
    while t < seconds:
        out.append([round(t, 3), (96 if i % 4 == 0 else 80) + r.random() * 2])
        out.append([round(t + beat / 2, 3), 56 + r.random() * 6])
        t += beat
        i += 1
    return out


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


if not all((pr.REFERENCE_DIR / f"{s}.json").exists() for s in ("moet-just-don-jackbotti", "furniture-expo-decorex")):
    print("SKIP  the Moet or Decorex reference record isn't saved on this machine")
    print("\nFAILS: 0")
    sys.exit(0)

p = ps.profile_from_references(["gq-miele-blend"])
moet, decorex = pr.load_reference("moet-just-don-jackbotti"), pr.load_reference("furniture-expo-decorex")
check("a music montage, flagged as inferred (blended, not measured as one edit)", p.edit_type == "music_montage" and p.inferred)
check("on the beat like his Miele Decorex edit: 83% of cuts on hits, 70 ms lead", p.hit_snap_rate == decorex["music_sync"]["cuts_within_40ms_of_a_strong_hit"] == 0.83
      and abs(p.cut_lead_seconds - 0.07) < 1e-9, (p.hit_snap_rate, p.cut_lead_seconds))
m_med = statistics.median(s["end"] - s["start"] for s in moet["edit"]["shots"])
d_med = statistics.median(s["end"] - s["start"] for s in decorex["edit"]["shots"])
check("its pace sits between the two, nearer the priority reel (Moet 0.55 s, Decorex 0.65 s)", m_med <= statistics.median(p.shot_lengths) <= d_med
      and abs(statistics.median(p.shot_lengths) - m_med) < abs(statistics.median(p.shot_lengths) - d_med), (m_med, statistics.median(p.shot_lengths), d_med))
check("the Moet reel counts double: twice its shots plus Decorex's", len(p.shot_lengths) == 2 * len(moet["edit"]["shots"]) + len(decorex["edit"]["shots"]))
curve = p.pacing_curve
check("its shape: a faster build late on (tenths 8-9 quicker than the edit's mean) and a slow ending (last tenth the slowest)", max(curve[7], curve[8]) < statistics.mean(curve)
      and curve[9] == max(curve), curve)
check("it closes on the Moet reel's logo hold (1.57 s)", abs(p.end_card_seconds - 1.57) < 0.01, p.end_card_seconds)
cards = [s for s in ps.available_styles() if s["slug"] == "gq-miele-blend"]
check("it is offered in Plan Edit, by a plain name", bool(cards) and ps.FRIENDLY_STYLES["gq-miele-blend"][0] == "GQ x Miele event reel")
check("the Moet reel on its own stays reference-only (it's cut on the action, not the beat)", all(s["slug"] != "moet-just-don-jackbotti" for s in ps.available_styles()))
try:
    ps.profile_from_references(["gq-miele-blend", "furniture-expo-decorex"])
    check("a blend can't be pooled with other references", False)
except ValueError as exc:
    check("a blend can't be pooled with other references", "blended style" in str(exc), str(exc))
try:
    ps._blend_profile({"slug": "x", "rhythm_weights": {"furniture-expo-decorex": 1}, "beat_from": ["moet-just-don-jackbotti"]})
    check("the beat timing can only come from an edit cut to the music", False)
except ValueError as exc:
    check("the beat timing can only come from an edit cut to the music", "isn't cut to the music" in str(exc), str(exc))

# ---- the real planner with this style: on the beat, and each shot starting on the action -------------------------------------------------------------------
clips = make_clips()
hits = beat_hits(80, bpm=120)
plan = pe.build_plan(profile=p, hits=hits, music_in=10.0, duration=p.target_duration_seconds, fps=25.0, clips=clips, bookend_file_id=None, seed=7)
shots = plan["shots"]
check("the cuts land on the music's hits (at least 75%, the style asks 83%)", plan["checks"]["cuts_on_hits"] >= 0.75, plan["checks"]["cuts_on_hits"])
lengths = [s["duration_frames"] / 25.0 for s in shots]
check("the plan's pace is the style's (median within 25%)", abs(statistics.median(lengths) - statistics.median(p.shot_lengths)) <= 0.25 * statistics.median(p.shot_lengths),
      (statistics.median(lengths), statistics.median(p.shot_lengths)))
by_id = {c["file_id"]: c for c in clips}
event_shots = [s for s in shots if s["moment_source"].startswith("event")]
on_action = [s for s in event_shots if any(s["source_in"] <= e["t"] <= s["source_in"] + 0.25 for e in by_id[s["file_id"]].get("events") or [])]
check("each shot with a described moment starts just before it, so the action begins at the cut (within 0.25 s of the start)", event_shots and len(on_action) == len(event_shots),
      (len(on_action), len(event_shots)))
check("the last shot holds for the logo ending", abs(lengths[-1] - p.end_card_seconds) < 0.2 or lengths[-1] >= 1.3, lengths[-3:])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
