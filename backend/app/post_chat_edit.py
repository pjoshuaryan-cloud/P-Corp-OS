"""POST "Describe an edit" (Cinematic Reel Autopilot phase 6a, 2026-11-18): one sentence in the POST tab becomes a planned edit.

    "Rabit Haus recap of the JD shoot, 3 2 1, 35 seconds, up to $1"

  1. understand(): Claude Haiku turns the sentence into a request -- which shoot, which style, which song, how long, the spending cap -- choosing ONLY
     from the shoots and styles listed to it (an id or slug it invents is dropped, never guessed). Well under a cent.
  2. build_card(): what doing it would take and cost, step by step: describe the clips that have no description (Claude, about 1 cent a clip), sort the
     moments into shot roles if the style is built in sections (Claude, a few cents), plan (no Claude call). Shown to Josh before anything is spent.
  3. Run (started by his Go): the steps in order, each one only if the money spent so far plus its estimate stays inside the cap; the run stops at the
     first step that would go over, and says so. The plan step uses the planner the app already has (a saved reference style: plan_for_job; a library
     style: a variant set whose first variant becomes the plan, so the previous plan is archived and can be restored).
Building in Premiere stays a click on Build My Edit: nothing here starts Premiere. Desktop-triggered only, never reachable from Frank.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

CHAT_MODEL = "claude-haiku-5-5"
DEFAULT_CAP_USD = 1.0
MAX_CAP_USD = 20.0
MIN_SECONDS, MAX_SECONDS = 15, 180
MOMENTS_PER_NEW_CLIP = 5   # Describe finds up to five moments a clip; used to scale the shot-roles estimate for clips not described yet

SYSTEM_PROMPT = """You turn one sentence from a video editor into an edit request for his own planning tool.
You get the shoots he has (id, name, date) and the edit styles he can use (slug, name, what it is). Pick ONLY from those lists.
Reply with ONLY JSON:
{"job_id": <a listed shoot id, or null if you can't tell which>, "style": "<a listed style slug, or null>", "song": "<words he used for the song, or null>",
 "seconds": <length in seconds, or null>, "usd_cap": <the most he said he'll spend in US dollars, or null>, "unclear": "<one short sentence on anything you couldn't tell, or empty>"}
"The JD shoot" means the shoot whose name mentions JD; "latest" means the newest. A length like "half a minute" is 30. Don't invent a cap he didn't give.
"song" is any words that could name a track, even numbers or a short title ("3 2 1", "the Drake one"); the tool matches them to his files.
"unclear" is ONLY for something he said that you couldn't match. Leave it empty for things he didn't mention (a missing song, length or cap is fine: the tool has defaults)."""


class ChatEditError(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def style_choices(reference_cards: list[dict[str, Any]], library_styles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every style the box may pick: the saved reference styles (Plan Edit's list) and the buildable library styles (the variants page's)."""
    out = [{"slug": c["slug"], "name": c.get("friendly_title") or c.get("title") or c["slug"], "kind": "reference", "about": c.get("blurb") or c.get("description") or "",
            "sections": False} for c in reference_cards]
    taken = {s["slug"] for s in out}
    out += [{"slug": s["slug"], "name": s["name"], "kind": "library", "about": s.get("intent", "")[:160], "sections": bool(s.get("sections"))}
            for s in library_styles if s.get("buildable") and s["slug"] not in taken]
    return out


def prompt_for(text: str, jobs: list[dict[str, Any]], styles: list[dict[str, Any]]) -> str:
    lines = ["Shoots:"] + [f"- {j['id']}: {j.get('shoot_name') or '?'} ({str(j.get('created_at') or '')[:10]})" for j in jobs]
    lines += ["", "Styles:"] + [f"- {s['slug']}: {s['name']}" + (f" -- {s['about']}" if s.get("about") else "") for s in styles]
    lines += ["", f"His sentence: {text.strip()}"]
    return "\n".join(lines)


def parse_reply(reply: str, jobs: list[dict[str, Any]], styles: list[dict[str, Any]]) -> dict[str, Any]:
    """Keeps only what is valid: a listed job id, a listed style, a length in range, a cap in range (else the $1 default)."""
    match = re.search(r"\{.*\}", reply or "", re.S)
    if not match:
        raise ChatEditError("Couldn't understand that. Try naming the shoot, the style and the length.")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise ChatEditError("Couldn't understand that. Try naming the shoot, the style and the length.") from exc
    ids = {int(j["id"]) for j in jobs}
    slugs = {s["slug"] for s in styles}
    job_id = data.get("job_id")
    job_id = int(job_id) if isinstance(job_id, (int, float)) and int(job_id) in ids else None
    style = data.get("style") if data.get("style") in slugs else None
    seconds = data.get("seconds")
    seconds = float(seconds) if isinstance(seconds, (int, float)) and MIN_SECONDS <= seconds <= MAX_SECONDS else None
    cap = data.get("usd_cap")
    cap_given = isinstance(cap, (int, float)) and 0 < cap <= MAX_CAP_USD
    song = data.get("song") if isinstance(data.get("song"), str) and data.get("song").strip() else None
    return {"job_id": job_id, "style": style, "song": song, "seconds": seconds, "usd_cap": float(cap) if cap_given else DEFAULT_CAP_USD,
            "cap_given": cap_given, "unclear": str(data.get("unclear") or "")[:200]}


async def understand(client: Any, text: str, jobs: list[dict[str, Any]], styles: list[dict[str, Any]]) -> dict[str, Any]:
    """One Haiku call. Returns the parsed request plus what the call really used."""
    if not text.strip():
        raise ChatEditError("Type what you want, for example: Rabit Haus recap of the JD shoot, 35 seconds.")
    if not jobs:
        raise ChatEditError("There are no shoots ready to plan yet.")
    try:
        response = await client.messages.create(model=CHAT_MODEL, max_tokens=300, thinking={"type": "disabled"}, output_config={"effort": "low"},
                                                system=SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt_for(text, jobs, styles)}])
    except Exception as exc:
        from app.post_shot_composition import VisionUnavailableError, _is_systemic_failure
        if _is_systemic_failure(exc):
            raise VisionUnavailableError("Claude is unavailable (API credit balance too low, or the API key was rejected).") from exc
        raise ChatEditError(f"Couldn't reach Claude ({type(exc).__name__}). Try again in a moment.") from exc
    if getattr(response, "stop_reason", None) == "refusal":
        raise ChatEditError("Claude wouldn't read that request. Try rewording it.")
    reply = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
    request = parse_reply(reply, jobs, styles)
    usage = getattr(response, "usage", None)
    request["usage"] = {"calls": 1, "in": int(getattr(usage, "input_tokens", 0) or 0), "out": int(getattr(usage, "output_tokens", 0) or 0)}
    return request


