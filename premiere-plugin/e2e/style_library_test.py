"""Tests for the Editing Style Library (2026-10-22): backend/app/post_style_library.py. Eleven editorial profiles as plain data, a custom hybrid, and an
execution report that keeps what the planner really does apart from what is only a proposal.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python style_library_test.py"""
import dataclasses
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_style_library as lib  # noqa: E402
from app.post_steady import MAX_PACE, MIN_PACE  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    return None


EXPECTED = ["high-energy-commercial", "premium-luxury", "lifestyle-social", "documentary-story", "music-led-montage", "sports-action", "food-beverage",
            "fashion-beauty", "event-highlights", "experimental-creative", "dialogue-interview"]
BASE = list(lib.LIBRARY.values())
BUILDABLE = [s for s in BASE if s.buildable]
PREMIUM, SPORTS, DIALOGUE, MUSIC = lib.LIBRARY["premium-luxury"], lib.LIBRARY["sports-action"], lib.LIBRARY["dialogue-interview"], lib.LIBRARY["music-led-montage"]

# ---- the library as a whole -------------------------------------------------------------------------------------------------------------------
check("the library has a version", lib.LIBRARY_VERSION == 1)
check("the roles are the five described kinds of moment plus 'hold'", lib.ROLES == ("action", "reaction", "camera_move", "reveal", "hero", "hold"))
check("there are exactly the 11 base profiles, by these slugs", sorted(lib.LIBRARY) == sorted(EXPECTED) and len(lib.LIBRARY) == 11, sorted(lib.LIBRARY))
check("every profile's key is its own slug", all(k == s.slug for k, s in lib.LIBRARY.items()))
check("every base style validates with no problems", all(not p for p in lib.validate_library().values()), {k: v for k, v in lib.validate_library().items() if v})
check("validate_library covers every base style", sorted(lib.validate_library()) == sorted(EXPECTED))
check("every pace is within the planner's range 0.8-2.0 (and the range is the planner's own)", all(MIN_PACE <= s.pace <= MAX_PACE for s in BASE) and (MIN_PACE, MAX_PACE) == (0.8, 2.0), [(s.slug, s.pace) for s in BASE])
check("every role weight is within -1..1 and names a known role", all(r in lib.ROLES and -1 <= w <= 1 for s in BASE for r, w in s.roles.items()))
check("every profile has real content: intent, colour, captions, continuity, avoid_when, at least one platform", all(
    len(s.intent) > 30 and s.colour and s.captions and len(s.continuity) >= 3 and len(s.avoid_when) >= 2 and s.platform["aspects"] and s.music["notes"] for s in BASE))
check("the paces follow the brief: high-energy and sports 0.8-0.9, lifestyle, music-led and event about 1.0, fashion 1.0-1.2, food about 1.2, premium 1.5-1.7, documentary 1.6-1.8",
      all(0.8 <= lib.LIBRARY[k].pace <= 0.9 for k in ("high-energy-commercial", "sports-action"))
      and all(0.95 <= lib.LIBRARY[k].pace <= 1.05 for k in ("lifestyle-social", "music-led-montage", "event-highlights"))
      and 1.0 <= lib.LIBRARY["fashion-beauty"].pace <= 1.2 and 1.15 <= lib.LIBRARY["food-beverage"].pace <= 1.25
      and 1.5 <= PREMIUM.pace <= 1.7 and 1.6 <= lib.LIBRARY["documentary-story"].pace <= 1.8, {s.slug: s.pace for s in BASE})
check("music-led-montage is exactly 1.0, his own measured rhythm", MUSIC.pace == 1.0)
check("a shot length range goes with every pace (median about 0.57 s times the pace sits inside it) except the interview, whose real rhythm is the multicam planner's", all(
    s.shot_seconds[0] <= 0.572 * s.pace <= s.shot_seconds[1] for s in BASE if s.slug != "dialogue-interview"), [(s.slug, s.pace, s.shot_seconds) for s in BASE])
