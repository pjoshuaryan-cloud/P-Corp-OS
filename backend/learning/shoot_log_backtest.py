"""Before the Shoot Log is built: would its reject rule hide clips Josh really used, and does sorting a shoot put those clips near the top?

Everything is read from data already on this Mac (or the Joshx SSD when it is plugged in). No footage is decoded, no API is called, nothing is written.

  reject rule:  a clip goes to Rejects only if it can't be read or is black for nearly its whole length.
  check flags:  soft, under, over, blown, crushed, shaky, short and near-duplicate only ever say "check", because a flag that hides footage has to be right.
  sort:         best moment Claude described in the clip, then how many moments it described.
  test:         "used" = the clip is on video 1 of his hand-cut edit. An edit seeded from a plan made with these descriptions can't test them, so those are shown but
                can't pass or fail anything.

  GATES, fixed in this file BEFORE the first run:
    rejects:    at most 5% of the clips he used land in Rejects.
    sort:       mean AUC over the hand-cut edits at least 0.60 (10 points better than chance), and the 90% bootstrap low end above 0.50. If it misses, the Shoot Log
                ships without a score and simply groups clips for him to pick.

Limits to read the result with: one S-Log3 shoot (HAUS) has the clip series; JD's series are on the Joshx SSD, so JD can only test the sort until it is plugged in.

Run from backend/:   .venv/bin/python -m learning.shoot_log_backtest
"""
from __future__ import annotations

import glob
import json
import random
from pathlib import Path
from typing import Any

from app.post_shoot_log import clip_flags, clip_stats, near_duplicate_groups, rejected
from learning.transfer_cut import _auc

DATA = Path(__file__).resolve().parents[1] / "data" / "learning"
HAUS = DATA / "projects" / "215347841" / "09_PROJECT FILES" / "edit_plans"
FEEDBACK = DATA / "feedback"

MAX_USED_IN_REJECTS = 0.05
MIN_SORT_AUC = 0.60
MIN_SORT_AUC_LOW_END = 0.50
BOOTSTRAPS = 2000
FLAG_NAMES = ("soft", "under", "over", "blown", "crushed", "shaky", "short", "near_duplicate")


def check_flags(clips: list[dict[str, Any]]) -> dict[str, set[str]]:
    """{flag: names of the clips it fires on}, using the Shoot Log's own rules, for one S-Log3 shoot's clips, each {"name", "duration", "m"}."""
    named = [{**c, "id": c["name"], "profile": "slog3"} for c in clips]
    flags: dict[str, set[str]] = {f: set() for f in FLAG_NAMES}
    for name, items in clip_flags(named).items():
        for item in items:
            flags[item["type"]].add(name)
    flags["near_duplicate"] = {cid for cid, g in near_duplicate_groups(named).items() if g["of"]}
    return flags


def sort_score(moment: dict[str, Any] | None) -> float:
    """The sort being tested: Claude's best moment in the clip, then how many it found. A clip with no description scores 0."""
    events = (moment or {}).get("events") or []
    return max((float(e.get("punch", 0)) for e in events), default=0.0) + 0.01 * min(len(events), 5)


def auc_with_range(scores: list[float], labels: list[int], seed: int = 7) -> tuple[float, list[float]]:
    """AUC and its bootstrap replicates (clips resampled within this shoot)."""
    rng = random.Random(seed)
    n, boots = len(scores), []
    for _ in range(BOOTSTRAPS):
        idx = [rng.randrange(n) for _ in range(n)]
        a = _auc([scores[i] for i in idx], [labels[i] for i in idx])
        if a == a:
            boots.append(a)
    return _auc(scores, labels), boots


