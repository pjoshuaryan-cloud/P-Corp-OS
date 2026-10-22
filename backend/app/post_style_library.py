"""
POST (2026-10-22) -- the Editing Style Library: reusable, data-driven editorial profiles.

Why this exists. The planner knows how to cut to music at a measured pace, but "what kind of edit is this?" was only
answered by saved reference edits (post_style.py). A filmmaker thinks in kinds of edit instead: a premium spot, a sports
reel, a food promo, event highlights. This module holds eleven such profiles as plain data, plus a way to blend any two
of them into a twelfth ("custom hybrid"), so the multi-variant planner can be asked for "a premium cut" or "70% sports,
30% fashion" and so a person can read, in plain words, what each profile means.

The honesty rule is the point of the module. A profile is an editor's wish list, and the planner can only do part of it:

  * EXECUTED (see the EXECUTED_* constants and EXECUTABLE below) = what the Premiere build really does today: hard cuts,
    cuts that snap to the music's hits, a pace multiplier on Josh's own measured rhythm, a flat / build / breathe pacing
    curve, a preference for kinds of moment, avoiding repeated looks, a few openings and endings, and a slow zoom on
    static footage.
  * PROPOSAL-ONLY = everything else (dissolves, speed ramps, flashes, whip pans, colour, typography, captions, sound
    design, off-beat cuts, continuity advice). It is written into a plan as text a person can act on, and is never
    executed. `execution_report` keeps the two lists apart and is built only from the EXECUTED_* constants, so it cannot
    claim something is executed that is not.

What is measured and what is not. Exactly one thing here is measured on Josh's own edits: his usual rhythm (128 of his own
short fast edits, median shot 0.57 s, backend/app/post_usual_pace.json). `pace` is a multiplier on that rhythm, so 1.0 IS
his measured pace. Every other number in every profile (role weights, curves, openings, endings, shot-length ranges, the
paces other than 1.0) is editorial guidance, not measured on his edits, and each profile's `provenance_note` says so.

Pure Python, standard library only; the only import from the app is the pace range, so the library and its tests run
without Premiere, a database or any network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.post_steady import MAX_PACE, MIN_PACE

LIBRARY_VERSION = 1

# The kinds of moment the clip describer produces (post_moments.EVENT_KINDS), plus "hold": a clean, steady stretch of a
# clip that has no described moment (the planner's fallback window).
ROLES = ("action", "reaction", "camera_move", "reveal", "hero", "hold")

VARIETIES = ("high", "medium", "low")
PACING_CURVES = ("flat", "build", "breathe")
PROVENANCES = ("measured", "guidance")
ASPECTS = ("9:16", "16:9", "1:1", "4:5")

# --- What the planner can DO today. Anything not named here is a proposal that is only described in a plan. ---------------
EXECUTED_TRANSITIONS = frozenset({"hard_cut"})
EXECUTED_EFFECTS = frozenset({"slow_zoom_on_static"})   # a slow push-in / pull-out on static footage
EXECUTED_PACING_CURVES = frozenset({"flat", "build", "breathe"})   # the planner scales shot lengths by a 10-bin curve
EXECUTED_OPENINGS = frozenset({"brand_card", "hero_first", "establishing_first", "action_first", "none"})   # brand_card needs the job's logo
EXECUTED_ENDINGS = frozenset({"brand_card", "hero_hold", "none"})
EXECUTED_MUSIC = frozenset({"cut_on_hits"})   # cuts snap to the music's hits; "allow_off_beat" is proposal-only
# Colour, typography, captions and sound design are text guidance only. Captions exist only for the narrated-story planner,
# which the library does not drive.
EXECUTED_TEXT_GUIDANCE: frozenset[str] = frozenset()

EXECUTABLE: dict[str, frozenset[str]] = {
    "transitions": EXECUTED_TRANSITIONS,
    "effects": EXECUTED_EFFECTS,
    "pacing_curves": EXECUTED_PACING_CURVES,
    "openings": EXECUTED_OPENINGS,
    "endings": EXECUTED_ENDINGS,
    "music": EXECUTED_MUSIC,
    "text_guidance": EXECUTED_TEXT_GUIDANCE,
}

# --- Vocabulary: every name a profile may use, with the plain words the report prints for it. -----------------------------
TRANSITION_LABELS = {
    "hard_cut": "hard cuts",
    "dissolve": "dissolves",
    "dip_to_black": "dips to black",
    "whip_pan": "whip pans",
    "match_cut": "match cuts",
    "smash_cut": "smash cuts",
    "j_l_cut": "J-cuts and L-cuts (sound leading or trailing the picture)",
}
EFFECT_LABELS = {
    "slow_zoom_on_static": "a slow zoom on static footage",
    "speed_ramp": "speed ramps",
    "flash": "flash frames",
    "zoom_blur": "zoom blurs",
    "whip": "whip moves",
    "light_leak": "light leaks",
    "glitch": "glitch effects",
    "freeze_frame": "freeze frames",
    "slow_motion": "slow motion",
    "punch_in": "punch-in crops",
    "camera_shake": "camera shake",
}
OPENING_LABELS = {   # executed openings
    "brand_card": "opens on your brand card (needs the job's logo)",
    "hero_first": "prefers to open on a hero moment (a preference the picker weighs, not a guarantee)",
    "establishing_first": "prefers to open on a steady establishing shot (a preference, not a guarantee)",
    "action_first": "prefers to open on an action moment (a preference, not a guarantee)",
}
ENDING_LABELS = {    # executed endings
    "brand_card": "ends on your brand card (needs the job's logo)",
    "hero_hold": "prefers to end on a held hero moment (a preference, not a guarantee)",
}
PROPOSAL_ONLY_OPENINGS = {
    "cold_open": "a cold open (a short teaser before the main edit)",
    "fade_in": "a fade in from black",
    "title_card": "an opening title card",
    "tease_burst": "a quick burst of the best shots before the main edit",
}
PROPOSAL_ONLY_ENDINGS = {
    "fade_out": "a fade out to black",
    "freeze_frame": "a freeze frame on the last shot",
    "loop_back": "a loop back to the first shot",
    "call_to_action_card": "a call-to-action end card",
}
ROLE_WORDS = {"action": "action", "reaction": "reaction", "camera_move": "camera-move", "reveal": "reveal", "hero": "hero", "hold": "steady-hold"}

ALL_OPENINGS = frozenset(OPENING_LABELS) | {"none"} | frozenset(PROPOSAL_ONLY_OPENINGS)
ALL_ENDINGS = frozenset(ENDING_LABELS) | {"none"} | frozenset(PROPOSAL_ONLY_ENDINGS)

ROLE_NOTABLE = 0.3   # a role weight at least this far from zero is worth saying out loud in the report
DIVERSITY = {"high": 1.3, "medium": 1.0, "low": 0.7}   # how strongly the planner avoids repeating a look
CURVE_BINS = 10
# Raw shapes of the two curves, scaled by the planner onto shot lengths; planner_config normalises each to a mean of exactly 1.0
# so a curve moves length around the edit without changing the overall pace.
_BUILD_RAW = (1.30, 1.22, 1.14, 1.06, 0.99, 0.92, 0.86, 0.81, 0.77, 0.75)           # shots get shorter toward the end
_BREATHE_RAW = (1.35, 1.12, 0.95, 0.85, 0.80, 0.80, 0.85, 0.95, 1.12, 1.35)         # longer opening and closing, quicker middle
FIRST_ROLE = {"hero_first": "hero", "establishing_first": "hold", "action_first": "action"}


@dataclass(frozen=True)
class LibraryStyle:
    """One editorial profile. See the module docstring for what is executed and what is only proposed.

    `pace` is a multiplier on Josh's measured usual rhythm (1.0 = his ~0.57 s median shot, higher = calmer), within the
    planner's range. `roles` gives each kind of moment a weight in [-1, 1] (a missing role counts as 0). `shot_seconds` is
    the preferred shot length and is informational: the pace is what the planner executes."""
    slug: str
    name: str
    intent: str
    roles: dict[str, float]
    variety: str
    pace: float
    shot_seconds: tuple[float, float]
    pacing_curve: str
    opening: str
    ending: str
    continuity: tuple[str, ...]
    music: dict[str, Any]       # {"cut_on_hits": bool, "allow_off_beat": bool, "notes": str}; the notes also carry the sound-design advice
    transitions: tuple[str, ...]
    effects: tuple[str, ...]
    colour: str
    captions: str               # captions and on-screen typography
    platform: dict[str, Any]    # {"aspects": tuple of ASPECTS, "seconds": (min, max)}
    avoid_when: tuple[str, ...]
    provenance: str             # "measured" or "guidance"
    provenance_note: str        # says exactly what, if anything, is measured
    buildable: bool
    build_note: str


# --- The eleven base profiles -----------------------------------------------------------------------------------------------

_GUIDANCE_NOTE = ("Guidance, not measured: the role weights, pacing curve, opening, ending, shot lengths and the pace multiplier in this profile are "
                  "editorial convention for this kind of edit. None of it was measured on your edits.")

_BUILT = "Built by the multi-variant planner from this profile's pace, moment preferences, variety, pacing curve, opening and ending."
_LOGO = " The brand card needs the job's logo."

LIBRARY: dict[str, LibraryStyle] = {}


def _add(style: LibraryStyle) -> None:
    LIBRARY[style.slug] = style


_add(LibraryStyle(
    slug="high-energy-commercial", name="High-energy commercial",
    intent="A fast, punchy product or brand spot that sells on momentum: every cut lands on a hit and the energy keeps climbing to a clean brand payoff.",
    roles={"action": 0.7, "reaction": 0.1, "camera_move": 0.5, "reveal": 0.4, "hero": 0.6, "hold": -0.8},
    variety="high", pace=0.85, shot_seconds=(0.25, 1.0), pacing_curve="build", opening="action_first", ending="brand_card",
    continuity=(
        "Alternate wide, medium and close framings so no two neighbouring shots look alike.",
        "Keep screen direction consistent: movement left to right is followed by movement left to right unless the cut is meant to jolt.",
        "Cut on the peak of a movement so the motion carries across the cut.",
        "Never cut between two near-identical angles of the same subject; it reads as a jump cut.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "Pick a track with a hard, clear kick and put its biggest hit on the hero shot. Sound design: whooshes and impacts under push-ins and the card reveal; duck the music 2-3 dB under any voice-over line."},
    transitions=("hard_cut", "whip_pan", "smash_cut"), effects=("slow_zoom_on_static", "speed_ramp", "flash", "zoom_blur"),
    colour="Punchy and contrasty: deep blacks, saturated brand colours, a clean slightly cool white balance. Keep skin tones natural.",
    captions="Short kinetic type, one to three words, popped in on the beat; a single product or offer line near the end.",
    platform={"aspects": ("9:16", "1:1", "16:9"), "seconds": (15, 45)},
    avoid_when=(
        "The footage is mostly slow or static; forcing fast cuts onto it looks frantic and empty.",
        "The brand voice is calm, premium or reflective.",
        "There is no strong rhythmic track, so the cuts have nothing to land on.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT + _LOGO,
))

_add(LibraryStyle(
    slug="premium-luxury", name="Premium / luxury",
    intent="A confident, unhurried piece that lets texture, light and craft do the selling: fewer, longer shots, restraint, and a held final image.",
    roles={"hero": 0.8, "reveal": 0.5, "camera_move": 0.5, "hold": 0.6, "action": -0.3, "reaction": -0.2},
    variety="medium", pace=1.6, shot_seconds=(0.6, 2.4), pacing_curve="breathe", opening="establishing_first", ending="brand_card",
    continuity=(
        "Let each shot finish its own movement before cutting; prefer cutting at the end of a slow camera move, not the middle.",
        "Keep a small, disciplined set of looks (shallow close-ups, one or two wides) and avoid mixing handheld with locked-off footage.",
        "Leave negative space in the frame where a title or the logo will sit.",
        "Hold on detail and material (stitching, grain, reflections) for a beat longer than feels necessary.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": True,
           "notes": "A sparse, cinematic or ambient bed; cut on the downbeat of a bar rather than on every hit, and an occasional cut just after the beat feels deliberate. Sound design: soft risers into reveals, one low impact on the hero shot, room tone under every hold."},
    transitions=("hard_cut", "dissolve", "dip_to_black"), effects=("slow_zoom_on_static", "slow_motion"),
    colour="Rich and restrained: deep but not crushed blacks, a gentle highlight roll-off, muted saturation with one accent colour (gold, deep green or the brand colour), warm-neutral skin.",
    captions="Minimal: a small, widely spaced title at the start and the end only; no word-by-word captions.",
    platform={"aspects": ("16:9", "4:5", "9:16"), "seconds": (30, 75)},
    avoid_when=(
        "The footage is shaky, rushed or poorly lit; a calm pace shows every flaw.",
        "The message is price-led or promotional.",
        "There are fewer than about ten usable clips, so long shots will repeat the same look.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE,
    buildable=True, build_note=_BUILT + _LOGO + " At pace 1.6 the median shot is still under a second: the planner can't go calmer than 2.0, so this is premium within your fast rhythm, not a slow cinematic pace.",
))

_add(LibraryStyle(
    slug="lifestyle-social", name="Lifestyle / social",
    intent="A warm, human, scroll-stopping piece for a feed: real people and candid moments, a hook in the first second, and nothing that needs the sound on.",
    roles={"reaction": 0.6, "action": 0.4, "hero": 0.3, "reveal": 0.2, "camera_move": 0.2, "hold": -0.2},
    variety="high", pace=1.0, shot_seconds=(0.3, 1.4), pacing_curve="flat", opening="hero_first", ending="none",
    continuity=(
        "Lead with the single most arresting moment so the first second earns the scroll.",
        "Stay close to faces and hands; cut from a candid reaction to the thing it is reacting to.",
        "Mix in one or two wide shots so the viewer knows where the people are.",
        "End on a shot that could loop back into the first one.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "An upbeat, current-sounding track with an obvious beat. Sound design: assume the viewer may watch muted; if sound is on, a small laugh or ambient pop on a reaction shot adds life."},
    transitions=("hard_cut", "whip_pan", "match_cut"), effects=("slow_zoom_on_static", "speed_ramp", "freeze_frame"),
    colour="Bright, natural and warm: lifted shadows, true-to-life skin, saturation up a touch, the same look across every shot so the feed looks cohesive.",
    captions="Burned-in, large, high-contrast captions inside the platform's safe zone (clear of the bottom fifth and the right edge); written to work with the sound off.",
    platform={"aspects": ("9:16", "4:5", "1:1"), "seconds": (8, 30)},
    avoid_when=(
        "The subject is serious, sensitive or formal.",
        "The footage is mostly landscapes or establishing shots with no people.",
        "The client's brand guide forbids casual or trend-led editing.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT,
))

_add(LibraryStyle(
    slug="documentary-story", name="Documentary / story",
    intent="A calm, story-first edit where the people and the place lead: shots stay long enough to be understood, and a reaction is allowed to land.",
    roles={"reaction": 0.7, "reveal": 0.5, "hold": 0.5, "hero": 0.2, "camera_move": 0.1, "action": 0.0},
    variety="low", pace=1.7, shot_seconds=(0.7, 2.8), pacing_curve="breathe", opening="establishing_first", ending="hero_hold",
    continuity=(
        "Show a wide before the details so the viewer always knows where they are.",
        "Cut on an action or a glance so every cut is motivated.",
        "Stay with one subject or place for a few shots before changing; sense matters more than variety.",
        "Let a reaction land before moving on to the next idea.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": True,
           "notes": "Music is a bed under the story, not a metronome; accept off-beat cuts where the story needs them. Sound design: keep natural ambience (room tone, wind, crowd) continuous across cuts and let it carry the transitions; let sound lead or trail the picture by a few frames."},
    transitions=("hard_cut", "dissolve", "j_l_cut", "dip_to_black"), effects=("slow_zoom_on_static", "slow_motion"),
    colour="Naturalistic: close to the camera's own look, neutral white balance, modest contrast, one consistent grade across the piece. Correct exposure before adding any style.",
    captions="Lower-third names, with a place and date for each new location; plain, readable subtitles for any unclear or non-English speech.",
    platform={"aspects": ("16:9", "4:5"), "seconds": (60, 300)},
    avoid_when=(
        "The brief is a short, punchy ad or a social clip under about thirty seconds.",
        "There is no story to follow, only unrelated moments.",
        "There is no ambient sound or dialogue worth keeping.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE,
    buildable=True, build_note=_BUILT + " It is cut to the music's hits at a calm rhythm; it does not follow a narration or a dialogue track (narrated stories use the separate story planner).",
))

_add(LibraryStyle(
    slug="music-led-montage", name="Music-led montage",
    intent="The song is the structure: hard cuts on the hits at your own usual rhythm, the best moment of each clip, and the biggest hit on the best shot.",
    roles={"action": 0.4, "camera_move": 0.4, "hero": 0.4, "reveal": 0.3, "reaction": 0.1, "hold": -0.4},
    variety="high", pace=1.0, shot_seconds=(0.3, 1.3), pacing_curve="flat", opening="none", ending="hero_hold",
    continuity=(
        "Choose the song first and build the edit to it.",
        "Put the track's biggest hit on the strongest shot in the footage.",
        "Vary subject and framing from shot to shot so a fast run of cuts stays readable.",
        "End on a held shot with a little air so the last hit rings out.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "Cuts land on the strongest hits; the song decides where the edit breathes and where it flurries. Sound design: usually nothing beyond the song; a single riser or impact into the final hold can help."},
    transitions=("hard_cut",), effects=("slow_zoom_on_static", "flash", "speed_ramp"),
    colour="Match the song's mood: warm and bright for an upbeat track, cooler and more contrasty for a hard one. Keep it consistent across all clips.",
    captions="None by default; a title or credit only at the very start or end.",
    platform={"aspects": ("9:16", "16:9", "1:1"), "seconds": (15, 40)},
    avoid_when=(
        "The song has no clear hits (a pad, a drone or speech), so there is nothing to cut to.",
        "The footage is mostly dialogue or a talking head.",
        "The story matters more than the rhythm.",
    ),
    provenance="guidance",   # only its pace is measured (the note says so); a bare "measured" badge on the whole profile would overstate it
    provenance_note=("Measured: the pace of 1.0x is your own usual rhythm, read from 128 of your short fast edits (median shot 0.57 s). "
                     "Not measured: the role weights, pacing curve, opening, ending and shot-length range, which are editorial guidance."),
    buildable=True, build_note=_BUILT,
))

_add(LibraryStyle(
    slug="sports-action", name="Sports / action",
    intent="Speed, impact and result: the fastest cutting the planner offers, built toward the winning moment, with the action always readable.",
    roles={"action": 0.9, "hero": 0.5, "camera_move": 0.4, "reaction": 0.4, "reveal": 0.2, "hold": -0.9},
    variety="medium", pace=0.8, shot_seconds=(0.2, 0.9), pacing_curve="build", opening="action_first", ending="hero_hold",
    continuity=(
        "Cut on the peak of the movement so the motion carries across the cut.",
        "Keep the direction of play consistent (left to right stays left to right) so the viewer never loses where the ball or athlete is going.",
        "Alternate wide play with tight faces: effort, then reaction.",
        "Pair an effort with its outcome wherever the footage allows.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "A fast, driving track with hard drops; put the biggest play on the biggest drop. Sound design: impact hits on collisions and landings, a crowd swell under the finish, a brief low-pass dip just before the final moment."},
    transitions=("hard_cut", "whip_pan", "smash_cut"), effects=("slow_zoom_on_static", "speed_ramp", "slow_motion", "freeze_frame", "zoom_blur"),
    colour="High contrast, saturated, crisp and slightly cool; protect highlights in bright sun and keep team colours accurate.",
    captions="Score, name and stat overlays only: short, bold, in the corners, never over the action.",
    platform={"aspects": ("9:16", "16:9"), "seconds": (20, 60)},
    avoid_when=(
        "The footage has little real movement.",
        "The coverage is slow, tactical or ceremonial, where the tension matters more than the speed.",
        "The footage was shot at a low frame rate; fast cuts on motion judder.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT,
))

_add(LibraryStyle(
    slug="food-beverage", name="Food / beverage",
    intent="Make it look delicious: a slow, enticing look at the hero dish or drink, quick sensory moments (pour, slice, sizzle) in the middle, and a held final product.",
    roles={"hero": 0.7, "reveal": 0.6, "action": 0.5, "reaction": 0.3, "camera_move": 0.3, "hold": 0.2},
    variety="medium", pace=1.2, shot_seconds=(0.4, 1.8), pacing_curve="breathe", opening="hero_first", ending="brand_card",
    continuity=(
        "Show the whole dish or product once, then go close; never stay only in close-ups.",
        "Cut on the moment of transformation (the pour, the cut, the first bite).",
        "Keep the same light direction and surface across neighbouring shots so the food looks like one meal.",
        "Pair a preparation shot with its finished result.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "Warm, groovy and mid-tempo; cut on the downbeat for each reveal. Sound design: this genre lives on sound (sizzle, pour, crunch, ice, cutlery); bring recorded or added foley up under the music on every hero shot."},
    transitions=("hard_cut", "match_cut", "dissolve"), effects=("slow_zoom_on_static", "slow_motion", "speed_ramp"),
    colour="Warm and appetising: a warm white balance, saturated reds, oranges and greens, bright clean highlights. Never let food go grey or green; protect the glints on liquids.",
    captions="Short ingredient or product-name callouts near the hero shots; price or call to action only on the final card.",
    platform={"aspects": ("9:16", "1:1", "4:5"), "seconds": (10, 40)},
    avoid_when=(
        "The food does not look appetising on camera (cold, dull or badly lit); fast cuts will not hide that.",
        "The piece is about a chef or a story rather than the food; use the documentary profile.",
        "Spoken instruction (a recipe walk-through) is the content.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT + _LOGO,
))

_add(LibraryStyle(
    slug="fashion-beauty", name="Fashion / beauty",
    intent="Attitude and silhouette: a striking look first, confident movement and detail, with a consistent grade so the clothes and skin are the stars.",
    roles={"hero": 0.8, "camera_move": 0.6, "reveal": 0.5, "reaction": 0.3, "hold": 0.3, "action": 0.2},
    variety="high", pace=1.1, shot_seconds=(0.3, 1.6), pacing_curve="flat", opening="hero_first", ending="hero_hold",
    continuity=(
        "Open on the strongest look and keep each subsequent look distinct.",
        "Alternate full-length silhouettes with fabric and detail close-ups.",
        "Keep a consistent camera height and framing logic within a sequence.",
        "Cut on a turn, a step or a gesture so the movement flows across the cut.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": True,
           "notes": "Stylish electronic or downtempo; hits matter less than attitude, so an occasional cut just off the beat feels deliberate. Sound design: fabric and footstep foley, a breath or shutter click as an accent on held frames."},
    transitions=("hard_cut", "match_cut", "whip_pan"), effects=("slow_zoom_on_static", "slow_motion", "freeze_frame", "light_leak"),
    colour="Stylised and consistent: either clean high-key (bright, low contrast, soft skin) or moody (deep contrast, desaturated with controlled colour accents). Pick one and keep it; skin tones come first.",
    captions="Brand, designer and look names as small, clean type at each new look; credits at the end.",
    platform={"aspects": ("9:16", "4:5", "16:9"), "seconds": (15, 60)},
    avoid_when=(
        "The garments or products are hard to see (bad light or motion blur); the edit exists to sell them.",
        "Hard, sports-style cutting is wanted.",
        "The footage is mostly interviews or behind-the-scenes.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT,
))

_add(LibraryStyle(
    slug="event-highlights", name="Event highlights",
    intent="Capture the night: the venue and the build-up, the crowd and the performance, rising to the peak moment and a sponsor close.",
    roles={"reaction": 0.6, "hero": 0.5, "action": 0.4, "reveal": 0.3, "camera_move": 0.3, "hold": 0.0},
    variety="high", pace=1.0, shot_seconds=(0.3, 1.5), pacing_curve="build", opening="establishing_first", ending="brand_card",
    continuity=(
        "Open wide on the venue so the audience knows where this is, then move in.",
        "Alternate stage with crowd so every performance shot has a reaction.",
        "Spread shots across the whole event rather than clustering on the first hour.",
        "Keep sponsor and brand moments clean and readable.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": False,
           "notes": "A track with a clear build and a lift; the event's peak moment should land on the biggest drop. Sound design: a few seconds of real room or crowd sound under the opening wide, then into the track; a crowd swell and applause on the finish."},
    transitions=("hard_cut", "whip_pan", "dissolve"), effects=("slow_zoom_on_static", "speed_ramp", "flash"),
    colour="Even and true to the venue: match the cameras to each other first, then a gentle contrast lift; keep the stage lighting's colour instead of neutralising it.",
    captions="Event name, date and venue in the opening seconds; sponsor logos on the closing card; speaker names as lower thirds when someone is identifiable.",
    platform={"aspects": ("16:9", "9:16"), "seconds": (30, 90)},
    avoid_when=(
        "There is no crowd or atmosphere footage, only talking heads.",
        "A multi-day event needs a chronological story; use the documentary profile.",
        "Sponsors are guaranteed a fixed amount of screen time, which needs manual timing.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=True, build_note=_BUILT + _LOGO,
))

_add(LibraryStyle(
    slug="experimental-creative", name="Experimental / creative",
    intent="Break the pattern on purpose: unexpected rhythm, long holds against sudden flurries, strong looks, and a structure that surprises.",
    roles={"camera_move": 0.6, "reveal": 0.5, "hold": 0.4, "action": 0.3, "hero": 0.2, "reaction": -0.2},
    variety="high", pace=0.9, shot_seconds=(0.2, 2.5), pacing_curve="breathe", opening="cold_open", ending="loop_back",
    continuity=(
        "Repeat a motif (a shape, a colour, a movement) so the surprises feel designed.",
        "Contrast scale and speed between neighbouring shots on purpose.",
        "Stack a short flurry of cuts, then hold one shot for a long beat.",
        "Keep one strong rule, then break it once.",
    ),
    music={"cut_on_hits": True, "allow_off_beat": True,
           "notes": "Bend the rhythm: let some cuts anticipate or trail the beat. Sound design: layered textures, stutter edits, reversed swells and sudden silence."},
    transitions=("hard_cut", "smash_cut", "match_cut", "whip_pan"),
    effects=("slow_zoom_on_static", "glitch", "speed_ramp", "freeze_frame", "zoom_blur", "light_leak", "slow_motion"),
    colour="Commit to a strong look rather than a neutral one (heavy contrast, a split tone, a limited palette or grain), as long as skin and the product stay readable when either matters.",
    captions="Typography is part of the design: oversized, off-grid or kinetic type is fine, but keep each line readable for at least a second.",
    platform={"aspects": ("9:16", "1:1", "16:9"), "seconds": (15, 90)},
    avoid_when=(
        "The client needs a clear, safe, on-brand message.",
        "The content is corporate, legal, medical or safety related.",
        "There is no time to review the result; its choices need a human eye.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE,
    buildable=True, build_note=_BUILT + " Only its pace, moment preferences, variety and curve are built; the cold open, the loop-back ending, the glitch and other effects are proposals.",
))

_add(LibraryStyle(
    slug="dialogue-interview", name="Dialogue / interview",
    intent="The words lead: a person speaking to camera, cut for clarity, with camera angles switched at natural pauses and b-roll covering any jump.",
    roles={"hold": 0.8, "reaction": 0.5, "hero": 0.3, "action": -0.3, "camera_move": -0.3},
    variety="low", pace=2.0, shot_seconds=(3.0, 9.0), pacing_curve="flat", opening="cold_open", ending="brand_card",
    continuity=(
        "Switch camera angle at a quiet gap, not in the middle of a word.",
        "Keep the same eyeline and screen direction between angles.",
        "Cover a jump cut with b-roll or a different angle rather than cutting the same framing twice.",
        "Open on a short strong quote as a cold open, then go back to the start.",
    ),
    music={"cut_on_hits": False, "allow_off_beat": True,
           "notes": "Music, if any, sits well under the voice: cut to the speech, never to the beat. Sound design: clean the dialogue first (noise and levels), keep room tone under every cut, and duck music at least 12 dB under speech."},
    transitions=("hard_cut", "j_l_cut", "dissolve"), effects=("slow_zoom_on_static",),
    colour="Match the cameras to each other first, then a natural, flattering skin-tone grade with the background slightly darker than the face.",
    captions="Burned-in subtitles for social, in sentence-sized chunks; a speaker name lower third on first appearance.",
    platform={"aspects": ("16:9", "9:16", "1:1"), "seconds": (45, 600)},
    avoid_when=(
        "There is no spoken dialogue to follow.",
        "The footage is a single camera with one unbroken take and no cover.",
        "The piece is meant to be driven by music rather than speech.",
    ),
    provenance="guidance", provenance_note=_GUIDANCE_NOTE, buildable=False,
    build_note=("Interviews are planned by the separate multicam planner (cameras synced by audio and switched at quiet gaps over one dialogue track), "
                "not by the multi-variant planner. This profile describes the intent so the library is complete, but it can't be built as a variant."),
))


# --- Checks -----------------------------------------------------------------------------------------------------------------

def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(style: LibraryStyle) -> list[str]:
    """Plain-English problems with a style; an empty list means it is valid."""
    problems: list[str] = []
    if not str(style.slug or "").strip():
        problems.append("The style has no slug.")
    if not str(style.name or "").strip():
        problems.append("The style has no name.")
    if not str(style.intent or "").strip():
        problems.append("The style has no one-sentence intent.")

    if not isinstance(style.roles, dict):
        problems.append("The role weights must be a mapping of role to weight.")
    else:
        for role, weight in style.roles.items():
            if role not in ROLES:
                problems.append(f"'{role}' is not a known role (the roles are {', '.join(ROLES)}).")
            elif not _finite(weight) or not -1.0 <= weight <= 1.0:
                problems.append(f"The weight for role '{role}' is {weight!r}; it has to be a number from -1 to 1.")

    if not _finite(style.pace) or not MIN_PACE <= style.pace <= MAX_PACE:
        problems.append(f"The pace is {style.pace!r}; it has to be between {MIN_PACE} and {MAX_PACE} times your usual rhythm.")

    shot = style.shot_seconds
    if not (isinstance(shot, (tuple, list)) and len(shot) == 2 and all(_finite(v) for v in shot)):
        problems.append("The shot length range has to be two numbers (shortest, longest) in seconds.")
    elif shot[0] <= 0 or shot[1] <= 0:
        problems.append("The shot lengths have to be more than zero seconds.")
    elif shot[0] > shot[1]:
        problems.append(f"The shortest preferred shot ({shot[0]} s) is longer than the longest ({shot[1]} s).")

    if style.variety not in VARIETIES:
        problems.append(f"The variety '{style.variety}' is not one of {', '.join(VARIETIES)}.")
    if style.pacing_curve not in PACING_CURVES:
        problems.append(f"The pacing curve '{style.pacing_curve}' is not one of {', '.join(PACING_CURVES)}.")
    if style.opening not in ALL_OPENINGS:
        problems.append(f"The opening '{style.opening}' is not a known opening ({', '.join(sorted(ALL_OPENINGS))}).")
    if style.ending not in ALL_ENDINGS:
        problems.append(f"The ending '{style.ending}' is not a known ending ({', '.join(sorted(ALL_ENDINGS))}).")

    music = style.music
    if not isinstance(music, dict) or not {"cut_on_hits", "allow_off_beat", "notes"} <= set(music):
        problems.append("The music settings need cut_on_hits, allow_off_beat and notes.")
    elif not (isinstance(music["cut_on_hits"], bool) and isinstance(music["allow_off_beat"], bool) and isinstance(music["notes"], str)):
        problems.append("In the music settings, cut_on_hits and allow_off_beat must be true or false and notes must be text.")

    for t in style.transitions:
        if t not in TRANSITION_LABELS:
            problems.append(f"The transition '{t}' is not a known transition ({', '.join(TRANSITION_LABELS)}).")
    for e in style.effects:
        if e not in EFFECT_LABELS:
            problems.append(f"The effect '{e}' is not a known effect ({', '.join(EFFECT_LABELS)}).")

    plat = style.platform
    if not isinstance(plat, dict) or not {"aspects", "seconds"} <= set(plat):
        problems.append("The platform settings need aspects and seconds.")
    else:
        aspects = plat["aspects"]
        if not aspects or any(a not in ASPECTS for a in aspects):
            problems.append(f"The platform aspect ratios must be a non-empty list from {', '.join(ASPECTS)}.")
        sec = plat["seconds"]
        if not (isinstance(sec, (tuple, list)) and len(sec) == 2 and all(_finite(v) for v in sec)) or sec[0] <= 0 or sec[0] > sec[1]:
            problems.append("The platform length has to be two positive numbers (shortest, longest) in seconds, shortest first.")

    if style.provenance not in PROVENANCES:
        problems.append(f"The provenance '{style.provenance}' has to be 'measured' or 'guidance'.")
    if not str(style.provenance_note or "").strip():
        problems.append("The provenance note is empty; it has to say exactly what, if anything, is measured.")
    if not isinstance(style.buildable, bool):
        problems.append("'buildable' has to be true or false.")
    if not str(style.build_note or "").strip():
        problems.append("The build note is empty; it has to say whether and how the planner builds this style.")
    return problems


def validate_library() -> dict[str, list[str]]:
    """Problems for every base style, keyed by slug (an empty list = valid)."""
    return {slug: validate(style) for slug, style in LIBRARY.items()}


# --- Hybrids ----------------------------------------------------------------------------------------------------------------

def _union(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Order-preserving, de-duplicated union."""
    seen: dict[str, None] = {}
    for g in groups:
        for item in g:
            seen.setdefault(item, None)
    return tuple(seen)