check("the three pacing curves are all in use, and so are all three varieties", {s.pacing_curve for s in BASE} == set(lib.PACING_CURVES) and {s.variety for s in BASE} == set(lib.VARIETIES))
try:
    PREMIUM.pace = 1.0  # type: ignore[misc]
    check("a base profile can't be changed in place", False)
except dataclasses.FrozenInstanceError:
    check("a base profile can't be changed in place", True)

# ---- what the planner can do: the EXECUTABLE constants ----------------------------------------------------------------------------------------
check("only the hard cut is an executed transition", lib.EXECUTED_TRANSITIONS == {"hard_cut"} and lib.EXECUTABLE["transitions"] == {"hard_cut"})
check("only the slow zoom on static footage is an executed effect", lib.EXECUTED_EFFECTS == {"slow_zoom_on_static"} and lib.EXECUTABLE["effects"] == {"slow_zoom_on_static"})
check("flat, build and breathe are the executed pacing curves", lib.EXECUTED_PACING_CURVES == {"flat", "build", "breathe"})
check("the executed openings and endings are the ones the brief lists", lib.EXECUTED_OPENINGS == {"brand_card", "hero_first", "establishing_first", "action_first", "none"}
      and lib.EXECUTED_ENDINGS == {"brand_card", "hero_hold", "none"})
check("cutting on the music's hits is executed; off-beat, colour, typography, captions and sound design are not", lib.EXECUTED_MUSIC == {"cut_on_hits"} and not lib.EXECUTED_TEXT_GUIDANCE)
check("speed ramps, flashes, zoom blurs, whips, light leaks, glitches and freeze frames are all known and none is executed",
      all(e in lib.EFFECT_LABELS and e not in lib.EXECUTED_EFFECTS for e in ("speed_ramp", "flash", "zoom_blur", "whip", "light_leak", "glitch", "freeze_frame")))

# ---- validate() catches each kind of bad input -------------------------------------------------------------------------------------------------
base = lib.LIBRARY["lifestyle-social"]


def bad(**changes):
    return lib.validate(dataclasses.replace(base, **changes))


check("a valid style gives an empty list", lib.validate(base) == [])
p = bad(roles={"action": 0.5, "dance": 0.2})
check("an unknown role is caught, and named", any("dance" in x and "role" in x for x in p), p)
p = bad(roles={"action": 1.5})
check("a role weight above 1 is caught", any("action" in x and "-1 to 1" in x for x in p), p)
p = bad(roles={"hero": -1.01})
check("a role weight below -1 is caught", any("hero" in x for x in p), p)
p = bad(roles={"hero": float("nan")})
check("a role weight that is not a number is caught", any("hero" in x for x in p), p)
check("the extremes -1 and 1 are fine", bad(roles={"hero": 1.0, "hold": -1.0}) == [])
p = bad(pace=0.5)
check("a pace below the range is caught", any("pace" in x.lower() and "0.8" in x for x in p), p)
p = bad(pace=2.5)
check("a pace above the range is caught", any("pace" in x.lower() and "2.0" in x for x in p), p)
check("the pace limits themselves are fine", bad(pace=0.8) == [] and bad(pace=2.0) == [])
p = bad(shot_seconds=(2.0, 1.0))
check("a shot range with min above max is caught", any("longer than the longest" in x for x in p), p)
p = bad(shot_seconds=(0.0, 1.0))
check("a shot range with a zero is caught", any("more than zero" in x for x in p), p)
p = bad(shot_seconds=(-1.0, 1.0))
check("a negative shot length is caught", any("more than zero" in x for x in p), p)
p = bad(shot_seconds=(1.0,))
check("a shot range that is not two numbers is caught", any("two numbers" in x for x in p), p)
p = bad(variety="extreme")
check("an unknown variety is caught", any("variety" in x and "extreme" in x for x in p), p)
p = bad(pacing_curve="zigzag")
check("an unknown pacing curve is caught", any("pacing curve" in x and "zigzag" in x for x in p), p)
p = bad(opening="fireworks")
check("an unknown opening is caught", any("opening" in x and "fireworks" in x for x in p), p)
p = bad(ending="fireworks")
check("an unknown ending is caught", any("ending" in x and "fireworks" in x for x in p), p)
check("a proposal-only opening and ending are valid (they are just not executed)", bad(opening="cold_open", ending="loop_back") == [])
p = bad(intent="   ")
check("an empty intent is caught", any("intent" in x for x in p), p)
p = bad(name="")
check("an empty name is caught", any("name" in x for x in p), p)
p = bad(platform={"aspects": ("9:16",), "seconds": (30, 10)})
check("platform seconds with min above max are caught", any("platform length" in x for x in p), p)
p = bad(platform={"aspects": ("9:16",), "seconds": (0, 10)})
check("platform seconds with a zero are caught", any("platform length" in x for x in p), p)
p = bad(platform={"aspects": ("5:7",), "seconds": (10, 30)})
check("an unknown aspect ratio is caught", any("aspect" in x for x in p), p)
p = bad(provenance="folklore")
check("a provenance other than measured or guidance is caught", any("provenance" in x for x in p), p)
check("both allowed provenances are fine", bad(provenance="measured") == [] and bad(provenance="guidance") == [])
p = bad(provenance_note="")
check("an empty provenance note is caught", any("provenance note" in x for x in p), p)
p = bad(transitions=("hard_cut", "teleport"))
check("an unknown transition is caught", any("teleport" in x for x in p), p)
p = bad(effects=("sparkles",))
check("an unknown effect is caught", any("sparkles" in x for x in p), p)
p = bad(music={"cut_on_hits": True})
check("music settings missing a key are caught", any("music" in x for x in p), p)
p = bad(roles={"dance": 3.0}, pace=9.0, variety="x", pacing_curve="y")
check("several problems at once are all reported (one line each)", len(p) >= 4, p)
check("every problem is a plain sentence (a string ending in a full stop)", all(isinstance(x, str) and x.endswith(".") for x in p), p)