def sort_summary(scores: list[float], labels: list[int]) -> dict[str, float]:
    """What the sort would have meant for him: where his clips land if he works down the list. Ties split in a fixed random order, so ties don't flatter a score."""
    rng = random.Random(11)
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], rng.random()))
    used_total = sum(labels)
    half, quarter = len(order) // 2, len(order) // 4
    ranked = [labels[i] for i in order]
    found, to_80 = 0, len(order)
    for pos, hit in enumerate(ranked, 1):
        found += hit
        if found >= 0.8 * used_total:
            to_80 = pos
            break
    return {"clips": len(order), "used": used_total, "top_half": sum(ranked[:half]) / used_total, "bottom_quarter": sum(ranked[-quarter:]) / used_total,
            "share_reviewed_for_80pct": to_80 / len(order)}


def gate_sort(aucs: list[float], boots: list[list[float]]) -> dict[str, Any]:
    """Mean AUC over the hand-cut edits, against the gate fixed above."""
    n = min(len(b) for b in boots)
    means = sorted(sum(b[i] for b in boots) / len(boots) for i in range(n))
    mean, low, high = sum(aucs) / len(aucs), means[int(0.05 * n)], means[int(0.95 * n) - 1]
    return {"mean_auc": mean, "low": low, "high": high, "passed": bool(mean >= MIN_SORT_AUC and low > MIN_SORT_AUC_LOW_END)}


def gate_rejects(used_rejected: int, used_total: int) -> dict[str, Any]:
    share = used_rejected / used_total if used_total else 0.0
    return {"share": share, "passed": bool(used_total and share <= MAX_USED_IN_REJECTS)}


def used_names(record: str) -> set[str]:
    return {s["name"] for s in json.loads((FEEDBACK / record).read_text())["his_shots"]}


def load_haus() -> list[dict[str, Any]]:
    pools = json.loads((HAUS / "clips.json").read_text())
    moments = json.loads((HAUS / "moments.json").read_text())
    steady = json.loads((HAUS / "steadiness.json").read_text())
    clips = []
    for pool, members in pools.items():
        for c in members:
            key = str(c["file_id"])
            clips.append({"name": c["name"], "pool": pool, "duration": float(c["duration"]), "moment": moments.get(key), "m": (steady.get(key) or {}).get("m")})
    return clips


def load_jd() -> list[dict[str, Any]]:
    moments = json.loads((DATA / "jd_moments_sonnet5_2026-10-08.json").read_text())
    return [{"name": v["name"], "pool": "jd", "duration": float(v.get("duration") or 0), "moment": v, "m": None} for v in moments.values()]


def report_sort(title: str, pool: list[dict[str, Any]], used: set[str], gated: bool) -> tuple[float, list[float]]:
    scores = [sort_score(c["moment"]) for c in pool]
    labels = [int(c["name"] in used) for c in pool]
    auc, boots = auc_with_range(scores, labels)
    ordered = sorted(boots)
    s = sort_summary(scores, labels)
    print(f"  {title:<44}{'' if gated else ' (shown only)'}")
    print(f"     {s['used']}/{s['clips']} clips used | AUC {auc:.3f} (90% {ordered[int(.05 * len(boots))]:.2f}-{ordered[int(.95 * len(boots)) - 1]:.2f}) | top half holds {s['top_half']:.0%} of his clips (chance 50%)"
          f" | bottom quarter {s['bottom_quarter']:.0%} (chance 25%) | to reach 80% of them, review {s['share_reviewed_for_80pct']:.0%} of the list")
    return auc, boots


