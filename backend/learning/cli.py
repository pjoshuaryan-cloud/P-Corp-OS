"""Command line for the learning tools.  Run from backend/:  .venv/bin/python -m learning.cli <command> ...

  measure     read the raw clips of a seeded sample of labelled shots (resumable; results cached in data/learning/measure/)
  evaluate    score the shot-picking rules against what the editor chose
  inventory   read every project under the given folders, resolve the footage across the mounted drives, and report how much of each project's
              editing decisions can be used as a labelled example. Writes data/learning/inventory.json (git-ignored).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import time

from learning import dataset, evaluate, footage

PRUNE = footage.SKIP_DIRS | {"AMM - APP", "P-Corp", "alpha-mode-media-app", "AlphaMode-Redesign", "Library", ".Trash"}


def find_projects(roots: list[str]) -> list[str]:
    found = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRUNE and not d.startswith("._")]
            found += [os.path.join(dirpath, f) for f in filenames if f.lower().endswith(".prproj") and not f.startswith("._")]
    return found


def cmd_inventory(args: argparse.Namespace) -> int:
    t0 = time.time()
    files = find_projects(args.roots)
    projects = dataset.collect_projects(files)
    if args.since:
        cutoff = datetime.datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        projects = [p for p in projects if p.mtime >= cutoff]
    if args.limit:
        projects = projects[: args.limit]
    print(f"{len(files)} project files -> {len(projects)} distinct projects ({sum(1 for p in projects if p.is_autosave)} only as auto-saves)", flush=True)
    index = footage.DriveIndex()
    for root in footage.mounted_roots(args.footage):
        index.add_root(root)
    print(f"footage index: {index.count} video files under {len(index.roots)} folders ({time.time() - t0:.0f}s)", flush=True)
    durations = footage.Durations()
    records, rows = [], []
    for i, pf in enumerate(projects, start=1):
        try:
            record = dataset.build_project(pf, index, durations)
        except Exception as exc:  # one unreadable project must not stop the rest
            print(f"  [{i}/{len(projects)}] {pf.name}: skipped ({type(exc).__name__}: {str(exc)[:80]})", flush=True)
            continue
        durations.save()
        records.append(record)
        row = dataset.summarise(record)
        row["date"] = datetime.date.fromtimestamp(pf.mtime).isoformat()
        rows.append(row)
        print(f"  [{i}/{len(projects)}] {pf.name[:40]:40s} {row['edits']} edit(s), {row['shots']:4d} shots, {row['usable']:4d} usable", flush=True)
    out = footage.DEFAULT_DATA / "inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"made": datetime.datetime.now().isoformat(timespec="seconds"), "records": records}))
    print(f"\n{'project':42s} {'date':10s} {'edits':>5s} {'shots':>6s} {'usable':>7s} {'share':>6s}")
    for r in sorted(rows, key=lambda r: -r["usable"]):
        if r["shots"]:
            print(f"{r['project'][:42]:42s} {r['date']} {r['edits']:5d} {r['shots']:6d} {r['usable']:7d} {100 * r['share']:5.0f}%")
    total, usable = sum(r["shots"] for r in rows), sum(r["usable"] for r in rows)
    print(f"\nall projects: {total} editing decisions, {usable} with their footage found ({100 * usable / max(total, 1):.0f}%). Saved to {out}")
    return 0


def _inventory() -> dict:
    return json.loads((footage.DEFAULT_DATA / "inventory.json").read_text())


def cmd_measure(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(footage.DEFAULT_DATA.parents[1]))
    from app import post_steady
    samples = evaluate.sample_shots(_inventory(), args.per_project, args.seed, args.max_clip_seconds)
    todo = sorted({s.path for s in samples if evaluate.load_measure(s.path) is None})
    footage_min = sum(s.src_duration for s in samples if s.path in set(todo)) / 60
    print(f"{len(samples)} sampled shots from {len({s.path for s in samples})} clips; {len(todo)} still to read (~{footage_min:.0f} min of footage)", flush=True)
    evaluate.MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    done, t0 = 0, time.time()

    async def one(path: str, limiter: asyncio.Semaphore) -> None:
        nonlocal done
        frames = await post_steady.read_clip(path, limiter)
        if frames is not None:
            evaluate.cache_file(path).write_text(json.dumps(post_steady.measure(frames)))
        done += 1
        if done % 10 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} read ({time.time() - t0:.0f}s)", flush=True)

    async def run() -> None:
        limiter = asyncio.Semaphore(args.workers)
        await asyncio.gather(*(one(p, limiter) for p in todo))

    asyncio.run(run())
    print("done", flush=True)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(footage.DEFAULT_DATA.parents[1]))
    samples = evaluate.sample_shots(_inventory(), args.per_project, args.seed, args.max_clip_seconds)
    measures = {s.path: m for s in samples if (m := evaluate.load_measure(s.path))}
    samples = [s for s in samples if s.path in measures]
    print(f"{len(samples)} labelled shots with their clips read, from {len({s.project for s in samples})} projects\n")
    rows = {"random guess": evaluate.evaluate_rule(samples, None, measures)}
    for name, rule in evaluate.RULES.items():
        rows[name] = evaluate.evaluate_rule(samples, rule, measures)
    print(f"{'rule':44s} {'top-1 hit':>10s} {'95% range':>14s} {'top-3 hit':>10s} {'95% range':>14s} {'rank of your window':>20s}")
    for name, ev in rows.items():
        s = evaluate.summarise(ev)
        print(f"{name:44s} {100 * s['hit1']:9.1f}% {100 * s['hit1_ci'][0]:5.1f}-{100 * s['hit1_ci'][1]:5.1f}% {100 * s['hit3']:9.1f}% {100 * s['hit3_ci'][0]:5.1f}-{100 * s['hit3_ci'][1]:5.1f}% {s['rank']:20.2f}")
    print("\nper project, top-3 hit rate (n shots) -- random vs the corporate engine's rule vs most motion:")
    projects = sorted({s.project for s in samples})
    def by(name):
        d = {}
        for r in rows[name]["results"]:
            d.setdefault(r["project"], []).append(r["hit3"])
        return d
    rnd, eng, mot = by("random guess"), by("steadiest (the corporate engine's rule)"), by("most motion")
    for p in projects:
        if p in rnd:
            n = len(rnd[p]); print(f"  {p[:36]:36s} n={n:2d}  random {100 * sum(rnd[p]) / n:4.0f}%  steadiest {100 * sum(eng[p]) / n:4.0f}%  most-motion {100 * sum(mot[p]) / n:4.0f}%")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="learning")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory", help="read projects and resolve their footage")
    inv.add_argument("roots", nargs="+", help="folders to search for .prproj files")
    inv.add_argument("--footage", nargs="*", default=[], help="extra folders to search for footage (mounted drives, ~/Movies and ~/Downloads are always searched)")
    inv.add_argument("--since", help="only projects last saved on or after YYYY-MM-DD")
    inv.add_argument("--limit", type=int, help="only the newest N projects")
    inv.set_defaults(func=cmd_inventory)
    for name, fn, helptext in (("measure", cmd_measure, "read the raw clips of a seeded sample of labelled shots"), ("evaluate", cmd_evaluate, "score the rules against the editor's choices")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--per-project", type=int, default=8)
        sp.add_argument("--seed", type=int, default=1)
        sp.add_argument("--max-clip-seconds", type=float, default=90.0)
        if name == "measure":
            sp.add_argument("--workers", type=int, default=4)
        sp.set_defaults(func=fn)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