# ---- execution_report: never claims a proposal as executed -------------------------------------------------------------------------------------
PROPOSAL_WORDS = ["dissolve", "dip to black", "whip pan", "match cut", "smash cut", "j-cut", "speed ramp", "flash", "zoom blur", "whip move", "light leak", "glitch",
                  "freeze", "slow motion", "colour", "sound design", "off-beat", "caption", "typography", "continuity", "cold open", "loop back", "fade"]
leaks = []
for s in BASE:
    ex = " | ".join(lib.execution_report(s)["executed"]).lower()
    leaks += [(s.slug, w) for w in PROPOSAL_WORDS if w in ex]
check("no base profile lists a proposal-only thing (dissolve, ramp, flash, colour, sound design, off-beat...) as executed", not leaks, leaks)
rep = lib.execution_report(PREMIUM)
check("a report has exactly the two lists, of plain strings", set(rep) == {"executed", "proposed_only"} and all(isinstance(x, str) for k in rep for x in rep[k]))
check("it states the pace as a multiple of his usual rhythm", "pace 1.6x your usual rhythm" in rep["executed"], rep["executed"])
check("it lists the executed things a premium profile does: hard cuts, hits, a breathe curve, an establishing open, a brand card, a slow zoom", all(
    any(k in item for item in rep["executed"]) for k in ("hard cuts", "snap to the music", "breathe pacing curve", "establishing", "brand card", "slow zoom")), rep["executed"])