def _blend_text(dominant: str, other: str) -> str:
    if not other or other == dominant:
        return dominant
    if not dominant:
        return other
    return f"{dominant} Also: {other}"


def _lookup(slug: str) -> LibraryStyle:
    if slug not in LIBRARY:
        raise ValueError(f"'{slug}' isn't a style in the library. The styles are: {', '.join(LIBRARY)}.")
    return LIBRARY[slug]


def hybrid(a_slug: str, b_slug: str, weight_a: float = 0.5, name: str | None = None) -> LibraryStyle:
    """The twelfth style type, a custom hybrid of two base styles. Numbers are blended (pace by a weighted geometric mean, clamped to the planner's
    range; role weights and shot lengths linearly); the categorical choices (variety, curve, opening, ending) come from the dominant style
    (`weight_a` of 0.5 or more makes `a` dominant); tuples are unioned. The weight is rounded to a whole percent, because the slug records it that way
    and `get_style(slug)` must give back the identical style. A hybrid is always guidance, and is buildable only when both styles are."""
    a, b = _lookup(a_slug), _lookup(b_slug)
    if not _finite(weight_a) or not 0.0 <= weight_a <= 1.0:
        raise ValueError(f"The weight has to be a number from 0 to 1 (the share of the first style); got {weight_a!r}.")
    pct = round(weight_a * 100)
    wa, wb = pct / 100.0, (100 - pct) / 100.0
    dom, other = (a, b) if wa >= 0.5 else (b, a)

    pace = a.pace ** wa * b.pace ** wb
    pace = round(min(MAX_PACE, max(MIN_PACE, pace)), 4)
    roles = {r: round(wa * a.roles.get(r, 0.0) + wb * b.roles.get(r, 0.0), 3) for r in ROLES}
    shot = (round(wa * a.shot_seconds[0] + wb * b.shot_seconds[0], 3), round(wa * a.shot_seconds[1] + wb * b.shot_seconds[1], 3))
    music = {
        "cut_on_hits": bool(a.music["cut_on_hits"] or b.music["cut_on_hits"]),
        "allow_off_beat": bool(a.music["allow_off_beat"] or b.music["allow_off_beat"]),
        "notes": _blend_text(dom.music["notes"], other.music["notes"]),
    }
    platform = {
        "aspects": _union(tuple(a.platform["aspects"]), tuple(b.platform["aspects"])),
        "seconds": (round(wa * a.platform["seconds"][0] + wb * b.platform["seconds"][0]), round(wa * a.platform["seconds"][1] + wb * b.platform["seconds"][1])),
    }
    buildable = a.buildable and b.buildable
    if buildable:
        build_note = "Built by the multi-variant planner from the blended settings (the pace, moment preferences and curve are blended; the opening, ending, variety and curve are the dominant style's)."
    else:
        blockers = " ".join(f"{s.name}: {s.build_note}" for s in (a, b) if not s.buildable)
        build_note = "Can't be built as a variant because one of its styles can't. " + blockers
    return LibraryStyle(
        slug=f"hybrid:{a_slug}+{b_slug}:{pct}",
        name=name or f"{a.name} + {b.name} ({pct}/{100 - pct})",
        intent=f"A custom blend: {pct}% {a.name} and {100 - pct}% {b.name}. {dom.intent}",
        roles=roles, variety=dom.variety, pace=pace, shot_seconds=shot, pacing_curve=dom.pacing_curve, opening=dom.opening, ending=dom.ending,
        continuity=_union(dom.continuity, other.continuity), music=music,
        transitions=_union(dom.transitions, other.transitions), effects=_union(dom.effects, other.effects),
        colour=_blend_text(dom.colour, other.colour), captions=_blend_text(dom.captions, other.captions), platform=platform,
        avoid_when=_union(a.avoid_when, b.avoid_when),
        provenance="guidance",
        provenance_note=(f"Guidance, not measured: this is a blend of '{a.name}' and '{b.name}' made by arithmetic on their editorial settings. "
                         "The blended role weights, pace multiplier and curve were not measured on your edits."),
        buildable=buildable, build_note=build_note,
    )


