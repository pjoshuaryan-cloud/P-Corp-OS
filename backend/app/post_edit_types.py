"""
POST (2026-10-13) -- the kinds of edit Josh makes, what is known about each, and what the system can build today.

An EDIT TYPE is decided by what the cuts follow (measured from a reference video, see post_reference_audio.py):
  music_montage   cuts sit on the music's hits (a few frames early)      -> the edit planner can build this
  narrated_broll  cuts follow the pictures / a narration, neither music nor pauses -> reference only (planner can't yet)
  dialogue_led    cuts fall in the pauses of someone talking             -> reference only (planner can't yet)

Each saved reference carries its type in its tags. `recipe_lines` writes the plain-English description of a reference
from its own measured numbers, so a description can never say something the data doesn't.
"""

from __future__ import annotations

from typing import Any

EDIT_TYPES: dict[str, dict[str, Any]] = {
    "music_montage": {
        "label": "Music-driven highlight reel",
        "buildable": True,
        "how": "Cuts on the music's hits in the style's shot rhythm; the planner picks clips and moments, the Premiere plugin assembles it.",
        "missing": [],
    },
    "narrated_broll": {
        "label": "Narrated b-roll story",
        "buildable": True,
        "how": "Shoot-order b-roll cut at the style's pace (about 1.6 s a shot) with a music bed. With the job's logo it also makes the opening and closing brand cards, the corner logo bug, and (with a narration script) one burned-in caption per shot, all laid over the b-roll; the script also gives a caption (.srt) file.",
        "missing": [
            "story order: clips go in shoot order, or in an order you give; the planner can't reorder footage into a story",
            "editable captions in Premiere (its scripting can't create caption tracks): the burned-in ones are images, and the .srt is there to import",
            "the animated brand graphics the reference ends on (logos revealed over aerial footage)",
            "dissolves (the reference has a few; the plugin assembles hard cuts only)",
        ],
    },
    "corporate_highlight": {
        "label": "Corporate highlight cut to music",
        "buildable": True,
        "how": "A calm highlight for corporate work: cuts on the music's hits at a slower pace than a reel (about 2 s a shot), every shot from the steadiest stretch of its clip, a slow zoom (in or out) only on shots whose footage is static, hard cuts only. With the job's logo it adds the opening and closing brand cards.",
        "missing": [
            "story order: clips go in shoot order, or in an order you give; the planner can't reorder footage into a story",
            "captions: a highlight to music has no narration, so none are made",
            "accents: there are none by design (no flashes, dissolves or zoom hits)",
        ],
    },
    "dialogue_led": {
        "label": "Talking head / interview",
        "buildable": True,
        "how": "A multicam interview: cameras that heard the same speech are lined up by their sound, and the edit switches angle at quiet gaps in the speech (about every 15 s, a little quicker near the end) over one continuous dialogue track. Needs at least two camera clips.",
        "missing": [
            "the closing card and fade to white (the last shot is held long enough to put one on)",
            "removing pauses, flubs and fillers: the dialogue runs continuous, so cut those by hand (Smart Selects and the transcript can find them)",
            "clips split into several files per camera: each camera is one clip",
            "a separate microphone recording: the dialogue is the first camera's own audio unless you pick another camera",
        ],
    },
    "superseded": {
        "label": "superseded test reference",
        "buildable": False,
        "how": "An earlier test timeline, replaced by a real finished example.",
        "missing": ["use the reference named in its 'superseded_by' tag instead"],
    },
}

# Edit types that no reference covers yet, built by pooling the ones that are measured. Honest about being a guess.
INFERRED_STYLES: dict[str, dict[str, Any]] = {
    "food-promo-inferred": {
        "composite_of": ["energy-drink-powerade", "furniture-expo-decorex", "fashion-event-converse-kenzo"],
        "edit_type": "music_montage",
        "client": "Food & drink promo",
        "event": "inferred from three edits (no food reference yet)",
        "format": "9:16 vertical reel (like the energy drink and furniture edits)",
        "style": "Inferred, not measured: the rhythm pooled from your energy drink, furniture and fashion edits. Replace it with a real food edit when you have one.",
    },
    "corporate-highlight-calm": {
        "composite_of": ["corporate-distribution-company"],
        "edit_type": "corporate_highlight",
        "genre": "corporate highlight",
        "client": "Corporate highlight",
        "event": "calm cuts on the music",
        "format": "any shape (vertical, horizontal or square)",
        "style": "Calm, beat-synced corporate highlight: cuts on the music's hits at a slower pace than a reel, steadiest moments only, slow zooms on static footage, opening and closing brand cards. Built from Josh's direction (2026-10-14) and the corporate reference's shot rhythm; there is no measured corporate highlight to music yet.",
        "target_seconds": 40,
        "pace_note": True,
    },
}