check("it says which moments the profile prefers (hero) and avoids (action is -0.3 so it is notable)", any(i.startswith("prefers hero") for i in rep["executed"]) and any(i.startswith("avoids action") for i in rep["executed"]), rep["executed"])
check("dissolves are proposed, with the plain reason that the build only does hard cuts", any("dissolves" in i and "only does hard cuts" in i for i in rep["proposed_only"]), rep["proposed_only"])
check("dips to black are proposed too, and 'hard cuts' is not repeated as a proposal", any("dips to black" in i for i in rep["proposed_only"]) and not any(i.startswith("hard cuts") for i in rep["proposed_only"]))
check("slow motion is proposed only", "slow motion" in rep["proposed_only"] and not any("slow motion" in i for i in rep["executed"]))
check("colour, captions, sound design and continuity advice appear as proposals", all(any(i.startswith(k) for i in rep["proposed_only"]) for k in ("colour:", "captions and typography:", "sound design:", "continuity:")))
check("allow-off-beat is a proposal for a profile that wants it (premium)", "allow off-beat cuts" in rep["proposed_only"])
check("and is not listed for a profile that doesn't (sports)", "allow off-beat cuts" not in lib.execution_report(SPORTS)["proposed_only"])
rep_sports = lib.execution_report(SPORTS)
check("speed ramps, freeze frames and zoom blurs are proposals for sports, the slow zoom is executed", all(x in rep_sports["proposed_only"] for x in ("speed ramps", "freeze frames", "zoom blurs")) and "slow zoom on static footage" in rep_sports["executed"], rep_sports)
check("whip pans and smash cuts are proposals for sports, with the reason", any("whip pans" in i and "hard cuts" in i for i in rep_sports["proposed_only"]) and any("smash cuts" in i for i in rep_sports["proposed_only"]))
check("sports prefers to open on action and end on a held hero, both executed AS PREFERENCES (the picker weighs them; no guarantee is claimed)",
      any(x.startswith("prefers to open on an action moment") and "not a guarantee" in x for x in rep_sports["executed"])
      and any(x.startswith("prefers to end on a held hero moment") and "not a guarantee" in x for x in rep_sports["executed"]), rep_sports["executed"])
exp = lib.execution_report(lib.LIBRARY["experimental-creative"])
check("a proposal-only opening and ending (cold open, loop back) are proposals, not executed", any(i.startswith("opening:") and "cold open" in i for i in exp["proposed_only"]) and any(i.startswith("ending:") and "loop back" in i for i in exp["proposed_only"])
      and not any("cold open" in i or "loop back" in i for i in exp["executed"]), exp)
# build a style that asks for everything unexecuted and confirm every wish lands under proposed_only
wild = dataclasses.replace(base, transitions=tuple(lib.TRANSITION_LABELS), effects=tuple(lib.EFFECT_LABELS), colour="teal and orange", captions="big type",
                           music={"cut_on_hits": True, "allow_off_beat": True, "notes": "add a riser"}, opening="title_card", ending="freeze_frame")
rw = lib.execution_report(wild)
non_hard = [t for t in lib.TRANSITION_LABELS if t != "hard_cut"]
non_zoom = [e for e in lib.EFFECT_LABELS if e != "slow_zoom_on_static"]
check("every non-hard-cut transition a style asks for is listed under proposed_only", all(any(lib.TRANSITION_LABELS[t] in i for i in rw["proposed_only"]) for t in non_hard), rw["proposed_only"])
check("every effect other than the slow zoom is listed under proposed_only", all(lib.EFFECT_LABELS[e] in rw["proposed_only"] for e in non_zoom), rw["proposed_only"])
ex_text = " | ".join(rw["executed"]).lower()
check("an extreme profile still executes only hard cuts and the slow zoom, never a listed wish", all(w not in ex_text for w in ("dissolve", "speed ramp", "whip", "glitch", "light leak", "freeze", "teal", "riser", "off-beat", "title card")), rw["executed"])
check("colour, captions, sound design, title card, freeze-frame ending and off-beat all land under proposed_only", all(any(k in i for i in rw["proposed_only"]) for k in ("colour: teal and orange", "captions and typography: big type", "sound design: add a riser", "title card", "freeze frame", "allow off-beat cuts")), rw["proposed_only"])
plain = dataclasses.replace(base, transitions=("hard_cut",), effects=(), colour="", captions="", music={"cut_on_hits": True, "allow_off_beat": False, "notes": ""}, continuity=())
rp = lib.execution_report(plain)
check("a style that wishes for nothing extra has nothing proposed", rp["proposed_only"] == [], rp["proposed_only"])
check("every proposal-only list item that begins 'continuity' and 'colour' is text guidance only (never in executed)", all(not i.startswith(("colour", "continuity", "sound design", "captions")) for s in BASE for i in lib.execution_report(s)["executed"]))
# the non-buildable interview executes nothing from the library
rd = lib.execution_report(DIALOGUE)
check("the interview profile executes nothing here, and says why first", rd["executed"] == [] and rd["proposed_only"][0].startswith("not buildable as a variant") and "multicam" in rd["proposed_only"][0], rd["proposed_only"][:2])
check("cutting to speech instead of the music is a proposal, not an executed rule", any("speech" in i and "always cuts on the music" in i for i in rd["proposed_only"]))
check("the report works on every base style and a hybrid without raising", all(lib.execution_report(s) for s in BASE) and bool(lib.execution_report(lib.hybrid("premium-luxury", "sports-action"))))

