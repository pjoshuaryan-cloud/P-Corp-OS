"""Coverage (backend/app/post_coverage.py and its routes): turning a brief into a shot list, checking footage against it, what counts as covered, weak or missing, the PDFs, and By Moment bins.
Real files, real contact sheets and real PDFs in a temp folder, with a stand-in for Claude. No drive, no API call, and nothing under backend/data is touched. What Claude really answers isn't tested here. Run:
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python coverage_test.py"""
import asyncio
import base64
import io
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from app import main, post_coverage as cov, post_moments, post_shoot_log as sl  # noqa: E402
from learning import transfer_cut  # noqa: E402

fails = 0
REAL_DATA = sl.DATA


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


class Block:
    type = "text"
    def __init__(self, text): self.text = text


class FakeMessages:
    """Answers by prompt. `looks` maps a shot's words to {clip name: (match, note)}; `shortlist` maps a shot id to clip names."""
    def __init__(self): self.calls = []; self.draft = None; self.shortlist = {}; self.looks = {}; self.boom = None; self.bad_next = 0; self.silent = set()
    async def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom
        text = self._answer(kw)
        if self.bad_next:
            self.bad_next -= 1
            text = "not json"
        return type("R", (), {"content": [Block(text)], "usage": type("U", (), {"input_tokens": 3000, "output_tokens": 150})()})()
    def _answer(self, kw):
        if kw["system"] == cov.DRAFT_PROMPT:
            return self.draft
        content = kw["messages"][0]["content"]
        if kw["system"].startswith("You check a shoot"):
            log = next(b["text"] for b in content if b["type"] == "text" and b["text"].startswith("Clip log"))
            numbers = {m.group(2): int(m.group(1)) for m in re.finditer(r"^(\d+) \| (\S+)", log, re.M)}
            shots = next(b["text"] for b in content if b["type"] == "text" and b["text"].startswith("Shot list"))
            ids = re.findall(r"^([ip][0-9a-f]+):", shots, re.M)
            return json.dumps({"items": [{"id": i, "clips": [numbers[n] for n in self.shortlist.get(i, []) if n in numbers]} for i in ids if i not in self.silent]})
        shot = content[0]["text"]
        shown = [int(m) for b in content if b["type"] == "text" for m in re.findall(r"^Clip (\d+):", b["text"])]
        for words, answers in self.looks.items():
            if words in shot:
                return json.dumps({"matches": [answers(n) if callable(answers) else {"clip": n, "match": answers, "note": "seen"} for n in shown]})
        return json.dumps({"matches": [{"clip": n, "match": "no", "note": ""} for n in shown]})


class FakeClient:
    def __init__(self): self.messages = FakeMessages()


class APIConnectionError(Exception):
    pass


async def finish(plan_id):
    while cov._JOBS[plan_id]["state"] == "running":
        await asyncio.sleep(0.02)
    return cov.job_state(plan_id)


def make_log(project, names=("C1.MP4", "C2.MP4", "C3.MP4", "C4.MP4", "C5.MP4", "C6.MP4")):
    ctx = sl.new_context(project, None)
    log = {"version": 1, "project_path": project, "name": ctx["name"], "clips": {}, "order": []}
    for n, name in enumerate(names, 1):
        cid = str(1000 + n)
        log["clips"][cid] = {"id": cid, "file_id": int(cid), "name": name, "path": f"/x/{name}", "duration": 8.0, "profile": "slog3", "vertical": True, "checks": {"result": "pass", "flags": []},
                             "tags": {"shot_size": "wide", "subjects": ["product"], "energy": "calm", "camera_move": "static", "vertical_crop_ok": True, "description": f"Clip {name}", "quality_note": ""}, "moments": {"scene": "x", "people": False, "events": [{"t": 1.0, "kind": "hero", "punch": 8, "what": "Bottle lifted"}]}}
        log["order"].append(cid)
        for i in range(4):
            out = io.BytesIO()
            Image.new("RGB", (270, 480), (20 * n, 90, 40 * i)).save(out, format="JPEG")
            sl._write_bytes(sl.thumb_path(ctx, cid, i), out.getvalue())
    sl._save_log(ctx, log)
    return ctx, {v["name"]: k for k, v in log["clips"].items()}