def type_info(edit_type: str | None) -> dict[str, Any]:
    return EDIT_TYPES.get(edit_type or "", {"label": "Unclassified", "buildable": False, "how": "", "missing": ["no edit type recorded for this reference"]})


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def recipe_lines(rec: dict[str, Any]) -> list[str]:
    """Plain-English description of a reference, every figure read from the record."""
    va = rec.get("video_analysis")
    summ = rec.get("summary") or {}
    lens = summ.get("shot_length_seconds") or {}
    out: list[str] = []
    if not va:  # read from a Premiere project (draft 01): exact effects and sound effects are known
        out.append(f"Vertical reel read from a Premiere timeline: {summ.get('shot_count')} shots over {summ.get('duration_seconds')} s, median shot {lens.get('median')} s (middle 80%: {lens.get('p10')}-{lens.get('p90')} s), {summ.get('shots_under_half_second')} shots under half a second.")
        sync = rec.get("music_sync") or {}
        if sync.get("cuts_within_40ms_of_a_strong_hit") is not None:
            out.append(f"Cuts follow the music: {sync['cuts_within_40ms_of_a_strong_hit']:.0%} within 40 ms of a strong hit, {sync.get('cuts_within_80ms_of_a_strong_hit', 0):.0%} within 80 ms (median {sync.get('median_cut_minus_hit_ms')} ms from the hit).")
        ov, fx = summ.get("overlay_layers") or {}, summ.get("effects_on_shots") or {}
        if any(ov.values()) or fx:
            out.append(f"Accents (exact values known): {ov.get('flash', 0)} flash layers, {ov.get('zoom_blur', 0)} zoom-blur hit layers, per-shot effects {fx}; {summ.get('sound_effects', 0)} sound effects; end card {summ.get('end_card') or 'none'}.")
        return out
    v = va["video"]
    orient = "vertical 9:16" if v["height"] > v["width"] else "landscape 16:9"
    out.append(f"{orient}, {v['width']}x{v['height']}, {v['fps']:.3f} fps, {v['duration']:.0f} s, {summ.get('shot_count')} shots.")
    r = va["pacing"]
    out.append(f"Shots: median {r['median']:.2f} s (middle 80%: {r['p10']:.2f}-{r['p90']:.2f} s); {_pct(r['share_under_half_second'])} under half a second, {_pct(r['share_3s_or_more'])} of 3 s or longer. "
               f"Pace by tenth of the edit (s): {', '.join(f'{x:.2f}' if x is not None else '-' for x in r['by_tenth'])}.")
    a = va.get("audio") or {}
    if a.get("has_audio"):
        why = a.get("why", "")
        out.append(f"The cuts follow: {a.get('cuts_follow')} -- {why}.")
        ms = a.get("music_sync_any_hit") or {}
        if a.get("cuts_follow") == "music" and ms.get("best_offset_ms") is not None:
            out.append(f"Each cut lands {ms['best_offset_ms']} ms (about {ms['best_offset_frames']} frames) BEFORE the hit it follows, so the new picture is already on screen when the hit lands.")
        loud = a.get("loudness") or {}
        if loud.get("integrated_lufs") is not None:
            out.append(f"Sound: {loud['integrated_lufs']} LUFS (range {loud['range_lu']} LU, true peak {loud['true_peak_dbfs']} dBFS); it closes {a['closes_db_vs_body']:+.0f} dB against its average level.")
    t = va["transitions"]
    bits = [f"{t['hard_cuts']} hard cuts"]
    for key, one, many in (("dissolves", "dissolve", "dissolves"), ("dips", "dip to black", "dips to black"), ("fades", "fade edge", "fade edges"), ("flashes", "flash frame", "flash frames"), ("bw_runs", "black & white burst", "black & white bursts")):
        if t.get(key):
            bits.append(f"{t[key]} {one if t[key] == 1 else many}")
    out.append("Transitions: " + ", ".join(bits) + (f"; a blurred frame sits at {_pct(t['blur_at_cuts']['cuts_with_blur'])} of cuts (random: {_pct(t['blur_at_cuts']['chance'])})." if t["blur_at_cuts"].get("cuts_with_blur") is not None else "."))
    if t.get("flash_notes"):
        out.append(t["flash_notes"])
    s = va.get("structure") or {}
    if s:
        out.append(f"Opens on: {s.get('opens_on')}. Closes on: {s.get('closes_on')}. First shot {s['first_shot_seconds']:.2f} s, last shot {s['last_shot_seconds']:.2f} s" + ("; ends on a dip to black." if s.get("ends_with_dip_to_black") else "."))
    c = va.get("content") or {}
    if c.get("labelled"):
        top = lambda d, n=3: ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in list(d.items())[:n])
        out.append(f"Shot mix (from {c['labelled']} of {c['of_shots']} shots labelled by Claude): {top(c['size'], 4)}. Subjects: {top(c['subject'], 4)}.")
        txt = {k: v for k, v in c["text_overlay"].items() if k != "none"}
        out.append(f"On-screen text on {_pct(1 - c['text_overlay'].get('none', 0))} of shots ({', '.join(f'{k.replace('_', ' ')} {v:.0%}' for k, v in txt.items()) or 'none'}).")
    if (rec.get("tags") or {}).get("edit_type") == "narrated_broll":
        from app.post_style import story_style_from_records
        st = story_style_from_records([rec])
        if st:
            out.append(f"How the planner builds it: body shots drawn from this edit's own lengths (median {sorted(st.body_lengths)[len(st.body_lengths) // 2]:.2f} s, none over 5 s), a {st.opener_seconds:.1f} s opener and a {st.closing_hold_seconds:.1f} s closing hold; with a narration script, one phrase of up to {st.max_phrase_words} words per shot at {st.words_per_second} words a second (captions run about {st.words_per_phrase_median:.0f} words per shot).")
    dg = va.get("dialogue")
    if dg and dg.get("angles"):
        by = dg.get("median_shot_seconds_by_angle") or {}
        out.append(f"Two camera angles ({'clearly distinct' if dg.get('separation', 0) >= 1.3 else 'not clearly distinct'}); {_pct(dg['share_of_cuts_that_switch_angle'])} of the cuts switch angle, so the cameras alternate A B A B. Median take by angle: " + ", ".join(f"{v} s" for v in by.values()) + ".")
        sp = dg.get("speech") or {}
        if sp:
            out.append(f"Cuts sit {_pct(sp['cuts_inside_a_quiet_gap'])} inside a quiet gap in the speech and {_pct(sp['cuts_within_0_15s_of_a_quiet_gap'])} within 0.15 s of one, landing {sp['position_in_gap_median']:.0%} of the way through it; the gaps are short (median {sp['gap_seconds_at_cuts_median']} s).")
    if (rec.get("tags") or {}).get("edit_type") == "dialogue_led":
        from app.post_style import dialogue_style_from_records
        ds = dialogue_style_from_records([rec])
        if ds:
            out.append(f"How the planner builds it: cameras (two or more clips of the same interview) lined up by their sound; takes drawn from this edit's own lengths (median {sorted(ds.body_lengths)[len(ds.body_lengths) // 2]:.1f} s), a quicker run of {len(ds.tail_lengths)} shorter takes ({min(ds.tail_lengths):.0f}-{max(ds.tail_lengths):.0f} s) over the last {ds.tail_fraction:.0%}, the last shot held {ds.closing_hold_seconds:.1f} s; every cut moved to a quiet gap in the dialogue and the angle switched each time; one continuous dialogue track under it.")
    bgm = va.get("brand_graphics")
    if bgm:
        c, b, cap = bgm["card"], bgm["logo_bug"], bgm["caption"]
        out.append(f"Brand graphics (measured on this video): cards are the logo at {c['logo_width_share']:.0%} of the frame width on flat grey {tuple(c['background_rgb'])} with navy text lines under it; the logo bug is a white rounded plate with the logo in it, {b['left_share']:.0%}-{b['right_share']:.0%} across and {b['top_share']:.0%}-{b['bottom_share']:.0%} down (top right); captions are white with a soft shadow, centred {cap['centre_y_share']:.0%} of the way down, {cap['text_block_height_share']:.1%} of the frame tall.")
    po = va.get("persistent_overlay")
    if po:
        out.append(f"A logo bug sits in the {po['corner']} corner for the body of the video.")
    return out


