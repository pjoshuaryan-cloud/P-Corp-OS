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
import hashlib
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
# What a description was made with (2026-10-22), stored on every NEW description so a changed prompt, model or sampling can be told apart from the cache.
# Older descriptions have none and count as "legacy": they are still used (re-describing costs real money) and never re-done without being asked.
PROMPT_VERSION = hashlib.sha1(MOMENTS_SYSTEM_PROMPT.encode()).hexdigest()[:10]
SAMPLER_VERSION = "stills every 0.5 s (clips up to 20 s), 0.75 s (up to 30 s), else 1 s; at most 40"
USAGE_FILE = "api_usage.jsonl"


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
            moments[str(clip["file_id"])] = {"name": clip["name"], "duration": clip["duration"], **result,
                                             "provenance": {"model": model, "prompt": PROMPT_VERSION, "sampler": SAMPLER_VERSION, "described_at": time.strftime("%Y-%m-%dT%H:%M:%S")}}
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


# Anthropic first-party list prices in US$ per million tokens (input, output), as listed in the Claude API reference on 2026-10-06. Used to cost what a run
# REALLY used (the usage ledger) and to show a list-price estimate beside the upper bound. The account's own bill is the truth.
LIST_PRICE_PER_M = {"claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
LIST_PRICE_SOURCE = "Anthropic list price as of 2026-10-06"


def usd(model: str | None, tokens_in: int, tokens_out: int) -> tuple[float, str]:
    """(cost, basis) at the model's list price, or at the upper-bound assumption for a model not listed."""
    price_in, price_out = LIST_PRICE_PER_M.get(model or "", (ASSUMED_USD_PER_M_IN, ASSUMED_USD_PER_M_OUT))
    basis = f"{LIST_PRICE_SOURCE} for {model}" if model in LIST_PRICE_PER_M else "upper-bound assumption (model's price not listed)"
    return round(tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out, 4), basis


def estimate_cost(clip_count: int, model: str | None = None) -> dict[str, Any]:
    """Before a run: `usd_at_most` is the deliberate upper bound the app has always shown; with `model` given, `usd_list_price` adds the estimate at that
    model's list price (claude-sonnet-5-5 is about 2.5 times cheaper than the bound)."""
    tokens_in, tokens_out = clip_count * TOKENS_IN_PER_CLIP, clip_count * TOKENS_OUT_PER_CLIP
    out = {
        "clips": clip_count, "input_tokens": tokens_in, "output_tokens": tokens_out,
        "usd_at_most": round(tokens_in / 1e6 * ASSUMED_USD_PER_M_IN + tokens_out / 1e6 * ASSUMED_USD_PER_M_OUT, 2),
        "assumption": f"${ASSUMED_USD_PER_M_IN:g} per million input tokens and ${ASSUMED_USD_PER_M_OUT:g} per million output tokens, as an upper bound",
    }
    if model in LIST_PRICE_PER_M:
        out["usd_list_price"], out["list_price_basis"] = usd(model, tokens_in, tokens_out)
        out["usd_list_price"] = round(out["usd_list_price"], 2)
    return out


def freshness(moments: dict[str, Any], model: str) -> dict[str, int]:
    """How the cached descriptions relate to what a new run would make: `current` (same model, prompt and sampling), `legacy` (made before versions were
    recorded) and `other_version` (a different model, prompt or sampling). Nothing is re-described automatically; this only reports."""
    out = {"current": 0, "legacy": 0, "other_version": 0}
    for rec in moments.values():
        prov = rec.get("provenance") if isinstance(rec, dict) else None
        if not prov:
            out["legacy"] += 1
        elif prov.get("model") == model and prov.get("prompt") == PROMPT_VERSION and prov.get("sampler") == SAMPLER_VERSION:
            out["current"] += 1
        else:
            out["other_version"] += 1
    return out


def record_usage(edit_dir: Path, *, job_id: int, operation: str, model: str, usage: dict[str, int], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Appends what one run REALLY used (token counts from the API's own responses) to the job's usage ledger, costed at list price. Returns the line."""
    tokens_in, tokens_out = int(usage.get("in", 0)), int(usage.get("out", 0))
    cost, basis = usd(model, tokens_in, tokens_out)
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "operation": operation, "model": model, "calls": int(usage.get("calls", 0)),
            "input_tokens": tokens_in, "output_tokens": tokens_out, "usd": cost, "price_basis": basis, **(extra or {})}
    edit_dir.mkdir(parents=True, exist_ok=True)
    with open(edit_dir / USAGE_FILE, "a") as fh:
        fh.write(json.dumps(line) + "\n")
    return line


def usage_summary(edit_dir: Path) -> dict[str, Any]:
    """Totals of the job's usage ledger by operation: calls, tokens, US$ at list price. Corrupt lines are skipped."""
    path = edit_dir / USAGE_FILE
    totals: dict[str, dict[str, Any]] = {}
    if path.exists():
        for raw in path.read_text().splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            t = totals.setdefault(line.get("operation", "?"), {"runs": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
            t["runs"] += 1
            for k in ("calls", "input_tokens", "output_tokens"):
                t[k] += int(line.get(k, 0))
            t["usd"] = round(t["usd"] + float(line.get("usd", 0.0)), 4)
    return {"by_operation": totals, "usd_total": round(sum(t["usd"] for t in totals.values()), 4)}


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
            if run["usage"].get("calls"):   # what this run really used, kept after the process forgets the run
                try:
                    await on_drive(record_usage, edit_dir, job_id=job_id, operation="describe_clips", model=model, usage=dict(run["usage"]),
                                   extra={"clips_described": run["done"], "clips_failed": len(run["failed"]), "state": run["state"]}, writing=True)
                except Exception as exc:  # the ledger must never break the run's own report
                    print(f"[post_moments] couldn't record usage for job {job_id}: {type(exc).__name__}")

    run["task"] = asyncio.get_running_loop().create_task(go())  # kept in the dict so it isn't garbage-collected mid-run
    _RUNS[job_id] = run
    return run_state(job_id)