def resolve_song(songs: list[dict[str, Any]], hint: str | None) -> dict[str, Any] | None:
    """The job's song his words name (every word of the hint in the file name), else the newest song (what Plan Edit uses by default)."""
    if not songs:
        return None
    words = _norm(hint).split() if hint else []
    if words:
        for s in songs:
            name = _norm(s["name"])
            if all(w in name.split() or w in name for w in words):
                return {**s, "matched": True}
    return {**songs[0], "matched": False}


def build_card(*, request: dict[str, Any], job: dict[str, Any], style: dict[str, Any], song: dict[str, Any] | None, describe: dict[str, Any],
               roles: dict[str, Any] | None) -> dict[str, Any]:
    """The steps and their estimated cost. `describe` is post_edit_plan.describe_status; `roles` is post_roles.status (only for a sectioned style)."""
    steps: list[dict[str, Any]] = []
    missing = int(describe.get("missing") or 0)
    if missing:
        est = describe.get("estimate") or {}
        steps.append({"step": "describe", "what": f"Describe the {missing} clip(s) that have no description yet", "usd": float(est.get("usd_list_price", est.get("usd_at_most", 0.0)) or 0.0),
                      "clips": missing, "claude": True})
    if style.get("sections"):
        if roles is None or not roles.get("sorted") or not roles.get("up_to_date") or missing:
            current = (roles or {}).get("estimate") or {}
            described = int((roles or {}).get("described_moments") or 0)
            expected = described + MOMENTS_PER_NEW_CLIP * missing
            usd = float(current.get("usd") or 0.0) * (expected / described) if described else 0.0007 * expected
            steps.append({"step": "sort_roles", "what": f"Sort about {expected} moments into shot roles (place, people, details, main moment)", "usd": round(usd, 3), "claude": True})
    steps.append({"step": "plan", "what": f"Plan a {style['name']} edit" + (f" of {request['seconds']:g} s" if request.get("seconds") else "")
                  + (f" to {song['name']}" if song else ""), "usd": 0.0, "claude": False})
    total = round(sum(s["usd"] for s in steps), 3)
    warnings = []
    if song is None:
        warnings.append("This shoot has no song in its music folder yet: put one there first.")
    elif request.get("song") and not song.get("matched"):
        warnings.append(f"No song matched \"{request['song']}\", so it uses the newest: {song['name']}.")
    if request.get("unclear"):
        warnings.append(request["unclear"])
    return {"job": {"id": job["id"], "shoot_name": job.get("shoot_name")}, "style": {"slug": style["slug"], "name": style["name"], "kind": style["kind"]},
            "song": song, "seconds": request.get("seconds"), "usd_cap": request["usd_cap"], "steps": steps, "usd_total": total,
            "over_cap": total > request["usd_cap"], "ready": song is not None and total <= request["usd_cap"], "warnings": warnings}