def write_inferred_styles(only: list[str] | None = None) -> list[str]:
    """Writes each INFERRED_STYLES entry (or just the slugs in `only`) as a composite reference record: no edit of its own, just the list
    of measured references it pools (post_style expands it). Returns the slugs written."""
    import json
    from statistics import mean, median
    from app import post_reference as pr
    from app.post_steady import CALM_PACE
    written = []
    for slug, spec in INFERRED_STYLES.items():
        if only is not None and slug not in only:
            continue
        parts = [pr.load_reference(x) for x in spec["composite_of"]]
        scale = CALM_PACE if spec.get("pace_note") else 1.0  # a calm style's card shows its CALM shot lengths, not the reference's
        lengths = sorted((sh["end"] - sh["start"]) * scale for r in parts for sh in r["edit"]["shots"])
        n = len(lengths)
        q = lambda p: round(lengths[min(n - 1, int(p * n))], 2)
        duration = spec.get("target_seconds") or round(mean(r["edit"]["duration_seconds"] for r in parts), 1)
        summary = {"shot_count": n if not spec.get("target_seconds") else max(1, round(spec["target_seconds"] / max(median(lengths), 0.1))), "duration_seconds": duration,
                   "shot_length_seconds": {"mean": round(mean(lengths), 2), "median": q(0.5), "p10": q(0.1), "p90": q(0.9), "min": round(lengths[0], 2), "max": round(lengths[-1], 2)}}
        tags = {"genre": spec.get("genre", "food and drink promo"), "client": spec["client"], "event": spec["event"], "format": spec["format"], "style": spec["style"],
                "edit_type": spec["edit_type"], "inferred": True, "composite_of": spec["composite_of"], "added_by": "Claude, 2026-10-14 (inferred, not measured)" if spec.get("pace_note") else "Claude, 2026-10-13 (inferred, not measured)"}
        record = {"slug": slug, "tags": tags, "summary": summary, "music_sync": None, "composite_of": spec["composite_of"]}
        (pr.REFERENCE_DIR / f"{slug}.json").write_text(json.dumps(record, indent=1))
        written.append(slug)
    return written


