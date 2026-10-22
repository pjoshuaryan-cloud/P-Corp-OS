"""Tests for description versions, cache reuse and the API usage ledger (backend/app/post_moments.py), with a FAKE Claude client: no real API call is made
and nothing is spent. Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python cost_cache_test.py"""
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_candidate_moments as cm, post_edit_plan as pe, post_moments as pm  # noqa: E402
from app.post_media import FFMPEG_PATH  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


class FakeClient:
    """Answers like Claude would (one described moment), counting calls and reporting token usage."""
    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls += 1
        reply = json.dumps({"scene": "test pattern", "people": False, "events": [{"t": 1.0, "kind": "action", "punch": 7, "what": "the bars move"}]})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)], usage=SimpleNamespace(input_tokens=3000, output_tokens=200))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    clip_path = tmp / "C0001.MP4"
    subprocess.run([FFMPEG_PATH, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_path)], check=True)
    clips = [{"file_id": 1, "name": "C0001.MP4", "path": str(clip_path), "duration": 3.0}, {"file_id": 2, "name": "C0002.MP4", "path": str(clip_path), "duration": 3.0}]
    edit = tmp / "edit_plans"
    edit.mkdir()
    # a description made before versions were recorded (clip 2): it must be reused, never re-described
    pm.save_moments(edit, {"2": {"name": "C0002.MP4", "duration": 3.0, "scene": "old", "people": False, "events": [{"t": 2.0, "kind": "hero", "punch": 8, "what": "old"}]}})

    client = FakeClient()
    report = asyncio.run(pm.probe_missing(client, "claude-sonnet-5-5", clips, edit, max_calls=10))
    moments = pm.load_moments(edit)
    check("only the clip with no description is sent to Claude (the legacy one is reused, which costs nothing)", client.calls == 1 and report["probed"] == 1, (client.calls, report))
    prov = moments["1"].get("provenance") or {}
    check("a new description records the model, prompt version and sampling it was made with", prov.get("model") == "claude-sonnet-5-5" and prov.get("prompt") == pm.PROMPT_VERSION and prov.get("sampler") == pm.SAMPLER_VERSION and prov.get("described_at"), prov)
    check("the legacy description is left exactly as it was (no version invented for it)", "provenance" not in moments["2"] and moments["2"]["scene"] == "old")
    fr = pm.freshness(moments, "claude-sonnet-5-5")
    check("freshness tells current from legacy descriptions", fr == {"current": 1, "legacy": 1, "other_version": 0}, fr)
    check("a different model makes the current one count as another version (reported, not re-run)", pm.freshness(moments, "claude-sonnet-5")["other_version"] == 1)
    changed = json.loads(json.dumps(moments))
    changed["1"]["provenance"]["prompt"] = "0000000000"
    check("a changed prompt is reported as another version", pm.freshness(changed, "claude-sonnet-5-5") == {"current": 0, "legacy": 1, "other_version": 1})
    again = FakeClient()
    asyncio.run(pm.probe_missing(again, "claude-sonnet-5-5", clips, edit, max_calls=10))
    check("a second run with everything described makes no API call at all", again.calls == 0)
    check("the missing list still only looks at the clip's length (a version change never triggers a paid re-run by itself)", pm.missing_clips(clips, changed) == [])

    # ---- the usage ledger ---------------------------------------------------------------------------------------------------------------------
    line = pm.record_usage(edit, job_id=7, operation="describe_clips", model="claude-sonnet-5-5", usage={"in": 1_000_000, "out": 1_000_000, "calls": 2}, extra={"clips_described": 2})
    check("usage is costed at the model's list price ($2 in + $10 out per million for claude-sonnet-5-5)", line["usd"] == 12.0 and "list price" in line["price_basis"], line)
    line2 = pm.record_usage(edit, job_id=7, operation="describe_clips", model="some-unlisted-model", usage={"in": 1_000_000, "out": 0, "calls": 1})
    check("a model with no listed price is costed at the upper bound and says so", line2["usd"] == pm.ASSUMED_USD_PER_M_IN and "upper-bound" in line2["price_basis"], line2)
    with open(edit / pm.USAGE_FILE, "a") as fh:
        fh.write("not json\n")
    summ = pm.usage_summary(edit)
    check("the summary totals runs, calls, tokens and dollars, skipping a corrupt line", summ["by_operation"]["describe_clips"]["runs"] == 2 and summ["by_operation"]["describe_clips"]["calls"] == 3
          and abs(summ["usd_total"] - (12.0 + pm.ASSUMED_USD_PER_M_IN)) < 1e-6, summ)
    check("an empty ledger sums to zero", pm.usage_summary(tmp / "nowhere") == {"by_operation": {}, "usd_total": 0})

    # ---- a real background run records what it used ------------------------------------------------------------------------------------------
    edit2 = tmp / "edit2"
    edit2.mkdir()

    async def run_once():
        fake = FakeClient()
        pm.start_run(99, fake, "claude-sonnet-5-5", clips, edit2, max_calls=10)
        task = pm._RUNS[99]["task"]
        await task
        return fake
    fake = asyncio.run(run_once())
    lines = [json.loads(x) for x in (edit2 / pm.USAGE_FILE).read_text().splitlines()]
    check("a finished Describe run writes one ledger line with the tokens the API reported", len(lines) == 1 and lines[0]["calls"] == fake.calls == 2 and lines[0]["input_tokens"] == 6000
          and lines[0]["output_tokens"] == 400 and lines[0]["clips_described"] == 2 and lines[0]["job_id"] == 99, lines)
    check("...costed at list price (6,000 in + 400 out = $0.016)", abs(lines[0]["usd"] - 0.016) < 1e-9, lines[0]["usd"])

    async def run_cached():
        pm._RUNS.pop(99, None)
        pm.start_run(99, FakeClient(), "claude-sonnet-5-5", clips, edit2, max_calls=10)
        await pm._RUNS[99]["task"]
    asyncio.run(run_cached())
    check("a run with nothing left to describe adds no ledger line (nothing was spent)", len((edit2 / pm.USAGE_FILE).read_text().splitlines()) == 1)

    # ---- estimates -------------------------------------------------------------------------------------------------------------------------------
    old_keys = set(pm.estimate_cost(10))
    new = pm.estimate_cost(165, "claude-sonnet-5-5")
    check("the estimate the app already shows keeps its keys and its upper bound", old_keys == {"clips", "input_tokens", "output_tokens", "usd_at_most", "assumption"} and new["usd_at_most"] == pm.estimate_cost(165)["usd_at_most"])
    check("with the model named, the list-price estimate is added beside it and is lower", new["usd_list_price"] < new["usd_at_most"] and "claude-sonnet-5-5" in new["list_price_basis"], new)
    main_src = (Path(__file__).resolve().parents[2] / "backend" / "app" / "main.py").read_text()
    describe_model = re.search(r'^DESCRIBE_MODEL = "([^"]+)"', main_src, re.M).group(1)
    check("the model the estimates are priced for is the model Describe clips really uses", describe_model == pe.DESCRIBE_MODEL_FOR_ESTIMATES, (describe_model, pe.DESCRIBE_MODEL_FOR_ESTIMATES))

    # ---- provenance reaches the planned shot's record ------------------------------------------------------------------------------------------------
    clip = {"file_id": 1, "name": "C0001.MP4", "duration": 3.0, "events": moments["1"]["events"], "moments_provenance": moments["1"]["provenance"]}
    rec = cm.describe(clip, {"start": 0.75, "duration": 0.5, "source": "event pick (action): the bars move"}, describe_provenance=clip["moments_provenance"])
    check("a candidate built on a versioned description carries that version", rec["provenance"]["describe"] == moments["1"]["provenance"])
    job = {"destination_root": str(tmp / "job"), "profile": "joshx"}
    (tmp / "job" / "09_PROJECT FILES" / "edit_plans").mkdir(parents=True)
    pm.save_moments(tmp / "job" / "09_PROJECT FILES" / "edit_plans", moments)
    attached = pe.attach_moments([dict(c) for c in clips], job)
    check("attach_moments hands a description's version to the planner, and nothing for a legacy one", attached[0].get("moments_provenance") == prov and "moments_provenance" not in attached[1])

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
