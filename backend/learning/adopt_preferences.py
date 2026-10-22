"""Lets what Josh's recorded decisions say about KINDS of moment (hero, reveal, action, ...) reach the planner -- but only if it holds up on edits it never saw.

The learning events (app/post_learning_events.py) count, per kind of moment the planner proposed, how often he kept it and how often he changed it (taste evidence
only: never an uncertain observation, never a change he said the client asked for). Once there are at least 30 such votes, `ranking_adjustments` proposes a small
nudge per kind (at most +-0.15, about one punch point of a described moment). This command decides whether that nudge is ADOPTED:

  1. the held-out test: on the 168 labelled shots of his finished edits (learning/taste.py's sample) the planner's order of a clip's described moments (strongest
     punch first) is compared with the same order plus the nudge; any shot whose clip appears anywhere in the events is left out, so nothing is tested on the
     decisions it was learned from;
  2. the gate, fixed before any run (the same bar as every other learning experiment here): the nudged order must win at least 10 more shots than it loses on BOTH
     the first pick and the top three;
  3. only then, and only with --save, the adopted file the planner reads (data/learning/adopted_kind_preferences.json) is written. A later run whose gate fails
     removes it again. Without that file every plan is exactly what it would have been.

Run from backend/:
  .venv/bin/python -m learning.adopt_preferences                                   report only
  .venv/bin/python -m learning.adopt_preferences --import "<job>/.../edit_plans"   first copy a job's review logs and events into the central store (repeatable)
  .venv/bin/python -m learning.adopt_preferences --save                            write (or remove) the adopted file
No Claude call, no drive needed after the import (the labelled shots' descriptions and measurements are cached in data/learning/).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from app import post_learning_events as le
from app import post_pick

GATE_MIN_NET_SHOTS = 10   # same bar as learning/taste.py, placement.py and the rhythm study: fixed before looking at any result
FEEDBACK_DIR = le._DATA / "feedback"


def _lines(path: Path) -> list[dict[str, Any]]:
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def import_sources(edit_dirs: list[Path], feedback_dir: Path = FEEDBACK_DIR, central: Path | None = None) -> dict[str, int]:
    """Copies what already exists into the central store: every Learn From My Edit / auto-save record, and for each job folder given its review log, slow-motion
    log and learning-events file. Event ids are deterministic, so importing twice adds nothing. Returns how many new events came from each kind of source."""
    central = central or le.CENTRAL_EVENTS
    added = {"learn_records": 0, "review_log": 0, "speed_log": 0, "job_events": 0}
    for f in sorted(Path(feedback_dir).glob("job*.json")):
        try:
            added["learn_records"] += le.append_events(central, le.from_learn_record(json.loads(f.read_text())))
        except (OSError, ValueError):
            continue
    for d in edit_dirs:
        d = Path(d)
        added["review_log"] += le.append_events(central, [e for rec in _lines(d / "review_log.jsonl") for e in le.from_review_record(rec)])
        added["speed_log"] += le.append_events(central, [e for rec in _lines(d / "review_speed_log.jsonl") for e in le.from_speed_record(rec)])
        added["job_events"] += le.append_events(central, le.load_events(d / le.EVENTS_FILE))
    return added


def clip_names(events: list[dict[str, Any]]) -> set[str]:
    """Every clip the events mention (lower-case file names): a labelled shot of one of these clips is NOT a held-out test of what they taught."""
    names = set()
    for e in events:
        for key in ("planned", "replacement"):
            c = e.get(key)
            if isinstance(c, dict) and isinstance(c.get("name"), str):
                names.add(le._basename(c["name"]).lower())
        m = e.get("media")
        if isinstance(m, dict) and isinstance(m.get("name"), str):
            names.add(le._basename(m["name"]).lower())
    return names


def _order(group: dict[str, Any], by_kind: dict[str, float]) -> list[int]:
    """The planner's ranking of a clip's described moments: punch (as the Picker's event bonus) plus the learned nudge for the moment's kind; ties keep Claude's order.
    With no nudge this is exactly Claude's order."""
    def score(i: int) -> float:
        c = group["cands"][i]
        return post_pick.EVENT_QUALITY * c["punch"] / 10.0 + post_pick.PREFERENCE_WEIGHT * by_kind.get(c["kind"], 0.0)
    return sorted(range(len(group["cands"])), key=lambda i: (-score(i), group["cands"][i]["rank"]))


def held_out_test(groups: list[dict[str, Any]], by_kind: dict[str, float], exclude: set[str]) -> dict[str, Any]:
    """First pick and top three, with and without the nudge, over the labelled shots whose clip is not in `exclude`; the gate on the net difference."""
    from learning.taste import _topk_hits
    used = [g for g in groups if le._basename(g["path"]).lower() not in exclude]
    h = {"base": ([], []), "nudged": ([], [])}
    for g in used:
        for arm, prefs in (("base", {}), ("nudged", by_kind)):
            flags = _topk_hits(_order(g, prefs), g, 3) if g["cands"] else []
            h[arm][0].append(bool(flags and flags[0]))
            h[arm][1].append(any(flags))
    net = [sum(1 for a, b in zip(h["base"][k], h["nudged"][k]) if b and not a) - sum(1 for a, b in zip(h["base"][k], h["nudged"][k]) if a and not b) for k in (0, 1)]
    n = max(len(used), 1)
    return {"shots": len(used), "excluded": len(groups) - len(used),
            "base": {"top1": round(sum(h["base"][0]) / n, 4), "top3": round(sum(h["base"][1]) / n, 4)},
            "nudged": {"top1": round(sum(h["nudged"][0]) / n, 4), "top3": round(sum(h["nudged"][1]) / n, 4)},
            "net_top1": net[0], "net_top3": net[1], "met": net[0] >= GATE_MIN_NET_SHOTS and net[1] >= GATE_MIN_NET_SHOTS}


def decide(events: list[dict[str, Any]], groups: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Pure: the whole decision from the events and the labelled shots. {"stage": "not_enough" | "tested", "summary", "proposal", "test"}."""
    summary = le.summarize(events)
    proposal = le.ranking_adjustments(events)
    if proposal is None:
        return {"stage": "not_enough", "summary": summary, "proposal": None, "test": None}
    test = held_out_test(groups or [], proposal["by_kind"], clip_names(events))
    return {"stage": "tested", "summary": summary, "proposal": proposal, "test": test}


def save(decision: dict[str, Any], path: Path | None = None) -> str:
    """Writes the adopted file when the gate passed, removes it when a tested proposal failed; leaves it alone when there isn't enough evidence yet."""
    path = Path(path or le.ADOPTED_PREFERENCES)
    if decision["stage"] != "tested":
        return "unchanged (not enough evidence to test anything)"
    if decision["test"]["met"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"schema": le.EVENT_SCHEMA_VERSION, "by_kind": decision["proposal"]["by_kind"], "support": decision["proposal"]["support"],
                "overall_keep_rate": decision["proposal"]["overall_keep_rate"], "gate": decision["test"], "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "made_by": "learning/adopt_preferences.py"}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=1))
        tmp.replace(path)
        return f"ADOPTED: wrote {path}"
    if path.exists():
        path.unlink()
        return f"gate not met: removed the previously adopted {path}"
    return "gate not met: nothing adopted"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--import", dest="imports", action="append", default=[], metavar="EDIT_PLANS_DIR", help="a job's edit_plans folder to import logs from")
    ap.add_argument("--save", action="store_true", help="write (or remove) the adopted file the planner reads")
    args = ap.parse_args()
    added = import_sources([Path(p) for p in args.imports])
    print(f"imported into {le.CENTRAL_EVENTS}: {added}")
    events = le.load_events(le.CENTRAL_EVENTS)
    s = le.summarize(events)
    print(f"events: {s['total']} ({s['by_confidence']}); taste votes on a kind of moment: {s['taste_votes']} (a proposal needs {le.DEFAULT_MIN_EVENTS})")
    print(f"per kind (shrunk keep rate): {json.dumps(le.kind_evidence(events))}")
    groups = None
    if le.ranking_adjustments(events) is not None:
        from learning.taste import build_groups
        groups = build_groups()
    d = decide(events, groups)
    if d["stage"] == "not_enough":
        print("not enough evidence yet: nothing proposed, nothing tested, the planner is unchanged")
    else:
        t = d["test"]
        print(f"proposal: {d['proposal']['by_kind']} from {d['proposal']['support']} votes")
        print(f"held-out test on {t['shots']} labelled shots ({t['excluded']} left out because their clip is in the events): first pick {t['base']['top1']:.1%} -> "
              f"{t['nudged']['top1']:.1%} (net {t['net_top1']:+d}), top three {t['base']['top3']:.1%} -> {t['nudged']['top3']:.1%} (net {t['net_top3']:+d}); "
              f"gate (+{GATE_MIN_NET_SHOTS} on both): {'MET' if t['met'] else 'not met'}")
    if args.save:
        print(save(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