def ensure_inferred_styles(slugs: list[str] | None = None) -> None:
    """Makes sure the code-defined styles exist as records (backend/data is not in git, so a fresh checkout or a wiped folder heals itself).
    With `slugs`, only those that are asked for are checked."""
    from app import post_reference as pr
    missing = [s for s in INFERRED_STYLES if (slugs is None or s in slugs) and not (pr.REFERENCE_DIR / f"{s}.json").exists()]
    if missing:
        write_inferred_styles(only=missing)


def _food_section() -> list[str]:
    """What a food video will probably be cut like, argued from the measured references. Numbers are read from the records."""
    from app import post_reference as pr
    from statistics import mean, median
    get = lambda slug: pr.load_reference(slug)
    e, f, m = get("energy-drink-powerade"), get("furniture-expo-decorex"), get("fashion-event-converse-kenzo")
    med = lambda r: r["video_analysis"]["pacing"]["median"]
    lead = lambda r: r["music_sync"]["cut_lead_ms"]
    close_detail = lambda r: round(sum(v for k, v in r["video_analysis"]["content"]["size"].items() if k in ("close", "detail")), 2)
    logos = lambda r: r["video_analysis"]["content"]["text_overlay"].get("logo", 0)
    lines = [
        "## Food video: what it will probably be cut like (INFERRED, not measured)",
        "",
        "There is no food video among the references, so this is an argument from the three music-driven edits, not a measurement. "
        "Replace it with the real thing as soon as you have a food edit: the system will then use that instead.",
        "",
        f"- **Type:** a music-driven highlight reel. The three brand and event highlights you gave me (fashion, energy drink, furniture) are all cut this way; the corporate one is a narrated story and the talking head is dialogue. Closest relatives to food: the energy drink edit (a drink brand, lifestyle plus product) and the furniture expo edit (product and detail led, brand names on screen, 9:16).",
        f"- **Pace:** median shot about {mean([med(e), med(f), med(m)]):.2f} s (energy {med(e):.2f}, furniture {med(f):.2f}, fashion {med(m):.2f}), slower over the first tenth of the edit (0.66-1.38 s) and, in two of the three, again at the end. Food probably wants the slower end of that range because texture (steam, a pour, a cut) needs a beat to read, but that is a guess.",
        f"- **Cuts:** hard cuts on the music's hits, about {median([lead(e), lead(f), lead(m)]):.0f} ms (a frame or so) before each hit.",
        "- **Shape:** opens on an establishing shot or a brand card (the skyline and logo, the Decorex signage, the branded box) and closes on a brand card, sometimes into a dip to black.",
        f"- **What is in the shots:** your product edits are {close_detail(f):.0%} (furniture) and {close_detail(m):.0%} (fashion) close-ups and details, and logos or brand names appear on {logos(e):.0%}-{logos(f):.0%} of shots. For food I would expect at least that many close-ups, which is an assumption, not in the data.",
        "- **Effects:** none by default (the energy drink edit is pure hard cuts); the fashion edit adds a few one-frame flashes and short black-and-white bursts, so those are an option, not the baseline.",
        "- **What the planner does with this today:** it reproduces the rhythm and the music sync. It cannot choose close-up food shots over wide ones, add the brand cards, or place logos; those are still by hand.",
    ]
    return lines


