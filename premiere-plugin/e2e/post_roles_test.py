"""Tests for backend/app/post_roles.py (reel autopilot phase 3 step 1) with a FAKE Claude client: no API call, nothing real written
(the edit folder is a temp dir)."""
import asyncio, json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_roles as r

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + str(msg)
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

MOMENTS = {
    "11": {"name": "JD_A.MP4", "scene": "Mall JD sign", "people": False, "events": [{"t": 1.0, "kind": "hero", "what": "JD sign readable"}, {"t": 3.0, "kind": "camera_move", "what": "orbit round sign"}]},
    "12": {"name": "JD_B.MP4", "scene": "Ribbon cutting", "people": True, "events": [{"t": 2.0, "kind": "action", "what": "scissors cut ribbon"}]},
    "13": {"name": "JD_C.MP4", "scene": "Sneaker wall", "people": False, "events": []},
}

text, ids = r.describe_for_prompt(MOMENTS)
check("every moment gets an id clip.index, clips without moments add none", ids == ["11.0", "11.1", "12.0"], ids)
check("the prompt carries scene, people and each moment's words", "Mall JD sign | people: no" in text and "11.1 [camera_move] orbit round sign" in text and "Ribbon cutting | people: yes" in text, text)

good = json.dumps({"roles": {"11.0": "place", "11.1": "movement", "12.0": "main_moment", "99.0": "place", "11.0x": "detail"}, "main_clips": ["12", "nope"], "note": "fine"})
p = r.parse_reply("Here you go:\n" + good, ids, set(MOMENTS))
check("parse keeps known ids and roles only", p["roles"] == {"11.0": "place", "11.1": "movement", "12.0": "main_moment"}, p)
check("main clips must be real clips", p["main_clips"] == ["12"], p["main_clips"])
p2 = r.parse_reply(json.dumps({"roles": {"11.0": "place", "11.1": "banana"}}), ids, set(MOMENTS))
check("an unknown role is dropped and the skipped moments are listed as missing, not guessed", p2["roles"] == {"11.0": "place"} and p2["missing"] == ["11.1", "12.0"], p2)
for bad in ("no json here", "{not json}", json.dumps({"x": 1})):
    try:
        r.parse_reply(bad, ids, set(MOMENTS)); ok = False
    except r.RolesError:
        ok = True
    check(f"bad reply raises RolesError ({bad[:12]!r})", ok)

s = r.summarise(p, MOMENTS)
check("summary counts per role", s["counts"] == {"place": 1, "person": 0, "detail": 0, "movement": 1, "main_moment": 1}, s["counts"])
check("summary names the clip and words", s["by_role"]["main_moment"] == [{"moment": "12.0", "clip": "JD_B.MP4", "t": 2.0, "what": "scissors cut ribbon"}] and s["main_clips"] == ["JD_B.MP4"], s)

class FakeClient:
    def __init__(self, reply, stop="end_turn"):
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)
        self.reply, self.stop = reply, stop
    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)], stop_reason=self.stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=200))

with tempfile.TemporaryDirectory() as d:
    edit = Path(d)
    (edit / "moments.json").write_text(json.dumps(MOMENTS))
    fc = FakeClient(good)
    rec = asyncio.run(r.sort_roles(fc, edit, job_id=7))
    check("one call, to Sonnet 5.5 at low effort, text only", len(fc.calls) == 1 and fc.calls[0]["model"] == "claude-sonnet-5-5" and fc.calls[0]["output_config"] == {"effort": "low"}
          and isinstance(fc.calls[0]["messages"][0]["content"], str))
    saved = r.load_roles(edit)
    check("saved with model, prompt version and the roles", saved and saved["model"] == "claude-sonnet-5-5" and saved["prompt"] == r.PROMPT_VERSION and saved["roles"]["12.0"] == "main_moment")
    check("cost at list price: 1000 in + 200 out on Sonnet 5.5 = $0.004", saved["usd"] == 0.004, saved["usd"])
    ledger = [json.loads(x) for x in (edit / "api_usage.jsonl").read_text().splitlines()]
    check("the real use goes on the job's usage ledger", len(ledger) == 1 and ledger[0]["operation"] == "sort_shot_roles" and ledger[0]["job_id"] == 7 and ledger[0]["input_tokens"] == 1000)
    try:
        asyncio.run(r.sort_roles(FakeClient(good, stop="max_tokens"), edit, job_id=7)); ok = False
    except r.RolesError:
        ok = True
    check("a cut-off answer is refused, not half-saved", ok)
    rec2 = asyncio.run(r.sort_roles(FakeClient(good), edit, job_id=7, save=False))
    check("save=False writes nothing more", len((edit / "api_usage.jsonl").read_text().splitlines()) == 1 and rec2["roles"])

with tempfile.TemporaryDirectory() as d:
    try:
        asyncio.run(r.sort_roles(FakeClient(good), Path(d), job_id=1)); ok = False
    except r.RolesError as e:
        ok = "Describe clips" in str(e)
    check("no descriptions -> a clear message, no call", ok)

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
