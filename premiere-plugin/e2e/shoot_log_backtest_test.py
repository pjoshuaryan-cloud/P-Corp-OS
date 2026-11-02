"""The Shoot Log back-test's own arithmetic: its results decide what gets built, so the rules and gates are checked on made-up clips with known answers. Reads and writes no real data. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python shoot_log_backtest_test.py"""
import base64
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.post_steady import THUMB_H, THUMB_W  # noqa: E402
from learning import shoot_log_backtest as b  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def series(luma=0.4, sharp=0.008, jerk=0.0, seconds=8, thumb=None, seed=0):
    """A clip's cached series: steady brightness and sharpness, motion alternating by `jerk`, per-second thumbnails from `thumb` (or a picture unique to `seed`)."""
    n = seconds * 8
    rng = np.random.default_rng(seed)
    if thumb is None:
        pic = (rng.random((THUMB_H, THUMB_W)) * 0.3 + luma - 0.15).clip(0, 1)
    else:
        pic = np.full((THUMB_H, THUMB_W), thumb, float)
    thumbs = np.repeat((pic * 255).astype(np.uint8)[None], seconds, axis=0)
    return {"fps": 8.0, "luma": [luma] * n, "sharp": [sharp] * n, "motion": [0.02 + (jerk if i % 2 else 0.0) for i in range(n)], "hi": [0.0] * n, "spikes": [], "seconds": float(seconds),
            "thumbs": base64.b64encode(thumbs.tobytes()).decode("ascii"), "thumb_n": seconds}


def clip(name, duration=8.0, **kw):
    return {"name": name, "duration": duration, "m": series(seed=sum(map(ord, name)), **kw)}


# ---- reject rule --------------------------------------------------------------------------------------------------------------------------------------------
check("an unreadable clip is rejected", b.rejected(None))
check("a clip black from start to finish is rejected", b.rejected(b.clip_stats(series(luma=0.095))))
check("a normal S-Log3 clip is not", not b.rejected(b.clip_stats(series(luma=0.36))))
half = series(luma=0.095)
half["luma"][:32] = [0.4] * 32
check("a clip black for half its length is not: he may want the other half", not b.rejected(b.clip_stats(half)))

# ---- check flags, one at a time on an otherwise ordinary shoot ------------------------------------------------------------------------------------------------
ordinary = [clip(f"C{i}") for i in range(20)]
flags = b.check_flags(ordinary + [clip("soft", sharp=0.001), clip("dark", luma=0.15), clip("bright", luma=0.7), clip("blown", thumb=0.9), clip("crushed", thumb=0.1), clip("shaky", jerk=0.2),
                                  clip("short", duration=1.5)])
for flag, name in (("soft", "soft"), ("under", "dark"), ("over", "bright"), ("blown", "blown"), ("crushed", "crushed"), ("shaky", "shaky"), ("short", "short")):
    check(f"{flag} fires on the clip built to trigger it", name in flags[flag], flags[flag])
check("the shakiest-tenth rule doesn't flag a shoot's ordinary clips when one really is shaky", not {c["name"] for c in ordinary} & flags["shaky"], flags["shaky"])
check("soft is judged against this shoot, so flat Log isn't all called soft", not b.check_flags([clip(f"L{i}", sharp=0.002) for i in range(10)])["soft"])
same = {"name": "again", "duration": 8.0, "m": ordinary[3]["m"]}
dup = b.check_flags(ordinary + [same])["near_duplicate"]
check("a repeat of an earlier clip is a near-duplicate, the first of them isn't", "again" in dup and ordinary[3]["name"] not in dup, dup)
check("different pictures aren't near-duplicates", not b.check_flags(ordinary)["near_duplicate"])
check("a shoot with nothing readable has no flags and doesn't crash", not any(b.check_flags([{"name": "x", "duration": 5.0, "m": None}]).values()))

# ---- sort -----------------------------------------------------------------------------------------------------------------------------------------------------
check("the sort takes the best moment, then how many", b.sort_score({"events": [{"punch": 4}, {"punch": 8}]}) == 8.02)
check("an undescribed clip sorts last", b.sort_score(None) == 0.0 and b.sort_score({"events": []}) == 0.0)
perfect, labels = list(range(20, 0, -1)), [1] * 10 + [0] * 10
s = b.sort_summary(perfect, labels)
check("a perfect sort puts all his clips in the top half and none in the bottom quarter", s["top_half"] == 1.0 and s["bottom_quarter"] == 0.0 and s["share_reviewed_for_80pct"] == 0.4, s)
tied = b.sort_summary([1.0] * 2000, [1] * 1000 + [0] * 1000)
check("all-equal scores land at chance, so ties can't flatter a score", abs(tied["top_half"] - 0.5) < 0.05 and abs(tied["bottom_quarter"] - 0.25) < 0.05, tied)
auc, boots = b.auc_with_range(perfect, labels)
check("AUC 1.0 for a perfect sort", auc == 1.0 and min(boots) == 1.0)
check("AUC 0.5 for all-equal scores", b.auc_with_range([1.0] * 20, labels)[0] == 0.5)

# ---- gates, at their edges ------------------------------------------------------------------------------------------------------------------------------------
check("rejects: exactly 5% passes", b.gate_rejects(5, 100)["passed"])
check("rejects: just over 5% fails", not b.gate_rejects(6, 100)["passed"])
check("rejects: nothing to measure doesn't pass", not b.gate_rejects(0, 0)["passed"])
check("sort: 0.60 with a low end above 0.50 passes", b.gate_sort([0.60, 0.60], [[0.55] * 100, [0.65] * 100])["passed"])
check("sort: 0.59 fails", not b.gate_sort([0.59, 0.59], [[0.55] * 100, [0.65] * 100])["passed"])
check("sort: a high AUC whose range reaches 0.50 fails", not b.gate_sort([0.70, 0.70], [[0.50] * 100, [0.50] * 100])["passed"])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
