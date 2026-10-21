"""The RHYTHM of Josh's real edits, measured from his saved Premiere projects, and the groups they fall into.

Why rhythm and not moments: which part of a clip he cuts on needs the raw footage on a drive (21 projects). How FAST he cuts, how many shots he uses,
how much he slows down or speeds up needs only the timeline inside the project file (about 170 projects). So this is the one thing about his taste that
can be learned from nearly everything he has ever made.

What it does:
  * reads data/learning/inventory.json (written by `learning.cli inventory`; the corrected one, after the zero-value parser fix),
  * keeps real edits (video 1, inside the exported range; drops Adobe tutorial projects, lists of whole clips, and sequences too short to have a rhythm),
  * measures each edit (median shot, cut rate, how many shots are under half a second, how regular the rhythm is, how much is slowed or sped up, how much
    a clip is reused, how the pace moves from the first third to the last),
  * groups them by those measures (k-means, plain numpy) and prints each group with example projects so Josh can NAME them.

Run from backend/:   .venv/bin/python -m learning.rhythm [--k N] [--inventory FILE] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data" / "learning"
INVENTORY = DATA / "inventory.json"
OUT = DATA / "rhythm_groups.json"

MIN_SHOTS = 8                 # fewer than this has no rhythm to speak of
WHOLE_CLIP_SHARE = 0.8        # median share of a source clip that each shot uses; above this the sequence is a clip list, not an edit (same rule as post_autosave)
MIN_SECONDS = 5.0             # shorter than this is a test, not a delivered edit
MAX_SECONDS = 600.0           # a ten-minute-plus timeline is a working timeline, not a cut with a rhythm
SKIP_PATH_PARTS = ("/Users/Shared/", "/Tutorial/", "Get Started")   # Adobe's own sample projects. NOT "/Adobe/Premiere Pro": Premiere keeps his own projects and auto-saves under Documents/Adobe/Premiere Pro
RETIME_TOLERANCE = 0.05       # speed within 5% of real time is not a retime
SHORT_SHOT_SECONDS = 0.5
LONG_SHOT_SECONDS = 2.0
CLUSTER_FEATURES = ("log_median", "cv", "short_share", "slowed_share", "log_seconds")


def pct(values: list[float], q: float) -> float:
    ranked = sorted(values)
    return ranked[min(len(ranked) - 1, int(q * len(ranked)))]


def v1_shots(edit: dict) -> list[dict]:
    return sorted((s for s in edit["shots"] if s.get("track") == 1), key=lambda s: s["t0"])


def measure(edit: dict) -> dict | None:
    """The rhythm of one edit, or None when it has none worth measuring (see the module note for why)."""
    shots = v1_shots(edit)
    if len(shots) < MIN_SHOTS:
        return None
    lengths = [s["t1"] - s["t0"] for s in shots if s["t1"] > s["t0"]]
    if len(lengths) < MIN_SHOTS:
        return None
    seconds = edit.get("length") or shots[-1]["t1"]
    if not (MIN_SECONDS <= seconds <= MAX_SECONDS):
        return None
    shares = [(s["src_out"] - s["src_in"]) / s["src_duration"] for s in shots if s.get("src_duration") and s["src_duration"] > 0]
    if shares and statistics.median(shares) >= WHOLE_CLIP_SHARE:
        return None
    speeds = [s["speed"] for s in shots if s.get("speed")]
    slowed = [v for v in speeds if v < 1 - RETIME_TOLERANCE]
    sped = [v for v in speeds if v > 1 + RETIME_TOLERANCE]
    third = max(1, len(lengths) // 3)
    first, last = statistics.median(lengths[:third]), statistics.median(lengths[-third:])
    clips = {s["recorded_path"] for s in shots if s.get("recorded_path")}
    on_top = sum(1 for s in edit["shots"] if s.get("track", 1) > 1)
    mean_len = statistics.mean(lengths)
    return {
        "lengths": [round(l, 3) for l in lengths],
        "shots": len(lengths), "seconds": round(seconds, 2), "median_shot": round(statistics.median(lengths), 3), "mean_shot": round(mean_len, 3),
        "p10": round(pct(lengths, 0.10), 3), "p90": round(pct(lengths, 0.90), 3), "cv": round(statistics.pstdev(lengths) / mean_len, 3),
        "cuts_per_second": round(len(lengths) / seconds, 3),
        "short_share": round(sum(1 for l in lengths if l < SHORT_SHOT_SECONDS) / len(lengths), 3),
        "long_share": round(sum(1 for l in lengths if l >= LONG_SHOT_SECONDS) / len(lengths), 3),
        "retimed_share": round((len(slowed) + len(sped)) / len(speeds), 3) if speeds else 0.0,
        "slowed_share": round(len(slowed) / len(speeds), 3) if speeds else 0.0,
        "sped_share": round(len(sped) / len(speeds), 3) if speeds else 0.0,
        "slowed_median_speed": round(statistics.median(slowed), 3) if slowed else None,
        "sped_median_speed": round(statistics.median(sped), 3) if sped else None,
        "shots_per_clip": round(len(lengths) / max(1, len(clips)), 2),
        "pace_change": round(last / first, 2) if first > 0 else None,   # >1: the last third's shots are longer than the first third's
        "layered_share": round(on_top / max(1, len(edit["shots"])), 3),
    }


def fingerprint(edit: dict) -> tuple:
    """The same cut stored in two copies of a project (BOS REVISION and BOS REVISION_1) must count once: same number of shots, same length, same first source moments."""
    shots = v1_shots(edit)
    return (len(shots), round(edit.get("length") or 0, 1), tuple((Path(s.get("recorded_path") or "").name.lower(), round(s.get("src_in") or 0, 1)) for s in shots[:4]))


def load_edits(path: Path = INVENTORY) -> tuple[list[dict], dict]:
    """[{project, sequence, date, ...measures}] for every usable edit, and a count of what was left out and why."""
    inv = json.loads(Path(path).read_text())
    kept: list[dict] = []
    left_out = {"tutorial or sample project": 0, "no rhythm to measure (too few shots, wrong length, or a clip list)": 0, "copy of an edit already counted": 0}
    total = 0
    seen: set[tuple] = set()
    for rec in sorted(inv["records"], key=lambda r: -(r.get("mtime") or 0)):   # newest copy of a cut is the one kept
        if any(part in rec.get("file", "") for part in SKIP_PATH_PARTS):
            left_out["tutorial or sample project"] += len(rec.get("edits", []))
            continue
        for edit in rec.get("edits", []):
            total += 1
            m = measure(edit)
            if m is None:
                left_out["no rhythm to measure (too few shots, wrong length, or a clip list)"] += 1
                continue
            fp = fingerprint(edit)
            if fp in seen:
                left_out["copy of an edit already counted"] += 1
                continue
            seen.add(fp)
            kept.append({"project": rec["project"], "sequence": edit["sequence"], "mtime": rec.get("mtime"), **m})
    left_out["edits looked at"] = total + left_out["tutorial or sample project"]
    return kept, left_out


def design_matrix(edits: list[dict]) -> np.ndarray:
    rows = [[math.log(e["median_shot"]), e["cv"], e["short_share"], e["slowed_share"], math.log(e["seconds"])] for e in edits]
    x = np.array(rows, dtype=float)
    return (x - x.mean(axis=0)) / np.where(x.std(axis=0) == 0, 1.0, x.std(axis=0))


def kmeans(x: np.ndarray, k: int, restarts: int = 25, seed: int = 7) -> tuple[np.ndarray, np.ndarray, float]:
    """Plain k-means with k-means++ starts; the best of several restarts. Returns (labels, centres, total squared distance)."""
    rng = np.random.default_rng(seed)
    best = (None, None, math.inf)
    for _ in range(restarts):
        centres = [x[rng.integers(len(x))]]
        while len(centres) < k:
            d2 = np.min(((x[:, None, :] - np.array(centres)[None, :, :]) ** 2).sum(axis=2), axis=1)
            centres.append(x[rng.choice(len(x), p=d2 / d2.sum())] if d2.sum() > 0 else x[rng.integers(len(x))])
        centres = np.array(centres)
        for _ in range(100):
            labels = np.argmin(((x[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2), axis=1)
            new = np.array([x[labels == j].mean(axis=0) if np.any(labels == j) else centres[j] for j in range(k)])
            if np.allclose(new, centres):
                break
            centres = new
        inertia = float(((x - centres[labels]) ** 2).sum())
        if inertia < best[2]:
            best = (labels, centres, inertia)
    return best


def silhouette(x: np.ndarray, labels: np.ndarray) -> float:
    """Mean silhouette (-1..1): how much closer each edit is to its own group than to the next nearest group. Above ~0.5 = clear groups, below ~0.25 = a smear."""
    ks = sorted(set(labels))
    if len(ks) < 2:
        return 0.0
    d = np.sqrt(((x[:, None, :] - x[None, :, :]) ** 2).sum(axis=2))
    scores = []
    for i in range(len(x)):
        own = labels == labels[i]
        if own.sum() <= 1:
            scores.append(0.0)
            continue
        a = d[i][own].sum() / (own.sum() - 1)
        b = min(d[i][labels == k].mean() for k in ks if k != labels[i])
        scores.append((b - a) / max(a, b))
    return float(np.mean(scores))


def describe_group(members: list[dict]) -> dict:
    med = lambda key: round(statistics.median(m[key] for m in members), 3)
    paces = [m["pace_change"] for m in members if m["pace_change"] is not None]
    slow = [m["slowed_median_speed"] for m in members if m["slowed_median_speed"] is not None]
    return {"edits": len(members), "projects": len({m["project"] for m in members}), "median_shot": med("median_shot"), "p10": med("p10"), "p90": med("p90"), "cv": med("cv"),
            "cuts_per_second": med("cuts_per_second"), "short_share": med("short_share"), "long_share": med("long_share"), "retimed_share": med("retimed_share"),
            "slowed_share": med("slowed_share"), "sped_share": med("sped_share"), "slowed_median_speed": round(statistics.median(slow), 2) if slow else None,
            "seconds": med("seconds"), "shots": med("shots"), "shots_per_clip": med("shots_per_clip"), "pace_change": round(statistics.median(paces), 2) if paces else None,
            "layered_share": med("layered_share")}


def group_edits(edits: list[dict], k: int) -> list[dict]:
    x = design_matrix(edits)
    labels, centres, _ = kmeans(x, k)
    groups = []
    for j in range(k):
        idx = [i for i in range(len(edits)) if labels[i] == j]
        if not idx:
            continue
        # examples: the edits nearest the group's centre, one per project, so a project that was cut in three versions is not three examples
        order = sorted(idx, key=lambda i: float(((x[i] - centres[j]) ** 2).sum()))
        seen, examples = set(), []
        for i in order:
            if edits[i]["project"] not in seen:
                seen.add(edits[i]["project"])
                examples.append(i)
            if len(examples) == 6:
                break
        members = [edits[i] for i in idx]
        groups.append({"summary": describe_group(members), "examples": [{k2: edits[i][k2] for k2 in ("project", "sequence", "seconds", "shots", "median_shot", "retimed_share")} for i in examples],
                       "members": [{"project": m["project"], "sequence": m["sequence"]} for m in members]})
    groups.sort(key=lambda g: g["summary"]["median_shot"])
    return groups


def choose_k(edits: list[dict], low: int = 2, high: int = 6) -> tuple[int, dict[int, float]]:
    x = design_matrix(edits)
    scores = {k: round(silhouette(x, kmeans(x, k)[0]), 3) for k in range(low, high + 1)}
    return max(scores, key=scores.get), scores


def report(groups: list[dict]) -> str:
    out = []
    for n, g in enumerate(groups, start=1):
        s = g["summary"]
        out.append(f"\nGROUP {n}: {s['edits']} edits from {s['projects']} projects")
        out.append(f"  median shot {s['median_shot']} s (p10 {s['p10']}, p90 {s['p90']}); {s['cuts_per_second']} cuts/s; {round(100 * s['short_share'])}% of shots under half a second; "
                   f"{round(100 * s['long_share'])}% over 2 s; regularity cv {s['cv']}")
        out.append(f"  typical edit {s['seconds']} s, {s['shots']} shots; {s['shots_per_clip']} shots per source clip; layered share {round(100 * s['layered_share'])}%; "
                   f"pace last third vs first {s['pace_change']}x")
        out.append(f"  retimed {round(100 * s['retimed_share'])}% (slowed {round(100 * s['slowed_share'])}%, median {s['slowed_median_speed']}x; sped up {round(100 * s['sped_share'])}%)")
        for e in g["examples"]:
            out.append(f"    - {e['project'][:44]:44s} | {e['sequence'][:28]:28s} | {e['seconds']:6.1f} s | {e['shots']:3d} shots | median {e['median_shot']} s | retimed {round(100 * e['retimed_share'])}%")
    return "\n".join(out)


PACE_GATE = 0.15   # fixed BEFORE the hold-out was run: a learned pace is adopted only if its typical error (median |log(predicted/actual median shot)|) is at least this much lower than EVERY existing preset's


def holdout_errors(edits: list[dict], presets: dict[str, float]) -> dict[str, list[tuple[str, float]]]:
    """Leave-one-PROJECT-out: for each edit, predict its median shot from the OTHER projects only (a constant, and a straight line in log length) and from each
    preset's own pace. {predictor: [(project, |log(predicted/actual)|)]}. 0.10 = 10% off, 0.69 = twice as slow or fast."""
    errors: dict[str, list[tuple[str, float]]] = {"constant (median of your other edits)": [], "length-aware (your other edits)": [], **{f"preset: {k}": [] for k in presets}}
    for project in sorted({e["project"] for e in edits}):
        test, train = [e for e in edits if e["project"] == project], [e for e in edits if e["project"] != project]
        if not test or len(train) < 10:
            continue
        constant = statistics.median(e["median_shot"] for e in train)
        xs, ys = [math.log(e["seconds"]) for e in train], [math.log(e["median_shot"]) for e in train]
        slope, intercept = np.polyfit(xs, ys, 1) if np.std(xs) > 1e-9 else (0.0, float(np.mean(ys)))   # every training edit the same length: no slope to fit
        for e in test:
            actual = e["median_shot"]
            errors["constant (median of your other edits)"].append((project, abs(math.log(constant / actual))))
            errors["length-aware (your other edits)"].append((project, abs(intercept + slope * math.log(e["seconds"]) - math.log(actual))))
            for k, pace in presets.items():
                errors[f"preset: {k}"].append((project, abs(math.log(pace / actual))))
    return errors