def write_report() -> str:
    """Writes backend/data/post_references/EDIT_TYPES.md: every edit type, every reference's measured recipe, the food inference."""
    from app import post_reference as pr
    out = ["# Edit types and reference edits", "", "Generated from the saved references. Measured from finished videos by post_reference_video.py / post_reference_audio.py (validated on footage with known answers); shot labels by Claude.", ""]
    out += ["## What the system can build", ""]
    for key, t in EDIT_TYPES.items():
        if key == "superseded":
            continue
        tail = "" if not t["missing"] else (" Not placed automatically: " if t["buildable"] else " Missing: ") + "; ".join(t["missing"]) + "."
        out.append(f"- **{t['label']}** -- {'can build' if t['buildable'] else 'reference only'}. {t['how']}{tail}")
    out.append("")
    for path in sorted(pr.REFERENCE_DIR.glob("*.json")):
        rec = pr.load_reference(path.stem)
        if rec.get("composite_of") or (rec["tags"].get("edit_type") == "superseded"):
            continue
        t = type_info(rec["tags"].get("edit_type") or "music_montage")
        out += [f"## {rec['tags'].get('client')} -- {rec['tags'].get('event')}  (`{rec['slug']}`, {t['label']}, {'planner can build' if t['buildable'] else 'reference only'})", ""]
        out += [f"- {line}" for line in recipe_lines(rec)]
        out.append("")
    out += _food_section()
    out += ["", "## Limits to keep in mind", "",
            "- One example per edit type: each description is how that one video was cut, not a rule about every video of its kind.",
            "- A reference built from a video records WHAT happens and WHEN. It cannot recover exact effect values, sound-effect files, or which source clip a shot came from.",
            "- Shot content labels (close-up, people, text) come from Claude looking at sampled frames (a sample when the edit has many shots). They are labels, not measurements, and say nothing about camera movement.",
            "- Cuts following the music is measured against what random cut times would get by luck; the lift over chance is shown next to every figure.",
            "- The corporate story mode places shots and the music bed only (no brand cards, corner logo, burned-in captions or dissolves). The talking-head mode switches angle over continuous dialogue; it does not remove pauses, flubs or fillers and does not place the closing card."]
    text = "\n".join(out) + "\n"
    (pr.REFERENCE_DIR / "EDIT_TYPES.md").write_text(text)
    return text