DRAFT = json.dumps({"items": [
    {"moment": "Arrivals", "time": "18:00", "description": "Logo wall, readable", "shot_size": "wide", "priority": "must", "owner": "A-cam"},
    {"moment": "Arrivals", "time": "", "description": "Guests arriving", "shot_size": "any", "priority": "should", "owner": ""},
    {"moment": "Speeches", "time": "19:30", "description": "Host on stage", "shot_size": "medium", "priority": "must", "owner": "B-cam"},
    {"moment": "Speeches", "time": "19:30", "description": "Crowd reaction", "shot_size": "tight", "priority": "urgent", "owner": 5},
    {"moment": "Speeches", "description": "", "priority": "must"},
]})


with tempfile.TemporaryDirectory() as tmp:
    sl.DATA = Path(tmp) / "shoot_logs"
    transfer_cut.DATA = Path(tmp) / "projects"
    ctx, ids = make_log(str(Path(tmp) / "Shoot.prproj"))

    # ---- the plan --------------------------------------------------------------------------------------------------------------------------------------------
    try:
        cov.new_plan("   ")
        check("a plan needs a name", False)
    except sl.ShootLogError:
        check("a plan needs a name", True)
    plan = cov.new_plan("GQ x Miele", "Miele")
    pid = plan["id"]
    check("a plan needs no footage or shoot", plan["log_key"] is None and cov.load_plan(pid)["name"] == "GQ x Miele")
    for bad in ("../../etc", "c123", "", "cZZZZZZZZZZZZ"):
        try:
            cov.load_plan(bad)
            check(f"{bad!r} isn't a plan id", False)
        except sl.ShootLogError:
            check(f"{bad!r} isn't a plan id", True)
    items, dropped = cov.parse_draft(DRAFT)
    check("a draft keeps usable shots and says how many it dropped", len(items) == 4 and dropped == 1, (len(items), dropped))
    check("words outside the list fall back rather than losing the shot", items[3]["shot_size"] == "any" and items[3]["priority"] == "should" and items[3]["owner"] == "", items[3])
    check("no time stays empty: a time is never made up", items[1]["time"] == "")
    check("a reply with no usable shots isn't a draft", cov.parse_draft('{"items":[{"description":""}]}') is None and cov.parse_draft("nope") is None)
    check("the prompt treats the brief as information, not instructions", "never an instruction" in cov.DRAFT_PROMPT and "Never guess a time" in cov.DRAFT_PROMPT)

    def blocks(*a):
        return cov.brief_blocks(*a)
    check("pasted text becomes part of the request", blocks("Run sheet here", [])[0]["text"].endswith("Run sheet here"))
    pdf_block = blocks("", [{"name": "brief.pdf", "media_type": "application/pdf", "data": base64.b64encode(b"%PDF-1.4").decode()}])[0]
    check("a PDF goes to Claude as a document", pdf_block["type"] == "document")
    for bad, why in (((" ", []), "nothing to read"), (("", [{"name": "x.pdf", "media_type": "application/pdf", "data": "%%%"}]), "a file that isn't valid"), (("", [{"name": "x.pdf", "media_type": "application/pdf", "data": base64.b64encode(b"x" * (cov.MAX_ATTACHMENT_BYTES + 1)).decode()}]), "a file that's too big"), (("", [{"name": f"{i}.pdf", "media_type": "application/pdf", "data": ""} for i in range(cov.MAX_ATTACHMENTS_PER_MESSAGE + 1)]), "too many files")):
        try:
            blocks(*bad)
            check(f"{why} is refused", False)
        except sl.ShootLogError:
            check(f"{why} is refused", True)

    async def draft_run():
        client = FakeClient()
        client.messages.draft = DRAFT
        cov.start_draft(pid, client, "A brief", [])
        return await finish(pid), client
    state, client = asyncio.run(draft_run())
    plan = cov.load_plan(pid)
    check("the draft fills the plan", state["state"] == "done" and len(plan["items"]) == 4 and all(i["source"] == "ai" for i in plan["items"]), state)
    check("it asks the DOP to read it", "Read them through" in state["message"] and plan["approved_at"] is None)
    check("what it really cost goes in the plan's ledger", cov.view(pid)["spent"]["usd_total"] > 0)
    first = plan["items"][0]["id"]

    # ---- editing -------------------------------------------------------------------------------------------------------------------------------------------
    cov.approve(pid, True)
    check("the DOP can approve it", cov.load_plan(pid)["approved_at"])
    edited = cov.update_item(pid, first, {"owner": "Josh"})
    check("an edit keeps the rest of the shot", edited["owner"] == "Josh" and edited["description"] == "Logo wall, readable" and edited["id"] == first)
    check("changing a list needs approving again", cov.load_plan(pid)["approved_at"] is None)
    for fields, why in (({"shot_size": "tight"}, "a bad size"), ({"priority": "urgent"}, "a bad priority"), ({"description": "   "}, "an empty shot"), ({"owner": 5}, "text that isn't text")):
        try:
            cov.update_item(pid, first, fields)
            check(f"{why} is refused", False)
        except sl.ShootLogError:
            check(f"{why} is refused", True)
    added = cov.add_item(pid, {"description": "Sponsor banner", "moment": "Arrivals", "priority": "must"})
    check("a shot added by hand is marked as his, with a new id", added["source"] == "user" and added["id"] == "i5")
    extra = cov.add_item(pid, {"description": "Throwaway"})
    cov.delete_item(pid, extra["id"])
    check("a shot can be removed", extra["id"] not in [i["id"] for i in cov.load_plan(pid)["items"]])
    third = cov.add_item(pid, {"description": "Another"})
    check("an id is never reused", third["id"] == "i7")
    cov.delete_item(pid, third["id"])
    ids_before = dict(cov.load_plan(pid)["moment_ids"])
    cov.update_item(pid, first, {"moment": "Doors open"})
    cov.update_item(pid, first, {"moment": "Arrivals"})
    check("a moment's number never changes, so a search bin keeps meaning the same thing", all(cov.load_plan(pid)["moment_ids"][k] == v for k, v in ids_before.items()))

    # ---- the verdict ------------------------------------------------------------------------------------------------------------------------------------------
    item = {"description": "Logo wall", "shot_size": "wide"}
    fp = cov.fingerprint(item)
    clips = {"a": {"name": "A.MP4", "status": "none"}, "b": {"name": "B.MP4", "status": "select"}, "r": {"name": "R.MP4", "status": "reject"}}
    def row(*matches, **kw):
        return {"fingerprint": kw.get("fp", fp), "error": kw.get("error"), "matches": [{"clip": c, "match": m, "note": n} for c, m, n in matches]}
    r = cov.item_result(item, row(("a", "yes", "seen"), ("b", "yes", "seen too")), clips)
    check("seen clearly in a usable clip is covered, your selects first", r["status"] == "covered" and r["evidence"][0]["clip"] == "b", r)
    check("a shot nobody has checked is not missing", cov.item_result(item, None, clips)["status"] == "unchecked")
    check("a shot Claude couldn't answer for is not missing", cov.item_result(item, row(error="no answer"), clips)["status"] == "unchecked")
    check("candidates that all turned out wrong means missing", cov.item_result(item, row(("a", "no", ""), ("b", "no", "")), clips)["status"] == "missing")
    check("no candidates at all means missing", cov.item_result(item, row(), clips)["status"] == "missing")
    r = cov.item_result(item, row(("a", "partly", "wrong size")), clips)
    check("only partly there is weak, and says why", r["status"] == "weak" and r["reason"] == "wrong size", r)
    r = cov.item_result(item, row(("r", "yes", "")), clips)
    check("only in a rejected clip is weak, not covered", r["status"] == "weak" and "rejected" in r["reason"], r)
    check("partly, in a rejected clip, is weak", cov.item_result(item, row(("r", "partly", "")), clips)["status"] == "weak")
    check("a good clip and a rejected one is covered", cov.item_result(item, row(("r", "yes", ""), ("a", "yes", "")), clips)["status"] == "covered")
    check("rewording a shot means it has to be checked again", cov.item_result({"description": "Logo wall, close", "shot_size": "close"}, row(("a", "yes", "")), clips)["status"] == "unchecked")
    check("a clip that's left the shoot proves nothing", cov.item_result(item, row(("gone", "yes", "")), clips)["status"] == "missing")
    r = cov.item_result(item, row(("a", "yes", "")), clips, {"status": "missing"})
    check("a person's verdict wins, and the check's answer is kept", r["status"] == "missing" and r["auto"] == "covered" and r["yours"], r)
    proof = lambda r: [e["clip"] for e in r["proof"]]
    check("a covered shot's proof is only the clips that clearly have it", proof(cov.item_result(item, row(("a", "yes", ""), ("b", "partly", "")), clips)) == ["a"])
    check("a rejected clip isn't shown as proof when a usable one is there", proof(cov.item_result(item, row(("r", "yes", ""), ("b", "partly", ""), ("a", "yes", "")), clips)) == ["a"])
    check("a weak shot shows the clip that nearly has it", proof(cov.item_result(item, row(("b", "partly", "wrong size")), clips)) == ["b"])
    check("a shot only in a rejected clip still shows that clip, so you can see why", proof(cov.item_result(item, row(("r", "yes", "")), clips)) == ["r"])
    check("a shot you called covered still shows what the check found", proof(cov.item_result(item, row(("a", "partly", "")), clips, {"status": "covered"})) == ["a"])
    check("a shot you called covered with nothing found shows nothing", proof(cov.item_result(item, row(), clips, {"status": "covered"})) == [])
    many = {**clips, "c": {"name": "C.MP4", "status": "none"}}
    check("proof is at most two clips, your selects first", proof(cov.item_result(item, row(("a", "yes", ""), ("c", "yes", ""), ("b", "yes", "")), many)) == ["b", "a"])
    check("every clip the check named stays in the evidence, for By Moment", len(cov.item_result(item, row(("a", "yes", ""), ("b", "partly", "")), clips)["evidence"]) == 2)
    check("an answer that skips a clip isn't accepted", cov.parse_look('{"matches":[{"clip":1,"match":"yes"}]}', {1, 2}) is None)
    check("a clip that wasn't shown can't be claimed", cov.parse_look('{"matches":[{"clip":1,"match":"yes"},{"clip":9,"match":"yes"}]}', {1}) == [{"clip": 1, "match": "yes", "note": ""}])
    check("an unknown answer isn't accepted", cov.parse_look('{"matches":[{"clip":1,"match":"maybe"}]}', {1}) is None)
    check("a shortlist ignores numbers that aren't clips and shots that aren't on the list", cov.parse_shortlist('{"items":[{"id":"i1","clips":[1,99,true,"2",1]},{"id":"zz","clips":[1]}]}', {"i1"}, 5) == {"i1": [1]})
    check("the strict prompt says why", "Be strict" in cov.LOOK_PROMPT and "Don't assume" in cov.LOOK_PROMPT and "generous" in cov.SHORTLIST_PROMPT)

    # ---- checking the footage ---------------------------------------------------------------------------------------------------------------------------------
    plan_ids = {i["description"]: i["id"] for i in cov.load_plan(pid)["items"]}
    try:
        asyncio.run(asyncio.sleep(0)); cov.start_check(pid, FakeClient())
        check("a check needs a linked shoot", False)
    except sl.ShootLogError as exc:
        check("a check needs a linked shoot", "Link a logged shoot" in str(exc), str(exc))
    try:
        cov.link_log(pid, "nope")
        check("only a logged shoot can be linked", False)
    except sl.ShootLogError:
        check("only a logged shoot can be linked", True)
    cov.link_log(pid, ctx["key"])
    other = cov.new_plan("Other")
    try:
        cov.link_log(other["id"], ctx["key"])
        check("a shoot has one plan", False)
    except sl.ShootLogError as exc:
        check("a shoot has one plan, and it says which", "GQ x Miele" in str(exc), str(exc))
    v = cov.view(pid)
    check("the estimate covers every unchecked shot and all the clips", v["estimate"]["shots"] == 5 and v["estimate"]["clips"] == 6 and 0 < v["estimate"]["usd"] <= v["estimate"]["cap_usd"], v["estimate"])
    check("everything starts as not checked", v["summary"]["counts"]["unchecked"] == 5)

    def scripted():
        client = FakeClient()
        m = client.messages
        m.shortlist = {plan_ids["Logo wall, readable"]: ["C1.MP4", "C2.MP4"], plan_ids["Guests arriving"]: ["C3.MP4"], plan_ids["Host on stage"]: ["C4.MP4"], plan_ids["Sponsor banner"]: [], plan_ids["Crowd reaction"]: ["C5.MP4"]}
        m.looks = {"Logo wall, readable": "yes", "Guests arriving": "partly", "Crowd reaction": "no", "Host on stage": "yes"}
        return client

    async def run_check(client, **kw):
        started = cov.start_check(pid, client, **kw)
        if not started["started"]:
            return started, None
        return started, await finish(pid)
    client = scripted()
    started, state = asyncio.run(run_check(client))
    check("the check finishes", state["state"] == "done", state)
    v = cov.view(pid)
    by = {r["description"]: r for r in v["rows"]}
    check("a deliberately skipped must-have is flagged missing (the spec's own test)", by["Sponsor banner"]["status"] == "missing" and "Sponsor banner" in v["summary"]["must_missing"], by["Sponsor banner"])
    check("a similar shot that isn't there is missing, not covered: candidates turned down", by["Crowd reaction"]["status"] == "missing")
    check("seen clearly is covered, showing the clip that proves it", by["Logo wall, readable"]["status"] == "covered" and {e["name"] for e in by["Logo wall, readable"]["evidence"]} == {"C1.MP4", "C2.MP4"})
    check("partly there is weak", by["Guests arriving"]["status"] == "weak")
    sent = client.messages.calls
    sheet = sent[0]
    check("the first look sends numbered contact sheets, the log and the list", sum(b["type"] == "image" for b in sheet["messages"][0]["content"]) == 1 and any("Clip log" in b.get("text", "") for b in sheet["messages"][0]["content"]) and sheet["system"].startswith("You check"))
    check("a shot with no candidates needs no closer look, so it costs nothing more", len(sent) == 1 + 4, len(sent))
    look = next(c for c in sent[1:] if "Logo wall" in c["messages"][0]["content"][0]["text"])
    check("the closer look sends every frame of each candidate, labelled", sum(b["type"] == "image" for b in look["messages"][0]["content"]) == 8 and "Clip 1:" in [b.get("text") for b in look["messages"][0]["content"]])
    data = base64.b64decode(sheet["messages"][0]["content"][0]["source"]["data"])
    with Image.open(io.BytesIO(data)) as sheet_image:
        check("a contact sheet stays small enough to cost what's estimated", max(sheet_image.size) <= 1568 and sheet_image.format == "JPEG", sheet_image.size)
    check("what it really cost goes in the ledger", "coverage_check" in cov.view(pid)["spent"]["by_operation"], cov.view(pid)["spent"])

    calls_before = len(client.messages.calls)
    started, _ = asyncio.run(run_check(client))
    check("nothing left to check means nothing is spent", started["started"] is False and len(client.messages.calls) == calls_before)
    cov.update_item(pid, plan_ids["Guests arriving"], {"description": "Guests arriving at the door"})
    plan_view = cov.view(pid)
    check("rewording one shot queues only that shot", plan_view["estimate"]["shots"] == 1 and {r["description"]: r["status"] for r in plan_view["rows"]}["Guests arriving at the door"] == "unchecked", plan_view["estimate"])
    client2 = scripted()
    client2.messages.looks["Guests arriving at the door"] = "yes"
    started, state = asyncio.run(run_check(client2))
    check("checking again only pays for that shot", len(client2.messages.calls) == 2 and state["state"] == "done", len(client2.messages.calls))

    # Rejecting after the check changes the report without another call.
    sl.add_override(ctx, ids["C4.MP4"], "status", "reject")
    by = {r["description"]: r for r in cov.view(pid)["rows"]}
    check("rejecting the only clip showing a must-have makes it weak, with no new call", by["Host on stage"]["status"] == "weak" and "rejected" in by["Host on stage"]["reason"], by["Host on stage"])
    check("the Shoot Log page can show the headline", sl.view(ctx)["coverage"]["must_missing"] >= 1 and sl.view(ctx)["coverage"]["id"] == pid, sl.view(ctx)["coverage"])

    # A person's verdict.
    cov.add_override(pid, plan_ids["Sponsor banner"], "covered")
    by = {r["description"]: r for r in cov.view(pid)["rows"]}
    check("a person's verdict wins", by["Sponsor banner"]["status"] == "covered" and by["Sponsor banner"]["yours"])
    check("the verdict is in its own file, and the check's answer stays", (cov.plan_dir(pid) / "overrides.jsonl").exists() and cov.load_report(pid)["items"][plan_ids["Sponsor banner"]]["matches"] == [])
    cov.add_override(pid, plan_ids["Sponsor banner"], "auto")
    check("undoing it hands the shot back to the check", {r["description"]: r["status"] for r in cov.view(pid)["rows"]}["Sponsor banner"] == "missing")
    for bad in ("maybe", ""):
        try:
            cov.add_override(pid, first, bad)
            check("a bad verdict is refused", False)
        except sl.ShootLogError:
            check("a bad verdict is refused", True)

    # ---- things going wrong -----------------------------------------------------------------------------------------------------------------------------------
    c3 = cov.new_plan("Failures", log_key=None)
    ctx3, _ = make_log(str(Path(tmp) / "Three.prproj"))
    cov.link_log(c3["id"], ctx3["key"])
    for d in ("Shot one", "Shot two", "Shot three"):
        cov.add_item(c3["id"], {"description": d, "priority": "must"})
    p3 = cov.load_plan(c3["id"])
    i1, i2, i3 = [i["id"] for i in p3["items"]]

    async def go(client, **kw):
        cov.start_check(c3["id"], client, **kw)
        return await finish(c3["id"])
    client = FakeClient()
    client.messages.silent = {i2}
    client.messages.shortlist = {i1: ["C1.MP4"], i3: []}
    client.messages.looks = {"Shot one": "yes"}
    state = asyncio.run(go(client))
    rows = {r["id"]: r for r in cov.view(c3["id"])["rows"]}
    check("a shot Claude said nothing about stays not checked, and is named", rows[i2]["status"] == "unchecked" and "Shot two" in state["failed"] and "couldn't be checked" in state["message"], (rows[i2], state))
    check("and it's queued for next time", cov.view(c3["id"])["estimate"]["shots"] == 1)
    client = FakeClient()
    client.messages.bad_next = 2
    state = asyncio.run(go(client))
    check("an unreadable first answer, twice, changes nothing and says so", state["state"] == "failed" and len(client.messages.calls) == 2, state)
    client = FakeClient()
    client.messages.boom = APIConnectionError("no signal")
    state = asyncio.run(go(client))
    check("no signal stops it and says to try again", state["state"] == "stopped" and "signal" in state["message"], state)
    (cov.plan_dir(c3["id"]) / "report.json").unlink()
    client = FakeClient()
    client.messages.shortlist = {i1: ["C1.MP4"], i2: ["C2.MP4"], i3: ["C3.MP4"]}
    client.messages.looks = {"Shot": "yes"}
    state = asyncio.run(go(client, cap_usd=0.012))
    check("the money limit stops it with the work kept", state["state"] == "stopped" and "limit" in state["message"] and cov.view(c3["id"])["summary"]["counts"]["unchecked"] >= 1, state)
    client = FakeClient()
    client.messages.shortlist = {i1: ["C1.MP4"], i2: ["C2.MP4"], i3: ["C3.MP4"]}
    client.messages.looks = {"Shot": "yes"}
    state = asyncio.run(go(client))
    check("the same click finishes the rest", cov.view(c3["id"])["summary"]["counts"]["unchecked"] == 0, cov.view(c3["id"])["summary"])

    # ---- By Moment bins ---------------------------------------------------------------------------------------------------------------------------------------
    plan_apply = sl.apply_plan(ctx)
    groups = {g["bin"]: g["search"] for g in plan_apply["bins"]["groups"]}
    notes = {c["name"]: c["note"] for c in plan_apply["clips"]}
    check("a checked plan adds By Moment search bins", "By Moment" in groups and {s["name"] for s in groups["By Moment"]} == {"Arrivals", "Speeches"}, groups.get("By Moment"))
    arrivals = next(s["query"] for s in groups["By Moment"] if s["name"] == "Arrivals")
    check("clips matched to a moment carry its word in Log Note", arrivals in notes["C1.MP4"] and arrivals in notes["C2.MP4"], notes["C1.MP4"])
    check("a rejected clip carries no moment word, so it can't show in a search bin", notes["C4.MP4"] == "rejected", notes["C4.MP4"])
    check("a clip tied to no moment gets no moment word", "moment" not in notes["C6.MP4"], notes["C6.MP4"])
    check("moment words are one unbroken word, none inside another", cov.moment_token(1) == "moment001" and cov.moment_token(12) == "moment012" and cov.moment_token(1) not in cov.moment_token(100) and cov.moment_token(1).isalnum())
    ctx4, _ = make_log(str(Path(tmp) / "Four.prproj"))
    check("a shoot with no plan gets no By Moment bin", "By Moment" not in {g["bin"] for g in sl.apply_plan(ctx4)["bins"]["groups"]} and sl.view(ctx4)["coverage"] is None)

    # ---- PDFs -------------------------------------------------------------------------------------------------------------------------------------------------
    cov.add_item(pid, {"description": "Awkward <b>words</b> & \u6f22\u5b57 \U0001F600", "moment": "Odd <moment>", "owner": "A&B", "shot_size": "close", "priority": "must"})
    report = cov.report_pdf(pid)
    shots = cov.shot_list_pdf(pid)
    check("both PDFs build, even with markup and characters the font lacks in the text", report[:4] == b"%PDF" and shots[:4] == b"%PDF" and len(report) > 2000, len(report))
    check("the report carries frames as proof", b"/Image" in report)
    empty = cov.new_plan("Empty")
    check("an empty plan still makes PDFs", cov.report_pdf(empty["id"])[:4] == b"%PDF" and cov.shot_list_pdf(empty["id"])[:4] == b"%PDF")
    many = cov.new_plan("Long list")
    for n in range(70):
        cov.add_item(many["id"], {"description": f"Shot {n} with a reasonably long description of what is seen", "moment": "One long moment", "priority": "must"})
    check("a long list splits across pages without breaking", cov.shot_list_pdf(many["id"])[:4] == b"%PDF" and cov.report_pdf(many["id"]).count(b"/Type /Page") >= 2)

    # ---- drafting again keeps the old list --------------------------------------------------------------------------------------------------------------------
    async def again():
        client = FakeClient()
        client.messages.draft = json.dumps({"items": [{"moment": "New", "description": "New shot", "shot_size": "any", "priority": "must"}]})
        cov.start_draft(many["id"], client, "New brief", [])
        return await finish(many["id"])
    asyncio.run(again())
    check("drafting again replaces the list and keeps the old one on disk", len(cov.load_plan(many["id"])["items"]) == 1 and list(cov.plan_dir(many["id"]).glob("items_before_*.json")))
    async def bad_again():
        client = FakeClient()
        client.messages.draft = "nope"
        cov.start_draft(many["id"], client, "New brief", [])
        return await finish(many["id"])
    state = asyncio.run(bad_again())
    check("a failed draft leaves the list alone", state["state"] == "failed" and cov.load_plan(many["id"])["items"][0]["description"] == "New shot", state)

    # ---- routes -----------------------------------------------------------------------------------------------------------------------------------------------
    main.AUTH_TOKEN = "t"
    async def no_audit(*a, **k):
        return None
    main._shoot_log_audit = no_audit
    web = TestClient(main.app)
    check("no token, no plans", web.get("/post/coverage").status_code == 422 and web.get("/post/coverage?token=wrong").status_code == 403)
    got = web.get("/post/coverage?token=t").json()
    check("the overview lists plans and logged shoots", any(p["id"] == pid for p in got["plans"]) and any(l["key"] == ctx["key"] for l in got["logs"]))
    made = web.post("/post/coverage?token=t", json={"name": "From the page", "client": "C"})
    check("a plan can be made", made.status_code == 200 and made.json()["name"] == "From the page")
    new = made.json()["id"]
    check("a nameless plan is a 400 that says why", web.post("/post/coverage?token=t", json={"name": " "}).status_code == 400)
    check("an unknown plan is a 404", web.get("/post/coverage/c000000000000?token=t").status_code == 404 and web.get("/post/coverage/..%2F..?token=t").status_code == 404)
    r = web.post(f"/post/coverage/{new}/items?token=t", json={"description": "A shot", "priority": "must"})
    check("a shot can be added", r.status_code == 200 and r.json()["id"] == "i1", r.text[:200])
    check("a bad edit is a 400", web.post(f"/post/coverage/{new}/items/i1?token=t", json={"priority": "urgent"}).status_code == 400)
    check("a good edit works", web.post(f"/post/coverage/{new}/items/i1?token=t", json={"owner": "B"}).json()["owner"] == "B")
    check("approving works", web.post(f"/post/coverage/{new}/approve?token=t", json={"approved": True}).json()["approved_at"])
    check("details can be changed", web.post(f"/post/coverage/{new}/details?token=t", json={"client": "New client"}).json()["client"] == "New client")
    check("a verdict is checked", web.post(f"/post/coverage/{new}/override?token=t", json={"item": "i1", "status": "nope"}).status_code == 400 and web.post(f"/post/coverage/{new}/override?token=t", json={"item": "i1", "status": "covered"}).status_code == 200)
    check("a shot can be removed", web.delete(f"/post/coverage/{new}/items/i1?token=t").status_code == 200)
    r = web.get(f"/post/coverage/{pid}/report.pdf?token=t")
    check("the report downloads as a PDF with a safe name", r.status_code == 200 and r.headers["content-type"] == "application/pdf" and "attachment" in r.headers["content-disposition"] and r.content[:4] == b"%PDF", r.headers)
    check("the shot list downloads", web.get(f"/post/coverage/{pid}/shot-list.pdf?token=t").content[:4] == b"%PDF")
    check("the page is served", web.get("/static/coverage.html").status_code == 200)
    check("coverage pages hold no database connection", main._is_slow_route("GET", f"/post/coverage/{pid}") and main._is_slow_route("POST", f"/post/coverage/{pid}/check"))
    async def fine(client, model):
        return None
    real_credit, post_moments.check_credit = post_moments.check_credit, fine
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    real_start, cov.start_check = cov.start_check, lambda p, client, recheck, cap: {"started": True, "estimate": {"shots": 1}, "job": None, "recheck": recheck, "cap": cap}
    r = web.post(f"/post/coverage/{pid}/check?token=t", json={"recheck": True, "max_usd": 0.5})
    check("a check is its own explicit request with a limit", r.status_code == 200 and r.json()["recheck"] is True and r.json()["cap"] == 0.5, r.text[:200])
    cov.start_check = real_start
    real_draft, cov.start_draft = cov.start_draft, lambda p, client, text, files: {"state": "running", "text": text}
    r = web.post(f"/post/coverage/{new}/draft?token=t", json={"text": "A brief"})
    check("a draft is its own explicit request", r.status_code == 200 and r.json()["job"]["text"] == "A brief", r.text[:200])
    check("an empty draft is refused before anything is spent", web.post(f"/post/coverage/{new}/draft?token=t", json={"text": " "}).status_code == 400)
    cov.start_draft = real_draft
    post_moments.check_credit = real_credit

    # ---- a list made on a phone goes through the same check -------------------------------------------------------------------------------------------------
    ctx2, _ = make_log(str(Path(tmp) / "Phone.prproj"))
    phone_shots = {"logo": "pa1b2c3d4e5", "banner": "pa1b2c3d4e6", "guests": "pa1b2c3d4e7"}
    phone_id = "cab12ab12ab12"
    check("a list made on a phone comes in", cov.import_phone_list({"plan_id": phone_id, "name": "JD from the phone", "client": "JD Sports", "shoot_date": "2026-11-09", "expires_at": "2026-11-12T23:59:59.000Z", "list_version": 4, "revoked_at": None, "items": [
        {"id": phone_shots["logo"], "moment": "Outside", "time": "09:00", "description": "Logo wall, readable", "size": "wide", "priority": "must", "owner": ""},
        {"id": phone_shots["banner"], "moment": "Outside", "time": "09:00", "description": "Sponsor banner", "size": "any", "priority": "must", "owner": "B-cam"},
        {"id": phone_shots["guests"], "moment": "In store", "time": "", "description": "Guests arriving", "size": "any", "priority": "should", "owner": ""},
    ]}, "a-token"))
    cov.link_log(phone_id, ctx2["key"])
    phone_client = FakeClient()
    phone_client.messages.shortlist = {phone_shots["logo"]: ["C1.MP4"], phone_shots["banner"]: [], phone_shots["guests"]: ["C3.MP4"]}
    phone_client.messages.looks = {"Logo wall, readable": "yes", "Guests arriving": "partly"}
    async def run_phone_check():
        started = cov.start_check(phone_id, phone_client)
        return started, await finish(phone_id) if started["started"] else None
    started, state = asyncio.run(run_phone_check())
    check("the footage check runs on it", started["started"] and state["state"] == "done", state)
    rows = {r["id"]: r for r in cov.view(phone_id)["rows"]}
    check("it finds what's there, by the phone's own shot ids", rows[phone_shots["logo"]]["status"] == "covered" and rows[phone_shots["logo"]]["evidence"][0]["name"] == "C1.MP4", rows[phone_shots["logo"]])
    check("partly there is weak", rows[phone_shots["guests"]]["status"] == "weak")
    check("and it flags the must-have that isn't there", rows[phone_shots["banner"]]["status"] == "missing" and "Sponsor banner" in cov.view(phone_id)["summary"]["must_missing"])
    check("a shot ticked on set but not found gets its warning", cov.on_set_unfound(cov.load_plan(phone_id)["items"], cov.view(phone_id)["rows"], {phone_shots["banner"]: {"done": True, "by": "B-cam", "at": "2026-11-09T09:00:00.000Z", "note": ""}}) == ["Sponsor banner"])
    cov.save_on_set_ticks(phone_id, {phone_shots["banner"]: {"done": True, "by": "B-cam", "at": "2026-11-09T09:00:00.000Z", "note": ""}})
    check("its report and shot list make PDFs", cov.report_pdf(phone_id)[:4] == b"%PDF" and cov.shot_list_pdf(phone_id)[:4] == b"%PDF")
    words, bins = cov.moments_for_log(ctx2, list(sl.load_log(ctx2)["clips"].values()))
    check("Apply gets By Moment bins from it", {b["name"] for b in bins} >= {"Outside"} and any(words.values()), bins)
    added = cov.add_item(phone_id, {"moment": "Outside", "description": "Added on the Mac afterwards", "priority": "should"})
    check("a shot added on the Mac can't clash with the phone's ids", added["id"] not in phone_shots.values() and len({i["id"] for i in cov.load_plan(phone_id)["items"]}) == 4)

check("nothing landed in the real data folder", not (REAL_DATA / "coverage").exists() or not any("GQ x Miele" in p.read_text() for p in (REAL_DATA / "coverage").glob("*/plan.json")))

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