def holdout_pace(edits: list[dict], presets: dict[str, float]) -> list[tuple[str, float, float]]:
    """[(predictor, typical error = median error, share within 25%)], best first."""
    rows = [(name, statistics.median(d for _, d in v), sum(1 for _, d in v if d <= math.log(1.25)) / len(v)) for name, v in holdout_errors(edits, presets).items() if v]
    return sorted(rows, key=lambda r: r[1])


def pace_gate(rows: list[tuple[str, float, float]]) -> tuple[bool, float | None, float | None]:
    """(met, best learned error, best preset error). Met only when the best learned predictor beats EVERY preset by PACE_GATE."""
    learned = [r[1] for r in rows if r[0].startswith(("constant", "length-aware"))]
    preset = [r[1] for r in rows if r[0].startswith("preset")]
    if not learned or not preset:
        return False, min(learned, default=None), min(preset, default=None)
    return min(learned) <= min(preset) - PACE_GATE, min(learned), min(preset)


def slowmo_by_frame_rate(inventory: Path = INVENTORY, kept: list[dict] | None = None) -> dict:
    """Which of his shots are slowed, by the SOURCE footage's frame rate (read from each project file, so it needs no footage on a drive).
    Only the shots of the edits `load_edits` keeps. {class: {shots, slowed, about_half, sped_up, median_slowed_speed}} plus the per-edit spread for high-fps footage."""
    from learning import dataset, prproj
    kept = load_edits(inventory)[0] if kept is None else kept
    wanted = {(e["project"], e["sequence"]) for e in kept}
    classes: dict[str, list[float]] = {"48 fps or more": [], "23 to 31 fps": [], "other": []}
    per_edit: dict[tuple, list[bool]] = {}
    for rec in json.loads(Path(inventory).read_text())["records"]:
        if not rec.get("edits") or not Path(rec["file"]).exists():
            continue
        try:
            sequences = prproj.read_sequences(rec["file"])
        except Exception:   # an unreadable project must not stop the rest
            continue
        for edit in dataset.delivered_edits(sequences):
            key = (rec["project"], edit["sequence"].name)
            if key not in wanted:
                continue
            for s in (s for s in edit["shots"] if s.track == 1 and s.speed and s.src_fps):
                name = "48 fps or more" if s.src_fps >= 48 else "23 to 31 fps" if 23 <= s.src_fps <= 31 else "other"
                classes[name].append(s.speed)
                if name == "48 fps or more":
                    per_edit.setdefault(key, []).append(s.speed < 1 - RETIME_TOLERANCE)
    out: dict = {}
    for name, speeds in classes.items():
        slowed = [v for v in speeds if v < 1 - RETIME_TOLERANCE]
        out[name] = {"shots": len(speeds), "slowed": len(slowed), "about_half": sum(1 for v in speeds if 0.4 <= v <= 0.6), "sped_up": sum(1 for v in speeds if v > 1 + RETIME_TOLERANCE),
                     "median_slowed_speed": round(statistics.median(slowed), 2) if slowed else None}
    shares = [sum(v) / len(v) for v in per_edit.values() if len(v) >= 8]
    out["per_edit_share_slowed_on_high_fps"] = {"edits": len(shares), **({q: round(pct(shares, f), 2) for q, f in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9))} if shares else {}),
                                                "never_slowed": sum(1 for x in shares if x == 0)}
    return out


