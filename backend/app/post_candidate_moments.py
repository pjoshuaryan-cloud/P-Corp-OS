"""
POST (2026-10-22) -- candidate moments: one record for every stretch of a clip the planner considers, with the evidence for it, how sure we are, where it came from
and how it scored.

Why: a planned shot used to carry one line of text (`moment_source`). Nothing recorded what else was offered, why this one won, which analysis it came from, or
how certain the choice was -- so a decision could not be explained to Josh, compared with an alternative, or linked to what he later did with it. This module
does not change WHICH stretch the planner picks (that stays in post_pick / post_steady / post_edit_plan, and default settings reproduce the plans exactly: see
premiere-plugin/e2e/candidate_engine_test.py). It describes candidates and choices in one versioned shape.

What is measured and what is judgement, said plainly in every record:
  * "measured": cut detection, steadiness, motion, sharpness and brightness come from reading the footage (post_steady), not from a model;
  * "judgement": the moment, its kind and its punch come from Claude looking at stills every 0.5-1 s (post_moments). On 168 of Josh's own shots Claude's first
    choice covers half of his shot 9% of the time and one of its top three 25% (random 6.5% / 18%): a useful first draft, not his taste;
  * nothing here is checked against his taste unless it says so.
"""
from __future__ import annotations

import hashlib
from typing import Any

CANDIDATE_SCHEMA_VERSION = 1
ENGINE_VERSION = "2026-10-22.1"
ROLES = ("action", "reaction", "camera_move", "reveal", "hero", "hold")   # the five kinds Claude names, plus "hold": a clean stretch with no described moment
MEASURED_FIRST_PICK = "Claude's first choice covers half of your shot 9% of the time on 168 of your shots (random 6.5%)"


def media_key(clip: dict[str, Any]) -> tuple[str, bool]:
    """(key, stable): the verified SHA-256 of the file when the job has one (survives renames and moves), else name + duration (stable=False)."""
    checksum = clip.get("checksum")
    if checksum:
        return f"sha256:{checksum}", True
    return f"name:{str(clip.get('name', '')).lower()}|dur:{float(clip.get('duration') or 0):.2f}", False


def candidate_id(clip: dict[str, Any], start: float, length: float, origin: str) -> str:
    key, _ = media_key(clip)
    return hashlib.sha1(f"{key}|{round(start * 1000)}|{round(length * 1000)}|{origin}".encode()).hexdigest()[:16]


def _event_near(clip: dict[str, Any], start: float, length: float) -> dict[str, Any] | None:
    """The described moment this window was built around (or covers): the strongest one whose time falls inside the window."""
    inside = [e for e in (clip.get("events") or []) if e.get("t") is not None and start - 0.05 <= float(e["t"]) <= start + length + 0.05]
    return max(inside, key=lambda e: float(e.get("punch", 0))) if inside else None


def origin_of(window: dict[str, Any]) -> str:
    source = str(window.get("source", ""))
    if source.startswith("event pick") or source.startswith("event ("):
        return "described_moment"
    if source.startswith("steadiest"):
        return "steadiest_stretch"
    if source.startswith("picked in review"):
        return "picked_in_review"
    if "hand-set" in source:
        return "hand_set"
    if "composition" in source:
        return "composition_pick"
    return "fallback"


def role_of(window: dict[str, Any], clip: dict[str, Any] | None = None) -> str:
    """The editorial role of a window: the kind of described moment it was built around, else "hold"."""
    kind = window.get("event_kind")
    if kind in ROLES:
        return kind
    if clip is not None and origin_of(window) in ("described_moment", "picked_in_review"):
        event = _event_near(clip, float(window.get("start", 0.0)), float(window.get("duration", 0.0)))
        if event and event.get("kind") in ROLES:
            return event["kind"]
    return "hold"


