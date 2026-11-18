"""POST shot roles for the Cinematic Reel Autopilot, phase 3 step 1 (2026-11-17).

The Rabit Haus event recap (post_style_library "rabit-haus-event-recap") runs in sections: open on the main person, then the
place, the people, the details, the main moment and a closing wide. To fill those sections the planner needs to know which
moments are which. Describe clips (post_moments) already stored, for every clip, a short scene label and up to five moments
with a few words each ("whip pan off gift card", "staff team applauding"). This module sorts those moments into roles with
ONE text-only Claude call per shoot: no frames are sent, nothing is re-watched.

Roles:
  place        - wides of the venue, the outside, signage that says where we are
  person       - people: faces, arrivals, reactions, groups, someone doing something human
  detail       - close-ups of things: products, hands, shoes, bags, stickers, decor, food
  movement     - the camera move IS the shot (whip pans, orbits, fly-throughs) and it isn't clearly one of the above
  main_moment  - THE event moments (the ribbon cutting, the performance, the DJ, the big reveal): one to three clips' worth

The result is cached as shot_roles.json next to the clip descriptions, with the model, prompt version and what it cost.
It is read by the planner later; it never changes the descriptions themselves. Josh checks the lists before anything uses them.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.post_moments import load_moments, record_usage, usd
from app.post_shot_composition import VisionUnavailableError, _is_systemic_failure

ROLES = ("place", "person", "detail", "movement", "main_moment")
ROLES_FILE = "shot_roles.json"
PROMPT_VERSION = "roles-1"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are an editor preparing a 30-40 second event recap in the manner of Rabit Haus: open on the main person, then the PLACE, the PEOPLE, the DETAILS, the MAIN MOMENT, and a closing wide.
You get the written descriptions of every clip from one shoot (a short scene label, whether people are in it, and its moments, each with an id and a few words). You do not see the footage.
Give EVERY moment exactly one role:
- place: wide shots of the venue or location, the outside, signage or a storefront that says where we are
- person: people are the subject: faces, arrivals, reactions, a group, someone walking, browsing, greeting, dancing casually
- detail: a close-up of a thing: product, shoe, bag, sticker, hand holding something, display, decor, food
- movement: the camera move itself is the point (whip pan, orbit, fly-through, fast push) and the subject isn't clearly a place, person or detail
- main_moment: one of the defining moments of the event (ribbon cutting, performance, DJ set, speech, a big reveal or celebration). Use it sparingly: only the moments that are THE event.
Judge from the words only. When a moment could be two roles, pick the one an editor would file it under for this recap.
Also name the clips that hold the event's main moments (one to three clips), best first.
Reply with ONLY JSON: {"roles":{"<moment id>":"place|person|detail|movement|main_moment", ...},"main_clips":["<clip id>", ...],"note":"one sentence on anything uncertain"}"""


class RolesError(Exception):
    pass


def roles_path(edit_dir: Path) -> Path:
    return edit_dir / ROLES_FILE


def load_roles(edit_dir: Path) -> dict[str, Any] | None:
    path = roles_path(edit_dir)
    return json.loads(path.read_text()) if path.exists() else None


def moment_id(clip_key: str, index: int) -> str:
    return f"{clip_key}.{index}"


def describe_for_prompt(moments: dict[str, Any]) -> tuple[str, list[str]]:
    """The user message (one line per clip, its moments indented) and the list of every moment id in it."""
    lines, ids = [], []
    for key in sorted(moments, key=lambda k: (str(moments[k].get("name") or ""), k)):
        rec = moments[key]
        if not isinstance(rec, dict):
            continue
        lines.append(f"clip {key} | {rec.get('scene') or '(no label)'} | people: {'yes' if rec.get('people') else 'no'}")
        for i, ev in enumerate(rec.get("events") or []):
            mid = moment_id(key, i)
            ids.append(mid)
            lines.append(f"  {mid} [{ev.get('kind', '?')}] {ev.get('what') or ''}".rstrip())
    return "\n".join(lines), ids