def get_style(slug: str) -> LibraryStyle:
    """A base style by slug, or a hybrid rebuilt from a 'hybrid:a+b:NN' slug (NN = the first style's percent). Raises ValueError for anything else."""
    if slug in LIBRARY:
        return LIBRARY[slug]
    if isinstance(slug, str) and slug.startswith("hybrid:"):
        parts = slug[len("hybrid:"):].split(":")
        if len(parts) == 2 and parts[1].isdigit():
            ab = parts[0].split("+")
            if len(ab) == 2:
                pct = int(parts[1])
                if 0 <= pct <= 100:
                    return hybrid(ab[0], ab[1], pct / 100.0)
        raise ValueError(f"'{slug}' isn't a valid hybrid slug; it looks like 'hybrid:<style>+<style>:<percent of the first>'.")
    raise ValueError(f"'{slug}' isn't a style in the library. The styles are: {', '.join(LIBRARY)}.")


# --- What the planner will do, and what it won't ------------------------------------------------------------------------------

def _num(x: float) -> str:
    s = f"{x:.2f}"
    return s[:-1] if s.endswith("0") else s


def _words(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def execution_report(style: LibraryStyle) -> dict[str, list[str]]:
    """{"executed": [...], "proposed_only": [...]} in plain words. Everything under "executed" is checked against the EXECUTED_* constants,
    so nothing the planner can't do is listed there. A style the variant planner can't build executes nothing from here: its items move to
    "proposed_only" with a line saying why."""
    executed: list[str] = [f"pace {_num(style.pace)}x your usual rhythm"]
    proposed: list[str] = []

    likes = [r for r in sorted(ROLES, key=lambda r: -style.roles.get(r, 0.0)) if style.roles.get(r, 0.0) >= ROLE_NOTABLE]
    dislikes = [r for r in sorted(ROLES, key=lambda r: style.roles.get(r, 0.0)) if style.roles.get(r, 0.0) <= -ROLE_NOTABLE]
    if likes:
        executed.append(f"prefers {_words([ROLE_WORDS[r] for r in likes])} moments")
    if dislikes:
        executed.append(f"avoids {_words([ROLE_WORDS[r] for r in dislikes])} moments")

    executed.append({"high": "high variety: avoids repeating a look strongly", "medium": "medium variety: avoids repeating a look", "low": "low variety: repeated looks are tolerated"}[style.variety])
    if style.pacing_curve in EXECUTED_PACING_CURVES:
        executed.append({"flat": "even pacing across the edit", "build": "build pacing curve (shots get shorter toward the end)", "breathe": "breathe pacing curve (longer opening and closing)"}[style.pacing_curve])

    if style.opening in EXECUTED_OPENINGS:
        if style.opening != "none":
            executed.append(OPENING_LABELS[style.opening])
    else:
        proposed.append(f"opening: {PROPOSAL_ONLY_OPENINGS.get(style.opening, style.opening)}")
    if style.ending in EXECUTED_ENDINGS:
        if style.ending != "none":
            executed.append(ENDING_LABELS[style.ending])
    else:
        proposed.append(f"ending: {PROPOSAL_ONLY_ENDINGS.get(style.ending, style.ending)}")

    executed.append("hard cuts")   # the only transition the planner makes, whatever the profile wishes for
    for t in style.transitions:
        if t not in EXECUTED_TRANSITIONS:
            proposed.append(f"{TRANSITION_LABELS.get(t, t)} (Premiere build only does hard cuts)")

    if "cut_on_hits" in EXECUTED_MUSIC:
        if style.music.get("cut_on_hits"):
            executed.append("cuts snap to the music's hits")
        else:
            proposed.append("cutting to the speech or picture instead of the music's hits (the planner always cuts on the music's hits)")
    if style.music.get("allow_off_beat"):
        proposed.append("allow off-beat cuts")

    for e in style.effects:
        if e in EXECUTED_EFFECTS:
            executed.append("slow zoom on static footage")
        else:
            proposed.append(EFFECT_LABELS.get(e, e))

    if style.colour:
        proposed.append(f"colour: {style.colour}")
    if style.captions:
        proposed.append(f"captions and typography: {style.captions}")
    if style.music.get("notes"):
        proposed.append(f"sound design: {style.music['notes']}")
    for line in style.continuity:
        proposed.append(f"continuity: {line}")

    if not style.buildable:
        proposed = [f"not buildable as a variant: {style.build_note}"] + [f"not executed here: {item}" for item in executed] + proposed
        executed = []
    return {"executed": executed, "proposed_only": proposed}


def _normalised(raw: tuple[float, ...]) -> list[float]:
    mean = sum(raw) / len(raw)
    return [round(v / mean, 4) for v in raw]


def planner_config(style: LibraryStyle) -> dict[str, Any]:
    """Exactly the parameters the multi-variant planner uses for this style. Raises ValueError for a style it can't build."""
    if not style.buildable:
        raise ValueError(f"'{style.name}' can't be built as a variant. {style.build_note}")
    curve = {"flat": None, "build": _normalised(_BUILD_RAW), "breathe": _normalised(_BREATHE_RAW)}[style.pacing_curve]
    return {
        "pace": float(style.pace),
        "role_weights": {r: float(style.roles.get(r, 0.0)) for r in ROLES},
        "diversity": DIVERSITY[style.variety],
        "pacing_curve": curve,
        "first_role": FIRST_ROLE.get(style.opening),
        "last_role": "hero" if style.ending == "hero_hold" else None,
        "slow_zooms": "slow_zoom_on_static" in style.effects,
        "opener_card": style.opening == "brand_card",
        "closing_card": style.ending == "brand_card",
    }


def list_styles() -> list[dict[str, Any]]:
    """The base styles in a form a screen can show: names, what is measured, whether they build, and what is executed versus proposed."""
    return [
        {
            "slug": s.slug, "name": s.name, "intent": s.intent, "provenance": s.provenance, "provenance_note": s.provenance_note,
            "pace": s.pace, "buildable": s.buildable, "build_note": s.build_note,
            "platform": {"aspects": list(s.platform["aspects"]), "seconds": list(s.platform["seconds"])},
            "execution_report": execution_report(s),
        }
        for s in LIBRARY.values()
    ]
