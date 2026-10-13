"""
POST (2026-10-08) -- per-clip "moments": where something HAPPENS in a clip, and what the clip shows.

Why this exists: tests against 41+ moments Josh cut by hand showed that composition, steadiness, plain
motion and even Claude's idea of a "punchy moment" do NOT reproduce which instant of a clip he chose
(all at chance) -- a handheld clip usually holds several comparable events and he took one of them.
So the goal here is NOT to guess his pick. It is to make sure a planned shot is an acceptable EVENT (a
gesture, reaction, camera move, reveal or hero shot) and not a dead moment, to know what each clip shows
so an edit can vary its scenes, and to offer several candidates per clip so he can swap.

One Claude call per clip (frames every 0.5-1.0 s, small). Results are cached in a JSON file next to the
edit plans (no database change). A systemic failure (credits gone, key rejected) stops the run loudly
via VisionUnavailableError instead of quietly degrading.
"""

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from app.post_media import _extract_still
from app.post_shot_composition import VisionUnavailableError, _is_systemic_failure
from app.ssd_guard import DriveNotResponding, on_drive

MOMENTS_SYSTEM_PROMPT = """You are an editor cutting a fast, music-driven social reel from handheld camera clips. You will see still frames from ONE clip, each labelled with its time in seconds.
Find the moments that would make a good punchy shot of 0.3-1.0 seconds:
- a distinct HUMAN ACTION or reaction: a clap, a laugh, a hug, holding a product up to the camera, a dance move, turning to the camera, walking toward a location, reaching for something
- a CAMERA MOVE or reveal: a whip pan, tilting up to a sign, pulling back to reveal a scene, a spin
- a clear HERO / BRANDING moment: a logo or key display clear and readable, confetti, a posed group
Prefer the instant an action BEGINS or PEAKS. A moment where nothing happens (people just standing, a static hold) is weak even if it is well framed.
Reply with ONLY JSON: {"scene":"3-6 word label of what this clip shows","people":true|false,"events":[{"t":seconds,"kind":"action|reaction|camera_move|reveal|hero","punch":0-10,"what":"max 10 words"}]} -- at most 5 events, best first, "t" exactly as labelled or between two labels."""

MAX_STILLS = 40
EVENT_KINDS = ("action", "reaction", "camera_move", "reveal", "hero")


def moments_path(edit_dir: Path) -> Path:
    return edit_dir / "moments.json"


def load_moments(edit_dir: Path) -> dict[str, Any]:
    """{file_id(str): {"name", "duration", "scene", "people", "events":[...]}} -- {} if never probed."""
    path = moments_path(edit_dir)
    return json.loads(path.read_text()) if path.exists() else {}


def save_moments(edit_dir: Path, moments: dict[str, Any]) -> None:
    edit_dir.mkdir(parents=True, exist_ok=True)
    moments_path(edit_dir).write_text(json.dumps(moments, indent=1))


