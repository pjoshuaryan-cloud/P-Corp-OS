"""
POST (2026-10-22) -- several genuinely different edit plans from the same analysed footage, and a comparison of them.

Why: one plan at a time gave Josh a single first draft to accept or rebuild. A variant set gives him two to four directions side by side (say his usual pace,
a high-energy commercial cut and a premium one), each built from the same song window, length and analysis, so they can be compared fairly, and the one he
likes becomes the job's plan.

How a variant is built: a profile from the Editing Style Library (post_style_library) is turned into planner settings (planner_config) and run through the SAME
highlight planner the app already uses, on Josh's measured usual rhythm scaled by the profile's pace:
  * the cut times come from the music's hits at that pace, with the profile's pacing curve (flat / build / breathe);
  * the picker prefers the profile's kinds of shot, opens and closes on its preferred kinds, and varies looks as hard as the profile asks;
  * every variant after the first is told which stretches the earlier ones used, so it shows different footage where the shoot allows.
Nothing is read twice: the clips, their descriptions, their steadiness analysis and the song analysis are loaded once for the whole set. A variant set makes
NO Claude API calls (it reuses descriptions already made).

What a variant does NOT do, said in every variant: anything the profile lists as proposal-only (dissolves, speed ramps, colour, typography, sound design,
off-beat cuts ...) is written down for Josh and never executed; the moment chosen in each clip is Claude's judgement plus the planner's rules, not his taste.

Files: edit_plans/variants/<set id>/variant_<n>.json (each a complete plan the plugin can build) and set.json (the comparison). Choosing a variant copies it to
edit_plan_latest.json through the same archive the planner uses, so the previous plan is kept and Build My Edit builds the chosen one with no plugin change.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

VARIANTS_VERSION = 1
MIN_VARIANTS, MAX_VARIANTS = 2, 4
DEFAULT_DIRECTIONS = ("music-led-montage", "high-energy-commercial", "premium-luxury", "event-highlights")
TOO_SIMILAR_SHARE = 0.35   # two variants whose shots overlap more than this share are reported as too alike (the shoot may have too few clips)


class VariantError(RuntimeError):
    pass


def _ts() -> str:
    return time.strftime("%Y%m%dT%H%M%S")


def variants_dir(edit_dir: Path) -> Path:
    return edit_dir / "variants"


# ------------------------------------------------------------------------------------------------------------- comparing plans
def _windows(plan: dict[str, Any]) -> list[tuple[int, float, float]]:
    return [(s["file_id"], float(s["source_in"]), float(s["source_out"])) for s in plan["shots"] if s.get("role") == "body"]


def overlap_share(a: dict[str, Any], b: dict[str, Any]) -> float:
    """The share of a's body shots whose stretch overlaps a stretch b uses from the same clip."""
    wa, wb = _windows(a), _windows(b)
    if not wa:
        return 0.0
    hits = sum(1 for f, s0, s1 in wa if any(f == g and s0 < t1 and s1 > t0 for g, t0, t1 in wb))
    return hits / len(wa)