# ---- planner_config -----------------------------------------------------------------------------------------------------------------------------
KEYS = {"pace", "role_weights", "diversity", "pacing_curve", "first_role", "last_role", "slow_zooms", "opener_card", "closing_card"}
cfgs = {s.slug: lib.planner_config(s) for s in BUILDABLE}
check("a planner config has exactly the nine documented parameters", all(set(c) == KEYS for c in cfgs.values()), [set(c) ^ KEYS for c in cfgs.values()][:2])
check("all six roles are present in the role weights, with the style's own weights (missing = 0)", all(set(c["role_weights"]) == set(lib.ROLES) for c in cfgs.values())
      and cfgs["documentary-story"]["role_weights"]["action"] == 0.0 and cfgs["sports-action"]["role_weights"]["action"] == 0.9)
check("the pace is passed through unchanged", all(cfgs[s.slug]["pace"] == s.pace for s in BUILDABLE))
check("diversity is 1.3 for high, 1.0 for medium and 0.7 for low variety", all(cfgs[s.slug]["diversity"] == {"high": 1.3, "medium": 1.0, "low": 0.7}[s.variety] for s in BUILDABLE))
check("each variety is exercised: lifestyle 1.3, sports 1.0, documentary 0.7", cfgs["lifestyle-social"]["diversity"] == 1.3 and cfgs["sports-action"]["diversity"] == 1.0 and cfgs["documentary-story"]["diversity"] == 0.7)
for s in BUILDABLE:
    c = cfgs[s.slug]["pacing_curve"]
    if s.pacing_curve == "flat":
        check(f"flat curve -> None ({s.slug})", c is None, c)
    else:
        check(f"{s.pacing_curve} curve -> 10 floats with mean 1.0 ({s.slug})", isinstance(c, list) and len(c) == 10 and abs(statistics.mean(c) - 1.0) < 0.005 and all(isinstance(v, float) and v > 0 for v in c), c)
build_c = lib.planner_config(lib.LIBRARY["high-energy-commercial"])["pacing_curve"]
breathe_c = lib.planner_config(PREMIUM)["pacing_curve"]
check("build gets steadily shorter, from about 1.3 down to about 0.75", all(a >= b for a, b in zip(build_c, build_c[1:])) and 1.2 <= build_c[0] <= 1.35 and 0.7 <= build_c[-1] <= 0.8, build_c)
check("breathe is longer at both ends than in the middle", breathe_c[0] > 1.2 and breathe_c[-1] > 1.2 and min(breathe_c[3:7]) < 0.9 and breathe_c[0] > breathe_c[4] and breathe_c[-1] > breathe_c[5], breathe_c)
check("a curve is a fresh list each call (changing it can't corrupt the next plan)", lib.planner_config(PREMIUM)["pacing_curve"] is not breathe_c)
FIRST = {"hero_first": "hero", "establishing_first": "hold", "action_first": "action", "brand_card": None, "none": None}
check("first_role maps hero_first -> hero, establishing_first -> hold, action_first -> action, anything else -> None", all(
    lib.planner_config(dataclasses.replace(base, opening=o))["first_role"] == r for o, r in FIRST.items()))
