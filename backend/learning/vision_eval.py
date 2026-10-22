"""Can Claude, LOOKING at the pictures, find the moment the editor used?

The signal-only tests (motion, blur, brightness, cuts) could not predict which instant of a clip Josh cuts on. This is the same test with pictures:
for every labelled shot, Claude sees keyframes of the raw clip (each labelled with its time) and the length of the shot to cut, and names the three
instants it would most want to use. The pick is scored exactly like every other rule in evaluate.py: a pick HITS when a window of the editor's shot
length centred on it covers at least half of the moment the editor used. Compared against random and the learned signal ranker on the SAME shots.

Costs real Claude tokens (one call per shot). Replies are cached on disk, so a re-run, or a bigger run after a pilot, never pays twice.

Run from backend/:  .venv/bin/python -m learning.vision_eval --n 30      (pilot)
                    .venv/bin/python -m learning.vision_eval              (every sampled shot)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from learning import evaluate, footage, rank_local

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FRAMES_DIR = footage.DEFAULT_DATA / "frames"
REPLY_DIR = footage.DEFAULT_DATA / "vision_eval"
MODEL = "claude-sonnet-5-5"
STILL_HEIGHT = 288          # px tall: enough to see what is happening, cheap to send
MAX_FRAMES = 40             # per clip; a longer clip is thinned evenly
API_CONCURRENCY = 5
EXTRACT_CONCURRENCY = 3
# Used only to put a dollar figure on the token counts. An assumption, not a quote: check the real bill.
ASSUMED_USD_PER_MTOK_IN, ASSUMED_USD_PER_MTOK_OUT = 3.0, 15.0

SYSTEM_PROMPT = """You are a video editor cutting a fast, music-driven social highlight reel out of raw camera clips. Shots in the reel are short hard cuts, typically 0.3 to 1.5 seconds.
You will see keyframes from ONE raw clip, each labelled with its time in seconds, and the length of the shot you are cutting. Choose the three different instants of this clip you would most want to use, best first. Judge only what is visible in the frames.
Each pick is the time at the CENTRE of the shot. The three picks must be clearly different moments (at least a second apart if the clip is long enough).
Reply with ONLY JSON: {"picks":[{"t":seconds,"why":"at most 12 words"},{"t":seconds,"why":"..."},{"t":seconds,"why":"..."}]}"""


# ------------------------------------------------------------------------------------------------------------------------------------------ frames
def _frames_dir(path: str) -> Path:
    st = os.stat(path)
    return FRAMES_DIR / hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()


def _extract(path: str) -> list[tuple[float, bytes]]:
    """Keyframes only (the decoder skips every other frame, so a 4K clip takes seconds, not minutes), each with its real time stamp."""
    folder = _frames_dir(path)
    index = folder / "times.json"
    if not index.exists():
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([FFMPEG, "-hide_banner", "-skip_frame", "nokey", "-i", path, "-vf", f"scale=-2:{STILL_HEIGHT},showinfo", "-fps_mode", "passthrough",
                                  "-q:v", "4", f"{tmp}/f_%04d.jpg"], capture_output=True, text=True, timeout=600)
            times = [float(m) for m in re.findall(r"pts_time:(-?[0-9.]+)", run.stderr)]
            files = sorted(glob.glob(f"{tmp}/f_*.jpg"))
            if len(files) != len(times):
                n = min(len(files), len(times)); files, times = files[:n], times[:n]
            for i, f in enumerate(files):
                (folder / f"{i:04d}.jpg").write_bytes(Path(f).read_bytes())
        index.write_text(json.dumps(times))
    times = json.loads(index.read_text())
    frames = [(max(t, 0.0), (folder / f"{i:04d}.jpg").read_bytes()) for i, t in enumerate(times)]
    if len(frames) > MAX_FRAMES:
        frames = [frames[int(i)] for i in np.linspace(0, len(frames) - 1, MAX_FRAMES)]
    return frames


# --------------------------------------------------------------------------------------------------------------------------------------- the ask
def _reply_file(path: str, src_in: float, length: float, variant: str = "pick") -> Path:
    key = f"{MODEL}|{path}|{src_in:.3f}|{length:.3f}" if variant == "pick" else f"{variant}|{MODEL}|{path}|{src_in:.3f}"
    return REPLY_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def parse_picks(text: str, duration: float) -> list[float]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    picks = []
    for p in data.get("picks", []) if isinstance(data, dict) else []:
        try:
            t = float(p.get("t"))
        except (TypeError, ValueError, AttributeError):
            continue
        if -0.5 <= t <= duration + 0.5:
            picks.append(min(max(t, 0.0), duration))
    return picks


async def ask(client, sample: evaluate.Sample, dur: float, frames: list[tuple[float, bytes]], variant: str = "pick") -> dict:
    """variant 'pick': the prompt above. variant 'moments': the prompt the app's Describe-clips step (app/post_moments.py) uses today, on the same frames."""
    cache = _reply_file(sample.path, sample.src_in, sample.length, variant)
    if cache.exists():
        return json.loads(cache.read_text())
    content: list[dict] = []
    for t, jpeg in frames:
        content.append({"type": "text", "text": f"t={t:.2f}s"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}})
    if variant == "moments":
        from app import post_moments
        content.append({"type": "text", "text": "Find the punchy moments as instructed."})
        response = await client.messages.create(model=MODEL, max_tokens=900, system=post_moments.MOMENTS_SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        parsed = post_moments.parse_moments_reply(text, dur)
        picks = [e["t"] for e in parsed["events"][:3]] if parsed else []
    else:
        content.append({"type": "text", "text": f"Clip length {dur:.1f} s. Shot to cut: {sample.length:.2f} s. Name your three picks."})
        response = await client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        picks = parse_picks(text, dur)
    record = {"picks": picks, "raw": text, "frames": len(frames), "tokens_in": response.usage.input_tokens, "tokens_out": response.usage.output_tokens}
    REPLY_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(record))
    return record


