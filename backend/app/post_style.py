"""
POST (2026-10-07) -- edit style profiles, derived from reference edits.

A profile is just numbers pulled from one or more saved references (post_reference.py): how long
shots run, how the pace changes across the edit, how long the closing card holds, and how tightly cuts
sit on music hits. Nothing in the planner is hard-coded to one reference: Josh's draft 01 is the first
preset, and a different kind of edit (slower, cinematic, product-led) gets its own reference and so its
own profile. Several references can be pooled.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

from app.post_reference import list_references, load_reference

PACING_BINS = 10
HIGHLIGHT_TARGET_SECONDS = 40.0  # Josh's corporate highlight runs 35-45 s


REFERENCE_FPS = 25.0  # references don't record their frame rate; Josh's reels are 25 fps
FLURRY_SHOT_SECONDS = 0.35  # a "flurry" = shots shorter than this, several in a row
ATTACH_LEAD_FRAMES = (-2.0, 6.0)  # an overlay belongs to the cut it starts up to 6 frames BEFORE (or 2 after)


@dataclass
class AccentStyle:
    """How a reference decorates its cuts, measured: flashes and zoom hits are short adjustment layers that start
    a frame or two BEFORE a cut; some shots carry their own zoom blur; the closing shots can go black & white
    with a logo. Every number is read off the reference (see accent_style_from_records)."""
    flash_frames: int
    flash_lead_frames: int
    flash_params: dict[str, float]  # Lumetri parameters, e.g. {"Exposure": 6.2}
    flash_per_flurry_cut: float  # chance a cut inside a flurry gets a flash
    flash_standalone_per_minute: float  # flashes on ordinary cuts outside flurries
    flash_min_pct: float  # weakest music hit a flash sat on
    zoom_hit_frames: int
    zoom_hit_lead_frames: int
    zoom_hit_params: dict[str, float]  # Impact Zoom Blur parameters
    zoom_hits_per_minute: float
    zoom_hit_min_gap_seconds: float
    zoom_hit_min_prev_seconds: float  # a zoom hit follows a shot at least this long
    zoom_hit_min_pct: float
    shot_zoom_rate: float  # share of shots that carry their own zoom blur
    shot_zoom_params: dict[str, float]
    shot_zoom_min_pct: float
    shot_zoom_decile_weights: list[float]  # relative likelihood per tenth of the edit (mean 1)
    closing_bw_shots: int  # how many of the last shots go black & white
    end_card_logo: bool
    end_card_flash_frames: int


@dataclass
class StoryStyle:
    """How a narrated b-roll story (the corporate edit type) is built, measured from its references: shot lengths in the
    body (not the opening card, not the long closing holds), how long the opener and the closing hold run, and how fast the
    narration is (read off the caption text: words per second, words per phrase)."""
    body_lengths: list[float]
    opener_seconds: float
    closing_hold_seconds: float
    words_per_second: float
    words_per_phrase_median: float
    max_phrase_words: int


@dataclass
class DialogueStyle:
    """How a multicam interview / talking head is cut, measured from its references: how long each take is, the quicker run at
    the end, how the cuts sit in the speech, and whether the cuts always switch camera angle."""
    body_lengths: list[float]
    tail_lengths: list[float]  # the shorter takes just before the closing card
    tail_fraction: float  # how much of the runtime that closing run covers
    closing_hold_seconds: float  # the final held shot (the logo card in the reference)
    cut_position_in_gap: float  # how far along a quiet gap the cut lands (0 = where it starts, 1 = where it ends)
    always_switches_angle: bool
    min_cameras: int = 2


def dialogue_style_from_records(recs: list[dict]) -> "DialogueStyle | None":
    """Pools the dialogue-led references in `recs`. None if none of them has the measured dialogue block."""
    body: list[float] = []
    tail: list[float] = []
    fractions: list[float] = []
    holds: list[float] = []
    positions: list[float] = []
    switches: list[float] = []
    for rec in recs:
        d = (rec.get("video_analysis") or {}).get("dialogue")
        shots = sorted(rec["edit"]["shots"], key=lambda x: x["start"])
        if not d or len(shots) < 8:
            continue
        lengths = [x["end"] - x["start"] for x in shots]
        typical = median(lengths)
        total = rec["edit"]["duration_seconds"] or sum(lengths)
        i = len(lengths)
        hold = lengths[-1] if lengths[-1] < 0.5 * typical else None  # the closing card
        if hold is not None:
            holds.append(hold)
            i -= 1
        run: list[float] = []
        while i > 0 and lengths[i - 1] < 0.5 * typical:  # the quicker run before it; sub-second pieces are fade artifacts
            if lengths[i - 1] >= 1.0:
                run.insert(0, lengths[i - 1])
            i -= 1
        tail.extend(run)
        fractions.append((sum(run) + (hold or 0.0)) / total)
        body.extend(lengths[:i])
        sp = (d.get("speech") or {})
        if sp.get("position_in_gap_median") is not None:
            positions.append(sp["position_in_gap_median"])
        if d.get("share_of_cuts_that_switch_angle") is not None:
            switches.append(d["share_of_cuts_that_switch_angle"])
    if not body:
        return None
    return DialogueStyle(body_lengths=body, tail_lengths=tail or [typical_or(body)], tail_fraction=round(float(median(fractions)), 3) if fractions else 0.0,
                         closing_hold_seconds=round(float(median(holds)), 2) if holds else 4.0, cut_position_in_gap=round(float(median(positions)), 2) if positions else 0.7,
                         always_switches_angle=bool(switches) and min(switches) >= 0.9)


def typical_or(values: list[float]) -> float:
    return float(median(values)) if values else 5.0


STORY_BODY_MAX_SECONDS = 5.0  # longer shots at the end of a story are held graphics/aerials, not the b-roll rhythm
STORY_BODY_MIN_SECONDS = 0.5  # shorter ones are transition frames the detector split off


def story_style_from_records(recs: list[dict]) -> "StoryStyle | None":
    """Pools the narrated-b-roll references in `recs`. None if none of them carries caption text to read a narration pace from."""
    body: list[float] = []
    openers: list[float] = []
    holds: list[float] = []
    words: list[int] = []
    secs: list[float] = []
    for rec in recs:
        shots = sorted(rec["edit"]["shots"], key=lambda x: x["start"])
        lengths = [x["end"] - x["start"] for x in shots]
        if len(shots) < 6:
            continue
        inner = [l for l in lengths[1:-1] if STORY_BODY_MIN_SECONDS <= l < STORY_BODY_MAX_SECONDS]
        body.extend(inner)
        openers.append(lengths[0])
        typical = median(inner) if inner else 1.6
        if lengths[-1] >= 3 * typical:
            holds.append(lengths[-1])
        for lab in ((rec.get("video_analysis") or {}).get("content") or {}).get("labels", []):
            if lab.get("text") == "caption_subtitle" and lab.get("text_words") and STORY_BODY_MIN_SECONDS <= lengths[lab["shot_index"]] < STORY_BODY_MAX_SECONDS:
                words.append(len(lab["text_words"].split()))
                secs.append(lengths[lab["shot_index"]])
    if not body or not words:
        return None
    ranked = sorted(words)
    return StoryStyle(body_lengths=body, opener_seconds=round(float(median(openers)), 2), closing_hold_seconds=round(float(median(holds)), 2) if holds else 4.0,
                      words_per_second=round(sum(words) / sum(secs), 2), words_per_phrase_median=float(median(words)),
                      max_phrase_words=max(4, int(ranked[min(len(ranked) - 1, int(0.95 * len(ranked)))])))


@dataclass
class StyleProfile:
    name: str
    source_slugs: list[str]
    target_duration_seconds: float
    shot_lengths: list[float]  # every shot length (seconds) in the pooled references
    pacing_curve: list[float]  # mean shot length in each tenth of the edit, pooled (seconds)
    end_card_seconds: float  # how long the closing shot holds; 0 = no closing hold
    hit_snap_rate: float  # share of cuts that sit on a music hit in the references (0-1)
    min_shot_seconds: float = 0.12
    max_shot_seconds: float = 2.5
    accents: AccentStyle | None = None  # None = this style has no accents (hard cuts only)
    cut_lead_seconds: float = 0.0  # how far BEFORE a music hit the reference's cuts sit (the song starts this much earlier so each hit lands just after its cut)
    edit_type: str = "music_montage"
    inferred: bool = False  # True = pooled from other references as a stand-in, not measured from an edit of this kind
    story: StoryStyle | None = None  # set for a narrated b-roll story: the planner builds it from a timeline, not from the music's hits
    dialogue: DialogueStyle | None = None  # set for a multicam interview: cameras switched at quiet gaps over continuous dialogue
    highlight: bool = False  # a corporate highlight cut to the music's hits at a calm pace (post_edit_highlight.py); `story` then only carries the reference's shot rhythm
    notes: list[str] = field(default_factory=list)
    default_pace: float | None = None  # a highlight's pace multiplier when the caller gives none (1.0 = the style's own rhythm); None = the planner's calm default
    rhythm_note: str | None = None  # a highlight style's own account of where its shot rhythm comes from; the plan's notes say it instead of the calm style's wording
    highlight_min_shot_seconds: float | None = None  # the shortest shot a highlight in this style may have; None = the calm highlight's 1 s

    @property
    def mean_shot_seconds(self) -> float:
        return mean(self.shot_lengths)


def _mode_params(dicts: list[dict[str, float]]) -> dict[str, float]:
    """Per parameter, the median value seen (robust to the odd outlier)."""
    keys = {k for d in dicts for k in d}
    return {k: round(float(median(d[k] for d in dicts if k in d)), 3) for k in sorted(keys)}


def _accent_style_one(rec: dict) -> dict | None:
    """Raw accent measurements from ONE reference record, or None if it has no accents."""
    edit = rec["edit"]
    shots = sorted(edit["shots"], key=lambda s: s["start"])
    if len(shots) < 4:
        return None
    cuts = [s["start"] for s in shots]
    lengths = [s["end"] - s["start"] for s in shots]
    total = max(edit["duration_seconds"], 1.0)
    pct = (rec.get("music_sync") or {}).get("cut_hit_percentiles") or {}
    pct_at = lambda k: float(pct.get(f"{cuts[k]:.3f}", 0.0))
    flurry = [sum(1 for j in (k - 1, k, k + 1) if 0 <= j < len(lengths) and lengths[j] < FLURRY_SHOT_SECONDS) >= 2 for k in range(len(cuts))]
    flashes, zooms = [], []
    for o in edit["overlays"]:
        if o["end"] - o["start"] >= 1.0 or o["kind"] not in ("flash", "zoom_blur"):
            continue
        k = min(range(len(cuts)), key=lambda i: abs(cuts[i] - o["start"]))
        lead = (cuts[k] - o["start"]) * REFERENCE_FPS
        if not (ATTACH_LEAD_FRAMES[0] <= lead <= ATTACH_LEAD_FRAMES[1]):
            continue
        item = {"k": k, "frames": round((o["end"] - o["start"]) * REFERENCE_FPS), "lead": lead, "params": o.get("params", {})}
        (flashes if o["kind"] == "flash" else zooms).append(item)
    zoom_shots = [i for i, s in enumerate(shots) if "AE.Impact_Zoom_Blur_FX" in s.get("params", {})]
    if not flashes and not zooms and not zoom_shots:
        return None
    card_k = len(cuts) - 1
    card_flash = [f for f in flashes if f["k"] >= card_k - 0]
    regular_flash = [f for f in flashes if f["k"] < card_k]
    in_flurry = [f for f in regular_flash if flurry[f["k"]]]
    standalone = [f for f in regular_flash if not flurry[f["k"]]]
    flurry_cuts = [k for k in range(1, len(cuts) - 1) if flurry[k]]
    prev_len = lambda k: lengths[k - 1] if k > 0 else 0.0
    zoom_times = sorted(cuts[z["k"]] for z in zooms)
    bw_tail = 0
    for s in reversed(shots):
        if any("Black & White" in e for e in s.get("effects", [])):
            bw_tail += 1
        else:
            break
    decile = [0] * 10
    for i in zoom_shots:
        decile[min(9, int(i / len(shots) * 10))] += 1
    return {
        "total": total,
        "flash_frames": [f["frames"] for f in regular_flash], "flash_lead": [f["lead"] for f in regular_flash], "flash_params": [f["params"].get("AE.ADBE Lumetri", {}) for f in regular_flash],
        "flash_per_flurry_cut": (len(in_flurry) / len(flurry_cuts)) if flurry_cuts else 0.0, "flash_standalone": len(standalone),
        "flash_pcts": [pct_at(f["k"]) for f in regular_flash if pct_at(f["k"]) > 0],
        "zoom_frames": [z["frames"] for z in zooms], "zoom_lead": [z["lead"] for z in zooms], "zoom_params": [z["params"].get("AE.Impact_Zoom_Blur_FX", {}) for z in zooms],
        "zoom_count": len(zooms), "zoom_min_gap": min((b - a for a, b in zip(zoom_times, zoom_times[1:])), default=3.0),
        "zoom_prev": [prev_len(z["k"]) for z in zooms], "zoom_pcts": [pct_at(z["k"]) for z in zooms if pct_at(z["k"]) > 0],
        "shot_zoom_rate": len(zoom_shots) / len(shots), "shot_zoom_params": [shots[i]["params"]["AE.Impact_Zoom_Blur_FX"] for i in zoom_shots],
        "shot_zoom_pcts": [pct_at(i) for i in zoom_shots if pct_at(i) > 0], "shot_zoom_decile": decile,
        "bw_tail": bw_tail, "logo": bool(edit.get("graphics")), "card_flash_frames": [f["frames"] for f in card_flash],
    }


def accent_style_from_records(recs: list[dict]) -> AccentStyle | None:
    """Pools the accent measurements of the given reference records. None if none of them has accents."""
    ones = [m for m in (_accent_style_one(r) for r in recs) if m]
    if not ones:
        return None
    flat = lambda key: [v for m in ones for v in m[key]]
    minutes = sum(m["total"] for m in ones) / 60.0
    def med(vals, default):
        return float(median(vals)) if vals else float(default)
    def low(vals, default, q=0.2):
        vals = sorted(vals)
        return float(vals[min(len(vals) - 1, int(q * len(vals)))]) if vals else float(default)
    deciles = [sum(m["shot_zoom_decile"][d] for m in ones) for d in range(10)]
    total_zoom = sum(deciles) or 1
    weights = [round(d / total_zoom * 10, 3) for d in deciles]
    return AccentStyle(
        flash_frames=max(1, round(med(flat("flash_frames"), 2))), flash_lead_frames=max(0, round(med(flat("flash_lead"), 1))),
        flash_params=_mode_params([p for p in flat("flash_params") if p]) or {"Exposure": 6.2},
        flash_per_flurry_cut=round(mean(m["flash_per_flurry_cut"] for m in ones), 3),
        flash_standalone_per_minute=round(sum(m["flash_standalone"] for m in ones) / minutes, 2),
        flash_min_pct=round(min(flat("flash_pcts"), default=70.0), 1),
        zoom_hit_frames=max(1, round(med(flat("zoom_frames"), 4))), zoom_hit_lead_frames=max(0, round(med(flat("zoom_lead"), 2))),
        zoom_hit_params=_mode_params([p for p in flat("zoom_params") if p]) or {"Zoom": 25.0},
        zoom_hits_per_minute=round(sum(m["zoom_count"] for m in ones) / minutes, 2),
        zoom_hit_min_gap_seconds=round(min(m["zoom_min_gap"] for m in ones), 2),
        zoom_hit_min_prev_seconds=round(min(flat("zoom_prev"), default=0.5) * 0.9, 2),
        zoom_hit_min_pct=round(low(flat("zoom_pcts"), 75.0), 1),
        shot_zoom_rate=round(mean(m["shot_zoom_rate"] for m in ones), 3), shot_zoom_params=_mode_params([p for p in flat("shot_zoom_params") if p]),
        shot_zoom_min_pct=round(low(flat("shot_zoom_pcts"), 75.0), 1), shot_zoom_decile_weights=weights,
        closing_bw_shots=round(mean(m["bw_tail"] for m in ones)), end_card_logo=any(m["logo"] for m in ones),
        end_card_flash_frames=max(1, round(med(flat("card_flash_frames"), 4))),
    )


DEFAULT_EDIT_TYPE = "music_montage"  # references read from a Premiere project (draft 01) predate edit types and are music-driven reels


def edit_type_of(rec: dict) -> str:
    return (rec.get("tags") or {}).get("edit_type") or DEFAULT_EDIT_TYPE


def _expand(slugs: list[str]) -> tuple[list[dict], bool]:
    """Loads the records for `slugs`; a composite (pooled stand-in) record is replaced by the records it is made of."""
    recs, inferred = [], False
    for slug in slugs:
        rec = load_reference(slug)
        if rec.get("composite_of"):
            inferred = inferred or bool((rec.get("tags") or {}).get("inferred"))
            sub, _ = _expand(list(rec["composite_of"]))
            recs.extend(sub)
        else:
            recs.append(rec)
    return recs, inferred


# --- "Your usual pace" (2026-10-21): the default style. Not a reference edit but the shot rhythm measured across his own saved Premiere projects
# (backend/learning/rhythm.py --export-usual-pace writes app/post_usual_pace.json, which is in git because backend/data is not). It runs through the highlight
# planner (hard cuts on the music's hits, best moment of each clip, optional brand cards), only with HIS shot lengths instead of the calm corporate ones.
USUAL_PACE_SLUG = "your-usual-pace"
USUAL_PACE_FILE = Path(__file__).with_name("post_usual_pace.json")


def load_usual_pace() -> dict:
    try:
        return json.loads(USUAL_PACE_FILE.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("Your usual pace hasn't been measured yet: run `.venv/bin/python -m learning.rhythm --export-usual-pace` from the backend folder.") from exc


def usual_pace_profile() -> StyleProfile:
    data = load_usual_pace()
    lengths = [float(x) for x in data["body_lengths"]]
    story = StoryStyle(body_lengths=lengths, opener_seconds=float(data["opener_seconds"]), closing_hold_seconds=float(data["closing_hold_seconds"]),
                       words_per_second=0.0, words_per_phrase_median=0.0, max_phrase_words=0)   # no narration: a highlight is cut to music
    return StyleProfile(
        name=USUAL_PACE_SLUG, source_slugs=[USUAL_PACE_SLUG], target_duration_seconds=float(round(data["typical_seconds"])), shot_lengths=lengths,
        pacing_curve=[round(mean(lengths), 3)] * PACING_BINS, end_card_seconds=min(4.5, float(data["closing_hold_seconds"])), hit_snap_rate=0.8,
        min_shot_seconds=float(data["min_shot_seconds"]), max_shot_seconds=float(data["max_shot_seconds"]), accents=None, edit_type="corporate_highlight",
        story=story, highlight=True, default_pace=1.0, highlight_min_shot_seconds=float(data["min_shot_seconds"]),
        rhythm_note=f"your usual pace: shot lengths are drawn from the real shots of {data['from_edits']} of your edits (median {data['median_shot']:.2f} s, middle 80% {data['p10']:.2f}-{data['p90']:.2f} s)",
    )


def profile_from_references(slugs: list[str], name: str | None = None) -> StyleProfile:
    """Pools the saved references named in `slugs` into one profile. Raises ValueError for a reference the planner can't
    build from (a talking head or a narrated b-roll story), saying so plainly."""
    from app.post_edit_types import ensure_inferred_styles, type_info
    if not slugs:
        raise ValueError("Pick at least one reference edit for the style.")
    if USUAL_PACE_SLUG in slugs:
        if len(slugs) > 1:
            raise ValueError("Your usual pace is a complete style of its own: it can't be pooled with other references.")
        return usual_pace_profile()
    ensure_inferred_styles(slugs)
    blends = [sl for sl in slugs if load_reference(sl).get("rhythm_weights")]
    if blends:
        if len(slugs) > 1:
            raise ValueError(f"'{blends[0]}' is a blended style of its own: it can't be pooled with other references.")
        return _blend_profile(load_reference(blends[0]), name)
    highlight = any((load_reference(sl).get("tags") or {}).get("edit_type") == "corporate_highlight" for sl in slugs)
    if highlight and len(slugs) > 1:
        raise ValueError("The corporate highlight style is a complete style of its own: it can't be pooled with other references.")
    refs, inferred = _expand(slugs)
    kinds = {edit_type_of(rec) for rec in refs}
    if len(kinds) > 1:
        raise ValueError("These references are different kinds of edit (" + ", ".join(sorted(type_info(k)["label"] for k in kinds)) + "), so they can't be pooled into one style. Pick references of one kind.")
    for rec in refs:
        info = type_info(edit_type_of(rec))
        if not info["buildable"]:
            raise ValueError(f"'{rec['slug']}' is a {info['label'].lower()} reference. It records how that kind of edit is cut, but the planner can't build that kind yet (it builds music-driven reels, narrated b-roll stories and multicam interviews).")
    lengths: list[float] = []
    bins: list[list[float]] = [[] for _ in range(PACING_BINS)]
    ends: list[float] = []
    snaps: list[float] = []
    leads: list[float] = []
    durations: list[float] = []
    for rec in refs:
        edit = rec["edit"]
        shots = sorted(edit["shots"], key=lambda s: s["start"])
        total = edit["duration_seconds"] or 1.0
        durations.append(total)
        for s in shots:
            length = s["end"] - s["start"]
            lengths.append(length)
            bins[min(PACING_BINS - 1, int(s["start"] / total * PACING_BINS))].append(length)
        if shots and shots[-1]["end"] - shots[-1]["start"] >= 1.5:
            ends.append(shots[-1]["end"] - shots[-1]["start"])
        sync = rec.get("music_sync") or {}
        if sync.get("cuts_within_40ms_of_a_strong_hit") is not None:
            snaps.append(sync["cuts_within_40ms_of_a_strong_hit"])
        if sync.get("cut_lead_ms") is not None:
            leads.append(sync["cut_lead_ms"] / 1000.0)
    overall = mean(lengths)
    curve = [mean(b) if b else overall for b in bins]
    ranked = sorted(lengths)
    p90 = ranked[min(len(ranked) - 1, int(0.90 * len(ranked)))]
    profile = StyleProfile(
        name=name or " + ".join(slugs), source_slugs=list(slugs), target_duration_seconds=round(mean(durations), 1),
        shot_lengths=lengths, pacing_curve=[round(c, 3) for c in curve], end_card_seconds=round(mean(ends), 2) if ends else 0.0,
        hit_snap_rate=round(mean(snaps), 2) if snaps else 0.8,
        max_shot_seconds=max(2.5, round(2.6 * p90, 2)),  # a slower style may hold longer than the 2.5 s a fast reel is capped at (draft 01's p90 of 0.92 s keeps its 2.5 s exactly)
        accents=accent_style_from_records(refs), cut_lead_seconds=round(float(median(leads)), 3) if leads else 0.0, inferred=inferred,
        edit_type=next(iter(kinds)), story=story_style_from_records(refs) if next(iter(kinds)) == "narrated_broll" else None,
        dialogue=dialogue_style_from_records(refs) if next(iter(kinds)) == "dialogue_led" else None,
    )
    if highlight:
        story = profile.story
        if story is None:
            raise ValueError("The corporate highlight style needs the corporate reference's shot rhythm, and none could be read from it.")
        profile.highlight, profile.edit_type = True, "corporate_highlight"
        profile.target_duration_seconds = HIGHLIGHT_TARGET_SECONDS
        profile.accents = None  # hard cuts only: corporate edits have no flashes or other accents
    return profile


def _blend_profile(rec: dict, name: str | None = None) -> StyleProfile:
    """A blended style (post_edit_types.INFERRED_STYLES with `rhythm_weights` and `beat_from`, 2026-10-24): the shot rhythm and its shape over the edit pooled
    from `rhythm_weights` (each reference counted as many times as its weight -- any reference with a measured shot rhythm, also one cut on the action
    rather than the beat), the beat timing (share of cuts on hits, cut lead) from `beat_from` (music-driven references only). Flagged inferred: no single
    edit was measured like this."""
    rhythm = [(load_reference(slug), int(w)) for slug, w in rec["rhythm_weights"].items()]
    beat = [load_reference(slug) for slug in rec.get("beat_from") or []]
    for b in beat:
        if edit_type_of(b) != "music_montage":
            raise ValueError(f"'{b['slug']}' isn't cut to the music, so it can't set when a blended style's cuts land.")
    lengths: list[float] = []
    bins: list[list[float]] = [[] for _ in range(PACING_BINS)]
    ends: list[float] = []
    durations: list[float] = []
    for r, weight in rhythm:
        shots = sorted(r["edit"]["shots"], key=lambda s: s["start"])
        total = r["edit"]["duration_seconds"] or 1.0
        for _ in range(weight):
            durations.append(total)
            for s in shots:
                lengths.append(s["end"] - s["start"])
                bins[min(PACING_BINS - 1, int(s["start"] / total * PACING_BINS))].append(s["end"] - s["start"])
            if shots and shots[-1]["end"] - shots[-1]["start"] >= 1.5:
                ends.append(shots[-1]["end"] - shots[-1]["start"])
    snaps = [b["music_sync"]["cuts_within_40ms_of_a_strong_hit"] for b in beat if (b.get("music_sync") or {}).get("cuts_within_40ms_of_a_strong_hit") is not None]
    leads = [b["music_sync"]["cut_lead_ms"] / 1000.0 for b in beat if (b.get("music_sync") or {}).get("cut_lead_ms") is not None]
    overall = mean(lengths)
    ranked = sorted(lengths)
    p90 = ranked[min(len(ranked) - 1, int(0.90 * len(ranked)))]
    return StyleProfile(
        name=name or rec["slug"], source_slugs=[rec["slug"]], target_duration_seconds=round(mean(durations), 1), shot_lengths=lengths,
        pacing_curve=[round(mean(b) if b else overall, 3) for b in bins], end_card_seconds=round(mean(ends), 2) if ends else 0.0,
        hit_snap_rate=round(mean(snaps), 2) if snaps else 0.8, max_shot_seconds=max(2.5, round(2.6 * p90, 2)), accents=accent_style_from_records(beat),
        cut_lead_seconds=round(float(median(leads)), 3) if leads else 0.0, inferred=True, edit_type="music_montage",
        notes=[f"Blended style: shot rhythm from {', '.join(f'{s} (x{w})' for s, w in rec['rhythm_weights'].items())}; cuts on the music like {', '.join(rec.get('beat_from') or [])}."],
    )


def available_styles(buildable_only: bool = True, **tag_filters) -> list[dict]:
    """Saved references a job can take its style from (optionally filtered by tags such as genre). By default only the ones
    the planner can build from; pass buildable_only=False to see every saved reference (talking head, corporate...)."""
    from app.post_edit_types import ensure_inferred_styles, type_info
    ensure_inferred_styles()
    records = list_references(**tag_filters)
    records.sort(key=lambda r: r["slug"] != USUAL_PACE_SLUG)   # your usual pace first: the planning screen preselects the first style
    if not buildable_only:
        return records
    return [r for r in records if type_info(edit_type_of(r))["buildable"]]


# Plain names for the planning screen (2026-10-20): a saved reference is called "jd-sports-moa-draft-01" in the files and "JD Sports -- Mall of Africa store opening" in the
# list, neither of which says what KIND of edit it makes. Keyed by slug; a reference not listed here falls back to its own title and description.
FRIENDLY_STYLES: dict[str, tuple[str, str]] = {
    USUAL_PACE_SLUG: ("Your usual pace", "Cuts to the music at the pace of your own edits, on the best moment of each clip, with optional opening and closing brand cards."),
    "corporate-highlight-calm": ("Calm corporate highlight", "Cuts to the music at an easy pace (about two seconds a shot), with opening and closing brand cards."),
    "jd-sports-moa-draft-01": ("Fast streetwear reel", "Quick cuts on the beat with flash and zoom accents (your JD Sports draft)."),
    "energy-drink-powerade": ("Energy-drink reel", "A fast vertical highlight, cut on the music."),
    "fashion-event-converse-kenzo": ("Fashion event highlight", "A music-driven launch-event highlight."),
    "furniture-expo-decorex": ("Expo and product highlight", "A music-driven vertical reel for an expo or showroom."),
    "food-promo-inferred": ("Food and drink promo (estimated)", "Rhythm blended from your drink, furniture and fashion edits."),
    "gq-miele-blend": ("GQ x Miele event reel", "On the beat like your Miele Decorex edit, with the Moet x Don C reel's pace: quick open, steady middle, faster build, "
                       "slow logo ending. Each shot starts on the action."),
    "corporate-distribution-company": ("Corporate story with narration", "Calm b-roll paced by a voice-over script."),
    "talking-head-beancounter": ("Talking head, several cameras", "Switches camera angle at the pauses in the dialogue."),
}


def friendly_style(slug: str, fallback_title: str = "", fallback_description: str = "") -> tuple[str, str]:
    """(plain name, one-line description) for a style slug."""
    if slug in FRIENDLY_STYLES:
        return FRIENDLY_STYLES[slug]
    first = (fallback_description or "").split(". ")[0].strip()
    return fallback_title or slug, (first[:140] + ("…" if len(first) > 140 else ""))
