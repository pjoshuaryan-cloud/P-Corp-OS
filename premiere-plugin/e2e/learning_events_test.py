"""Tests for the learning-event record (2026-10-22): one versioned, append-only record type for explicit feedback, observed edits and inferred preferences, with the
confidence of each kept honest (backend/app/post_learning_events.py). Offline: pure functions plus a store in a temp folder, no Premiere, no server.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python learning_events_test.py"""
import copy
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_learning_events as le  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def error_of(**kw):
    """The ValueError text make_event raises for GOOD with `kw` changed, or None when it is accepted."""
    try:
        le.make_event(**{**GOOD, **kw})
        return None
    except ValueError as exc:
        return str(exc)


PLANNED = {"candidate_id": "210:1000", "file_id": 210, "name": "C9920.MP4", "source_in": 1.0, "source_out": 1.52, "kind": "hero", "punch": 7.0, "speed": None}
REPLACEMENT = {"candidate_id": "212:4250", "file_id": 212, "name": "C9922.MP4", "source_in": 4.25, "source_out": 4.77, "kind": "reveal", "punch": 8.0, "speed": None}
GOOD = dict(category="explicit_feedback", confidence="confirmed", outcome="swapped", source="review_page", job_id=7, ts="2026-10-22T10:00:00",
            slot={"index": 2, "role": "body", "seconds": 0.52, "cut_at": 3.2}, planned=PLANNED, replacement=REPLACEMENT, reasons=["wrong_moment"])

# ---- the vocabularies -----------------------------------------------------------------------------------------------------------------------
check("the schema is version 1", le.EVENT_SCHEMA_VERSION == 1)
check("three categories, three confidence levels", le.CATEGORIES == ("explicit_feedback", "observed_edit", "inferred_preference") and le.CONFIDENCE == ("confirmed", "observed", "uncertain"))
check("the outcomes and sources are the agreed ones", len(le.OUTCOMES) == 16 and "reasoned" in le.OUTCOMES and "sped_up" in le.OUTCOMES and "chosen" in le.OUTCOMES
      and le.SOURCES == ("review_page", "learn_button", "autosave_watch", "importer", "planner", "variants_page"))
check("choosing a variant is not a vote for or against any kind of moment", "chosen" not in le._KEPT_OUTCOMES + le._CHANGED_OUTCOMES)
with tempfile.TemporaryDirectory() as _tmp:
    _ev = le.make_event(category="explicit_feedback", confidence="confirmed", outcome="chosen", source="variants_page", job_id=3, ts="2026-10-22T10:00:00",
                        context={"set_id": "20261022T100000", "chosen": "premium-luxury", "offered": ["music-led-montage", "premium-luxury"]})
    check("a job's events go to its own learning_events.jsonl, and the same event twice is stored once",
          le.record_for_job(Path(_tmp), [_ev, None]) == 1 and le.record_for_job(Path(_tmp), [_ev]) == 0 and len(le.load_events(Path(_tmp) / le.EVENTS_FILE)) == 1)
    _bad = dict(_ev, outcome="nonsense")
    check("recording for a job never raises: a bad event is refused and reported as -1, nothing written", le.record_for_job(Path(_tmp), [_bad]) == -1
          and len(le.load_events(Path(_tmp) / le.EVENTS_FILE)) == 1)
check("twelve reason codes with plain labels, and only client_request is not a taste signal",
      len(le.REASON_CODES) == 12 and le.REASON_CODES["action_starts_too_late"] == "Action starts too late" and le.REASON_CODES["client_request"] == "Client asked for it"
      and le.NOT_TASTE_REASONS == frozenset({"client_request"}))

