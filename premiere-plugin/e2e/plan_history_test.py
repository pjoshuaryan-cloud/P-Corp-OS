"""Tests for the plan history (backend/app/post_plan_history.py) and the plain style names (post_style.friendly_style).
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python plan_history_test.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_plan_history as ph  # noqa: E402
from app.post_style import FRIENDLY_STYLES, friendly_style  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


def plan(shots=3, *, style="jd-sports-moa-draft-01", seconds=31.8, review=None, accents=None, event=3, steadiest=0, tag=""):
    p = {"style": style, "duration_seconds": seconds, "music": {"source": "/x/Danny Shields - GOOFY (1).mp3"}, "tag": tag,
         "shots": [{"index": i + 1, "file_id": i, "name": f"C{i}.MP4", "source_in": 1.0 + i} for i in range(shots)],
         "checks": {"moment_sources": {"event": event, "steadiest": steadiest}}}
    if review is not None:
        p["review"] = review
    if accents is not None:
        p["accents"] = accents
    return p


def write(folder: Path, name: str, p: dict, mtime: float | None = None):
    f = folder / name
    f.write_text(json.dumps(p))
    if mtime:
        os.utime(f, (mtime, mtime))
    return f


name_of = lambda slug: friendly_style(slug)[0]
NOW = time.time()

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    reviewed = plan(review={"approved": [1, 2, 3], "original": {"1": {}, "2": {}}}, accents={"counts": {}}, tag="reviewed")
    fresh = plan(tag="fresh")
    other = plan(shots=4, style="corporate-highlight-calm", seconds=140.0, event=0, steadiest=4, tag="old steadiest")
    write(d, "edit_plan_latest.json", reviewed, NOW)
    write(d, "edit_plan_prev_20261009T081908.json", reviewed)                 # an archive that is identical to the current plan
    write(d, "edit_plan_YOURS_reviewed_20261009.json", reviewed)              # a copy saved under a name, also identical
    write(d, "edit_plan_prev_20261008T093000.json", fresh)
    write(d, "edit_plan_prev_20261015T160332.json", other)
    write(d, "edit_plan_B_events.json", plan(tag="b events", event=3))
    for junk in ("moments.json", "steadiness.json", "plan_names.json", "edit_plan_latest.json.part", "._edit_plan_prev_x.json", "edit_preview.json"):
        (d / junk).write_text("{}")
    plans = ph.list_plans(d, name_of)
    files = [e["file"] for e in plans]
    check("identical copies are listed once, under the current plan", files[0] == "edit_plan_latest.json" and plans[0]["current"] and set(plans[0]["also_saved_as"]) == {"edit_plan_prev_20261009T081908.json", "edit_plan_YOURS_reviewed_20261009.json"}, plans[0]["also_saved_as"])
    check("only real plans are listed (no moments, steadiness, names, partial or hidden files)", all(f.startswith("edit_plan_") for f in files) and len(files) == 4, files)
    check("a reviewed plan with swaps and accents says so", plans[0]["kind_title"] == "Reviewed (2 swapped) + accents" and plans[0]["swapped"] == 2 and plans[0]["accents"], plans[0]["kind_title"])
    check("a plan saved under a file name shows it in words as 'saved as', and keeps its own plain title", plans[0]["saved_as"] == "YOURS reviewed 20261009" and plans[0]["label"] is None and plans[0]["title"] == plans[0]["kind_title"], (plans[0]["saved_as"], plans[0]["title"]))
    fresh_entry = next(e for e in plans if e["file"] == "edit_plan_prev_20261008T093000.json")
    check("a fresh plan is called one", fresh_entry["kind_title"] == "Fresh plan" and not fresh_entry["accents"] and fresh_entry["swapped"] == 0, fresh_entry["kind_title"])
    check("the line under it gives length, shots, plain style name and how the moments were chosen", fresh_entry["subtitle"] == "31.8 s · 3 shots · Fast streetwear reel · cut on described moments", fresh_entry["subtitle"])
    old_entry = next(e for e in plans if e["file"] == "edit_plan_prev_20261015T160332.json")
    check("an old steadiest-stretch plan says that", old_entry["subtitle"].endswith("Calm corporate highlight · steadiest stretches") and old_entry["seconds"] == 140.0, old_entry["subtitle"])
    check("an archive's date comes from its name (when the plan was made), not when it was copied", old_entry["saved_at"].startswith("2026-10-15T16:03:32"), old_entry["saved_at"])
    check("after the current plan, newest first", [e["saved_at"] for e in plans[1:]] == sorted([e["saved_at"] for e in plans[1:]], reverse=True), [e["saved_at"] for e in plans])

    # ---- restore --------------------------------------------------------------------------------------------------------------------------
    latest_before = (d / "edit_plan_latest.json").read_text()
    result = ph.restore_plan(d, "edit_plan_prev_20261015T160332.json")
    check("restoring a plan makes it the current one", json.loads((d / "edit_plan_latest.json").read_text())["tag"] == "old steadiest" and result["restored"], result)
    check("the plan it replaced was already saved identically, so no clutter was added", result["kept_as"] is None and "edit_plan_prev_20261009T081908.json" in os.listdir(d), result)
    check("the restored plan's own file is still there", (d / "edit_plan_prev_20261015T160332.json").exists())
    again = ph.restore_plan(d, "edit_plan_prev_20261015T160332.json")
    check("restoring the plan that is already current changes nothing", again["restored"] is False and "already" in again["message"])
    new_plan = plan(shots=5, tag="brand new, never saved elsewhere")
    write(d, "edit_plan_latest.json", new_plan)
    before = set(os.listdir(d))
    result = ph.restore_plan(d, "edit_plan_prev_20261008T093000.json")
    added = set(os.listdir(d)) - before
    check("a current plan that isn't saved anywhere else is kept first, then replaced", result["kept_as"] and len(added) == 1 and next(iter(added)) == result["kept_as"] and json.loads((d / result["kept_as"]).read_text())["tag"] == "brand new, never saved elsewhere", (result, added))
    check("the kept plan appears in the history right away", any(e["file"] == result["kept_as"] for e in ph.list_plans(d, name_of)))
    check("restoring leaves every other plan file untouched", all((d / f).exists() for f in ("edit_plan_prev_20261009T081908.json", "edit_plan_YOURS_reviewed_20261009.json", "edit_plan_B_events.json")))
    check("the old current plan is restorable too", json.loads((d / "edit_plan_latest.json").read_text())["tag"] == "fresh" and ph.restore_plan(d, result["kept_as"])["restored"] and json.loads((d / "edit_plan_latest.json").read_text())["tag"] == "brand new, never saved elsewhere")

    # ---- what is refused ----------------------------------------------------------------------------------------------------------------
    outside = Path(tmp).parent / "edit_plan_evil.json"
    outside.write_text(json.dumps(plan()))
    for bad in ("../edit_plan_evil.json", "/etc/passwd", "moments.json", "edit_plan_nothere.json", "", "edit_plan_latest.json.part", "../../x"):
        try:
            ph.restore_plan(d, bad)
            ok = False
        except ph.PlanHistoryError:
            ok = True
        check(f"restore refuses {bad!r}", ok)
    outside.unlink()
    (d / "edit_plan_notaplan.json").write_text(json.dumps({"hello": 1}))
    (d / "edit_plan_garbage.json").write_text("not json at all")
    for bad in ("edit_plan_notaplan.json", "edit_plan_garbage.json"):
        try:
            ph.restore_plan(d, bad)
            ok = False
        except ph.PlanHistoryError:
            ok = True
        check(f"restore refuses {bad} (not a plan)", ok)
    check("files that aren't plans never show in the list", all(e["file"] not in ("edit_plan_notaplan.json", "edit_plan_garbage.json") for e in ph.list_plans(d, name_of)))

    # ---- names ---------------------------------------------------------------------------------------------------------------------------
    r = ph.rename_plan(d, "edit_plan_B_events.json", "  The   first   machine plan ")
    check("a plan can be given a name of your own, tidied", r["label"] == "The first machine plan", r)
    check("the name shows in the history in place of the generated one", next(e for e in ph.list_plans(d, name_of) if e["file"] == "edit_plan_B_events.json")["title"] == "The first machine plan")
    check("a name is capped at 60 characters", len(ph.rename_plan(d, "edit_plan_B_events.json", "x" * 200)["label"]) == 60)
    ph.rename_plan(d, "edit_plan_B_events.json", "")
    check("an empty name removes it again", "edit_plan_B_events.json" not in json.loads((d / "plan_names.json").read_text()))
    try:
        ph.rename_plan(d, "../plan_names.json", "x")
        ok = False
    except ph.PlanHistoryError:
        ok = True
    check("a name can't be given to something that isn't a saved plan", ok)
    check("an empty or missing folder lists nothing", ph.list_plans(Path(tmp) / "nope", name_of) == [] and ph.list_plans(Path(tempfile.mkdtemp()), name_of) == [])

# ---- plain style names --------------------------------------------------------------------------------------------------------------------
check("the saved references have plain names", name_of("corporate-highlight-calm") == "Calm corporate highlight" and name_of("jd-sports-moa-draft-01") == "Fast streetwear reel" and len(FRIENDLY_STYLES) == 8)
check("a style with no plain name falls back to its own title and a first-sentence description", friendly_style("new-style", "Some Client -- event", "A fast reel. With extras and more detail.") == ("Some Client -- event", "A fast reel"), friendly_style("new-style", "Some Client -- event", "A fast reel. With extras and more detail."))
check("a style with nothing at all falls back to its slug", friendly_style("slug-only") == ("slug-only", ""))

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