# --- the run (in this process; one at a time) -----------------------------------------------------------------------------------------------
_RUN: dict[str, Any] = {}

StepRunner = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]   # (step, card) -> {"usd": spent, "note": str, ...}


def run_state() -> dict[str, Any] | None:
    return {k: v for k, v in _RUN.items() if k != "task"} if _RUN else None


def start(card: dict[str, Any], runners: dict[str, StepRunner]) -> dict[str, Any]:
    """Runs the card's steps in the background, each only if what's been spent plus its estimate stays inside the cap. `runners` maps a step name to the
    coroutine that does it (main.py wires them to the real describe, sort and plan code)."""
    if _RUN.get("state") == "running":
        raise ChatEditError("An edit is already being prepared. Wait for it to finish.")
    _RUN.clear()
    _RUN.update({"state": "running", "card": card, "steps": [dict(s, state="waiting") for s in card["steps"]], "spent_usd": 0.0, "message": None, "result": None,
                 "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished_at": None})

    async def go() -> None:
        try:
            for step in _RUN["steps"]:
                if _RUN["spent_usd"] + step["usd"] > card["usd_cap"] + 1e-9:
                    step["state"] = "skipped"
                    _RUN["state"] = "stopped"
                    _RUN["message"] = (f"Stopped before \"{step['what']}\": it would take the spend to about ${_RUN['spent_usd'] + step['usd']:.2f}, "
                                       f"over your ${card['usd_cap']:g} cap. Nothing past this point was done.")
                    return
                step["state"] = "running"
                out = await runners[step["step"]](step, card)
                step["state"] = "done"
                step["spent_usd"] = round(float(out.get("usd", 0.0)), 4)
                step["note"] = out.get("note")
                _RUN["spent_usd"] = round(_RUN["spent_usd"] + step["spent_usd"], 4)
                if out.get("result") is not None:
                    _RUN["result"] = out["result"]
            _RUN["state"] = "done"
            _RUN["message"] = f"Planned. Spent ${_RUN['spent_usd']:.3f} with Claude. Review it, then click Build My Edit in Premiere."
        except Exception as exc:   # a background task never dies silently
            for step in _RUN["steps"]:
                if step["state"] == "running":
                    step["state"] = "failed"
            _RUN["state"] = "failed"
            _RUN["message"] = str(exc)[:300] or type(exc).__name__
        finally:
            _RUN["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    _RUN["task"] = asyncio.get_running_loop().create_task(go())
    return run_state()