check("a proposal-only opening gives no first role and no opener card", lib.planner_config(dataclasses.replace(base, opening="cold_open"))["first_role"] is None
      and lib.planner_config(dataclasses.replace(base, opening="cold_open"))["opener_card"] is False)
check("last_role is hero only for hero_hold", lib.planner_config(dataclasses.replace(base, ending="hero_hold"))["last_role"] == "hero"
      and all(lib.planner_config(dataclasses.replace(base, ending=e))["last_role"] is None for e in ("brand_card", "none", "loop_back")))
check("opener_card and closing_card follow brand_card", lib.planner_config(dataclasses.replace(base, opening="brand_card", ending="brand_card"))["opener_card"] is True
      and lib.planner_config(dataclasses.replace(base, opening="brand_card", ending="brand_card"))["closing_card"] is True
      and lib.planner_config(dataclasses.replace(base, opening="none", ending="hero_hold"))["closing_card"] is False)
check("premium: establishing open ('hold') and a brand-card close", cfgs["premium-luxury"]["first_role"] == "hold" and cfgs["premium-luxury"]["closing_card"] is True and cfgs["premium-luxury"]["opener_card"] is False)
check("slow_zooms follows 'slow_zoom_on_static' in the effects", lib.planner_config(dataclasses.replace(base, effects=("slow_zoom_on_static",)))["slow_zooms"] is True
      and lib.planner_config(dataclasses.replace(base, effects=("speed_ramp",)))["slow_zooms"] is False)
msg = raises(lib.planner_config, DIALOGUE)
check("the interview profile is refused with a ValueError that names the multicam planner", msg is not None and "multicam" in msg, msg)
check("exactly one base profile is not buildable: the interview", [s.slug for s in BASE if not s.buildable] == ["dialogue-interview"])
check("the planner config is plain data (JSON-serialisable)", bool(json.dumps(cfgs)))

# ---- hybrid -------------------------------------------------------------------------------------------------------------------------------------------
H = lib.hybrid("sports-action", "premium-luxury")
check("a hybrid has the slug hybrid:a+b:percent", H.slug == "hybrid:sports-action+premium-luxury:50", H.slug)
check("its pace lies between the two (here the geometric mean of 0.8 and 1.6, about 1.13)", SPORTS.pace < H.pace < PREMIUM.pace and abs(H.pace - (0.8 * 1.6) ** 0.5) < 0.001, H.pace)
check("the pace is a weighted geometric mean: 25% sports gives 0.8^0.25 * 1.6^0.75", abs(lib.hybrid("sports-action", "premium-luxury", 0.25).pace - 0.8 ** 0.25 * 1.6 ** 0.75) < 0.001)
check("a heavier weight pulls the pace toward that style", lib.hybrid("sports-action", "premium-luxury", 0.9).pace < H.pace < lib.hybrid("sports-action", "premium-luxury", 0.1).pace)
check("weights of exactly 0 and 1 give the second and the first style's pace", abs(lib.hybrid("sports-action", "premium-luxury", 1.0).pace - 0.8) < 1e-9 and abs(lib.hybrid("sports-action", "premium-luxury", 0.0).pace - 1.6) < 1e-9)
check("role weights blend linearly", abs(H.roles["action"] - (0.9 + -0.3) / 2) < 0.001 and abs(H.roles["hold"] - (-0.9 + 0.6) / 2) < 0.001 and set(H.roles) == set(lib.ROLES), H.roles)
check("shot lengths blend linearly", abs(H.shot_seconds[0] - (SPORTS.shot_seconds[0] + PREMIUM.shot_seconds[0]) / 2) < 0.001 and abs(H.shot_seconds[1] - (SPORTS.shot_seconds[1] + PREMIUM.shot_seconds[1]) / 2) < 0.001, H.shot_seconds)
check("at 50/50 the first style is dominant: variety, curve, opening and ending come from it", (H.variety, H.pacing_curve, H.opening, H.ending) == (SPORTS.variety, SPORTS.pacing_curve, SPORTS.opening, SPORTS.ending), (H.variety, H.pacing_curve, H.opening, H.ending))
H2 = lib.hybrid("sports-action", "premium-luxury", 0.3)
check("below 50% the second style is dominant instead", (H2.variety, H2.pacing_curve, H2.opening, H2.ending) == (PREMIUM.variety, PREMIUM.pacing_curve, PREMIUM.opening, PREMIUM.ending), (H2.variety, H2.pacing_curve, H2.opening, H2.ending))
check("tuples are unioned, de-duplicated, in order (sports first)", H.transitions[:3] == SPORTS.transitions and len(set(H.transitions)) == len(H.transitions) and set(H.transitions) == set(SPORTS.transitions) | set(PREMIUM.transitions)
      and set(H.effects) == set(SPORTS.effects) | set(PREMIUM.effects) and len(set(H.continuity)) == len(H.continuity) == len(set(SPORTS.continuity) | set(PREMIUM.continuity)), H.transitions)