def describe(clip: dict[str, Any], window: dict[str, Any], *, parts: dict[str, Any] | None = None, score: float | None = None,
             describe_provenance: dict[str, Any] | None = None, length: float | None = None) -> dict[str, Any]:
    """The candidate record for `window` of `clip` (a window as post_steady / post_edit_plan shape it: start, duration, source, steady?, event_punch?).
    `parts` / `score`: the picker's score breakdown when the window was ranked. `length`: the shot's real length when it differs from the window's (the
    picker caches windows by length rounded to 1/8 s, so a 0.44 s slot can reuse a window worked out for 0.48 s; the shot itself runs for its slot).
    Pure: reads nothing from disk."""
    start, length = float(window["start"]), float(length if length is not None else window["duration"])
    origin = origin_of(window)
    role = role_of(window, clip)
    event = _event_near(clip, start, length) if origin in ("described_moment", "picked_in_review") else None
    steady = window.get("steady") or {}
    fps = clip.get("fps")
    key, stable = media_key(clip)
    duration = float(clip.get("duration") or 0.0)

    evidence: list[str] = []
    uncertain: list[str] = []
    if event:
        evidence.append(f"Claude described a {str(event.get('kind', 'moment')).replace('_', ' ')} here: \"{event.get('what', '')}\" (punch {event.get('punch')}/10, judged from stills)")
        uncertain.append("the moment's time comes from stills 0.5-1 s apart, so it can be off by up to half a second")
        uncertain.append(MEASURED_FIRST_PICK)
    elif origin == "steadiest_stretch":
        evidence.append("no described moment was usable here, so this is the steadiest clean stretch of the clip (measured)")
    elif origin == "picked_in_review":
        evidence.append("you picked this moment in review")
    elif origin in ("hand_set", "composition_pick"):
        evidence.append(str(window.get("source", "")))
    else:
        evidence.append(str(window.get("source", "no analysis was available for this clip")))
    if steady:
        evidence.append("no hard cut inside (measured)" if not steady.get("cuts") else "every stretch of this clip has a cut in it: least bad (measured)")
        if steady.get("static"):
            evidence.append("the footage is static here (measured)")
        luma = steady.get("luma")
        if luma is not None:
            if luma < 0.16:
                evidence.append(f"underexposed (mean brightness {luma:.2f}, measured)")
            elif luma > 0.86:
                evidence.append(f"overexposed (mean brightness {luma:.2f}, measured)")
    else:
        uncertain.append("this clip's footage was not read for steadiness, cuts or exposure")

    technical = {"cut_inside": bool(steady.get("cuts")) if steady else None, "static": steady.get("static") if steady else None,
                 "exposure": (None if not steady or steady.get("luma") is None else "under" if steady["luma"] < 0.16 else "over" if steady["luma"] > 0.86 else "ok")}
    invalid = []
    if technical["cut_inside"]:
        invalid.append("a hard cut inside the stretch")
    record = {
        "schema": CANDIDATE_SCHEMA_VERSION, "engine": ENGINE_VERSION,
        "id": candidate_id(clip, start, length, origin),
        "media": {"file_id": clip.get("file_id"), "name": clip.get("name"), "key": key, "stable": stable},
        "source_in": round(start, 3), "source_out": round(start + length, 3), "duration": round(length, 3),
        "timebase": {"fps": fps, "in_frame": round(start * fps) if fps else None, "out_frame": round((start + length) * fps) if fps else None},
        "origin": origin, "role": role,
        "event": ({"t": event.get("t"), "kind": event.get("kind"), "punch": event.get("punch"), "what": event.get("what")} if event else None),
        "position_in_clip": round(start / duration, 3) if duration > 0 else None,
        "features": ({k: steady.get(k) for k in ("score", "mean_motion", "peak_motion", "jerk", "blur", "luma", "exposure")} if steady else None),
        "technical": technical,
        "valid": not invalid, "invalid_reasons": invalid,
        "confidence": {"basis": "judgement (Claude, from stills)" if event else ("measured" if steady else "none"),
                       "checked_against_your_taste": origin == "picked_in_review", "uncertain": uncertain},
        "evidence": evidence,
        "provenance": {"engine": ENGINE_VERSION, "describe": describe_provenance or ("legacy description (no version recorded)" if clip.get("events") else None),
                       "steadiness": "post_steady cache v2" if steady else None},
    }
    if parts is not None or score is not None:
        record["score"] = {"total": None if score is None else round(float(score), 4), "parts": parts or {},
                           "note": "relative ranking among this slot's options, not a measure of quality"}
    return record


def compact(record: dict[str, Any]) -> dict[str, Any]:
    """What a planned shot carries (the full record minus the bulky features)."""
    return {k: v for k, v in record.items() if k != "features"}


def clip_candidates(clip: dict[str, Any], length: float, *, limit: int = 5) -> list[dict[str, Any]]:
    """Every candidate stretch of `clip` for a shot of `length` seconds, best first in the planner's own order: its described moments (strongest punch first,
    each window centred on the moment, skipping any with a cut inside or a black picture), then its steadiest clean stretch. Each is a full candidate record,
    with `window` holding the planner-shaped window. Needs the clip's steadiness analysis; [] without it."""
    from app import post_steady
    if not clip.get("steady"):
        return []
    out = []
    windows = post_steady._event_windows(clip, length, [], limit)
    taken = [(w["start"], w["start"] + w["duration"]) for w in windows]
    steadiest = post_steady.window_for_slot({**clip, "events": []}, length, taken) if len(windows) < limit else None
    for w in windows + ([steadiest] if steadiest else []):
        record = describe(clip, w)
        record["window"] = w
        out.append(record)
    return out


def explain_choice(record: dict[str, Any]) -> str:
    """One plain sentence for a planned shot: what it is, why it won, how sure that is."""
    what = record.get("event") or {}
    if record["origin"] == "described_moment":
        head = f"{str(what.get('kind', 'moment')).replace('_', ' ').capitalize()}: {what.get('what', '')}"
    elif record["origin"] == "steadiest_stretch":
        head = "A clean, steady stretch (no described moment fitted here)"
    elif record["origin"] == "picked_in_review":
        head = "Your pick in review"
    else:
        head = "Fallback stretch"
    parts = (record.get("score") or {}).get("parts") or {}
    why = []
    if parts.get("looks_like_earlier") is not None:
        why.append("looks different from the shots before it" if parts["looks_like_earlier"] < 0.2 else "the least repetitive option left")
    if parts.get("event"):
        why.append("a strong described moment")
    if parts.get("role_bonus"):
        why.append("fits the style's preferred shots")
    if record["origin"] == "picked_in_review":
        sure = "your choice"
    elif record["confidence"]["basis"].startswith("judgement"):
        sure = "judged by Claude from stills, not your taste"
    else:
        sure = "measured from the footage" if record["confidence"]["basis"] == "measured" else "little analysis available"
    return head + (f" -- {', '.join(why)}" if why else "") + f" ({sure})."
