"""Does a denser SECOND LOOK around each described moment find the instant better?  (master-prompt priority 1, "temporal understanding")

The first pass (Describe clips) sees a still every 0.5-1 s and says WHERE something happens. This second pass takes each of its top moments and looks at a dense strip of
frames around it (every STEP seconds, +-WINDOW seconds), so Claude can see what happens before, during and after, and names the best stretch of the shot's length.

Scored exactly like everything else: a pick HITS when its window covers at least half of the moment the editor used; top 1 = the first moment's window, top 3 = the
three moments' windows. Compared on the same shots with (a) the first pass alone (window centred on the moment: what the planner does today) and two controls that use
NO Claude on the strip: (b) the steadiest window within the same neighbourhood and (c) a random window within it -- so a gain cannot be "it moved the window nearby".
Declared before running: one prompt, no tuning on these shots.

Costs real Claude tokens; replies are cached. Run from backend/:
  .venv/bin/python -m learning.second_look --n 20     (pilot: real cost and time)
  .venv/bin/python -m learning.second_look            (every sampled shot)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from learning import evaluate, footage, vision_eval

WINDOW = 1.2        # seconds either side of the first-pass moment
STEP = 0.2          # seconds between frames of the strip
HEIGHT = 224        # px tall (the first pass uses 288): keeps the cost near the first pass's
MODEL = "claude-sonnet-5-5"
FIRST_PASS_VARIANT = "moments"   # the app's Describe-clips prompt, as cached by vision_eval
STRIPS_DIR = footage.DEFAULT_DATA / "frames2"
REPLY_DIR = footage.DEFAULT_DATA / "second_look"
API_CONCURRENCY, EXTRACT_CONCURRENCY = 5, 4
CONTROL_DRAWS = 200

SYSTEM_PROMPT = """You are a video editor choosing the exact instant to cut on. You will see a short strip of frames from ONE raw clip, around a moment that was already picked as promising. Each frame is labelled with its time in seconds. You are told what the moment was thought to be and how long the shot you are cutting is.
Find the best stretch of that length inside the strip: the one that holds the decisive part of the action -- the build-up just before it, the peak, and its completion if there is room -- so a viewer reads it at a glance. Judge only what is visible.
Reply with ONLY JSON: {"start":seconds,"peak":seconds,"why":"at most 12 words"} -- "start" is the time the shot should begin (exactly as labelled or between two labelled times), "peak" the instant of the decisive moment."""


def _strip_dir(path: str, t0: float, t1: float) -> Path:
    st = os.stat(path)
    return STRIPS_DIR / hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}|{t0:.3f}|{t1:.3f}|{STEP}|{HEIGHT}".encode()).hexdigest()


def extract_strip(path: str, t0: float, t1: float) -> list[tuple[float, bytes]]:
    """Frames every STEP seconds from t0 to t1 (decoded in one short pass), each with its time. Cached on disk."""
    folder = _strip_dir(path, t0, t1)
    if not (folder / "done").exists():
        folder.mkdir(parents=True, exist_ok=True)
        run = subprocess.run([vision_eval.FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{t0:.3f}", "-i", path, "-t", f"{t1 - t0:.3f}", "-vf", f"fps={1 / STEP:.4f},scale=-2:{HEIGHT}",
                              "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True, timeout=600)
        parts = [b"\xff\xd8" + p for p in run.stdout.split(b"\xff\xd8") if p]
        for i, jpeg in enumerate(parts):
            (folder / f"{i:03d}.jpg").write_bytes(jpeg)
        (folder / "done").write_text(str(len(parts)))
    n = int((folder / "done").read_text())
    return [(round(t0 + i * STEP, 3), (folder / f"{i:03d}.jpg").read_bytes()) for i in range(n)]


def _reply_file(path: str, t: float, length: float) -> Path:
    return REPLY_DIR / (hashlib.sha1(f"{MODEL}|{path}|{t:.3f}|{length:.3f}|{WINDOW}|{STEP}|{HEIGHT}".encode()).hexdigest() + ".json")


def parse_start(text: str, lo: float, hi: float) -> float | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        start = float(json.loads(match.group(0)).get("start"))
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return None
    return min(max(start, lo), hi)


async def refine(client, path: str, event: dict, length: float, dur: float) -> dict | None:
    """The second look at one moment. Returns {"start", "tokens_in", "tokens_out"} or None when the strip is too short or the reply unusable."""
    t0, t1 = max(0.0, event["t"] - WINDOW), min(dur, event["t"] + WINDOW)
    if t1 - t0 < length + 0.1:
        return None
    cache = _reply_file(path, event["t"], length)
    if cache.exists():
        rec = json.loads(cache.read_text())
    else:
        frames = await asyncio.to_thread(extract_strip, path, t0, t1)
        if len(frames) < 3:
            return None
        content: list[dict] = []
        for t, jpeg in frames:
            content.append({"type": "text", "text": f"t={t:.2f}s"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}})
        content.append({"type": "text", "text": f"The moment: {event.get('kind', 'moment')} -- {event.get('what', '')}. The shot is {length:.2f} s long. Where should it start?"})
        response = await client.messages.create(model=MODEL, max_tokens=300, system=SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        rec = {"raw": text, "frames": len(frames), "tokens_in": response.usage.input_tokens, "tokens_out": response.usage.output_tokens}
        REPLY_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rec))
    start = parse_start(rec["raw"], t0, max(t1 - length, t0))
    return None if start is None else {"start": start, "tokens_in": rec["tokens_in"], "tokens_out": rec["tokens_out"]}


def first_pass_events(sample: evaluate.Sample, dur: float) -> list[dict]:
    from app import post_moments
    f = vision_eval._reply_file(sample.path, sample.src_in, sample.length, FIRST_PASS_VARIANT)
    if not f.exists():
        return []
    parsed = post_moments.parse_moments_reply(json.loads(f.read_text())["raw"], dur)
    return parsed["events"][:3] if parsed else []


def _hit(sample: evaluate.Sample, start: float, length: float) -> bool:
    return evaluate.overlap(start, sample.src_in, length) >= evaluate.HIT_OVERLAP


def _neighbourhood(event: dict, length: float, dur: float) -> np.ndarray:
    lo, hi = max(0.3, event["t"] - WINDOW), min(event["t"] + WINDOW - length, dur - length - 0.04)
    return np.arange(lo, hi + 1e-9, 0.125) if hi >= lo else np.array([min(max(event["t"] - length / 2, 0.0), max(dur - length - 0.04, 0.0))])


async def run(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from anthropic import AsyncAnthropic
    from app import post_steady
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (backend/.env)."); return 1
    vision_eval.MODEL = MODEL
    inventory = json.loads((footage.DEFAULT_DATA / args.inventory).read_text())
    measures = {s.path: evaluate.load_measure(s.path) for s in evaluate.sample_shots(inventory) if os.path.exists(s.path)}
    samples = [s for s in evaluate.sample_shots(inventory) if measures.get(s.path)]
    random.Random(7).shuffle(samples)
    samples = samples[: args.n] if args.n else samples

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    api, extract = asyncio.Semaphore(API_CONCURRENCY), asyncio.Semaphore(EXTRACT_CONCURRENCY)
    systemic: list[str] = []
    done = {"n": 0}
    t0 = time.time()

    async def one(s: evaluate.Sample):
        dur = min(s.src_duration, measures[s.path]["seconds"]); L = min(s.length, dur - 0.05)
        events = first_pass_events(s, dur)
        refined = []
        for e in events:
            try:
                async with extract:
                    async with api:
                        refined.append(await refine(client, s.path, e, L, dur))
            except Exception as exc:
                if getattr(exc, "status_code", None) in (401, 403) or "credit balance" in str(exc).lower():
                    systemic.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                print(f"  skipped a moment of {os.path.basename(s.path)}: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                refined.append(None)
        done["n"] += 1
        if done["n"] % 10 == 0:
            print(f"  {done['n']}/{len(samples)} shots ({time.time() - t0:.0f}s)", flush=True)
        return s, dur, L, events, refined

    rows = await asyncio.gather(*(one(s) for s in samples))
    if systemic:
        print("STOPPED: the API refused the calls (" + systemic[0] + "). Check the Anthropic credit balance."); return 1

    rng = np.random.default_rng(5)
    arms = {"first pass alone (window centred on the moment: today)": ([], []), "second look (Claude on the dense strip)": ([], []),
            "control: steadiest window in the same neighbourhood": ([], []), "control: random window in the same neighbourhood": ([], [])}
    paired = {"first": [], "second": []}
    tin = tout = calls = 0
    used = 0
    for s, dur, L, events, refined in rows:
        if not events:
            continue
        m = measures[s.path]
        centred = [min(max(e["t"] - L / 2, 0.0), max(dur - L - 0.04, 0.0)) for e in events]
        second = [r["start"] if r else c for r, c in zip(refined, centred)]      # a moment that could not be refined keeps its first-pass window
        steady = []
        for e in events:
            starts = _neighbourhood(e, L, dur)
            scores = [post_steady.score_window(m, float(x), L)["score"] for x in starts]
            steady.append(float(starts[int(np.argmin(scores))]))
        for r in refined:
            if r:
                tin += r["tokens_in"]; tout += r["tokens_out"]; calls += 1
        used += 1
        for name, picks in zip(arms, (centred, second, steady, None)):
            if picks is not None:
                chosen = vision_eval._distinct(picks, L)
                flags = [_hit(s, x, L) for x in chosen]
                arms[name][0].append(float(bool(flags and flags[0]))); arms[name][1].append(float(any(flags)))
            else:   # random: Monte Carlo over one random start per moment's neighbourhood
                h1 = h3 = 0.0
                for _ in range(CONTROL_DRAWS):
                    chosen = vision_eval._distinct([float(rng.choice(_neighbourhood(e, L, dur))) for e in events], L)
                    flags = [_hit(s, x, L) for x in chosen]
                    h1 += bool(flags and flags[0]); h3 += any(flags)
                arms[name][0].append(h1 / CONTROL_DRAWS); arms[name][1].append(h3 / CONTROL_DRAWS)
        paired["first"].append((arms["first pass alone (window centred on the moment: today)"][0][-1], arms["first pass alone (window centred on the moment: today)"][1][-1]))
        paired["second"].append((arms["second look (Claude on the dense strip)"][0][-1], arms["second look (Claude on the dense strip)"][1][-1]))

    usd = tin / 1e6 * vision_eval.ASSUMED_USD_PER_MTOK_IN + tout / 1e6 * vision_eval.ASSUMED_USD_PER_MTOK_OUT
    print(f"\nSecond look on {used} shots ({len({s.project for s, *_ in rows})} projects), {calls} refinements; random guess for reference: top 1 6.5%, top 3 18.1% (full sample)")
    for name, (h1, h3) in arms.items():
        ci = evaluate.bootstrap(h3)
        print(f"  {name:58s} top 1 {np.mean(h1):5.1%}   top 3 {np.mean(h3):5.1%}  (95% {ci[0]:.1%}-{ci[1]:.1%})")
    f1, f3 = zip(*paired["first"]); s1, s3 = zip(*paired["second"])
    gain1 = sum(1 for a, b in zip(f1, s1) if b > a); loss1 = sum(1 for a, b in zip(f1, s1) if b < a)
    gain3 = sum(1 for a, b in zip(f3, s3) if b > a); loss3 = sum(1 for a, b in zip(f3, s3) if b < a)
    print(f"\n  second look vs first pass, shot by shot: top 1 gained {gain1} / lost {loss1};  top 3 gained {gain3} / lost {loss3}")
    print(f"  tokens: {tin:,} in / {tout:,} out for {calls} calls = {tin // max(calls, 1):,} in per refinement;  est. ${usd:.2f} for these {used} shots (${usd / max(used, 1):.3f} each, at an ASSUMED $3/$15 per M tokens)")
    print(f"  projected for all 168 shots: about ${usd / max(used, 1) * 168:.2f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=0, help="only the first N shots (seeded shuffle; replies are cached, so a bigger run reuses them)")
    parser.add_argument("--inventory", default="inventory_before_zero_fix.json")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