check("avoid_when and the platform aspects are unions too", set(H.avoid_when) == set(SPORTS.avoid_when) | set(PREMIUM.avoid_when) and set(H.platform["aspects"]) == set(SPORTS.platform["aspects"]) | set(PREMIUM.platform["aspects"]))
check("a hybrid is guidance, never measured, even when one parent is the measured montage", lib.hybrid("music-led-montage", "premium-luxury").provenance == "guidance" and H.provenance == "guidance"
      and "not measured" in lib.hybrid("music-led-montage", "premium-luxury").provenance_note)
check("a hybrid validates, and so does every pair at several weights", not lib.validate(H) and all(not lib.validate(lib.hybrid(a, b, w)) for a in EXPECTED for b in EXPECTED[:4] for w in (0.0, 0.25, 0.5, 1.0)))
check("its pace never leaves the planner's range", all(MIN_PACE <= lib.hybrid(a, b, w).pace <= MAX_PACE for a in EXPECTED for b in EXPECTED for w in (0.0, 0.5, 1.0)))
check("a hybrid of two buildable styles is buildable, and its planner config works", H.buildable and set(lib.planner_config(H)) == KEYS)
check("a hybrid with the interview is not buildable, says so, and planner_config refuses it", not lib.hybrid("premium-luxury", "dialogue-interview").buildable and "multicam" in lib.hybrid("premium-luxury", "dialogue-interview").build_note
      and raises(lib.planner_config, lib.hybrid("premium-luxury", "dialogue-interview")) is not None)
check("it takes a name, and has a sensible default", lib.hybrid("sports-action", "premium-luxury", name="My blend").name == "My blend" and "Sports / action" in H.name and "Premium / luxury" in H.name)
check("unknown slugs are rejected plainly (first, second)", "nope" in (raises(lib.hybrid, "nope", "premium-luxury") or "") and "nope" in (raises(lib.hybrid, "premium-luxury", "nope") or ""))
check("a hybrid can't be nested inside another hybrid (its slug isn't a base style)", raises(lib.hybrid, H.slug, "premium-luxury") is not None)
check("weights outside 0..1 are rejected", all(raises(lib.hybrid, "sports-action", "premium-luxury", w) is not None for w in (-0.01, 1.01, 5, float("nan"), float("inf"))))
check("a weight of exactly 0 or 1 is accepted", raises(lib.hybrid, "sports-action", "premium-luxury", 0) is None and raises(lib.hybrid, "sports-action", "premium-luxury", 1) is None)
rt = lib.get_style(H.slug)
check("get_style round-trips a hybrid slug back into the identical blended style", rt == H and rt.slug == H.slug, (rt.slug, H.slug))
check("it round-trips at awkward weights too (the weight is stored as a whole percent)", all(lib.get_style(lib.hybrid("food-beverage", "fashion-beauty", w).slug) == lib.hybrid("food-beverage", "fashion-beauty", w) for w in (0.0, 0.07, 0.333, 0.5, 0.667, 0.995, 1.0)))
check("the slug records the percent: 0.333 gives :33", lib.hybrid("food-beverage", "fashion-beauty", 0.333).slug.endswith(":33"))
check("get_style also returns the base styles", all(lib.get_style(k) is lib.LIBRARY[k] for k in EXPECTED))
check("get_style rejects an unknown slug and malformed hybrids with ValueError", all(raises(lib.get_style, s) is not None for s in ("nope", "hybrid:", "hybrid:sports-action:50", "hybrid:sports-action+nope:50", "hybrid:a+b+c:50", "hybrid:sports-action+premium-luxury:abc", "hybrid:sports-action+premium-luxury:101")))