def parse_moments_reply(text: str, duration: float) -> dict[str, Any] | None:
    """{"scene", "people", "events":[{"t","kind","punch","what"}]} with events clamped to the clip and sorted
    best first, or None if the reply is unusable."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return None
    events = []
    for e in data["events"]:
        if not isinstance(e, dict):
            continue
        try:
            t, punch = float(e.get("t")), float(e.get("punch"))
        except (TypeError, ValueError):
            continue
        if not (0.0 <= t <= duration + 0.5) or not (0.0 <= punch <= 10.0):
            continue
        kind = str(e.get("kind") or "")
        events.append({"t": round(min(t, duration), 2), "kind": kind if kind in EVENT_KINDS else "action", "punch": punch, "what": str(e.get("what") or "")[:80]})
    if not events:
        return None
    events.sort(key=lambda e: -e["punch"])
    return {"scene": str(data.get("scene") or "")[:60], "people": bool(data.get("people")), "events": events[:5]}


def _frame_times(duration: float) -> list[float]:
    step = 0.5 if duration <= 20 else (0.75 if duration <= 30 else 1.0)
    times, t = [], 0.25
    while t < duration - 0.2 and len(times) < MAX_STILLS:
        times.append(round(t, 2))
        t += step
    return times


async def find_moments(client: Any, model: str, path: str, duration: float, usage: dict | None = None) -> dict[str, Any] | None:
    """One clip's moments, or None if the clip couldn't be read/understood. Raises VisionUnavailableError when
    the API can't be used at all (credits, key). `usage` (optional) accumulates real token counts."""
    times = _frame_times(duration)
    limiter = asyncio.Semaphore(6)
    stills = await asyncio.gather(*(_extract_still(path, t, limiter) for t in times))
    content: list[dict] = []
    for t, jpeg in zip(times, stills):
        if jpeg:
            content += [{"type": "text", "text": f"t={t}s"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}}]
    if not content:
        return None
    content.append({"type": "text", "text": "Find the punchy moments as instructed."})
    try:
        response = await client.messages.create(model=model, max_tokens=900, system=MOMENTS_SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
    except Exception as exc:
        print(f"[post_moments] vision call failed: {type(exc).__name__}: {str(exc)[:200]}")
        if _is_systemic_failure(exc):
            raise VisionUnavailableError("Claude vision is unavailable (API credit balance too low, or the API key was rejected). Fix that, then run this again.") from exc
        return None
    if usage is not None:
        usage["in"] = usage.get("in", 0) + response.usage.input_tokens
        usage["out"] = usage.get("out", 0) + response.usage.output_tokens
        usage["calls"] = usage.get("calls", 0) + 1
    return parse_moments_reply("".join(b.text for b in response.content if getattr(b, "type", "") == "text"), duration)


def missing_clips(clips: list[dict], moments: dict[str, Any]) -> list[dict]:
    """Clips with no cached description (or one made for a different version of the file), in the order given."""
    return [c for c in clips if str(c["file_id"]) not in moments or abs(moments[str(c["file_id"])].get("duration", 0) - c["duration"]) > 0.05]


async def probe_missing(
    client: Any, model: str, clips: list[dict], edit_dir: Path, *, max_calls: int, concurrency: int = 3,
    on_result: Callable[[str, bool], None] | None = None, should_stop: Callable[[], bool] | None = None, usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Probes every clip not already cached (and whose duration hasn't changed), saving after each result so an
    interrupted run keeps its work. Stops after `max_calls` calls (a hard cost cap). `on_result(name, ok)` is told as
    each clip finishes; `should_stop()` is checked before each clip starts (calls already in flight finish). Returns a
    run report."""
    moments = await on_drive(load_moments, edit_dir)
    todo = missing_clips(clips, moments)[:max_calls]
    usage = usage if usage is not None else {}
    sem = asyncio.Semaphore(concurrency)
    failed: list[str] = []
    fatal: list[VisionUnavailableError] = []
    drive_down: list[DriveNotResponding] = []
    done = [0]
    stopped = [False]

    def halted() -> bool:
        if should_stop is not None and should_stop():
            stopped[0] = True
        return bool(fatal) or bool(drive_down) or stopped[0]

    async def one(clip: dict) -> None:
        if halted():
            return
        # The slot is held through the save too, so at most `concurrency` clips are ever in flight (sent to Claude and not
        # yet saved): if the drive stops answering, no more clips are sent behind the ones already waiting to save.
        async with sem:
            if halted():
                return
            try:
                result = await find_moments(client, model, clip["path"], clip["duration"], usage)
            except VisionUnavailableError as exc:
                fatal.append(exc)
                return
            if result is None:
                failed.append(clip["name"])
                if on_result: on_result(clip["name"], False)
                return
            moments[str(clip["file_id"])] = {"name": clip["name"], "duration": clip["duration"], **result}
            try:
                await on_drive(save_moments, edit_dir, moments, writing=True)
            except DriveNotResponding as exc:
                drive_down.append(exc)  # stop sending clips to Claude: they couldn't be saved
                return
            done[0] += 1
        if on_result: on_result(clip["name"], True)

    await asyncio.gather(*(one(c) for c in todo))
    stopped_for = str(fatal[0]) if fatal else (drive_down[0].message + " Clips already saved are kept; the few Claude had just described but that couldn't be saved will be redone next time." if drive_down else None)
    return {"probed": done[0], "attempted": len(todo), "failed": failed, "stopped_for": stopped_for, "cancelled": stopped[0], "usage": usage, "cached_total": len(moments)}


# --------------------------------------------------------------------------- running it from the app

class MomentsError(RuntimeError):
    pass


# Measured on job 34 (about 3.3k input tokens per clip, replies of a few hundred tokens). The price is an UPPER-BOUND
# assumption for the model used ($ per million tokens) -- the real bill is whatever the account's pricing says.
TOKENS_IN_PER_CLIP = 3300
TOKENS_OUT_PER_CLIP = 400
ASSUMED_USD_PER_M_IN = 5.0
ASSUMED_USD_PER_M_OUT = 25.0


def estimate_cost(clip_count: int) -> dict[str, Any]:
    tokens_in, tokens_out = clip_count * TOKENS_IN_PER_CLIP, clip_count * TOKENS_OUT_PER_CLIP
    return {
        "clips": clip_count, "input_tokens": tokens_in, "output_tokens": tokens_out,
        "usd_at_most": round(tokens_in / 1e6 * ASSUMED_USD_PER_M_IN + tokens_out / 1e6 * ASSUMED_USD_PER_M_OUT, 2),
        "assumption": f"${ASSUMED_USD_PER_M_IN:g} per million input tokens and ${ASSUMED_USD_PER_M_OUT:g} per million output tokens, as an upper bound",
    }


async def check_credit(client: Any, model: str) -> None:
    """A one-token call, so a run doesn't start (and 100 clips fail one by one) when credits are gone or the key is
    rejected. Raises VisionUnavailableError for that, MomentsError if Claude just can't be reached."""
    try:
        await client.messages.create(model=model, max_tokens=1, messages=[{"role": "user", "content": "ok"}])
    except Exception as exc:
        if _is_systemic_failure(exc):
            raise VisionUnavailableError("Claude vision is unavailable (API credit balance too low, or the API key was rejected). Add credits at console.anthropic.com/settings/billing, then try again.") from exc
        raise MomentsError(f"Couldn't reach Claude to check your balance ({type(exc).__name__}). Nothing was sent; try again in a minute.") from exc


_RUNS: dict[int, dict[str, Any]] = {}  # per job, in this process: a restart forgets a run but not the finished clips


def run_state(job_id: int) -> dict[str, Any] | None:
    run = _RUNS.get(job_id)
    if run is None:
        return None
    return {k: v for k, v in run.items() if k not in ("task", "cancel")} | {"usage": dict(run["usage"])}


def request_cancel(job_id: int) -> dict[str, Any] | None:
    run = _RUNS.get(job_id)
    if run is not None and run["state"] == "running":
        run["cancel"] = True
    return run_state(job_id)


def start_run(job_id: int, client: Any, model: str, clips: list[dict], edit_dir: Path, max_calls: int, planned_total: int | None = None) -> dict[str, Any]:
    """Starts describing the job's missing clips in the background and returns at once; poll run_state(job_id)."""
    existing = _RUNS.get(job_id)
    if existing is not None and existing["state"] == "running":
        raise MomentsError("This job is already being described.")
    total = planned_total if planned_total is not None else min(len(missing_clips(clips, load_moments(edit_dir))), max_calls)
    run: dict[str, Any] = {"state": "running", "total": total, "done": 0, "failed": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "finished_at": None, "message": None, "usage": {}, "cancel": False}

    def on_result(name: str, ok: bool) -> None:
        if ok:
            run["done"] += 1
        else:
            run["failed"].append(name)

    async def go() -> None:
        try:
            report = await probe_missing(client, model, clips, edit_dir, max_calls=max_calls, on_result=on_result, should_stop=lambda: run["cancel"], usage=run["usage"])
            if report["stopped_for"]:
                run["state"], run["message"] = "stopped", report["stopped_for"]
            elif report["cancelled"]:
                run["state"], run["message"] = "cancelled", f"Stopped. {run['done']} clip(s) described and kept."
            else:
                run["state"] = "done"
                run["message"] = f"Described {run['done']} clip(s)." + (f" {len(run['failed'])} couldn't be read." if run["failed"] else "")
        except DriveNotResponding as exc:
            run["state"], run["message"] = "stopped", exc.message
        except Exception as exc:  # a background task must never die silently
            run["state"], run["message"] = "failed", f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"[post_moments] run for job {job_id} failed: {run['message']}")
        finally:
            run["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    run["task"] = asyncio.get_running_loop().create_task(go())  # kept in the dict so it isn't garbage-collected mid-run
    _RUNS[job_id] = run
    return run_state(job_id)