def score(sample: evaluate.Sample, dur: float, picks: list[float]) -> tuple[bool, bool]:
    L = min(sample.length, dur - 0.05)
    hits = []
    for t in picks[:3]:
        start = min(max(t - L / 2, 0.0), max(dur - L - 0.04, 0.0))
        hits.append(evaluate.overlap(start, sample.src_in, L) >= evaluate.HIT_OVERLAP)
    return (bool(hits and hits[0]), any(hits))


# ------------------------------------------------------------------------------------------------------------------------------------------ run
async def run(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from anthropic import AsyncAnthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (backend/.env)."); return 1

    inventory = json.loads((footage.DEFAULT_DATA / args.inventory).read_text())
    measures = {s.path: m for s in evaluate.sample_shots(inventory) if (m := evaluate.load_measure(s.path))}
    samples = [s for s in evaluate.sample_shots(inventory) if measures.get(s.path)]
    random.Random(7).shuffle(samples)
    samples = samples[: args.n] if args.n else samples
    print(f"{len(samples)} labelled shots from {len({s.project for s in samples})} projects ({MODEL})", flush=True)

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    api, extract = asyncio.Semaphore(API_CONCURRENCY), asyncio.Semaphore(EXTRACT_CONCURRENCY)
    done = {"n": 0}; t0 = time.time(); systemic: list[str] = []

    async def one(s: evaluate.Sample):
        dur = min(s.src_duration, measures[s.path]["seconds"])
        try:
            async with extract:
                frames = await asyncio.to_thread(_extract, s.path)
            if len(frames) < 3:
                return s, dur, None
            async with api:
                record = await ask(client, s, dur, frames, args.variant)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {str(exc)[:160]}"
            if getattr(exc, "status_code", None) in (401, 403) or "credit balance" in str(exc).lower():
                systemic.append(msg)
            print(f"  skipped {os.path.basename(s.path)}: {msg}", flush=True)
            return s, dur, None
        done["n"] += 1
        if done["n"] % 10 == 0:
            print(f"  {done['n']}/{len(samples)} asked ({time.time() - t0:.0f}s)", flush=True)
        return s, dur, record

    rows = [r for r in await asyncio.gather(*(one(s) for s in samples))]
    if systemic:
        print("STOPPED: the API refused the calls (" + systemic[0] + "). Check the Anthropic credit balance."); return 1
    rows = [(s, d, r) for s, d, r in rows if r]

    # the same shots, scored three ways
    random_eval = evaluate.evaluate_rule([s for s, _, _ in rows], None, measures)
    random_hit1 = float(np.mean([r["hit1"] for r in random_eval["results"]])); random_hit3 = float(np.mean([r["hit3"] for r in random_eval["results"]]))
    hits1, hits3, tin, tout, nopick = [], [], 0, 0, 0
    for s, d, rec in rows:
        h1, h3 = score(s, d, rec["picks"]); hits1.append(float(h1)); hits3.append(float(h3))
        tin += rec["tokens_in"]; tout += rec["tokens_out"]; nopick += not rec["picks"]
    n = len(rows)
    usd = tin / 1e6 * ASSUMED_USD_PER_MTOK_IN + tout / 1e6 * ASSUMED_USD_PER_MTOK_OUT
    ci = evaluate.bootstrap(hits3)
    print(f"\nClaude looking at the pictures ('{args.variant}' prompt), n={n} shots ({len({s.project for s, _, _ in rows})} projects)")
    print(f"  top-1 {np.mean(hits1):.1%}   (random {random_hit1:.1%})")
    print(f"  top-3 {np.mean(hits3):.1%}   95% range {ci[0]:.1%}-{ci[1]:.1%}   (random {random_hit3:.1%};  the signal-only learned ranker scored 25.9% on the full 166)")
    print(f"  replies with no usable pick: {nopick}")
    print(f"  tokens: {tin:,} in / {tout:,} out = {tin // max(n, 1):,} in per shot;  est. ${usd:.2f} for these {n} shots (${usd / max(n, 1):.3f} each, at an ASSUMED $3/$15 per M tokens)")
    if n >= 100:
        by_project: dict[str, list[tuple[float, float]]] = {}
        for (s, d, rec), h in zip(rows, hits3):
            by_project.setdefault(s.project, []).append((h, 0))
        print("\n  per project top-3 (claude):  " + "   ".join(f"{p[:18]} {np.mean([h for h, _ in v]):.0%}" for p, v in sorted(by_project.items())))
    return 0


def _distinct(starts: list[float], L: float, k: int = 3) -> list[float]:
    """The first k of `starts` (in priority order) that are at least half a window apart, so three picks are three different moments."""
    out: list[float] = []
    for s in starts:
        if all(abs(s - c) >= L * 0.5 for c in out):
            out.append(s)
        if len(out) == k:
            break
    return out


def analyse(args: argparse.Namespace) -> int:
    """No API calls: reads the cached replies. How do the pictures compare with the signal-only ranker, and do the two catch the same shots?"""
    inventory = json.loads((footage.DEFAULT_DATA / args.inventory).read_text())
    measures = {s.path: m for s in evaluate.sample_shots(inventory) if (m := evaluate.load_measure(s.path))}
    samples = [s for s in evaluate.sample_shots(inventory) if measures.get(s.path)]
    picks_by_shot = {}
    for s in samples:
        f = _reply_file(s.path, s.src_in, s.length, args.variant)
        if f.exists():
            picks_by_shot[(s.path, round(s.src_in, 3))] = json.loads(f.read_text())["picks"]
    samples = [s for s in samples if (s.path, round(s.src_in, 3)) in picks_by_shot]
    items = rank_local.prepare(samples, measures)
    signal = rank_local.cross_validate(items, l2=1.0)
    signal_picks = {(r["path"], r["src_in"]): r["picks"] for r in signal["rows"]}
    shot = {(s.path, s.src_in): s for s in samples}

    def claude_starts(s: evaluate.Sample) -> list[float]:
        dur = min(s.src_duration, measures[s.path]["seconds"]); L = min(s.length, dur - 0.05)
        return [min(max(t - L / 2, 0.0), max(dur - L - 0.04, 0.0)) for t in picks_by_shot[(s.path, round(s.src_in, 3))]]

    def hit(s: evaluate.Sample, start: float) -> bool:
        dur = min(s.src_duration, measures[s.path]["seconds"]); L = min(s.length, dur - 0.05)
        return evaluate.overlap(start, s.src_in, L) >= evaluate.HIT_OVERLAP

    recipes = {
        "pictures: Claude's 3 picks": lambda c, g: c[:3],
        "signals: learned ranker's 3 picks": lambda c, g: g[:3],
        "mixed: Claude 1st, signals 1st, Claude 2nd": lambda c, g: [x for pair in zip(c, g) for x in pair][:3] if c and g else (c or g),
        "mixed: Claude 1st + 2nd, signals 1st": lambda c, g: c[:2] + g[:1],
        "mixed: signals 1st + 2nd, Claude 1st": lambda c, g: [c[0]] + g[:2] if c else g[:3],
    }
    print(f"{len(items)} shots, 21 projects, each project scored by a model trained on the others (signals); Claude's picks need no training")
    results = {}
    for name, recipe in recipes.items():
        h1, h3 = [], []
        for it in items:
            s = shot[(it["path"], it["src_in"])]
            starts = _distinct(recipe(claude_starts(s), signal_picks[(it["path"], it["src_in"])]), it["L"])
            if name.startswith("mixed: Claude 1st, signals"):   # interleave properly: c1, g1, c2, g2 ...
                c, g = claude_starts(s), signal_picks[(it["path"], it["src_in"])]
                starts = _distinct([x for pair in zip(c, g) for x in pair], it["L"])
            flags = [hit(s, x) for x in starts]
            h1.append(float(bool(flags and flags[0]))); h3.append(float(any(flags)))
        results[name] = (h1, h3)
        ci = evaluate.bootstrap(h3)
        print(f"  {name:48s} top-1 {np.mean(h1):5.1%}   top-3 {np.mean(h3):5.1%}  (95% {ci[0]:.1%}-{ci[1]:.1%})")
    print(f"  {'random guess':48s} top-1 {signal['random_hit1']:5.1%}   top-3 {signal['random_hit3']:5.1%}")
    a, b = results["pictures: Claude's 3 picks"][1], results["signals: learned ranker's 3 picks"][1]
    both = sum(1 for x, y in zip(a, b) if x and y); only_a = sum(1 for x, y in zip(a, b) if x and not y); only_b = sum(1 for x, y in zip(a, b) if y and not x)
    print(f"\n  top-3 hits: both {both}, only pictures {only_a}, only signals {only_b}, neither {len(a) - both - only_a - only_b}")
    pos = np.array([picks_by_shot[(s.path, round(s.src_in, 3))][0] / max(min(s.src_duration, measures[s.path]["seconds"]), 1e-9) for s in samples if picks_by_shot[(s.path, round(s.src_in, 3))]])
    his = np.array([s.src_in / max(min(s.src_duration, measures[s.path]["seconds"]), 1e-9) for s in samples])
    print(f"  Claude's first pick sits at {np.median(pos):.0%} of the clip (median); his shots start at {np.median(his):.0%} (median)")
    return 0


def planner_check(args: argparse.Namespace) -> int:
    """No API calls. Runs the app's REAL window chooser (app.post_steady.window_for_slot) on every labelled shot, with and without the
    event-first rule, using the cached Claude replies as the clip's described events. Top-1 = the first stretch it picks for a slot; top-3 = that plus
    the next two it would offer from the same clip (the review's alternatives)."""
    from app import post_moments, post_steady
    inventory = json.loads((footage.DEFAULT_DATA / args.inventory).read_text())
    measures = {s.path: m for s in evaluate.sample_shots(inventory) if (m := evaluate.load_measure(s.path))}
    samples = [s for s in evaluate.sample_shots(inventory) if measures.get(s.path)]
    rng_eval = evaluate.evaluate_rule(samples, None, measures)
    print(f"{len(samples)} shots;  random guess: top-1 {np.mean([r['hit1'] for r in rng_eval['results']]):.1%}  top-3 {np.mean([r['hit3'] for r in rng_eval['results']]):.1%}")
    for variant in ("moments", "pick"):
        events_by_shot = {}
        for s in samples:
            f = _reply_file(s.path, s.src_in, s.length, variant)
            if not f.exists():
                continue
            rec = json.loads(f.read_text()); dur = min(s.src_duration, measures[s.path]["seconds"])
            if variant == "moments":
                parsed = post_moments.parse_moments_reply(rec["raw"], dur)
                events_by_shot[(s.path, s.src_in)] = parsed["events"] if parsed else []
            else:
                events_by_shot[(s.path, s.src_in)] = [{"t": t, "kind": "pick", "punch": 10 - i, "what": ""} for i, t in enumerate(rec["picks"])]
        for label, flag in (("old rule (steadiest, small event bonus)", False), ("new rule (Claude's event first)", True)):
            post_steady.EVENT_FIRST = flag
            h1, h3, used = [], [], []
            for s in samples:
                key = (s.path, s.src_in)
                if key not in events_by_shot:
                    continue
                m = measures[s.path]; clip = {"steady": m, "duration": s.src_duration, "events": events_by_shot[key]}
                dur = min(s.src_duration, m["seconds"]); L = min(s.length, dur - 0.05)
                taken, hits = [], []
                for _ in range(3):
                    w = post_steady.window_for_slot(clip, L, taken)
                    hits.append(evaluate.overlap(w["start"], s.src_in, L) >= evaluate.HIT_OVERLAP)
                    taken.append((w["start"], w["start"] + w["duration"]))
                    if len(hits) == 1:
                        used.append(w["source"].startswith("event pick"))
                h1.append(float(hits[0])); h3.append(float(any(hits)))
            post_steady.clear_series_cache()
            ci = evaluate.bootstrap(h3)
            print(f"  [{variant:7s} events] {label:42s} top-1 {np.mean(h1):5.1%}   top-3 {np.mean(h3):5.1%} (95% {ci[0]:.1%}-{ci[1]:.1%})   event-picked first stretch in {np.mean(used):.0%} of shots   n={len(h1)}")
    post_steady.EVENT_FIRST = True
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=0, help="only the first N shots (seeded shuffle; replies are cached, so a later full run reuses them)")
    parser.add_argument("--inventory", default="inventory_before_zero_fix.json")
    parser.add_argument("--model", default=MODEL, help="Claude model to ask (the app's Describe-clips step uses claude-sonnet-5)")
    parser.add_argument("--variant", choices=("pick", "moments"), default="pick", help="'moments' = the prompt the app's Describe-clips step uses today")
    parser.add_argument("--planner", action="store_true", help="no API calls: run the app's real window chooser with and without the event-first rule on the cached replies")
    parser.add_argument("--analyse", action="store_true", help="no API calls: compare/combine the cached replies with the signal ranker")
    args = parser.parse_args()
    globals()["MODEL"] = args.model
    if args.planner:
        return planner_check(args)
    return analyse(args) if args.analyse else asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