def metrics(plan: dict[str, Any]) -> dict[str, Any]:
    """What a variant is like, measured from the plan itself: shot count and lengths, roles, clips, opening and closing shot."""
    fps = float(plan["fps"])
    body = [s for s in plan["shots"] if s.get("role") == "body"]
    lengths = [s["duration_frames"] / fps for s in body] or [0.0]
    roles: dict[str, int] = {}
    for s in body:
        role = (s.get("candidate") or {}).get("role") or "unknown"
        roles[role] = roles.get(role, 0) + 1
    half = len(lengths) // 2
    quarters = [lengths[round(q * len(lengths) / 4):round((q + 1) * len(lengths) / 4)] for q in range(4)]
    return {
        "shots": len(plan["shots"]), "body_shots": len(body), "seconds": plan.get("duration_seconds"),
        "median_shot": round(statistics.median(lengths), 2), "mean_shot": round(statistics.mean(lengths), 3),
        "first_half_median": round(statistics.median(lengths[:half]), 2) if half else None,
        "second_half_median": round(statistics.median(lengths[half:]), 2) if half else None,
        # means, not medians, for the shape: cuts snap to beats, so at most tempos half the shots are exactly one beat long and medians tie
        "first_half_mean": round(statistics.mean(lengths[:half]), 3) if half else None,
        "second_half_mean": round(statistics.mean(lengths[half:]), 3) if half else None,
        "quarter_means": [round(statistics.mean(q), 3) if q else None for q in quarters],
        "distinct_clips": len({s["file_id"] for s in body}), "role_mix": {k: round(v / max(len(body), 1), 2) for k, v in sorted(roles.items())},
        "opening_role": (body[0].get("candidate") or {}).get("role") if body else None,
        "closing_role": (plan["shots"][-1].get("candidate") or {}).get("role") if plan["shots"] else None,
        "cuts_on_hits": (plan.get("checks") or {}).get("cuts_on_hits"),
        "distinct_looks": ((plan.get("checks") or {}).get("repetition") or {}).get("distinct_looks"),
    }