def main() -> None:
    haus, jd = load_haus(), load_jd()
    horizontal = [c for c in haus if c["pool"] == "horizontal"]
    vertical = [c for c in haus if c["pool"] == "vertical"]
    final, rough = used_names("project215347841_20261023T004027.json"), used_names("project215347841_20261022T203333.json")
    vertical_edit = used_names("project215347841_20261023T120326.json")
    draft = used_names("job34_20261021T072906.json")
    jd_edit = used_names("job34_20261021T072906_2.json")

    print("SHOOT LOG BACK-TEST (gates fixed in this file before the first run)\n")
    print("1. REJECT RULE: unreadable, or black for at least 95% of the clip")
    used_haus = {c["name"] for c in haus} & (final | rough | vertical_edit)
    haus_rejected = {c["name"] for c in haus if rejected(clip_stats(c["m"]) if c["m"] else None)}
    measured = [json.loads(Path(p).read_text()) for p in sorted(glob.glob(str(DATA / "measure" / "*.json")))]
    measured_rejected = sum(rejected(clip_stats(m)) for m in measured)
    total_used = len(used_haus) + len(measured)
    used_rejected = len(used_haus & haus_rejected) + measured_rejected
    g = gate_rejects(used_rejected, total_used)
    print(f"  HAUS: {len(haus_rejected)} of {len(haus)} clips rejected, {len(used_haus & haus_rejected)} of the {len(used_haus)} he used")
    print(f"  Clips used across his other measured projects: {measured_rejected} of {len(measured)} rejected")
    print(f"  GATE at most {MAX_USED_IN_REJECTS:.0%} of used clips: {g['share']:.1%} -> {'PASS' if g['passed'] else 'FAIL'}\n")

    print("2. CHECK FLAGS on HAUS horizontal, his finished hand cut (flag | his clips flagged | clips he left out flagged)")
    flags = check_flags(horizontal)
    names = {c["name"] for c in horizontal}
    used, left_out = names & final, names - final
    for f in FLAG_NAMES:
        print(f"  {f:<15}{len(flags[f] & used):>3}/{len(used):<3} {len(flags[f] & used) / len(used):>4.0%}   |  {len(flags[f] & left_out):>3}/{len(left_out):<3} {len(flags[f] & left_out) / max(len(left_out), 1):>4.0%}")
    anywhere = set().union(*flags.values())
    print(f"  {'any flag':<15}{len(anywhere & used):>3}/{len(used):<3} {len(anywhere & used) / len(used):>4.0%}   |  {len(anywhere & left_out):>3}/{len(left_out):<3} {len(anywhere & left_out) / max(len(left_out), 1):>4.0%}")
    print("  If every flag meant reject, as the spec's checks allow, that first 'any flag' figure is how much of his finished cut would have been hidden.\n")

    print("3. SORT: Claude's best moment in the clip, then how many moments")
    a1, b1 = report_sort("HAUS horizontal, finished hand cut", horizontal, final, True)
    a2, b2 = report_sort("JD, hand edit 'draft 01' (older model's descriptions)", jd, draft, True)
    g = gate_sort([a1, a2], [b1, b2])
    print(f"  GATE mean AUC at least {MIN_SORT_AUC:.2f}, low end above {MIN_SORT_AUC_LOW_END:.2f}: {g['mean_auc']:.3f} (90% {g['low']:.2f}-{g['high']:.2f}) -> {'PASS' if g['passed'] else 'FAIL'}\n")
    report_sort("HAUS horizontal, his rough cut (same project)", horizontal, rough, False)
    report_sort("HAUS vertical, his re-edit of the built plan", vertical, vertical_edit, False)
    report_sort("JD, edit built from a plan", jd, jd_edit, False)

    print("\n4. OTHER WAYS TO SORT (shown only; trying several can't pass the gate), AUC on HAUS horizontal's finished cut")
    labels = [int(c["name"] in final) for c in horizontal]
    stats = [clip_stats(c["m"]) for c in horizontal]
    for title, values in (("how many moments Claude found", [len((c["moment"] or {}).get("events") or []) for c in horizontal]), ("sharpness", [s["sharp"] for s in stats]),
                          ("least shaky", [-s["jerk"] for s in stats]), ("most motion", [s["motion"] for s in stats]), ("longest clip", [c["duration"] for c in horizontal])):
        print(f"  {title:<32}{_auc([float(v) for v in values], labels):.3f}")


if __name__ == "__main__":
    main()
