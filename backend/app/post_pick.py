"""Which clip, and which stretch of it, goes in each shot of a corporate edit (2026-10-15).

Josh's brief: look through ALL the footage, give the best options, and don't be repetitive -- he wants to polish, grade and export the same day.
The first version took every Nth clip in shoot order and the steadiest stretch of it, without ever looking at what a shot shows. On a real corporate
test pool that produced 18 shots from about 7 distinct scenes, with the same aerial or warehouse aisle back to back. So every shot is now chosen like this:

  for each slot, in timeline order, every clip that is long enough is asked for its best stretch (no cut inside, smooth, sharp, well exposed; a small
  bonus where Claude has described a strong event), and the clip + stretch with the best total score wins:

      score =  quality of the stretch
             - how much it looks like shots already in the edit   (the previous shot counts most, then the one before, then everything earlier a little)
             - using a clip that is already in the edit
             - how far the clip sits from where this shot falls in the shoot   (small: the edit still follows the shoot broadly and covers all of it)
             + a small bonus for covering a described event

"Looks like" is the correlation of 16x9 grey thumbnails taken from the clip's own analysis (post_steady), plus Claude's scene label when the clip has been
described. Everything is local and deterministic; the weights are stated assumptions, not measurements of Josh's taste (the moments module found that no
signal reproduces which instant of a clip he picks -- this makes sure each shot is CLEAN and the edit is VARIED, and leaves the taste calls to him).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app import post_candidate_moments, post_steady

QUALITY_SCALE = 0.3        # quality = 1 / (1 + steadiness_score / QUALITY_SCALE): a clean window is ~0.95, a shaky one ~0.6, one with a cut ~0. Was 0.1; on the 165 static-heavy GWM clips that made the very stillest
                           # footage win every slot (7 shots in a row of people standing at the booth), so how still a shot is now counts for less than whether it adds a new look
SIM_FLOOR, SIM_FULL = 0.12, 0.45  # thumbnail correlation where two shots start to count as "the same look" / are surely the same. Was 0.30 / 0.70 (same-scene pairs averaged 0.68 on the Diplomat pool);
                           # on the GWM expo hall, wide shots of one booth from different angles correlate only 0.15-0.4, and they read as the same kind of shot to a viewer
SAME_SCENE_SIM = 0.85      # two clips Claude gave the same scene label count at least this alike
DIVERSITY_WEIGHT = 1.2     # an adjacent repeat of a look costs 1.2: more than any difference in quality between clean stretches
RECENCY = (1.0, 0.7, 0.55) # weight of the previous shot, the one before it, the one before that; everything earlier counts RECENCY_FLOOR
RECENCY_FLOOR = 0.5       # a look already used ANYWHERE in the edit still costs this (so a third repeat is avoided, and repeats land far apart)
REUSE_PENALTY = 5.0        # a clip that is already in the edit: only when the shoot has too few clips. Was 0.8, which gave 78 selects from just 58 of 165 clips; at 5 every clip is used once before any is repeated
OVERLAP_PENALTY = 2.0      # no free stretch left in the clip: it would repeat footage already used
CUT_PENALTY = 5.0          # a stretch with a hard cut inside it is only ever the least-bad option: no amount of variety makes up for it
POSITION_WEIGHT = 0.4      # per unit of distance (0..1) between a clip's place in the shoot and where this shot falls in the edit
EVENT_QUALITY = 0.2        # added for a stretch that covers a described event, times punch / 10
ALIKE = 0.5                # for the plan's repetition report: two shots at or above this correlation are "alike"
EVENT_CANDIDATES = 3       # a described clip offers its best three moments to each slot, and the one that adds the most variety wins. Measured on Josh's GWM footage: taking only each clip's
                           # single best moment made every shot a hero/logo shot of the same showroom (27 distinct looks in 76 shots vs 41 for the old steadiest-window plan)


# Optional terms (2026-10-22), all ZERO unless a caller asks for them, so default plans are exactly what they were (premiere-plugin/e2e/candidate_engine_test.py):
ROLE_WEIGHT = 0.4            # a style's preference for a kind of shot (-1..1) is worth up to this: less than the gap between a clean and a shaky stretch
FIRST_LAST_ROLE_BONUS = 0.5  # the first or last shot of a style that wants to open / close on a particular kind of shot (e.g. a hero)
VARIANT_OVERLAP_PENALTY = 1.5  # a stretch another variant of the same edit already uses: alternatives should show different footage
VARIANT_SAME_CLIP_PENALTY = 0.35  # a different stretch of a clip another variant uses
PREFERENCE_WEIGHT = 1.0      # learned per-kind adjustments (post_learning_events, already clipped to +-0.15); only passed in once they clear the adoption gate


def _ramp(sim: float) -> float:
    return min(1.0, max(0.0, (sim - SIM_FLOOR) / (SIM_FULL - SIM_FLOOR)))


def _recency(distance: int) -> float:
    """How much a shot `distance` places away (1 = the neighbour) counts when judging repetition."""
    return RECENCY[distance - 1] if distance <= len(RECENCY) else RECENCY_FLOOR


def look_penalty(scene: str, sig: np.ndarray | None, others: list[tuple[int, np.ndarray | None, str]]) -> tuple[float, float]:
    """(penalty, similarity to the nearest neighbour) of a shot against `others` = [(distance in shots, signature, scene label)]."""
    penalty, nearest, nearest_distance = 0.0, 0.0, 10 ** 6
    for distance, other_sig, other_scene in others:
        sim = post_steady.similarity(sig, other_sig)
        if scene and scene == other_scene:
            sim = max(sim, SAME_SCENE_SIM)
        penalty += _recency(distance) * _ramp(sim)
        if distance < nearest_distance:
            nearest, nearest_distance = sim, distance
    return penalty, nearest


class Picker:
    def __init__(self, clips: list[dict[str, Any]], *, role_weights: dict[str, float] | None = None, diversity: float = 1.0,
                 avoid: dict[int, list[tuple[float, float]]] | None = None, preferences: dict[str, float] | None = None) -> None:
        """`role_weights`: a style's preference per kind of shot (post_style_library); `diversity`: how hard to avoid repeated looks (1.0 = as always);
        `avoid`: stretches other variants of the same edit already use, by file id; `preferences`: learned per-kind adjustments that passed the adoption gate."""
        self.role_weights = role_weights or {}
        self.diversity = diversity
        self.avoid = avoid or {}
        self.preferences = preferences or {}
        self.pool = [c for c in clips if c.get("steady")]
        self.order = {c["file_id"]: i for i, c in enumerate(clips)}
        self.denominator = max(len(clips) - 1, 1)
        self.chosen: list[dict[str, Any]] = []
        self.used: dict[int, list[tuple[float, float]]] = {}
        self._windows: dict[tuple, dict[str, Any]] = {}
        self._event_windows: dict[tuple, list[dict[str, Any]]] = {}

    def _taken(self, clip: dict[str, Any]) -> list[tuple[float, float]]:
        """Stretches of the clip this edit already uses, plus (for a variant) the ones other variants use, so the clip offers different footage."""
        return self.used.get(clip["file_id"], []) + self.avoid.get(clip["file_id"], [])

    def _window(self, clip: dict[str, Any], length: float) -> dict[str, Any]:
        taken = self._taken(clip)
        key = (clip["file_id"], round(length * 8), tuple((round(a, 2), round(b, 2)) for a, b in taken))
        if key not in self._windows:
            self._windows[key] = post_steady.window_for_slot(clip, length, taken)
        return self._windows[key]

    def _candidates(self, clip: dict[str, Any], length: float) -> list[dict[str, Any]]:
        """The windows of `clip` this slot may choose between: its best few described moments, else the single best stretch (_window)."""
        taken = self._taken(clip)
        key = (clip["file_id"], round(length * 8), tuple((round(a, 2), round(b, 2)) for a, b in taken))
        if key not in self._event_windows:
            self._event_windows[key] = post_steady.event_windows(clip, length, taken, EVENT_CANDIDATES) if EVENT_CANDIDATES > 1 else []
        return self._event_windows[key] or [self._window(clip, length)]

    def _signature(self, clip: dict[str, Any], window: dict[str, Any]) -> np.ndarray | None:
        return post_steady.window_signature(clip.get("thumbs"), window["start"], window["duration"])

    def _looks_like(self, clip: dict[str, Any], sig: np.ndarray | None) -> tuple[float, float]:
        """(penalty, similarity to the previous shot) against everything chosen so far."""
        scene = (clip.get("scene") or "").strip().lower()
        return look_penalty(scene, sig, [(back, other["sig"], other["scene"]) for back, other in enumerate(reversed(self.chosen), start=1)])

    def pick(self, length: float, target_position: float, *, exclude: set[int] | None = None, prefer_role: str | None = None) -> dict[str, Any] | None:
        """The best {clip, window, sig, score, parts} for a slot of `length` seconds that falls at `target_position` (0..1) of the edit, or None if no
        clip is long enough. `prefer_role`: this slot would rather be that kind of shot (a style's opening or closing shot)."""
        best: dict[str, Any] | None = None
        for clip in self.pool:
            if (exclude and clip["file_id"] in exclude) or clip["duration"] < length + 0.2:
                continue
            for window in self._candidates(clip, length):
                sig = self._signature(clip, window)
                quality = 1.0 / (1.0 + window["steady"]["score"] / QUALITY_SCALE)
                looks, previous = self._looks_like(clip, sig)
                reuse = REUSE_PENALTY if clip["file_id"] in self.used else 0.0
                overlap = OVERLAP_PENALTY if window.get("overlaps_earlier_use") else 0.0
                overlap += CUT_PENALTY if window["steady"]["cuts"] else 0.0
                position = POSITION_WEIGHT * abs(self.order[clip["file_id"]] / self.denominator - target_position)
                event = EVENT_QUALITY * (window.get("event_punch") or 0) / 10.0
                role = post_candidate_moments.role_of(window)
                role_bonus = ROLE_WEIGHT * self.role_weights.get(role, 0.0) + (FIRST_LAST_ROLE_BONUS if prefer_role and role == prefer_role else 0.0)
                preference = PREFERENCE_WEIGHT * self.preferences.get(role, 0.0)
                variant = 0.0
                if self.avoid.get(clip["file_id"]):
                    s0, s1 = window["start"], window["start"] + window["duration"]
                    variant = VARIANT_OVERLAP_PENALTY if any(s0 < b and s1 > a for a, b in self.avoid[clip["file_id"]]) else VARIANT_SAME_CLIP_PENALTY
                score = quality - self.diversity * DIVERSITY_WEIGHT * looks - reuse - overlap - position + event + role_bonus + preference - variant
                if best is None or score > best["score"]:
                    best = {"clip": clip, "window": window, "sig": sig, "score": score, "similar_to_previous": previous,
                            "parts": {"quality": round(quality, 3), "looks_like_earlier": round(looks, 3), "reused_clip": bool(reuse), "event": round(event, 3),
                                      "role": role, "role_bonus": round(role_bonus, 3), "learned_preference": round(preference, 3), "other_variant_penalty": round(variant, 3),
                                      "position_penalty": round(position, 3)}}
        return best

    def register(self, clip: dict[str, Any], window: dict[str, Any], sig: np.ndarray | None = None) -> float:
        """Records a chosen shot (also the ones placed by another rule, like the establishing clip) and returns how alike it is to the previous shot."""
        sig = sig if sig is not None else self._signature(clip, window)
        previous = 0.0
        scene = (clip.get("scene") or "").strip().lower()
        if self.chosen:
            previous = post_steady.similarity(sig, self.chosen[-1]["sig"])
            if scene and scene == self.chosen[-1]["scene"]:
                previous = max(previous, SAME_SCENE_SIM)
        self.chosen.append({"file_id": clip["file_id"], "sig": sig, "scene": scene})
        self.used.setdefault(clip["file_id"], []).append((window["start"], window["start"] + window["duration"]))
        return previous

    def report(self) -> dict[str, Any]:
        """How repetitive the finished edit is: adjacent shots that look alike, alike pairs anywhere, and how many distinct looks there are."""
        n = len(self.chosen)
        alike = [[False] * n for _ in range(n)]
        adjacent, worst_adjacent, pairs = 0, 0.0, 0
        for i in range(n):
            for j in range(i + 1, n):
                sim = post_steady.similarity(self.chosen[i]["sig"], self.chosen[j]["sig"])
                if self.chosen[i]["scene"] and self.chosen[i]["scene"] == self.chosen[j]["scene"]:
                    sim = max(sim, SAME_SCENE_SIM)
                if sim >= ALIKE:
                    alike[i][j] = alike[j][i] = True
                    pairs += 1
                    if j == i + 1:
                        adjacent += 1
                if j == i + 1:
                    worst_adjacent = max(worst_adjacent, sim)
        seen, looks = set(), 0
        for i in range(n):  # distinct looks = connected groups of alike shots
            if i in seen:
                continue
            looks += 1
            stack = [i]
            while stack:
                k = stack.pop()
                if k in seen:
                    continue
                seen.add(k)
                stack.extend(j for j in range(n) if alike[k][j] and j not in seen)
        return {"alike_neighbours": adjacent, "worst_neighbour_similarity": round(worst_adjacent, 2), "alike_pairs": pairs, "distinct_looks": looks, "shots": n,
                "has_signatures": any(c["sig"] is not None for c in self.chosen)}


# ------------------------------------------------------------------------------------------------------- swaps for the review step
ALTERNATIVES_PER_SHOT = 4


def _plan_infos(plan: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    fps = plan["fps"]
    out = []
    for shot in plan["shots"]:
        clip = by_id.get(shot["file_id"])
        length = shot["duration_frames"] / fps
        out.append({"file_id": shot["file_id"], "start": shot["source_in"], "length": length, "scene": ((clip or {}).get("scene") or "").strip().lower(),
                    "sig": post_steady.window_signature((clip or {}).get("thumbs"), shot["source_in"], length)})
    return out


def _scored_for_slot(picker: Picker, plan: dict[str, Any], infos: list[dict[str, Any]], k: int,
                     also_taken: list[tuple[int, float, float]] | tuple = ()) -> list[dict[str, Any]]:
    """Every clean stretch that could fill shot `k` of the plan, best first, scored like a planned shot against the plan's OTHER shots as they stand (`infos`).
    `also_taken`: (file_id, start, end) stretches this slot must not offer again (what it has already shown in review)."""
    shot = plan["shots"][k]
    n = len(infos)
    length = infos[k]["length"]
    target = (k + 0.5) / n if shot["role"] == "body" else (0.0 if shot["role"] == "opener" else 1.0)
    neighbours = [(abs(j - k), infos[j]["sig"], infos[j]["scene"]) for j in range(n) if j != k]
    used_elsewhere = {infos[j]["file_id"] for j in range(n) if j != k}
    scored: list[dict[str, Any]] = []
    for clip in picker.pool:
        if clip["duration"] < length + 0.2:
            continue
        taken = [(infos[j]["start"], infos[j]["start"] + infos[j]["length"]) for j in range(n) if infos[j]["file_id"] == clip["file_id"] and j != k]
        if clip["file_id"] == infos[k]["file_id"]:
            taken.append((infos[k]["start"], infos[k]["start"] + infos[k]["length"]))  # a different stretch of the same clip, not the current one
        taken += [(a, b) for f, a, b in also_taken if f == clip["file_id"]]
        key = (clip["file_id"], round(length * 8), tuple((round(a, 2), round(b, 2)) for a, b in taken))
        window = picker._windows.get(key) or picker._windows.setdefault(key, post_steady.window_for_slot(clip, length, taken))
        if window.get("overlaps_earlier_use") or window["steady"]["cuts"]:
            continue
        sig = picker._signature(clip, window)
        quality = 1.0 / (1.0 + window["steady"]["score"] / QUALITY_SCALE)
        looks, nearest = look_penalty((clip.get("scene") or "").strip().lower(), sig, neighbours)
        same_clip = clip["file_id"] == infos[k]["file_id"]
        if same_clip and post_steady.similarity(sig, infos[k]["sig"]) >= ALIKE:
            continue  # the same shot again, a quarter second along
        score = (quality - DIVERSITY_WEIGHT * looks - (REUSE_PENALTY if clip["file_id"] in used_elsewhere else 0.0)
                 - POSITION_WEIGHT * abs(picker.order[clip["file_id"]] / picker.denominator - target) + EVENT_QUALITY * (window.get("event_punch") or 0) / 10.0)
        scored.append({"score": score, "clip": clip, "window": window, "sig": sig, "same_clip": same_clip, "nearest": nearest, "quality": quality})
    scored.sort(key=lambda c: -c["score"])
    return scored


def alternatives(plan: dict[str, Any], clips: list[dict[str, Any]], per_shot: int = ALTERNATIVES_PER_SHOT) -> dict[int, list[dict[str, Any]]]:
    """For every shot of a corporate plan, the best OTHER stretches to swap in: the plan's other shots stay as they are, and each candidate is scored like a
    planned shot (clean + exposed, not looking like its neighbours on either side, not a clip used elsewhere, near where it falls in the shoot). The offered set
    is varied: no two alternatives for a shot look alike, and the same clip is offered at most once. {shot index: [candidate]}; shots without a steadiness
    analysis, and opening/closing shots on an establishing clip chosen by the user, get none."""
    post_steady.clear_series_cache()
    picker = Picker(clips)
    by_id = {c["file_id"]: c for c in clips}
    infos = _plan_infos(plan, by_id)
    bookended = bool((plan.get("checks") or {}).get("bookend"))
    result: dict[int, list[dict[str, Any]]] = {}
    for k, shot in enumerate(plan["shots"]):
        if shot["role"] != "body" and bookended:
            result[shot["index"]] = []
            continue
        length = infos[k]["length"]
        scored = _scored_for_slot(picker, plan, infos, k)
        offered: list[dict[str, Any]] = []
        for cand in scored:
            if len(offered) >= per_shot:
                break
            if any(o["clip"]["file_id"] == cand["clip"]["file_id"] or post_steady.similarity(o["sig"], cand["sig"]) >= ALIKE for o in offered):
                continue
            offered.append(cand)
        result[shot["index"]] = [{
            "file_id": c["clip"]["file_id"], "name": c["clip"]["name"], "source_in": c["window"]["start"], "seconds": round(length, 3),
            "origin": "same_clip" if c["same_clip"] else "other_clip", "steady": c["window"]["steady"],
            "tag": "static" if c["window"]["steady"]["static"] else "steady",
            "note": ("another stretch of this clip" if c["same_clip"] else "a different clip") + (", looks different from its neighbours" if c["nearest"] < SIM_FLOOR else "")
                    + (", static footage" if c["window"]["steady"]["static"] else ", steady") + (f" -- {c['window']['source']}" if "event" in c["window"]["source"] else ""),
        } for c in offered]
    post_steady.clear_series_cache()  # the per-clip arrays were only needed while scoring
    return result


def regenerate(plan: dict[str, Any], clips: list[dict[str, Any]], indices: list[int], seen: dict[int, list[tuple[int, float, float]]] | None = None) -> dict[int, dict[str, Any]]:
    """A fresh pick for each shot in `indices`, in timeline order, scored exactly like a review swap (_scored_for_slot) against the plan's other shots; each new
    pick becomes the neighbour the next one is judged against, so a regenerated run of shots is varied within itself. `seen`: per shot, every (file_id, start, end)
    it has already shown, never offered again (so pressing Regenerate twice moves on instead of swinging back). {index: {file_id, name, source_in, seconds,
    window, score}}; a shot with nothing new left is left out. Pure: the plan is not changed."""
    seen = seen or {}
    post_steady.clear_series_cache()
    picker = Picker(clips)
    by_id = {c["file_id"]: c for c in clips}
    infos = _plan_infos(plan, by_id)
    position = {s["index"]: k for k, s in enumerate(plan["shots"])}
    out: dict[int, dict[str, Any]] = {}
    for index in sorted((i for i in indices if i in position), key=position.get):
        k = position[index]
        scored = _scored_for_slot(picker, plan, infos, k, also_taken=seen.get(index, []))
        if not scored:
            continue
        best = scored[0]
        clip, window = best["clip"], best["window"]
        out[index] = {"file_id": clip["file_id"], "name": clip["name"], "path": clip.get("path"), "source_in": window["start"], "seconds": round(infos[k]["length"], 3),
                      "window": window, "score": round(best["score"], 4)}
        infos[k] = {**infos[k], "file_id": clip["file_id"], "start": window["start"], "scene": (clip.get("scene") or "").strip().lower(), "sig": best["sig"]}
    post_steady.clear_series_cache()
    return out


def valid_alternative(plan: dict[str, Any], clips: list[dict[str, Any]], slot_index: int, file_id: int, source_in: float) -> dict[str, Any] | None:
    """Whether (file_id, source_in) is a usable stretch for a slot even if the review no longer lists it (its list can change after another swap): the clip is the
    job's own, long enough, the stretch lies inside it and has no cut. Returns the stretch's steadiness record, or None."""
    shot = next((s for s in plan["shots"] if s["index"] == slot_index), None)
    clip = next((c for c in clips if c["file_id"] == file_id), None)
    if shot is None or clip is None or not clip.get("steady"):
        return None
    length = shot["duration_frames"] / plan["fps"]
    seconds = min(clip["duration"], clip["steady"]["seconds"])
    if source_in < 0 or source_in + length > seconds - 0.02:
        return None
    window = post_steady.score_window(clip["steady"], source_in, length)
    post_steady.clear_series_cache()
    return None if window["cuts"] else window