# ---- make_event ----------------------------------------------------------------------------------------------------------------------------
e = le.make_event(**GOOD)
check("make_event fills the schema version, a 16-hex id and the taste signal", e["schema"] == 1 and re.fullmatch(r"[0-9a-f]{16}", e["id"]) and e["taste_signal"] is True, e)
check("it validates clean", le.validate_event(e) == [], le.validate_event(e))
now_event = le.make_event(**{**GOOD, "ts": None})
check("a missing ts becomes local ISO time to the second", re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", now_event["ts"]), now_event["ts"])
check("the shapes are filled in completely (missing keys are None)", set(e["planned"]) == {"candidate_id", "file_id", "name", "source_in", "source_out", "kind", "punch", "speed"}
      and set(e["slot"]) == {"index", "role", "seconds", "cut_at"} and e["plan_ref"] is None and e["media"] is None and e["context"] is None)
sparse = le.make_event(**{**GOOD, "planned": {"name": "x.mp4"}, "plan_ref": {"basis": "matched", "junk": 1}})
check("a sparse candidate is filled, and keys outside the shape are dropped", sparse["planned"]["source_in"] is None and sparse["plan_ref"] == {"file": None, "made_at": None, "basis": "matched"}, sparse)
long_note = le.make_event(**{**GOOD, "note": "x" * 500})
check("a note is capped at 280 characters", len(long_note["note"]) == 280)
check("a blank note becomes None", le.make_event(**{**GOOD, "note": "   "})["note"] is None)
check("a single reason given as a bare string is accepted as a one-item list", le.make_event(**{**GOOD, "reasons": "wrong_moment"})["reasons"] == ["wrong_moment"])
source_ctx = {"style": {"a": [1, 2]}}
made = le.make_event(**{**GOOD, "context": source_ctx})
source_ctx["style"]["a"].append(3)
check("the event owns its context (changing the caller's dict later does not change the event)", made["context"] == {"style": {"a": [1, 2]}}, made["context"])

# ---- ids -----------------------------------------------------------------------------------------------------------------------------------
check("the same content gives the same id", le.make_event(**GOOD)["id"] == le.make_event(**GOOD)["id"])
check("the id ignores the note and the context (they are not identifying)", le.make_event(**{**GOOD, "note": "a", "context": {"k": 1}})["id"] == e["id"])
check("the order the reasons were given in does not change the id",
      le.make_event(**{**GOOD, "reasons": ["wrong_moment", "weak_composition"]})["id"] == le.make_event(**{**GOOD, "reasons": ["weak_composition", "wrong_moment"]})["id"])
for field, value in (("ts", "2026-10-22T10:00:01"), ("outcome", "replaced"), ("job_id", 8), ("source", "importer"), ("reasons", ["weak_composition"]),
                     ("replacement", {**REPLACEMENT, "source_in": 5.0, "source_out": 5.52}), ("planned", {**PLANNED, "name": "C0001.MP4"}), ("slot", {**GOOD["slot"], "index": 3}),
                     ("plan_ref", {"file": "edit_plan_latest.json", "made_at": None, "basis": "matched"})):
    check(f"a different {field} gives a different id", le.make_event(**{**GOOD, field: value})["id"] != e["id"])

# ---- the confidence rules ------------------------------------------------------------------------------------------------------------------
check("client_request makes taste_signal False even when the event is confirmed", le.make_event(**{**GOOD, "reasons": ["client_request"]})["taste_signal"] is False)
check("client_request among other reasons still removes the taste signal", le.make_event(**{**GOOD, "reasons": ["wrong_moment", "client_request"]})["taste_signal"] is False)
check("another reason keeps it", le.make_event(**{**GOOD, "reasons": ["other"]})["taste_signal"] is True)
unc = le.make_event(category="observed_edit", confidence="uncertain", outcome="kept", source="learn_button", job_id=7, ts="2026-10-22T10:00:00", planned=PLANNED)
check("an uncertain event is never a taste signal", unc["taste_signal"] is False)
obs = le.make_event(category="observed_edit", confidence="observed", outcome="kept", source="learn_button", job_id=7, ts="2026-10-22T10:00:00", planned=PLANNED,
                    plan_ref={"file": None, "made_at": "2026-10-22T09:00:00", "basis": "matched"})
check("an observed event matched to its plan is a taste signal", obs["taste_signal"] is True)
check("an explicit event with no reason at all is a taste signal", le.make_event(**{**GOOD, "reasons": []})["taste_signal"] is True)

# ---- validation: every rule rejects ----------------------------------------------------------------------------------------------------------
check("explicit feedback must be confirmed", "must be 'confirmed'" in (error_of(confidence="observed") or ""), error_of(confidence="observed"))
check("explicit feedback marked uncertain is rejected too", error_of(confidence="uncertain") is not None)
check("an observed edit can't be confirmed", "never be 'confirmed'" in (error_of(category="observed_edit", confidence="confirmed") or ""), error_of(category="observed_edit", confidence="confirmed"))
check("an observed edit may be observed or uncertain", error_of(category="observed_edit", confidence="observed") is None and error_of(category="observed_edit", confidence="uncertain") is None)
for basis in ("latest", "newer", "none"):
    msg = error_of(category="observed_edit", confidence="observed", plan_ref={"file": None, "made_at": None, "basis": basis})
    check(f"an observed edit compared with a plan of basis {basis!r} can only be uncertain", msg is not None and "matched" in msg, msg)
check("the same edit with basis 'matched' is fine", error_of(category="observed_edit", confidence="observed", plan_ref={"file": None, "made_at": None, "basis": "matched"}) is None)
check("a reason must be a known code", "Unknown reason" in (error_of(reasons=["looks_bad"]) or ""), error_of(reasons=["looks_bad"]))
check("outcome 'reasoned' needs at least one reason", "needs at least one reason" in (error_of(outcome="reasoned", reasons=[]) or ""), error_of(outcome="reasoned", reasons=[]))
check("outcome 'reasoned' with a reason is accepted", error_of(outcome="reasoned", reasons=["weak_composition"]) is None)
check("a window with source_out <= source_in is rejected", "bad window" in (error_of(planned={**PLANNED, "source_in": 2.0, "source_out": 2.0}) or ""))
check("a window that runs backwards is rejected", "bad window" in (error_of(replacement={**REPLACEMENT, "source_in": 5.0, "source_out": 4.0}) or ""))
check("a negative source_in is rejected", "bad window" in (error_of(planned={**PLANNED, "source_in": -0.5, "source_out": 1.0}) or ""))
check("a window with only one end given is not judged", error_of(planned={"name": "x.mp4", "source_in": 3.0}) is None)
check("a window that is not numbers is rejected", error_of(planned={**PLANNED, "source_in": "soon"}) is not None)
check("an inferred preference with no support must be uncertain", "must be 'uncertain'" in (error_of(category="inferred_preference", confidence="observed") or ""),
      error_of(category="inferred_preference", confidence="observed"))
check("an inferred preference with support below 30 can't be observed", error_of(category="inferred_preference", confidence="observed", context={"support": 29}) is not None)
check("an inferred preference with support of 30 may be observed", error_of(category="inferred_preference", confidence="observed", context={"support": 30}) is None)
check("an inferred preference may be uncertain", error_of(category="inferred_preference", confidence="uncertain") is None)
check("an inferred preference can never be confirmed, even with support", error_of(category="inferred_preference", confidence="confirmed", context={"support": 99}) is not None)
for field, value in (("category", "guess"), ("confidence", "sure"), ("outcome", "liked"), ("source", "telepathy")):
    check(f"an unknown {field} is rejected", f"Unknown {field}" in (error_of(**{field: value}) or ""), error_of(**{field: value}))
check("job_id must be a whole number", error_of(job_id="7") is not None and error_of(job_id=None) is not None and error_of(job_id=True) is not None and error_of(job_id=7.5) is not None)
check("a ts that is not a date is rejected", error_of(ts="yesterday") is not None)
check("a slot needs a whole-number index", error_of(slot={"index": "two"}) is not None)
check("plan_ref.basis must be a known word", error_of(plan_ref={"file": None, "made_at": None, "basis": "maybe"}) is not None)
check("context must be a dictionary", error_of(context=["a"]) is not None)
check("media must be what media_identity returns", error_of(media={"name": "x"}) is not None)
check("something that can't be JSON is rejected", error_of(context={"x": object()}) is not None)

problems = le.validate_event({**e, "schema": 2})
check("a wrong schema version is reported", any("schema version" in p for p in problems), problems)
problems = le.validate_event({**e, "taste_signal": False})
check("an inconsistent taste_signal is reported", any("taste_signal" in p for p in problems), problems)
problems = le.validate_event({**e, "reasons": ["client_request"]})
check("a confirmed event with client_request but taste_signal still True is reported", any("taste_signal" in p for p in problems), problems)
problems = le.validate_event({**e, "job_id": 99})
check("an event changed after it was made fails the id check", any("does not match" in p for p in problems), problems)
problems = le.validate_event({**e, "id": "0000000000000000"})
check("a made-up id is reported", any("does not match" in p for p in problems), problems)
check("a non-dictionary is rejected without crashing", le.validate_event("nope") and le.validate_event(None))
many = error_of(confidence="observed", reasons=["looks_bad"], planned={**PLANNED, "source_out": 0.5}, job_id="x")
check("make_event lists EVERY problem in one error", many is not None and many.count("\n- ") >= 4, many)

# ---- media ---------------------------------------------------------------------------------------------------------------------------------
m1 = le.media_identity(name="C9920.MP4", duration=11.5201, checksum="ab12cd", file_id=210)
m2 = le.media_identity(name="C9920.MP4", duration=11.5201)
check("media with a checksum is keyed by it and stable", m1 == {"key": "sha256:ab12cd", "stable": True, "name": "C9920.MP4", "duration": 11.5201, "file_id": 210}, m1)
check("media without a checksum is keyed by lower-case name and duration, and is not stable", m2["key"] == "name:c9920.mp4|dur:11.52" and m2["stable"] is False, m2)
check("a checksum already prefixed is not prefixed twice", le.media_identity(name="a.mp4", duration=1.0, checksum="sha256:ff")["key"] == "sha256:ff")
check("the name is the basename, so a moved file keeps its identity", le.media_identity(name="/Volumes/Lexar/GWM/C9920.MP4", duration=11.52)["key"] == m2["key"]
      and le.media_identity(name="D:\\cards\\C9920.MP4", duration=11.52)["key"] == m2["key"])
check("a missing duration doesn't crash", le.media_identity(name="a.mp4", duration=None)["key"] == "name:a.mp4|dur:unknown")
check("an event can carry the media identity", le.make_event(**{**GOOD, "media": m1})["media"]["key"] == "sha256:ab12cd")

known = [
    {"name": "C0001.MP4", "duration": 10.0, "checksum": "aa", "file_id": 1},
    {"name": "C0002.MP4", "duration": 12.0, "checksum": "bb", "file_id": 2},
    {"name": "A001.MOV", "duration": 5.0, "checksum": "cc", "file_id": 3},
    {"name": "A001.MOV", "duration": 9.0, "checksum": "dd", "file_id": 4},
    {"name": "B007.MOV", "duration": 7.0, "checksum": "ee", "file_id": 5},
    {"name": "B007.MOV", "duration": 7.02, "checksum": "ff", "file_id": 6},
]
item, conf = le.match_media("C0001.MP4", 10.03, known)
check("a unique name with a duration inside 0.05 s is a match", item and item["file_id"] == 1 and conf == "observed", (item, conf))
item, conf = le.match_media("c0001.mp4", 10.0, known)
check("matching ignores case", item and item["file_id"] == 1 and conf == "observed")
item, conf = le.match_media("C0001.MP4", 10.2, known)
check("a unique name whose duration is off by more than 0.05 s is uncertain (the file may have been replaced)", item is None and conf == "uncertain", (item, conf))
item, conf = le.match_media("C0002.MP4", None, known)
check("with no duration given, the only file of that name is a match", item and item["file_id"] == 2 and conf == "observed")
item, conf = le.match_media("A001.MOV", 9.01, known)
check("duplicate names are resolved by duration", item and item["file_id"] == 4 and conf == "observed", (item, conf))
item, conf = le.match_media("A001.MOV", 5.0, known)
check("duplicate names, the other one", item and item["file_id"] == 3 and conf == "observed")
item, conf = le.match_media("A001.MOV", 7.5, known)
check("duplicate names with no duration that fits are uncertain", item is None and conf == "uncertain", (item, conf))
item, conf = le.match_media("A001.MOV", None, known)
check("duplicate names with no duration given are uncertain", item is None and conf == "uncertain")
item, conf = le.match_media("B007.MOV", 7.01, known)
check("two files that BOTH fit the duration are ambiguous, hence uncertain", item is None and conf == "uncertain", (item, conf))
item, conf = le.match_media("Z999.MP4", 3.0, known)
check("a name nobody has is uncertain (missing media)", item is None and conf == "uncertain")
item, conf = le.match_media("C0001.MP4", 10.0, [])
check("nothing known at all is uncertain", item is None and conf == "uncertain")
item, conf = le.match_media("/Volumes/NEWDRIVE/Renamed Folder/C0002.MP4", 12.0, known)
check("a relocated file (different folder, same basename) still matches", item and item["file_id"] == 2 and conf == "observed", (item, conf))
item, conf = le.match_media("C:\\Users\\x\\C0002.MP4", 12.0, known)
check("a Windows path matches by basename too", item and item["file_id"] == 2)
item, conf = le.match_media("C0001.MP4", 10.05, known)
check("a duration exactly 0.05 s off still matches", item and item["file_id"] == 1, (item, conf))

# ---- the store -----------------------------------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "deeper" / "learning_events.jsonl"
    batch = [le.make_event(**{**GOOD, "ts": f"2026-10-22T10:00:0{i}"}) for i in range(3)]
    check("appending creates the parent folders and writes every new event", le.append_events(path, batch) == 3 and path.exists())
    check("appending the same events again stores nothing", le.append_events(path, batch) == 0)
    check("the file still has exactly three lines", len(path.read_text().splitlines()) == 3)
    check("appending a mix writes only the new one", le.append_events(path, [batch[0], le.make_event(**{**GOOD, "ts": "2026-10-22T11:00:00"})]) == 1)
    twice = le.make_event(**{**GOOD, "ts": "2026-10-22T12:00:00"})
    check("the same event twice in one batch is stored once", le.append_events(path, [twice, copy.deepcopy(twice)]) == 1)
    check("an empty batch writes nothing", le.append_events(path, []) == 0)
    loaded = le.load_events(path)
    check("load_events returns what was written, in order", len(loaded) == 5 and loaded[0] == batch[0] and loaded[-1] == twice, len(loaded))
    check("every line is one JSON object", all(isinstance(json.loads(line), dict) for line in path.read_text().splitlines()))

    bad_batch = [le.make_event(**{**GOOD, "ts": "2026-10-22T13:00:00"}), {**batch[0], "confidence": "uncertain"}]
    before = path.read_text()
    try:
        le.append_events(path, bad_batch)
        raised = False
    except ValueError as exc:
        raised = "event 1" in str(exc)
    check("a batch with an invalid event raises, naming it, and writes NOTHING (not even the valid one)", raised and path.read_text() == before)

    corrupt = Path(tmp) / "corrupt.jsonl"
    good1, good2 = le.make_event(**{**GOOD, "ts": "2026-10-22T14:00:00"}), le.make_event(**{**GOOD, "ts": "2026-10-22T14:00:01"})
    corrupt.write_text("\n".join([json.dumps(good1), "", "not json at all", "[1, 2, 3]", json.dumps({**good1, "confidence": "uncertain"}),
                                  json.dumps({"schema": 2, "id": "x"}), "   ", json.dumps(good2), '{"half": "writ']))
    got = le.load_events(corrupt)
    check("corrupt, blank, non-object and invalid lines are skipped; the valid ones come back", got == [good1, good2], [g["id"] for g in got])
    check("a missing file loads as nothing", le.load_events(Path(tmp) / "nope.jsonl") == [])
    before_n = len(corrupt.read_text().splitlines())
    added = le.append_events(corrupt, [le.make_event(**{**GOOD, "ts": "2026-10-22T14:00:02"})])
    after = corrupt.read_text().splitlines()
    check("appending after a half-written last line starts a fresh line and the new event loads", added == 1 and len(after) == before_n + 1 and le.load_events(corrupt)[-1]["ts"] == "2026-10-22T14:00:02")
    check("ids already in the file are found even if other lines are corrupt", le.append_events(corrupt, [good1]) == 0)

# ---- importers: realistic records ------------------------------------------------------------------------------------------------------------
SWAP = {"ts": "2026-10-21T10:15:02", "job_id": 48, "style": "usual-pace", "action": "swap",
        "slot": {"index": 3, "role": "body", "seconds": 0.52, "cut_at_seconds": 1.4},
        "chosen": {"id": "212:4250", "file_id": 212, "name": "C9922.MP4", "source_in": 4.25, "seconds": 0.52, "origin": "same_clip", "kind": "reveal", "what": "door opens", "punch": 8.0, "scene": None, "people": False, "clip_position": 0.37},
        "passed_over": [
            {"id": "210:1000", "file_id": 210, "name": "C9920.MP4", "source_in": 1.0, "seconds": 0.52, "origin": "current", "kind": "hero", "what": "car turns in", "punch": 7.0},
            {"id": "230:700", "file_id": 230, "name": "C9930.MP4", "source_in": 0.7, "seconds": 0.52, "origin": "other_clip", "kind": "camera_move", "what": "slide", "punch": 6.0}],
        "kept_current": False}
APPROVE = {**SWAP, "ts": "2026-10-21T10:15:40", "action": "approve", "chosen": {**SWAP["passed_over"][0], "origin": "current"},
           "passed_over": [SWAP["chosen"]], "kept_current": True}
(swapped,) = le.from_review_record(SWAP)
check("a review swap is ONE explicit_feedback 'swapped' event, confirmed, from the importer", swapped["category"] == "explicit_feedback" and swapped["outcome"] == "swapped"
      and swapped["confidence"] == "confirmed" and swapped["source"] == "importer" and swapped["taste_signal"] is True, swapped)
check("its planned candidate is the passed-over 'current' one, with the window made from seconds",
      swapped["planned"]["candidate_id"] == "210:1000" and swapped["planned"]["kind"] == "hero" and swapped["planned"]["source_in"] == 1.0 and swapped["planned"]["source_out"] == 1.52, swapped["planned"])
check("its replacement is what he chose", swapped["replacement"]["candidate_id"] == "212:4250" and swapped["replacement"]["source_out"] == 4.77 and swapped["replacement"]["kind"] == "reveal")
check("it carries the slot, the job, the timestamp of the record and the context",
      swapped["slot"] == {"index": 3, "role": "body", "seconds": 0.52, "cut_at": 1.4} and swapped["job_id"] == 48 and swapped["ts"] == SWAP["ts"]
      and swapped["context"] == {"style": "usual-pace", "imported_from": "review_log", "planned_by_you": False}, swapped)
check("importing the same record twice gives the same id (so the store keeps one)", le.from_review_record(copy.deepcopy(SWAP))[0]["id"] == swapped["id"])
(approved,) = le.from_review_record(APPROVE)
check("a review approve is ONE 'approved' event whose planned candidate is the accepted moment", approved["outcome"] == "approved" and approved["planned"]["candidate_id"] == "210:1000"
      and approved["replacement"] is None and approved["confidence"] == "confirmed" and approved["category"] == "explicit_feedback", approved)
(kept_swap,) = le.from_review_record({**SWAP, "ts": "2026-10-21T10:16:00", "kept_current": True, "chosen": {**SWAP["passed_over"][0]}})
check("a 'swap' that kept the current moment counts as approved", kept_swap["outcome"] == "approved")
(no_current,) = le.from_review_record({**SWAP, "ts": "2026-10-21T10:17:00", "passed_over": [SWAP["passed_over"][1]]})
check("a swap whose log has no 'current' candidate still imports, with no planned side", no_current["planned"] is None and no_current["outcome"] == "swapped")
(with_reason,) = le.from_review_record({**SWAP, "ts": "2026-10-21T10:18:00", "reasons": ["client_request", "made_up_code"], "note": "client wanted the door"})
check("reasons on a review record pass through (unknown codes dropped) and client_request removes the taste signal",
      with_reason["reasons"] == ["client_request"] and with_reason["taste_signal"] is False and with_reason["note"] == "client wanted the door", with_reason)
check("a review record with no ts, no job, no chosen or an unknown action imports to nothing",
      le.from_review_record({k: v for k, v in SWAP.items() if k != "ts"}) == [] and le.from_review_record({**SWAP, "job_id": None}) == []
      and le.from_review_record({k: v for k, v in SWAP.items() if k != "chosen"}) == [] and le.from_review_record({**SWAP, "action": "dance"}) == [] and le.from_review_record("x") == [])

SLOW = {"ts": "2026-10-21T11:00:00", "job_id": 48, "style": "usual-pace", "action": "slow", "slot": {"index": 4, "role": "body", "seconds": 0.5, "cut_at_seconds": 2.0},
        "speed": 0.5, "was": 1.0, "clip": {"name": "C9922.MP4", "fps": 50.0, "seconds": 12.0}, "moment": {"kind": "hero", "punch": 8.0, "what": "car drifts"}, "clip_position": 0.4}
(slowed,) = le.from_speed_record(SLOW)
check("a slow record is an explicit 'slowed' event, confirmed", slowed["category"] == "explicit_feedback" and slowed["outcome"] == "slowed" and slowed["confidence"] == "confirmed" and slowed["taste_signal"], slowed)
check("it keeps the speeds, the clip's frame rate and the moment in its context", slowed["context"]["speed"] == 0.5 and slowed["context"]["was"] == 1.0 and slowed["context"]["clip_fps"] == 50.0
      and slowed["context"]["moment"]["kind"] == "hero" and slowed["slot"]["index"] == 4 and slowed["replacement"]["speed"] == 0.5 and slowed["planned"]["speed"] == 1.0, slowed)
check("the moment's kind is NOT put in planned.kind (a speed decision is not a vote on the moment)", slowed["planned"]["kind"] is None)
(normal,) = le.from_speed_record({**SLOW, "ts": "2026-10-21T11:05:00", "action": "normal", "speed": 1.0, "was": 0.5})
check("a 'normal' record is a 'kept' event with context speed 1.0 and the speed it was", normal["outcome"] == "kept" and normal["context"]["speed"] == 1.0 and normal["context"]["was"] == 0.5 and normal["confidence"] == "confirmed", normal)
check("a speed record with an unknown action or no ts imports to nothing", le.from_speed_record({**SLOW, "action": "fast"}) == [] and le.from_speed_record({k: v for k, v in SLOW.items() if k != "ts"}) == [])
check("undoing a slow-motion shot does not count as a keep of its moment", le.kind_evidence([normal, slowed]) == {})

LEARN = {
    "ts": "2026-10-21T07:29:06", "job_id": 48, "shoot": "GWM - Highlight Video", "sequence": "GWM - Highlight Video - Edit 2026-10-15T13:57:37.402Z", "plan_style": "corporate-highlight-calm",
    "source": "auto-save", "plan_basis": "matched", "plan_made_at": "2026-10-15T15:45:53", "stale_plan": False,
    "plan_shots": [
        {"index": 1, "name": "C0001.MP4", "source_in": 1.0, "source_out": 1.5, "state": "kept", "moment": "event (hero): car turns in -- Claude's judgment"},
        {"index": 2, "name": "C0002.MP4", "source_in": 2.0, "source_out": 2.6, "state": "different_moment", "moment": "steadiest window around an event (reveal): door opens -- Cla"},
        {"index": 3, "name": "C0003.MP4", "source_in": 0.5, "source_out": 1.2, "state": "dropped", "moment": "hand-set pick"},
        {"index": 4, "name": "C0004.MP4", "source_in": 3.0, "source_out": 3.5, "state": "kept", "moment": "event (hero): drift", "speed": 0.5, "he_slowed": True}],
    "his_shots": [
        {"order": 1, "name": "C0001.MP4", "timeline_start": 0.0, "timeline_seconds": 0.5, "source_in": 1.0, "source_out": 1.5, "speed": 1.0, "status": "same_moment", "plan_slot": 1, "event": {"rank": 1, "kind": "hero", "punch": 7.0}},
        {"order": 2, "name": "C0002.MP4", "timeline_start": 0.5, "timeline_seconds": 0.6, "source_in": 9.0, "source_out": 9.6, "speed": 1.0, "status": "other_moment", "plan_slot": None},
        {"order": 3, "name": "C0002.MP4", "timeline_start": 1.1, "timeline_seconds": 0.6, "source_in": 4.0, "source_out": 4.6, "speed": 1.0, "status": "other_moment", "plan_slot": None},
        {"order": 4, "name": "C0009.MP4", "timeline_start": 1.7, "timeline_seconds": 0.4, "source_in": 1.0, "source_out": 1.4, "speed": 1.0, "status": "not_in_plan", "plan_slot": None},
        {"order": 5, "name": "C0004.MP4", "timeline_start": 2.1, "timeline_seconds": 1.0, "source_in": 3.0, "source_out": 3.5, "speed": 0.5, "status": "same_moment", "plan_slot": 4},
        {"order": 6, "name": "C0010.MP4", "timeline_start": 3.1, "timeline_seconds": 0.5, "source_in": 2.0, "source_out": 3.0, "speed": 2.0, "status": "not_in_plan", "plan_slot": None}]}
events = le.from_learn_record(LEARN)
by_outcome = {}
for ev in events:
    by_outcome.setdefault(ev["outcome"], []).append(ev)
check("a matched learn record becomes: 2 kept, 1 replaced, 1 dropped, 2 added, 1 slowed, 1 sped_up (8 events)", {k: len(v) for k, v in by_outcome.items()} == {"kept": 2, "replaced": 1, "dropped": 1, "added": 2, "slowed": 1, "sped_up": 1}, {k: len(v) for k, v in by_outcome.items()})
check("they are all observed edits", all(ev["category"] == "observed_edit" for ev in events))
check("with a matched, non-stale plan every one is 'observed' and a taste signal", all(ev["confidence"] == "observed" and ev["taste_signal"] for ev in events), [ev["confidence"] for ev in events])
check("the auto-save record's source is autosave_watch; a button record's is learn_button", all(ev["source"] == "autosave_watch" for ev in events)
      and all(ev["source"] == "learn_button" for ev in le.from_learn_record({**LEARN, "source": "button"})))
check("plan_ref, project and context follow the record", events[0]["plan_ref"] == {"file": None, "made_at": "2026-10-15T15:45:53", "basis": "matched"} and events[0]["project"] == LEARN["sequence"]
      and events[0]["context"]["style"] == "corporate-highlight-calm" and events[0]["context"]["shoot"] == "GWM - Highlight Video", events[0])
check("every imported event validates", all(le.validate_event(ev) == [] for ev in events))
kept = by_outcome["kept"]
check("a kept shot carries the planned window and the kind read from the plan's own words", kept[0]["planned"]["name"] == "C0001.MP4" and kept[0]["planned"]["source_in"] == 1.0 and kept[0]["planned"]["kind"] == "hero"
      and kept[0]["slot"]["index"] == 1 and kept[0]["replacement"] is None, kept[0])
replaced = by_outcome["replaced"][0]
check("a replaced shot's replacement is his other-moment shot of the SAME clip nearest in source time (4.0 s, not 9.0 s)", replaced["replacement"]["name"] == "C0002.MP4" and replaced["replacement"]["source_in"] == 4.0, replaced["replacement"])
check("a kind in 'steadiest window around an event (reveal)' wording is found", replaced["planned"]["kind"] == "reveal")
dropped = by_outcome["dropped"][0]
check("a dropped shot has no replacement and no kind when the plan's wording names none", dropped["replacement"] is None and dropped["planned"]["kind"] is None and dropped["slot"]["index"] == 3)
added = sorted(by_outcome["added"], key=lambda ev: ev["replacement"]["source_in"])
check("an added shot is his shot the plan never had", [a["replacement"]["name"] for a in added] == ["C0009.MP4", "C0010.MP4"] and added[0]["planned"] is None and added[0]["slot"] is None, added)
slowed_shot, sped_shot = by_outcome["slowed"][0], by_outcome["sped_up"][0]
check("his shot at speed 0.5 is a 'slowed' event on the slot it sits in, with the plan's shot attached", slowed_shot["replacement"]["speed"] == 0.5 and slowed_shot["slot"]["index"] == 4 and slowed_shot["planned"]["name"] == "C0004.MP4", slowed_shot)
check("his shot at speed 2.0 is a 'sped_up' event", sped_shot["replacement"]["speed"] == 2.0 and sped_shot["replacement"]["name"] == "C0010.MP4")
check("the plan shot he kept AND slowed gives both a 'kept' and a 'slowed' event with different ids", len({ev["id"] for ev in events}) == len(events) == 8)
check("a speed of 0.97 or 1.03 is not a retime", not [ev for ev in le.from_learn_record({**LEARN, "his_shots": [{**LEARN["his_shots"][0], "speed": 0.97}, {**LEARN["his_shots"][1], "speed": 1.03}]})
                                                      if ev["outcome"] in ("slowed", "sped_up")])
check("a shot with no recorded speed is not a retime", not [ev for ev in le.from_learn_record({**LEARN, "his_shots": [{**LEARN["his_shots"][0], "speed": None}]}) if ev["outcome"] in ("slowed", "sped_up")])
check("importing the same learn record twice gives the same ids", [ev["id"] for ev in le.from_learn_record(copy.deepcopy(LEARN))] == [ev["id"] for ev in events])

for label, rec in (("basis 'latest'", {**LEARN, "plan_basis": "latest", "stale_plan": True}), ("basis 'newer'", {**LEARN, "plan_basis": "newer", "stale_plan": True}),
                   ("basis 'none'", {**LEARN, "plan_basis": "none", "stale_plan": True}), ("a matched basis but flagged stale", {**LEARN, "stale_plan": True}),
                   ("basis 'latest' without the stale flag", {**LEARN, "plan_basis": "latest", "stale_plan": False}), ("no basis at all", {k: v for k, v in LEARN.items() if k != "plan_basis"})):
    unsure = le.from_learn_record(rec)
    check(f"{label}: every event is 'uncertain' and none is a taste signal", len(unsure) == 8 and all(ev["confidence"] == "uncertain" and ev["taste_signal"] is False for ev in unsure), [(ev["confidence"], ev["taste_signal"]) for ev in unsure])
    check(f"{label}: the reason is written down and the events are still valid", all("why_uncertain" in ev["context"] and le.validate_event(ev) == [] for ev in unsure))
check("an uncertain event keeps the basis it was compared with", le.from_learn_record({**LEARN, "plan_basis": "latest", "stale_plan": True})[0]["plan_ref"]["basis"] == "latest")
check("a learn record with no ts or no job imports to nothing", le.from_learn_record({k: v for k, v in LEARN.items() if k != "ts"}) == [] and le.from_learn_record({**LEARN, "job_id": "48"}) == [])
check("a learn record with nothing in it imports to nothing", le.from_learn_record({**LEARN, "plan_shots": [], "his_shots": []}) == [])
check("a nonsense window on one shot does not stop the rest", len(le.from_learn_record({**LEARN, "plan_shots": [{**LEARN["plan_shots"][0], "source_in": 5.0, "source_out": 4.0}, *LEARN["plan_shots"][1:]]})) == 8)
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "events.jsonl"
    written = le.append_events(store, events) + le.append_events(store, le.from_review_record(SWAP)) + le.append_events(store, le.from_speed_record(SLOW))
    again = le.append_events(store, le.from_learn_record(copy.deepcopy(LEARN))) + le.append_events(store, le.from_review_record(copy.deepcopy(SWAP)))
    check("re-importing the same logs into the store writes nothing the second time", written == 10 and again == 0, (written, again))

# ---- processing ----------------------------------------------------------------------------------------------------------------------------


def moment(kind, kept, *, n, confidence="confirmed", reasons=(), category="explicit_feedback"):
    """One keep-or-change vote on a planned moment of `kind`; n makes it a distinct event."""
    return le.make_event(category=category, confidence=confidence, outcome="approved" if kept else "swapped", source="importer", job_id=100 + n, ts=f"2026-10-22T09:{n // 60:02d}:{n % 60:02d}",
                         slot={"index": n, "role": "body", "seconds": 0.5, "cut_at": None}, planned={"name": f"C{n:04d}.MP4", "kind": kind, "source_in": 1.0, "source_out": 1.5},
                         replacement=None if kept else {"name": f"C{n + 1000:04d}.MP4", "source_in": 2.0, "source_out": 2.5}, reasons=reasons)


evidence_set = ([moment("hero", True, n=i) for i in range(6)] + [moment("hero", False, n=10 + i) for i in range(2)]
                + [moment("reveal", True, n=20)] + [moment("reveal", False, n=30 + i) for i in range(3)])
noise = ([moment("hero", False, n=40 + i, confidence="uncertain", category="observed_edit") for i in range(5)]
         + [moment("reveal", False, n=50 + i, reasons=["client_request"]) for i in range(3)])
ev_clean, ev_noisy = le.kind_evidence(evidence_set), le.kind_evidence(evidence_set + noise)
check("kind_evidence counts kept against changed per kind", ev_clean["hero"]["kept"] == 6 and ev_clean["hero"]["changed"] == 2 and ev_clean["hero"]["n"] == 8
      and ev_clean["reveal"]["kept"] == 1 and ev_clean["reveal"]["changed"] == 3, ev_clean)
check("the keep rate is shrunk: (kept + 2) / (kept + changed + 4)", abs(ev_clean["hero"]["keep_rate"] - 8 / 12) < 1e-3 and abs(ev_clean["reveal"]["keep_rate"] - 3 / 8) < 1e-3, ev_clean)
check("uncertain events and client_request events change nothing", ev_noisy == ev_clean, ev_noisy)
check("a kind seen only in uncertain events does not appear at all", "camera_move" not in le.kind_evidence([moment("camera_move", False, n=60, confidence="uncertain", category="observed_edit")]))
check("kind_evidence of nothing is nothing", le.kind_evidence([]) == {})
dropped_ev = le.make_event(category="observed_edit", confidence="observed", outcome="dropped", source="autosave_watch", job_id=1, planned={"name": "d.mp4", "kind": "hero"})
other_outcomes = [le.make_event(**{**GOOD, "outcome": o, "ts": f"2026-10-22T08:00:0{i}"}) for i, o in enumerate(("slowed", "shortened", "moved", "locked"))]
check("a dropped moment counts as changed; slowing, shortening, moving or locking are not votes", le.kind_evidence([dropped_ev, *other_outcomes])["hero"] == {"kept": 0, "changed": 1, "n": 1, "keep_rate": 0.4}, le.kind_evidence([dropped_ev, *other_outcomes]))
no_kind = le.make_event(**{**GOOD, "outcome": "approved", "planned": {"name": "z.mp4"}, "replacement": None})
check("a planned moment with no kind is not a vote", le.kind_evidence([no_kind]) == {})

# repeated looks at one unfinished edit must not vote more than once
def learn_at(ts, state):
    return {**LEARN, "ts": ts, "plan_shots": [{**LEARN["plan_shots"][0], "state": state}], "his_shots": []}


looks = [ev for ts, st in (("2026-10-21T07:00:00", "kept"), ("2026-10-21T07:10:00", "kept"), ("2026-10-21T07:20:00", "kept")) for ev in le.from_learn_record(learn_at(ts, st))]
check("three auto-saves of the same unfinished edit are three records", len(looks) == 3 and len({ev["id"] for ev in looks}) == 3)
check("but the same planned shot counts ONCE in the evidence", le.kind_evidence(looks)["hero"]["n"] == 1 and le.kind_evidence(looks, collapse_repeats=False)["hero"]["n"] == 3)
changed_mind = [ev for ts, st in (("2026-10-21T07:00:00", "kept"), ("2026-10-21T07:20:00", "different_moment")) for ev in le.from_learn_record(learn_at(ts, st))]
check("when he changes his mind between saves, the latest look wins", le.kind_evidence(changed_mind)["hero"]["kept"] == 0 and le.kind_evidence(changed_mind)["hero"]["changed"] == 1, le.kind_evidence(changed_mind))
check("latest_per_decision leaves explicit feedback and other sequences alone", len(le.latest_per_decision(looks + evidence_set + le.from_learn_record({**learn_at("2026-10-21T08:00:00", "kept"), "sequence": "Another edit"}))) == 1 + len(evidence_set) + 1)
unsure_later = le.from_learn_record({**learn_at("2026-10-21T09:00:00", "different_moment"), "plan_basis": "latest", "stale_plan": True})
check("a LATER uncertain look cannot cancel an earlier observed one", le.kind_evidence(looks[:1] + unsure_later)["hero"]["kept"] == 1)

check("ranking_adjustments is None below the minimum", le.ranking_adjustments(evidence_set) is None and le.ranking_adjustments([]) is None)
thirty = [moment("hero", True, n=i) for i in range(20)] + [moment("hero", False, n=100 + i) for i in range(5)] + [moment("reveal", True, n=200 + i) for i in range(2)] + [moment("reveal", False, n=300 + i) for i in range(3)]
check("29 votes is still below the default minimum of 30", le.ranking_adjustments(thirty[:-1]) is None)
check("uncertain and client_request events do not count toward the minimum", le.ranking_adjustments(thirty[:-1] + noise) is None)
adj = le.ranking_adjustments(thirty)
check("30 votes gives a proposal with support, a timestamp and the schema version", adj is not None and adj["support"] == 30 and adj["schema"] == 1 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", adj["computed_at"]), adj)
overall = (22 + 2) / (30 + 4)
check("the adjustment is the kind's shrunk keep rate minus the overall one", abs(adj["by_kind"]["hero"] - (22 / 29 - overall)) < 1e-3 and abs(adj["overall_keep_rate"] - overall) < 1e-3, adj)
check("and it is clipped to +-0.15 (reveal's raw difference is about -0.26)", adj["by_kind"]["reveal"] == -0.15 and all(-0.15 <= v <= 0.15 for v in adj["by_kind"].values()), adj)
big = [moment("hero", True, n=i) for i in range(30)] + [moment("reveal", False, n=100 + i) for i in range(30)]
check("a kind kept far above average is clipped at +0.15", le.ranking_adjustments(big)["by_kind"] == {"hero": 0.15, "reveal": -0.15}, le.ranking_adjustments(big))
check("a lower minimum can be asked for", le.ranking_adjustments(evidence_set, min_events=10) is not None and le.ranking_adjustments(evidence_set, min_events=10)["support"] == 12)
check("computing a proposal does not change the events", thirty[0] == moment("hero", True, n=0))

mixed = [swapped, approved, slowed, normal, *events, unc, obs, le.make_event(**{**GOOD, "reasons": ["client_request", "wrong_moment"], "ts": "2026-10-22T15:00:00"}),
         le.make_event(category="inferred_preference", confidence="uncertain", outcome="kept", source="planner", job_id=48, context={"support": 4}),
         le.make_event(**{**GOOD, "outcome": "reasoned", "reasons": ["weak_composition"], "ts": "2026-10-22T15:01:00"})]
s = le.summarize(mixed)
check("summarize: the total matches and every breakdown adds up to it", s["total"] == len(mixed) and sum(s["by_category"].values()) == len(mixed) and sum(s["by_confidence"].values()) == len(mixed)
      and sum(s["by_outcome"].values()) == len(mixed), s)
check("summarize: counts by category", s["by_category"]["explicit_feedback"] == 6 and s["by_category"]["observed_edit"] == 10 and s["by_category"]["inferred_preference"] == 1, s["by_category"])
check("summarize: counts by confidence", s["by_confidence"] == {"confirmed": 6, "observed": 9, "uncertain": 2}, s["by_confidence"])
check("summarize: counts by outcome and reason", s["by_outcome"]["swapped"] == 2 and s["by_outcome"]["kept"] == 6 and s["by_outcome"]["slowed"] == 2 and s["by_outcome"]["reasoned"] == 1
      and s["by_reason"]["wrong_moment"] == 1 and s["by_reason"]["client_request"] == 1 and s["by_reason"]["weak_composition"] == 1, (s["by_outcome"], s["by_reason"]))
expected_taste = sum(1 for ev in mixed if ev["confidence"] in ("confirmed", "observed") and "client_request" not in ev["reasons"])
check("summarize: the taste signals are the confirmed or observed ones without client_request", s["taste_signals"] == expected_taste == 14, (s["taste_signals"], expected_taste))
check("summarize of nothing is all zeros", le.summarize([])["total"] == 0 and le.summarize([])["taste_signals"] == 0 and set(le.summarize([])["by_category"].values()) == {0})
check("summarize: 'taste_votes' counts only the events that vote for or against a kind of moment (what a proposal needs 30 of), never locks, reasons or choices",
      s["taste_votes"] == len(le._kind_votes(mixed, True)) and s["taste_votes"] < s["taste_signals"] and le.summarize([])["taste_votes"] == 0, (s["taste_votes"], s["taste_signals"]))
_lock = le.make_event(category="explicit_feedback", confidence="confirmed", outcome="locked", source="review_page", job_id=48, ts=le.now_precise(),
                      planned={"name": "C0001.MP4", "source_in": 1.0, "source_out": 1.5, "kind": "hero"})
check("a lock is trustworthy but not a vote", le.summarize([_lock])["taste_signals"] == 1 and le.summarize([_lock])["taste_votes"] == 0)
check("live events are timed to the microsecond and still pass validation", re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}", _lock["ts"]) and not le.validate_event(_lock), _lock["ts"])

rc = le.reason_counts(mixed)
check("reason_counts counts the reasons of explicit events only", rc == {"wrong_moment": 1, "client_request": 1, "weak_composition": 1}, rc)
check("reason_counts ignores reasons on observed edits", le.reason_counts([le.make_event(category="observed_edit", confidence="uncertain", outcome="kept", source="importer", job_id=1, reasons=["other"])]) == {})
check("reason_counts of nothing is nothing", le.reason_counts([]) == {})

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