USUAL_PACE_FILE = Path(__file__).resolve().parent.parent / "app" / "post_usual_pace.json"   # in git (backend/data is not), read by app/post_style.py
USUAL_MAX_MEDIAN = 1.5      # an edit whose median shot is longer than this is long-form (interviews, films), not the music-driven pace being learned
USUAL_MAX_SECONDS = 120.0
USUAL_POINTS = 100          # the shot-length distribution is stored as this many evenly spaced quantiles; the planner draws from them at random
USUAL_MIN_SHOT = 0.25       # the shortest shot the planner may cut at this pace (about six frames at 25 fps); his own p10 is 0.28-0.38 s
USUAL_MAX_SHOT = 4.5        # the longest, same cap as the highlight planner


def weighted_quantiles(values: list[float], weights: list[float], points: int) -> list[float]:
    """`points` evenly spaced quantiles (the midpoints 0.5/points, 1.5/points, ...) of a weighted sample."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    total = sum(weights)
    out, cum, k = [], 0.0, 0
    for n in range(points):
        target = (n + 0.5) / points * total
        while k < len(order) - 1 and cum + weights[order[k]] < target:
            cum += weights[order[k]]
            k += 1
        out.append(values[order[k]])
    return out


def usual_pace(edits: list[dict], opener_seconds: float, closing_hold_seconds: float) -> dict:
    """His usual rhythm, ready for the planner: the shots (video 1, last shot left out because it is a closing hold) of his short, fast edits, each EDIT counting
    equally however many shots it has, as `USUAL_POINTS` quantiles of shot length. `opener_seconds` / `closing_hold_seconds` are the brand-card timings the
    highlight planner already uses; they are carried along so the style does not depend on any reference file at run time."""
    chosen = [e for e in edits if e["median_shot"] < USUAL_MAX_MEDIAN and e["seconds"] < USUAL_MAX_SECONDS and len(e["lengths"]) >= MIN_SHOTS]
    if not chosen:
        raise ValueError("no short, fast edits to learn a usual pace from")
    values, weights = [], []
    for e in chosen:
        body = e["lengths"][:-1]
        values += body
        weights += [1.0 / len(body)] * len(body)
    quantiles = [round(min(USUAL_MAX_SHOT, max(USUAL_MIN_SHOT, v)), 3) for v in weighted_quantiles(values, weights, USUAL_POINTS)]
    return {
        "made": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "selection": f"video 1 shots (the last shot of each edit left out) of your edits under {USUAL_MAX_SECONDS:.0f} s whose median shot is under {USUAL_MAX_MEDIAN} s, every edit counting equally; "
                     f"the same cut stored in two project copies counts once; Adobe's tutorial projects and clip lists are left out",
        "from_edits": len(chosen), "from_projects": len({e["project"] for e in chosen}), "shots_pooled": len(values),
        "typical_seconds": round(statistics.median(e["seconds"] for e in chosen), 1),
        "median_shot": round(statistics.median(quantiles), 3), "p10": round(quantiles[len(quantiles) // 10], 3), "p90": round(quantiles[(9 * len(quantiles)) // 10], 3),
        "min_shot_seconds": USUAL_MIN_SHOT, "max_shot_seconds": USUAL_MAX_SHOT,
        "opener_seconds": round(opener_seconds, 2), "closing_hold_seconds": round(closing_hold_seconds, 2),
        "body_lengths": quantiles,
    }


def export_usual_pace(edits: list[dict], path: Path = USUAL_PACE_FILE) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.post_style import profile_from_references
    story = profile_from_references(["corporate-highlight-calm"]).story
    pace = usual_pace(edits, story.opener_seconds, story.closing_hold_seconds)
    Path(path).write_text(json.dumps(pace, indent=1) + "\n")
    return pace


def preset_paces() -> dict[str, float]:
    """The median shot length of each style the planner can build from today, read from its own profiles (empty when the planner's reference store isn't reachable)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    out: dict[str, float] = {}
    try:
        from app.post_style import profile_from_references
        for slug in ("corporate-highlight-calm", "jd-sports-moa-draft-01", "energy-drink-powerade", "fashion-event-converse-kenzo", "furniture-expo-decorex"):
            try:
                out[slug] = statistics.median(profile_from_references([slug]).shot_lengths)
            except Exception:
                continue
    except Exception:
        pass
    return out