def parse_reply(text: str, ids: list[str], clip_keys: set[str]) -> dict[str, Any]:
    """Validates the model's JSON. Unknown ids and roles are dropped; moments it skipped are listed as missing (never guessed)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise RolesError("Claude's reply had no JSON in it.")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise RolesError(f"Claude's reply wasn't valid JSON ({exc}).") from exc
    raw = data.get("roles") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise RolesError("Claude's reply had no roles.")
    wanted = set(ids)
    roles = {mid: role for mid, role in raw.items() if mid in wanted and role in ROLES}
    main = [c for c in (data.get("main_clips") or []) if isinstance(c, str) and c in clip_keys][:3]
    return {"roles": roles, "main_clips": main, "missing": [m for m in ids if m not in roles], "note": str(data.get("note") or "")[:300]}


def summarise(result: dict[str, Any], moments: dict[str, Any]) -> dict[str, Any]:
    """Counts per role and, per role, the clips it covers with their words -- what Josh reads to check the sorting."""
    by_role: dict[str, list[dict[str, Any]]] = {r: [] for r in ROLES}
    for mid, role in result["roles"].items():
        key, idx = mid.rsplit(".", 1)
        rec = moments.get(key) or {}
        events = rec.get("events") or []
        ev = events[int(idx)] if idx.isdigit() and int(idx) < len(events) else {}
        by_role[role].append({"moment": mid, "clip": rec.get("name") or key, "t": ev.get("t"), "what": ev.get("what") or ""})
    for role in by_role:
        by_role[role].sort(key=lambda x: (x["clip"], x["t"] or 0))
    return {"counts": {r: len(v) for r, v in by_role.items()}, "by_role": by_role,
            "main_clips": [(moments.get(k) or {}).get("name") or k for k in result["main_clips"]]}


async def sort_roles(client: Any, edit_dir: Path, *, job_id: int, model: str = DEFAULT_MODEL, moments: dict[str, Any] | None = None,
                     save: bool = True) -> dict[str, Any]:
    """One Claude call: every described moment of the job gets a role. Saves shot_roles.json and logs the real cost (unless save=False)."""
    moments = moments if moments is not None else load_moments(edit_dir)
    if not moments:
        raise RolesError("This shoot has no clip descriptions yet. Run Describe clips first.")
    text, ids = describe_for_prompt(moments)
    if not ids:
        raise RolesError("The clip descriptions have no moments to sort.")
    try:
        response = await client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, output_config={"effort": "low"},
                                                messages=[{"role": "user", "content": text}])
    except Exception as exc:
        if _is_systemic_failure(exc):
            raise VisionUnavailableError("Claude is unavailable (API credit balance too low, or the API key was rejected).") from exc
        raise RolesError(f"Couldn't reach Claude ({type(exc).__name__}). Nothing was saved; try again.") from exc
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise RolesError("Claude's answer was cut off (too many moments for one reply). Nothing was saved.")
    reply = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
    result = parse_reply(reply, ids, set(moments))
    usage = getattr(response, "usage", None)
    tokens_in, tokens_out = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
    cost, _basis = usd(model, tokens_in, tokens_out)
    record = {"made": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "prompt": PROMPT_VERSION, "moments_sorted": len(result["roles"]),
              "moments_total": len(ids), "usd": cost, "input_tokens": tokens_in, "output_tokens": tokens_out, **result}
    if save:
        edit_dir.mkdir(parents=True, exist_ok=True)
        roles_path(edit_dir).write_text(json.dumps(record, indent=1))
        record_usage(edit_dir, job_id=job_id, operation="sort_shot_roles", model=model,
                     usage={"calls": 1, "in": tokens_in, "out": tokens_out}, extra={"moments": len(ids)})
    return record


# --- For the button (2026-11-18): what the sorting would cost, and whether a shoot's roles are up to date ------------------------------
CHARS_PER_INPUT_TOKEN = 2.2    # measured on the JD Midlands run: 31,777 characters of descriptions -> 14,042 input tokens
OUTPUT_TOKENS_PER_MOMENT = 9.2  # same run: 3,528 output tokens for 390 moments


def estimate(moments: dict[str, Any], model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """The cost of sorting this shoot's moments, from the measured ratios above (an estimate: the bill is what the API reports)."""
    text, ids = describe_for_prompt(moments)
    tokens_in = round((len(SYSTEM_PROMPT) + len(text)) / CHARS_PER_INPUT_TOKEN)
    tokens_out = round(OUTPUT_TOKENS_PER_MOMENT * len(ids)) + 80
    cost, basis = usd(model, tokens_in, tokens_out)
    return {"moments": len(ids), "clips": sum(1 for v in moments.values() if isinstance(v, dict) and v.get("events")),
            "input_tokens": tokens_in, "output_tokens": tokens_out, "usd": round(cost, 3), "model": model, "basis": basis}


def status(edit_dir: Path, moments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether the shoot's moments have been sorted, and whether that sorting still covers every described moment."""
    moments = moments if moments is not None else load_moments(edit_dir)
    _text, ids = describe_for_prompt(moments)
    saved = load_roles(edit_dir)
    out: dict[str, Any] = {"described_moments": len(ids), "estimate": estimate(moments) if ids else None, "sorted": False}
    if saved:
        roles = saved.get("roles") or {}
        unsorted = [m for m in ids if m not in roles]
        out.update({"sorted": True, "made": saved.get("made"), "model": saved.get("model"), "usd": saved.get("usd"),
                    "moments_sorted": len(roles), "unsorted_now": len(unsorted), "up_to_date": not unsorted,
                    **{k: v for k, v in summarise(saved, moments).items() if k in ("counts", "main_clips")}})
    return out
