"""
POST (2026-10-06) -- per-frame COMPOSITION ratings across a clip.

Replaces post_shot_intent.py. The steadiest-and-sharpest picker fixed "it took the
worst parts" but not what Josh actually cares about, which his own hand-corrected
cuts of the first two clips showed: he cuts on the frames where the subject is
COMPLETE and well framed (in clip 2 the overhead sign is fully in view; a few
frames later it is cropped at the edges and he stops), in a SHORT shot (1.4s and
2.2s), usually from the OPENING of the clip. Steadiness measured the wrong thing.

One Claude call per clip: stills sampled across the clip, each labelled with its
time, each rated 0-10 as a usable b-roll frame. post_media turns the ratings into
a short shot (the contiguous run around the best frame), combined with a mild
steadiness penalty and a mild preference for the start of the clip.

Deliberately separate from post_vision_agent.py (a purely descriptive tool whose
boundaries forbid judging intent or making editing calls). This one is advisory
and only decides which part of a clip reaches the rough cut; it never edits,
deletes or modifies footage. Costs real Claude API tokens (one call per clip);
callers must handle failure by falling back and saying so, never silently.
"""

import base64
import json
import re
from typing import Any

class VisionUnavailableError(RuntimeError):
    """Claude vision can't be used at all right now (credit balance exhausted, key
    rejected) -- unlike a one-off failed call. Callers must stop and report it:
    quietly substituting a cruder picker for a whole batch of clips hides a
    problem the user has to fix."""


def _is_systemic_failure(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in (401, 403) or "credit balance" in str(exc).lower()


COMPOSITION_SYSTEM_PROMPT = """You are helping a video editor choose the best short shot from a camera clip for a rough cut.

You will see still frames from ONE clip, each labelled with its time in seconds. Rate EACH frame 0-10 as a usable b-roll frame, judging only what is visible:
- First decide what the MAIN subject is (the hero product, display, sign, person, performance or venue the camera is clearly about). It must be COMPLETE and clearly the point of the shot: not cropped by the frame edges, its own text fully in view, nothing important half out of frame. Minor background items (a small stand, a sign on the periphery, a passer-by, a pillar) being cut off by the frame edge is NOT a flaw if the main subject is intact.
- Subject presence: the main subject should be LARGE and bold in the frame, taking a good share of it. A wider frame where the whole subject is visible but small, with a lot of empty floor, ceiling or background around it, is WEAKER than a closer frame where the subject fills the frame -- even if the closer frame trims a little of the subject's periphery, as long as its key parts (face, main logo or text) are intact.
- Deliberate framing: the main subject sits comfortably inside the frame, centred or on a deliberate third, level (not tilted or leaning). A subject that has drifted toward an edge, or a camera caught mid-swing between subjects, is a flaw.
- Unobstructed and in focus.
Score 9-10 only for a frame you would happily use as-is. 6-8 = usable but flawed (subject partly cropped, slightly tilted, a bit off-centre). 0-5 = not usable (accidental, awkward, subject cut off or missing, obstructed, blurred, camera pointing at floor/ceiling, a body or bag filling the frame).
Compare frames within the clip: a frame where the subject is complete scores higher than a neighbour where the camera has drifted and part of it is cropped. Judge each frame on what it shows, not on what you imagine happens next.

Reply with ONLY JSON: {"frames":[{"t":1.5,"score":8,"subject":"short description","issue":null}, ...]} -- one entry per frame, "t" exactly as labelled, "subject" at most 8 words, "issue" a short reason whenever the score is below 8."""


def parse_composition_reply(text: str, times: list[float]) -> dict[float, dict] | None:
    """{time: {"score": float, "subject": str, "issue": str|None}} for every frame
    the model rated validly (time matched to the nearest labelled time), or None
    if the reply is unusable. A frame the model skipped is absent."""
    data = None
    # The prompt asks for {"frames": [...]}, but a bare [...] is an easy slip: accept both.
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                break
            except json.JSONDecodeError:
                continue
    if data is None:
        return None
    frames = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(frames, list):
        return None
    rated: dict[float, dict] = {}
    for item in frames:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t"))
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        if not times or not (0.0 <= score <= 10.0):
            continue
        nearest = min(times, key=lambda x: abs(x - t))
        if abs(nearest - t) > 0.26:
            continue
        issue = item.get("issue")
        rated[nearest] = {
            "score": score,
            "subject": str(item.get("subject") or "")[:80],
            "issue": str(issue)[:120] if issue else None,
        }
    return rated or None


async def rate_frames(
    client: Any, model: str, frames: list[tuple[float, bytes]], context: str
) -> dict[float, dict] | None:
    """frames: [(time_seconds, jpeg_bytes), ...]. One call rating all of a clip's
    sampled frames. Returns parse_composition_reply's mapping, or None on any API
    or parsing failure (the caller falls back and reports it)."""
    if not frames:
        return {}
    times = [t for t, _ in frames]
    content: list[dict] = []
    for t, jpeg in frames:
        content.append({"type": "text", "text": f"t={t}s"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")},
        })
    content.append({"type": "text", "text": f"{context}\nRate every frame as instructed."})
    try:
        response = await client.messages.create(
            model=model, max_tokens=3500, system=COMPOSITION_SYSTEM_PROMPT,  # no temperature: this model rejects it (HTTP 400)
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        print(f"[post_shot_composition] vision call failed: {type(exc).__name__}: {str(exc)[:200]}")
        if _is_systemic_failure(exc):
            raise VisionUnavailableError(
                "Claude vision is unavailable (API credit balance too low, or the API key was rejected). "
                "Fix that, then run Detect Highlights again."
            ) from exc
        return None
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    rated = parse_composition_reply(text, times)
    if rated is None:
        print(f"[post_shot_composition] unusable reply: {text[:200]!r}")
    return rated