def print_holdout(edits: list[dict]) -> None:
    presets = preset_paces()
    print("preset paces (median shot, s): " + ", ".join(f"{k} {v:.2f}" for k, v in presets.items()))
    for label, subset in (("all edits", edits), ("under 2 minutes", [e for e in edits if e["seconds"] < 120]), ("25-60 s", [e for e in edits if 25 <= e["seconds"] <= 60])):
        rows = holdout_pace(subset, presets)
        print(f"\n{label}: {len(subset)} edits from {len({e['project'] for e in subset})} projects")
        for name, err, within in rows:
            print(f"  {name:62s} typical error {err:.2f} (x{math.exp(err):.2f})  within 25%: {round(100 * within)}%")
        met, best_learned, best_preset = pace_gate(rows)
        if best_learned is not None and best_preset is not None:
            print(f"  gate (learned must beat EVERY preset by {PACE_GATE}): best learned {best_learned:.2f} vs best preset {best_preset:.2f} -> " + ("MET" if met else "NOT MET"))


def print_slowmo(inventory: Path, edits: list[dict]) -> None:
    res = slowmo_by_frame_rate(inventory, edits)
    print("shots slowed or sped up, by the source footage's frame rate (video 1 shots of the measured edits):")
    for name in ("48 fps or more", "23 to 31 fps", "other"):
        r = res[name]
        if r["shots"]:
            print(f"  {name:15s} {r['shots']:5d} shots: slowed {round(100 * r['slowed'] / r['shots'], 1)}% (about half speed {round(100 * r['about_half'] / r['shots'], 1)}%, median slowed shot {r['median_slowed_speed']}x), sped up {round(100 * r['sped_up'] / r['shots'], 1)}%")
    p = res["per_edit_share_slowed_on_high_fps"]
    print(f"  per edit, share of its 48+ fps shots that are slowed: {p}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--inventory", default=str(INVENTORY))
    ap.add_argument("--k", type=int, default=0, help="number of groups (default: the one with the clearest groups, 2 to 6)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--holdout", action="store_true", help="test learned pace against the planner's own presets (leave-one-project-out) instead of grouping")
    ap.add_argument("--slowmo", action="store_true", help="which shots he slows down, by the source footage's frame rate, instead of grouping")
    ap.add_argument("--export-usual-pace", action="store_true", help=f"write his usual shot rhythm to {USUAL_PACE_FILE.name} (the planner's default style reads it)")
    args = ap.parse_args(argv)
    edits, left_out = load_edits(Path(args.inventory))
    if args.export_usual_pace:
        pace = export_usual_pace(edits)
        print(f"written {USUAL_PACE_FILE}: {pace['from_edits']} edits from {pace['from_projects']} projects, {pace['shots_pooled']} shots; median shot {pace['median_shot']} s (p10 {pace['p10']}, p90 {pace['p90']}); typical edit {pace['typical_seconds']} s")
        return 0
    if args.holdout:
        print_holdout(edits)
        return 0
    if args.slowmo:
        print_slowmo(Path(args.inventory), edits)
        return 0
    print(f"{len(edits)} edits from {len({e['project'] for e in edits})} projects measured; left out: " + ", ".join(f"{v} {k}" for k, v in left_out.items() if k != "edits looked at"))
    if len(edits) < 12:
        print("too few edits to group")
        return 1
    k, scores = (args.k, {}) if args.k else choose_k(edits)
    if scores:
        print("clearness of the groups by number of groups (silhouette; ~0.5+ clear, ~0.25 or less a smear): " + ", ".join(f"{kk}: {v}" for kk, v in scores.items()))
    print(f"using {k} groups")
    groups = group_edits(edits, k)
    print(report(groups))
    Path(args.out).write_text(json.dumps({"made": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "k": k, "silhouette": scores, "left_out": left_out, "edits": edits, "groups": groups}, indent=1))
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