def compare(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """Pairwise overlap and clip sharing, plus which pairs are too alike to be real alternatives."""
    pairs = []
    for i in range(len(plans)):
        for j in range(i + 1, len(plans)):
            ci = {f for f, _, _ in _windows(plans[i])}
            cj = {f for f, _, _ in _windows(plans[j])}
            share = round(max(overlap_share(plans[i], plans[j]), overlap_share(plans[j], plans[i])), 2)
            pairs.append({"a": i + 1, "b": j + 1, "shared_stretches": share, "shared_clips": round(len(ci & cj) / max(len(ci | cj), 1), 2),
                          "too_alike": share > TOO_SIMILAR_SHARE})
    return {"pairs": pairs, "too_alike": [p for p in pairs if p["too_alike"]]}


# ----------------------------------------------------------------------------------------------------------------- one variant
def _cards_not_made(executed: list[str], proposed: list[str], why: str) -> None:
    """A brand card the direction wants but that wasn't drawn is not 'done in the plan': move its line to the proposals, saying why."""
    for line in [x for x in executed if "brand card" in x]:
        executed.remove(line)
        proposed.append(f"{line} -- not made: {why}")


def _curve_measured(curve: str, m: dict[str, Any]) -> str:
    """What the pacing curve actually did in this plan. Every cut snaps to a music hit, so the curve shifts shot lengths on average (on synthetic songs from 100
    to 175 BPM a build shortens the second half by about a fifth against an even rhythm, averaged over 12 seeds) but any one plan can come out flatter, or even
    the other way round: so the plan reports what it measured instead of promising the shape."""
    if curve == "build" and m.get("first_half_mean") is not None:
        return f" Measured: shots average {m['first_half_mean']:.2f} s in the first half and {m['second_half_mean']:.2f} s in the second."
    q = m.get("quarter_means") or []
    if curve == "breathe" and len(q) == 4 and None not in q:
        return f" Measured: the opening and closing quarters average {(q[0] + q[3]) / 2:.2f} s a shot, the middle {(q[1] + q[2]) / 2:.2f} s."
    return ""


def describe_variant(style: Any, cfg: dict[str, Any], plan: dict[str, Any], *, index: int, set_id: str, with_cards: bool) -> dict[str, Any]:
    """The variant block a plan carries: its direction in plain words, what is executed and what is only proposed, its measured shape and its limits."""
    from app import post_style_library as lib
    report = lib.execution_report(style)
    m = metrics(plan)
    curve = {None: "an even rhythm", "build": "a rhythm that builds (shots get shorter toward the end)", "breathe": "a rhythm that breathes (longer opening and closing shots)"}
    curve_name = style.pacing_curve if style.pacing_curve != "flat" else None
    def a(word: str) -> str:
        word = word.replace("_", " ")
        return ("an " if word[:1] in "aeiou" else "a ") + word
    approach = (f"{style.intent} Cut at {cfg['pace']:g}x your usual rhythm with {curve.get(curve_name, 'an even rhythm')}; median shot {m['median_shot']} s over {m['body_shots']} shots."
                + _curve_measured(style.pacing_curve, m)
                + (f" Prefers to open on {a(cfg['first_role'])} shot (it opened on {a(str(m['opening_role']))})." if cfg.get("first_role") else "")
                + (f" Prefers to end on {a(cfg['last_role'])} hold (it ended on {a(str(m['closing_role']))})." if cfg.get("last_role") else ""))
    limitations = [
        "Which moment of each clip is used is Claude's judgement from stills plus the planner's rules, not checked against your taste.",
        "Everything listed under 'proposed only' is advice for you; the Premiere build does hard cuts only.",
    ]
    if style.provenance_note:
        limitations.append(style.provenance_note)
    executed, proposed = list(report["executed"]), list(report["proposed_only"])
    if (cfg.get("opener_card") or cfg.get("closing_card")) and not with_cards:
        limitations.append("This direction wants brand cards, but the job has no logo (or no standard frame size), so none were made.")
        _cards_not_made(executed, proposed, "the job has no logo or no standard frame size")
    return {
        "version": VARIANTS_VERSION, "set_id": set_id, "index": index, "style": style.slug, "name": style.name, "intent": style.intent,
        "approach": approach, "executed": executed, "proposed_only": proposed,
        "pacing": {"pace": cfg["pace"], "curve": style.pacing_curve, "median_shot": m["median_shot"], "body_shots": m["body_shots"]},
        "music_strategy": "Cuts snap to the music's hits (measured on the song); " + str(style.music.get("notes", "")),
        "structure": {"opening": style.opening, "ending": style.ending, "chronology": "the edit broadly follows the shoot's order; it never reorders footage into a story"},
        "expected_duration_seconds": plan.get("duration_seconds"),
        "metrics": m,
        "confidence": {"basis": f"your usual rhythm is measured on your own edits; the {cfg['pace']:g}x pace on it, the shot preferences, curve and structure are editorial guidance",
                       "limitations": limitations},
        "api_calls": 0,
    }


def build_variant(style_slug: str, *, profile: Any, hits: list[list[float]], music_in: float, duration: float, fps: float, clips: list[dict[str, Any]],
                  avoid: dict[int, list[tuple[float, float]]], seed: int, with_cards: bool, index: int, set_id: str,
                  preferences: dict[str, float] | None = None) -> dict[str, Any]:
    """One variant plan (pure: no files, no network). Raises VariantError for a profile the variant planner can't build. `preferences`: learned per-kind
    nudges, passed only when they cleared the adoption gate (post_learning_events.adopted_preferences)."""
    from app import post_style_library as lib
    from app.post_edit_highlight import build_highlight_plan
    from app.post_edit_plan import EditPlanError
    try:
        style = lib.get_style(style_slug)
        cfg = lib.planner_config(style)
    except (KeyError, ValueError) as exc:
        raise VariantError(f"'{style_slug}' can't be built as a variant: {exc}") from exc
    try:
        plan = build_highlight_plan(profile=profile, hits=hits, music_in=music_in, duration=duration, fps=fps, clips=clips, bookend_file_id=None, seed=seed,
                                    pace=cfg["pace"], slow_zooms=cfg["slow_zooms"], with_opener=bool(cfg["opener_card"] and with_cards),
                                    pacing_curve=cfg["pacing_curve"],
                                    picker_options={"role_weights": cfg["role_weights"], "diversity": cfg["diversity"], "avoid": avoid, "preferences": preferences},
                                    slot_roles={"first": cfg["first_role"], "last": cfg["last_role"]})
    except EditPlanError as exc:
        raise VariantError(f"'{style.name}' couldn't be planned: {exc}") from exc
    plan["style"] = f"library:{style.slug}"
    plan["variant"] = describe_variant(style, cfg, plan, index=index, set_id=set_id, with_cards=with_cards)
    plan["variant"]["wants_cards"] = bool(cfg["opener_card"] or cfg["closing_card"])
    if preferences:
        from app.post_edit_plan import learned_note
        plan["notes"].append(learned_note(preferences))
        plan["variant"]["confidence"]["basis"] += "; moments are also nudged by kinds your own decisions taught (it passed the held-out test on your finished edits)"
    return plan


def build_set(directions: list[str], *, profile: Any, hits: list[list[float]], music_in: float, duration: float, fps: float, clips: list[dict[str, Any]],
              seed: int = 7, with_cards: bool = False, set_id: str | None = None, preferences: dict[str, float] | None = None) -> dict[str, Any]:
    """Every variant of a set, each avoiding the stretches the ones before it used, plus the comparison. Pure: no files, no network."""
    if not (MIN_VARIANTS <= len(directions) <= MAX_VARIANTS):
        raise VariantError(f"Ask for {MIN_VARIANTS} to {MAX_VARIANTS} variants (got {len(directions)}).")
    if len(set(directions)) != len(directions):
        raise VariantError("Each variant needs a different style.")
    set_id = set_id or _ts()
    avoid: dict[int, list[tuple[float, float]]] = {}
    plans = []
    for k, slug in enumerate(directions, start=1):
        plan = build_variant(slug, profile=profile, hits=hits, music_in=music_in, duration=duration, fps=fps, clips=clips, avoid={f: list(v) for f, v in avoid.items()},
                             seed=seed + k - 1, with_cards=with_cards, index=k, set_id=set_id, preferences=preferences)
        problems = validate_plan(plan, clips)
        if problems:   # never expected: the planner builds valid plans; this is the guard that a variant is never saved broken
            raise VariantError(f"'{plan['variant']['name']}' came out invalid: " + " ".join(problems[:3]))
        plans.append(plan)
        for f, s0, s1 in _windows(plan):
            avoid.setdefault(f, []).append((s0, s1))
    comparison = compare(plans)
    notes = []
    for p in comparison["too_alike"]:
        notes.append(f"Variants {p['a']} and {p['b']} share {round(100 * p['shared_stretches'])}% of their stretches: the shoot may have too few different clips for "
                     "them to be truly different.")
    notes += pace_notes(plans)
    return {"set_id": set_id, "seed": seed, "plans": plans, "comparison": comparison, "notes": notes}


PACE_GAP = 0.1          # two directions whose paces differ by at least this are meant to cut at visibly different speeds ...
PACE_MEASURED_GAP = 0.05  # ... so a faster one whose average shot is not at least 5% shorter is reported


def pace_notes(plans: list[dict[str, Any]]) -> list[str]:
    """Where a direction meant to cut faster than another did not, say so. Every cut snaps to a strong hit in a window around its target length, so on some songs and
    seeds the hits decide more than the pace does: on Josh's GWM footage (8 seeds, 20-45 s) high-energy averaged 13% shorter shots than the montage but came out no
    faster in 2-3 of the 8 seeds. The measured numbers are the truth; this only points the difference out."""
    out = []
    for i in range(len(plans)):
        for j in range(len(plans)):
            a, b = plans[i]["variant"], plans[j]["variant"]
            if a["pacing"]["pace"] <= b["pacing"]["pace"] - PACE_GAP and a["metrics"]["mean_shot"] >= b["metrics"]["mean_shot"] * (1 - PACE_MEASURED_GAP):
                out.append(f"Variant {a['index']} ({a['name']}) is meant to cut faster than variant {b['index']} ({b['name']}) but its shots average "
                           f"{a['metrics']['mean_shot']:.2f} s against {b['metrics']['mean_shot']:.2f} s: on this song the strong beats decided most cut points. "
                           "Build again for different picks, or try a longer edit.")
    return out


# ------------------------------------------------------------------------------------------------------------------ validation
def validate_plan(plan: dict[str, Any], clips: list[dict[str, Any]] | None = None, existing: set[str] | None = None) -> list[str]:
    """Every way the plan would not build as planned, in plain words ([] = sound). Always: back-to-back shots from frame 0, positive lengths, a possible source
    window that fills its slot (at the shot's speed), the total length. With `clips` (the job's clips): every shot's clip is still one of the job's and its window
    lies inside the clip. With `existing` (paths the caller found on the drive): missing media."""
    problems: list[str] = []
    fps = plan.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        return ["The plan has no frame rate."]
    shots = sorted(plan.get("shots") or [], key=lambda s: s.get("start_frame", 0))
    if not shots:
        return ["The plan has no shots."]
    by_id = {c["file_id"]: c for c in clips or []}
    frame = 0
    for s in shots:
        label = f"Shot {s.get('index')} ({s.get('name')})"
        start, length = s.get("start_frame"), s.get("duration_frames")
        if not isinstance(length, int) or length <= 0:
            problems.append(f"{label} has no length.")
            continue
        if start != frame:
            problems.append(f"{label} starts at frame {start}, but the shot before it ends at frame {frame} (a gap or an overlap on the timeline).")
        frame = (start or 0) + length
        si, so = s.get("source_in"), s.get("source_out")
        if not isinstance(si, (int, float)) or not isinstance(so, (int, float)) or si < 0 or so <= si:
            problems.append(f"{label} has an impossible source window ({si} to {so} s).")
            continue
        speed = float(s.get("speed") or 1.0)
        if abs((so - si) / speed * fps - length) > 1.0:
            problems.append(f"{label}: its source window is {(so - si) / speed * fps:.1f} frames at its speed, but its slot is {length} frames.")
        if clips is not None:
            clip = by_id.get(s.get("file_id"))
            if clip is None:
                problems.append(f"{label} isn't one of this job's clips any more.")
            elif so > float(clip.get("duration") or 0) + 0.05:
                problems.append(f"{label} runs past the end of its clip ({so:.2f} s of a {float(clip.get('duration') or 0):.2f} s clip).")
            elif existing is not None and clip.get("path") not in existing:
                problems.append(f"{label} isn't on the drive (missing media: {clip.get('path')}).")
    if plan.get("duration_frames") != frame:
        problems.append(f"The plan says it is {plan.get('duration_frames')} frames long, but its shots add up to {frame}.")
    return problems


# ------------------------------------------------------------------------------------------------------------------ job level
def add_cards(plan: dict[str, Any], job: dict[str, Any], logo: str | None, size: tuple[int, int] | None, out_dir: Path) -> None:
    """Draws the brand cards this variant's direction asks for (an opening card over its opening slot and/or a closing card over its closing hold) with the
    job's logo, the same way the planner draws a corporate highlight's cards. A direction that ends on a held hero moment gets no closing card. Mutates `plan`."""
    from app import post_style_library as lib
    from app.post_brand_graphics import GraphicsError, build_graphics
    cfg = lib.planner_config(lib.get_style(plan["variant"]["style"]))
    try:
        gfx, notes = build_graphics(plan, job=job, logo_path=logo, size=size, out_dir=out_dir, tagline=None, contact_lines=None, burn_captions=False, logo_bug=False)
    except GraphicsError as exc:
        plan["notes"].append(f"Brand cards skipped: {exc}")
        _cards_not_made(plan["variant"]["executed"], plan["variant"]["proposed_only"], str(exc).rstrip("."))
        return
    if gfx:
        gfx["cards"] = [c for c in gfx["cards"] if (c["role"] == "opener" and cfg["opener_card"]) or (c["role"] == "closer" and cfg["closing_card"])]
        if gfx["cards"]:
            plan["graphics"] = gfx
    plan["notes"].extend(notes)
    if "graphics" not in plan:
        _cards_not_made(plan["variant"]["executed"], plan["variant"]["proposed_only"], (notes[0] if notes else "the card couldn't be drawn").rstrip("."))


def _write_set(folder: Path, result: dict[str, Any], summary: dict[str, Any]) -> None:
    from app.post_edit_plan import plan_to_json
    folder.mkdir(parents=True, exist_ok=True)
    for plan in result["plans"]:
        (folder / f"variant_{plan['variant']['index']}.json").write_text(plan_to_json(plan))
    (folder / "set.json").write_text(json.dumps(summary, indent=1))


def set_summary(result: dict[str, Any], *, song: str | None, music_in: float, duration: float, made_at: str) -> dict[str, Any]:
    return {
        "version": VARIANTS_VERSION, "set_id": result["set_id"], "seed": result.get("seed"), "made_at": made_at, "song": song, "music_in_seconds": round(music_in, 3),
        "duration_seconds": duration,
        "variants": [{k: p["variant"][k] for k in ("index", "style", "name", "intent", "approach", "executed", "proposed_only", "pacing", "metrics", "confidence",
                                                   "structure", "music_strategy", "expected_duration_seconds", "api_calls")} for p in result["plans"]],
        "comparison": result["comparison"], "notes": result["notes"], "api_calls": 0,
    }


async def plan_variants_for_job(job_id: int, *, count: int = 3, styles: list[str] | None = None, target_seconds: float | None = None, music_path: str | None = None,
                                music_in_seconds: float | None = None, seed: int = 7, quick: bool = True, postgres_conn: Any = None) -> dict[str, Any]:
    """Loads the job's clips, descriptions, steadiness analysis and song ONCE, builds the set, renders one music cut for it and saves everything under
    edit_plans/variants/<set id>/. Makes no Claude API call. Returns the set summary. The job's current plan is not touched."""
    from app import post_music, post_style
    from app.post_db import get_post_job
    from app.post_edit_plan import (EditPlanError, MUSIC_FADE_OUT_SECONDS, _fps_from_job, attach_moments, bring_song_into_project, choose_music_window, edit_dir,
                                    find_logo, load_job_clips, music_dir)
    from app.post_steady import analyse_clips
    from app.ssd_guard import on_drive
    job = await get_post_job(job_id, postgres_conn=postgres_conn)
    if job is None:
        raise VariantError(f"No POST job with id {job_id}.")
    if not job.get("media_analyzed_at"):
        raise VariantError(f"Job #{job_id} needs Analyze Media run first.")
    directions = list(styles) if styles else list(DEFAULT_DIRECTIONS[:count])
    if styles and len(styles) != count and count:
        directions = list(styles)[:max(count, MIN_VARIANTS)]
    clips = await load_job_clips(job_id, postgres_conn)
    if not clips:
        raise VariantError("This job has no analysed video clips to cut from.")
    await on_drive(attach_moments, clips, job)
    counts = await analyse_clips(clips, job, only_cached=quick)
    profile = post_style.usual_pace_profile()
    duration = float(target_seconds or profile.target_duration_seconds)
    fps = _fps_from_job(job)
    mdir = music_dir(job)
    song = music_path or await on_drive(post_music.find_music_file, str(mdir))
    if not song:
        raise VariantError(f"No music yet: put a track in {mdir} (or give its path) and try again.")
    try:
        analysis = await post_music.analyze_music(song)
    except post_music.MusicAnalysisError as exc:
        raise VariantError(str(exc)) from exc
    song = await on_drive(bring_song_into_project, song, mdir, timeout=180.0, writing=True)
    try:
        music_in = choose_music_window(analysis["hits"], analysis["duration"], duration, music_in_seconds)
    except EditPlanError as exc:   # e.g. a track shorter than the edit: a plain reason, not a 500
        raise VariantError(str(exc)) from exc
    logo = await on_drive(find_logo, job)
    from app.post_brand_graphics import frame_size_for_job
    with_cards = bool(logo and frame_size_for_job(job))
    set_id = _ts()
    try:   # 2-4 full picker passes over every clip: off the event loop, so chat and the other routes stay responsive meanwhile
        from app.post_learning_events import adopted_preferences
        result = await asyncio.to_thread(build_set, directions, profile=profile, hits=analysis["hits"], music_in=music_in, duration=duration, fps=fps, clips=clips,
                                         seed=seed, with_cards=with_cards, set_id=set_id, preferences=adopted_preferences())
    except EditPlanError as exc:
        raise VariantError(str(exc)) from exc
    folder = variants_dir(edit_dir(job)) / set_id
    cut_path = mdir / f"{Path(song).stem}_variants_{set_id}.wav"   # its own file: the job's current plan keeps its own music cut
    longest = max(result["plans"], key=lambda p: p["duration_frames"])   # one cut serves the set: long enough for the longest variant, with that plan's own fade
    try:
        await post_music.render_music_cut(song, str(cut_path), music_in, longest["duration_frames"] / fps, longest["music"].get("fade_out_seconds", MUSIC_FADE_OUT_SECONDS))
    except post_music.MusicAnalysisError as exc:
        raise VariantError(f"The variants were planned, but the music couldn't be cut: {exc}") from exc
    fade = longest["music"].get("fade_out_seconds", MUSIC_FADE_OUT_SECONDS)
    for plan in result["plans"]:
        plan["music"].update({"source": song, "cut_path": str(cut_path), "tempo_bpm": analysis["tempo_bpm"], "track_seconds": analysis["duration"],
                              "fade_out_seconds": fade})   # the one cut the whole set shares: every plan says how it really fades
        plan["job_id"], plan["shoot_name"] = job_id, job["shoot_name"]
        plan["notes"].append(f"Variant {plan['variant']['index']} of set {set_id}: {plan['variant']['name']}. Steadiness: {counts['analysed']} clip(s) read now, "
                             f"{counts['cached']} from this job's cache" + (", reading only what was cached" if quick else "") + ".")
        if with_cards and plan["variant"]["wants_cards"]:
            from app.post_brand_graphics import GRAPHICS_SUBFOLDER
            from app.post_edit_plan import _GRAPHICS_FOLDER
            from app.ssd_guard import require_connected
            gfx_dir = require_connected(job["destination_root"]) / _GRAPHICS_FOLDER[job["profile"]] / GRAPHICS_SUBFOLDER
            await on_drive(add_cards, plan, job, logo, frame_size_for_job(job), gfx_dir, writing=True, timeout=240.0)
    summary = set_summary(result, song=song, music_in=music_in, duration=duration, made_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    summary["steadiness"] = counts
    await on_drive(_write_set, folder, result, summary, writing=True, timeout=60.0)
    return summary


def list_sets(edit_dir: Path) -> list[dict[str, Any]]:
    """Every saved variant set of the job, newest first: {set_id, made_at, variants: [name ...]}."""
    root = variants_dir(edit_dir)
    out = []
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            try:
                summary = json.loads((folder / "set.json").read_text())
            except (OSError, ValueError):
                continue
            out.append({"set_id": summary.get("set_id", folder.name), "made_at": summary.get("made_at"), "variants": [v.get("name") for v in summary.get("variants", [])]})
    return out


def load_set(edit_dir: Path, set_id: str) -> dict[str, Any]:
    folder = variants_dir(edit_dir) / set_id
    if not set_id.replace("T", "").isdigit() or not (folder / "set.json").exists():
        raise VariantError(f"There is no variant set '{set_id}' for this job.")
    return json.loads((folder / "set.json").read_text())


def load_variant(edit_dir: Path, set_id: str, index: int) -> dict[str, Any]:
    load_set(edit_dir, set_id)
    path = variants_dir(edit_dir) / set_id / f"variant_{int(index)}.json"
    if not path.exists():
        raise VariantError(f"Set '{set_id}' has no variant {index}.")
    return json.loads(path.read_text())


def use_variant(edit_dir: Path, set_id: str, index: int) -> dict[str, Any]:
    """Makes a variant the job's plan: the current plan is archived first (post_plan_history lists it, Restore brings it back), then the variant is written as
    edit_plan_latest.json with a named copy. Returns the chosen plan. Brand cards are drawn by the caller (they need the drive and the job's logo)."""
    from app.post_edit_plan import _save_plan_files
    plan = load_variant(edit_dir, set_id, index)
    plan.setdefault("variant", {})["chosen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_plan_files(plan, edit_dir, f"variant_{set_id}_{index}")
    return plan