# ---- list_styles --------------------------------------------------------------------------------------------------------------------------------------
ls = lib.list_styles()
check("list_styles has the 11 base styles, in library order", [x["slug"] for x in ls] == list(lib.LIBRARY) and len(ls) == 11)
check("each entry has what a screen needs", all({"slug", "name", "intent", "provenance", "provenance_note", "pace", "buildable", "build_note", "execution_report"} <= set(x) for x in ls))
try:
    text = json.dumps(ls)
    check("the list is JSON-serialisable (json.dumps works)", len(text) > 1000)
except (TypeError, ValueError) as exc:
    check("the list is JSON-serialisable (json.dumps works)", False, exc)
check("it round-trips through JSON (tuples become lists, nothing lost)", json.loads(json.dumps(ls))[0]["execution_report"] == ls[0]["execution_report"])
check("its entries agree with the styles (pace, buildable) and the interview is the one that isn't", all(x["pace"] == lib.LIBRARY[x["slug"]].pace and x["buildable"] == lib.LIBRARY[x["slug"]].buildable for x in ls)
      and [x["slug"] for x in ls if not x["buildable"]] == ["dialogue-interview"])
check("a hybrid is JSON-serialisable too", bool(json.dumps({**dataclasses.asdict(H), "report": lib.execution_report(H)})))

# ---- provenance: only the montage's pace is measured -----------------------------------------------------------------------------------------------
others = [s for s in BASE if s.slug != "music-led-montage"]
check("music-led-montage's note says its pace is his measured usual rhythm, from 128 of his edits at a 0.57 s median", "usual rhythm" in MUSIC.provenance_note and "measured" in MUSIC.provenance_note.lower() and "128" in MUSIC.provenance_note and "0.57" in MUSIC.provenance_note, MUSIC.provenance_note)
check("and it also says what is NOT measured (the weights, curve, opening and ending)", "Not measured" in MUSIC.provenance_note and "role weights" in MUSIC.provenance_note)
check("no profile as a whole is labelled measured (only the montage's pace is, and its note says exactly that)", all(s.provenance == "guidance" for s in lib.LIBRARY.values()), [s.slug for s in lib.LIBRARY.values() if s.provenance != "guidance"])
check("no other profile's note mentions the measured rhythm", all("usual rhythm" not in s.provenance_note and "128" not in s.provenance_note and "0.57" not in s.provenance_note for s in others), [s.slug for s in others if "usual rhythm" in s.provenance_note])
check("every other profile says its role weights are guidance, not measured", all("not measured" in s.provenance_note.lower() and "role weights" in s.provenance_note and "guidance" in s.provenance_note.lower() for s in others), [s.slug for s in others])
check("the montage's 128-edit claim matches the measured file the app really uses", (lambda d: d["from_edits"] == 128 and abs(d["median_shot"] - 0.57) < 0.01)(json.loads((Path(__file__).resolve().parents[2] / "backend" / "app" / "post_usual_pace.json").read_text())))

# ---- build notes ----------------------------------------------------------------------------------------------------------------------------------
check("every buildable profile's note says it is built by the planner; the interview's says it is not, and why", all("multi-variant planner" in s.build_note for s in BUILDABLE) and "multicam planner" in DIALOGUE.build_note and "can't be built as a variant" in DIALOGUE.build_note)
check("profiles with a brand card say it needs the job's logo", all("logo" in s.build_note for s in BUILDABLE if "brand_card" in (s.opening, s.ending)), [s.slug for s in BUILDABLE if "brand_card" in (s.opening, s.ending) and "logo" not in s.build_note])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
