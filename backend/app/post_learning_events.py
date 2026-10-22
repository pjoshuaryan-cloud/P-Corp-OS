"""
POST (2026-10-22) -- ONE versioned, append-only record type for everything the system learns from Josh's edits.

Why: the learning side of POST collects a lot (the review page's swaps and approvals, the slow-motion toggle, Learn From My Edit, the auto-save watch) but each log
has its own shape, none carries a schema version, none says HOW SURE we are of what it records, and nothing can act on any of it. This module is the single
record they all convert into, plus the plain counting that turns records into evidence. It reads and writes no log of its own accord: callers hand it dicts
and a path.

The rules the record is built around (every one of them is enforced by validate_event, not just written down here):

  1. A finished timeline is EVIDENCE, not a verdict. A change in it may reflect client feedback or a constraint of that one project rather than Josh's general
     taste. So an observed edit is never "confirmed", and a reason of "client_request" removes a record from the taste evidence even when Josh gave it himself.
  2. Four kinds of knowledge stay distinguishable and are never blended:
        explicit feedback     Josh TOLD us (a click on the review page, a reason he gave)           -> confidence "confirmed"
        observed edit         seen directly in his saved timeline AND matched to the plan that
                              timeline was actually built from                                      -> confidence "observed"
        observed, unmatched   seen in his timeline but compared with a plan he did not build from,
                              or media that could not be matched with certainty                     -> confidence "uncertain"
        inferred preference   a conclusion drawn from several records                               -> "uncertain" unless it rests on >= 30 examples
  3. Uncertain records are kept (they cost nothing and may become useful) but are never treated as confirmed: they are never a taste signal and no counting
     function in this module looks at them.
  4. Learning never needs model fine-tuning. All of it is counting records, with a prior so a handful of examples cannot swing anything.
  5. This module only PROPOSES. A learned ordering must still pass the planner's held-out adoption gate (learning/taste.py) before it changes a single plan.

Records are JSON lines, one event per line, ids are deterministic (the same event appended twice is stored once), and the schema version is on every record so
an older reader can skip what it does not understand.

Pure functions wherever possible (make_event, validate_event, the importers, the counting); the only file access is append_events / load_events.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_log = logging.getLogger(__name__)

EVENT_SCHEMA_VERSION = 1

CATEGORIES = ("explicit_feedback", "observed_edit", "inferred_preference")

# confirmed = Josh told us (a review-page click or a reason he gave).
# observed  = seen directly in his saved timeline AND matched to the plan that timeline was actually built from.
# uncertain = anything else: plan basis not matched, ambiguous media mapping, missing media, an inference from few examples.
CONFIDENCE = ("confirmed", "observed", "uncertain")

OUTCOMES = ("kept", "replaced", "shortened", "extended", "moved", "dropped", "added", "slowed", "sped_up", "approved", "swapped", "locked", "unlocked", "regenerated", "reasoned",
            "chosen")   # chosen: he picked one variant of a set (context names the style and the ones he passed over); says nothing about any single shot

SOURCES = ("review_page", "learn_button", "autosave_watch", "importer", "planner", "variants_page")

EVENTS_FILE = "learning_events.jsonl"   # one per job, beside its plans (edit_plans/); every producer appends here
_DATA = Path(__file__).resolve().parents[1] / "data" / "learning"   # git-ignored, on the Mac
CENTRAL_EVENTS = _DATA / "events" / "events.jsonl"   # every job's events mirrored in one place, so the adoption gate runs with the drives unplugged
ADOPTED_PREFERENCES = _DATA / "adopted_kind_preferences.json"   # written ONLY by learning/adopt_preferences.py after its held-out gate passes; the planner reads it

# Which plan a timeline was compared with (post_plan_history.plan_for_build_time's words): "matched" is the only one that makes an edit "observed".
PLAN_BASES = ("matched", "latest", "newer", "none")

REASON_CODES: dict[str, str] = {
    "action_starts_too_late": "Action starts too late",
    "action_starts_too_early": "Action starts too early",
    "wrong_moment": "Wrong moment of the clip",
    "weak_composition": "Weak composition",
    "poor_technical_quality": "Poor technical quality (focus, exposure, shake)",
    "wrong_visual_direction": "Wrong visual direction",
    "repetitive_shot": "Too similar to another shot",
    "poor_continuity": "Poor continuity with the shots around it",
    "wrong_duration": "Wrong duration",
    "not_suitable_for_brief": "Not suitable for the brief",
    "client_request": "Client asked for it",
    "other": "Other reason",
}
# A reason that says nothing about Josh's taste: a client's wish is a constraint on the project, not a preference of his.
NOT_TASTE_REASONS = frozenset({"client_request"})

NOTE_MAX_CHARS = 280
MIN_INFERENCE_SUPPORT = 30          # an inferred preference may only be "observed" when it rests on at least this many examples
MEDIA_DURATION_TOLERANCE = 0.05     # seconds: two files with the same name count as the same media when their durations agree this closely
SLOWED_BELOW = 0.95                 # one of his shots with a speed under this was slowed down (post_learn.RETIMED_TOLERANCE is the same 5%)
SPED_UP_ABOVE = 1.05
PRIOR_KEPT, PRIOR_CHANGED = 2, 2    # Beta(2,2): a kind with no evidence sits at 50%, and a few examples move it only a little
ADJUSTMENT_LIMIT = 0.15             # a proposed ranking adjustment never exceeds this either way
DEFAULT_MIN_EVENTS = 30

_KEPT_OUTCOMES = ("kept", "approved")
_CHANGED_OUTCOMES = ("replaced", "swapped", "dropped")

_PLAN_REF_KEYS = ("file", "made_at", "basis")
_SLOT_KEYS = ("index", "role", "seconds", "cut_at")
_CANDIDATE_KEYS = ("candidate_id", "file_id", "name", "source_in", "source_out", "kind", "punch", "speed")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def now_precise() -> str:
    """Local time to the microsecond, for events a click produces live: the id includes the time, and two identical decisions moments apart (lock, unlock,
    lock) are separate decisions. Importers keep their record's own time instead, so importing a log twice still stores each event once."""
    return datetime.now().isoformat(timespec="microseconds")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _basename(name: str | None) -> str:
    """The file name without any folder, either slash style: media is matched by basename, never by full path (drives get renamed and projects get moved)."""
    return (name or "").replace("\\", "/").rsplit("/", 1)[-1]


# ---- the record -------------------------------------------------------------------------------------------------------------------------------

def _shaped(value: Any, keys: tuple[str, ...]) -> Any:
    """A dict reduced to exactly `keys` (missing ones None) so every stored record has the same shape; anything else Josh wants kept goes in `context`.
    None stays None, and a non-dict is left alone so validate_event can report it."""
    if not isinstance(value, dict):
        return value
    return {k: value.get(k) for k in keys}


def _round(v: Any) -> Any:
    return round(float(v), 3) if _is_number(v) else None


def _candidate_identity(c: Any) -> list[Any] | None:
    """Which clip and which stretch of it: what makes two candidates 'the same moment' for the purpose of the id."""
    if not isinstance(c, dict):
        return None
    name = c.get("name")
    return [c.get("candidate_id"), c.get("file_id"), name.lower() if isinstance(name, str) else None, _round(c.get("source_in")), _round(c.get("source_out"))]


def _taste_signal(confidence: Any, reasons: Iterable[Any]) -> bool:
    """True only when the record is trustworthy (confirmed or observed) AND none of its reasons is one that says nothing about taste."""
    return confidence in ("confirmed", "observed") and not any(r in NOT_TASTE_REASONS for r in reasons)


def event_id(e: dict[str, Any]) -> str:
    """First 16 hex characters of a SHA-1 over what identifies the event: category, outcome, source, job, which plan, which slot, the planned and replacement
    candidates (identity and window), the reasons (sorted) and the timestamp. Free text and context are left out, so correcting a note does not make a new event."""
    plan_ref = e.get("plan_ref") if isinstance(e.get("plan_ref"), dict) else {}
    slot = e.get("slot") if isinstance(e.get("slot"), dict) else {}
    reasons = e.get("reasons") if isinstance(e.get("reasons"), (list, tuple)) else []
    parts = [e.get("category"), e.get("outcome"), e.get("source"), e.get("job_id"), [plan_ref.get("file"), plan_ref.get("made_at"), plan_ref.get("basis")], slot.get("index"),
             _candidate_identity(e.get("planned")), _candidate_identity(e.get("replacement")), sorted(str(r) for r in reasons), e.get("ts")]
    blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def make_event(*, category: str, confidence: str, outcome: str, source: str, job_id: int, ts: str | None = None, project: str | None = None,
               plan_ref: dict | None = None, slot: dict | None = None, planned: dict | None = None, replacement: dict | None = None, media: dict | None = None,
               reasons: Iterable[str] = (), note: str | None = None, context: dict | None = None) -> dict[str, Any]:
    """One learning event, complete and validated. Fills `schema`, `ts` (local time, ISO, to the second, when not given), the deterministic `id` and `taste_signal`.
    `note` is cut to 280 characters. Raises ValueError listing EVERY problem if the event is not valid (see validate_event).

    Shapes:
      plan_ref     {"file": str, "made_at": str | None, "basis": "matched" | "latest" | "newer" | "none" | None}
      slot         {"index": int, "role": str | None, "seconds": float | None, "cut_at": float | None}
      planned /    {"candidate_id": str | None, "file_id": int | None, "name": str | None, "source_in": float | None, "source_out": float | None,
      replacement   "kind": str | None, "punch": float | None, "speed": float | None}
      media        what media_identity() returns
      context      any dict (style, variant, shoot, ...); the only free-form part of the record
    Keys outside these shapes are dropped so every stored record looks the same."""
    if isinstance(reasons, str):
        reasons = [reasons]
    reason_list: list[Any] = []
    for r in reasons or ():
        if r not in reason_list:
            reason_list.append(r)
    if isinstance(note, str):
        note = note.strip()[:NOTE_MAX_CHARS] or None
    e: dict[str, Any] = {
        "schema": EVENT_SCHEMA_VERSION, "id": "", "ts": ts if ts is not None else _now(), "category": category, "confidence": confidence,
        "taste_signal": _taste_signal(confidence, reason_list), "outcome": outcome, "source": source, "job_id": job_id, "project": project,
        "plan_ref": _shaped(copy.deepcopy(plan_ref), _PLAN_REF_KEYS), "slot": _shaped(copy.deepcopy(slot), _SLOT_KEYS),
        "planned": _shaped(copy.deepcopy(planned), _CANDIDATE_KEYS), "replacement": _shaped(copy.deepcopy(replacement), _CANDIDATE_KEYS),
        "media": copy.deepcopy(media), "reasons": reason_list, "note": note, "context": copy.deepcopy(context),
    }
    e["id"] = event_id(e)
    problems = validate_event(e)
    if problems:
        raise ValueError("Invalid learning event:\n- " + "\n- ".join(problems))
    return e


def _window_problems(label: str, c: Any) -> list[str]:
    if c is None:
        return []
    if not isinstance(c, dict):
        return [f"{label} must be a dictionary describing a candidate, not {type(c).__name__}."]
    problems = []
    a, b = c.get("source_in"), c.get("source_out")
    for key, v in (("source_in", a), ("source_out", b)):
        if v is not None and not _is_number(v):
            problems.append(f"{label}.{key} must be a number of seconds, not {v!r}.")
    if _is_number(a) and _is_number(b) and not (b > a >= 0):
        problems.append(f"{label} has a bad window: source_out ({b}) must be greater than source_in ({a}), and source_in must not be negative.")
    return problems


def validate_event(e: dict[str, Any]) -> list[str]:
    """Every way an event breaks the rules, in plain English. An empty list means it is valid."""
    if not isinstance(e, dict):
        return [f"An event must be a dictionary, not {type(e).__name__}."]
    problems: list[str] = []
    if e.get("schema") != EVENT_SCHEMA_VERSION:
        problems.append(f"The schema version is {e.get('schema')!r}; this code reads version {EVENT_SCHEMA_VERSION}.")
    category, confidence, outcome, source = e.get("category"), e.get("confidence"), e.get("outcome"), e.get("source")
    for label, value, allowed in (("category", category, CATEGORIES), ("confidence", confidence, CONFIDENCE), ("outcome", outcome, OUTCOMES), ("source", source, SOURCES)):
        if value not in allowed:
            problems.append(f"Unknown {label} {value!r}; it must be one of: {', '.join(allowed)}.")
    if not _is_int(e.get("job_id")):
        problems.append(f"job_id must be a whole number, not {e.get('job_id')!r}.")
    ts = e.get("ts")
    try:
        if not isinstance(ts, str):
            raise ValueError
        datetime.fromisoformat(ts)
    except ValueError:
        problems.append(f"ts must be an ISO date-time such as 2026-10-22T14:30:00, not {ts!r}.")
    if e.get("project") is not None and not isinstance(e.get("project"), str):
        problems.append("project must be text (or left empty).")

    plan_ref, slot, media, context = e.get("plan_ref"), e.get("slot"), e.get("media"), e.get("context")
    if plan_ref is not None:
        if not isinstance(plan_ref, dict):
            problems.append("plan_ref must be a dictionary (or left empty).")
        else:
            if plan_ref.get("basis") is not None and plan_ref.get("basis") not in PLAN_BASES:
                problems.append(f"plan_ref.basis {plan_ref.get('basis')!r} is not one of: {', '.join(PLAN_BASES)}.")
            for key in ("file", "made_at"):
                if plan_ref.get(key) is not None and not isinstance(plan_ref.get(key), str):
                    problems.append(f"plan_ref.{key} must be text (or left empty).")
    if slot is not None:
        if not isinstance(slot, dict):
            problems.append("slot must be a dictionary (or left empty).")
        elif not _is_int(slot.get("index")):
            problems.append(f"slot.index must be a whole number, not {slot.get('index')!r}.")
    problems += _window_problems("planned", e.get("planned"))
    problems += _window_problems("replacement", e.get("replacement"))
    if media is not None and not (isinstance(media, dict) and isinstance(media.get("key"), str)):
        problems.append("media must be what media_identity() returns (a dictionary with a text key).")
    if context is not None and not isinstance(context, dict):
        problems.append("context must be a dictionary (or left empty).")
    note = e.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX_CHARS):
        problems.append(f"note must be text of at most {NOTE_MAX_CHARS} characters.")

    reasons = e.get("reasons")
    if not isinstance(reasons, (list, tuple)):
        problems.append("reasons must be a list of reason codes.")
        reasons = []
    else:
        unknown = [r for r in reasons if not (isinstance(r, str) and r in REASON_CODES)]
        if unknown:
            problems.append(f"Unknown reason code(s) {unknown!r}; the known ones are: {', '.join(REASON_CODES)}.")
    if outcome == "reasoned" and not reasons:
        problems.append("An event with outcome 'reasoned' needs at least one reason.")

    # What each category is allowed to claim.
    if category == "explicit_feedback" and confidence != "confirmed":
        problems.append(f"Explicit feedback is Josh telling us, so it must be 'confirmed', not {confidence!r}.")
    if category == "observed_edit":
        if confidence == "confirmed":
            problems.append("An observed edit can never be 'confirmed': a timeline shows what he did, not that he told us why. Use 'observed' or 'uncertain'.")
        elif confidence == "observed" and isinstance(plan_ref, dict) and plan_ref.get("basis") in ("latest", "newer", "none"):
            problems.append(f"An observed edit must be matched to the plan the timeline was built from, but plan_ref.basis is {plan_ref.get('basis')!r}: it can only be 'uncertain'.")
    if category == "inferred_preference":
        support = context.get("support") if isinstance(context, dict) else None
        if confidence == "confirmed":
            problems.append("An inferred preference can never be 'confirmed': Josh did not say it.")
        elif confidence == "observed" and not (_is_number(support) and support >= MIN_INFERENCE_SUPPORT):
            problems.append(f"An inferred preference must be 'uncertain' unless context['support'] is at least {MIN_INFERENCE_SUPPORT} examples (it is {support!r}).")

    taste = e.get("taste_signal")
    if not isinstance(taste, bool):
        problems.append("taste_signal must be true or false.")
    elif taste != _taste_signal(confidence, reasons):
        problems.append(f"taste_signal is {taste}, but it should be {not taste}: it is true only for a confirmed or observed event with no 'client_request' reason.")
    try:
        json.dumps(e)
    except (TypeError, ValueError):
        problems.append("The event cannot be written as JSON (something in it is not plain text, numbers, lists or dictionaries).")
    if e.get("id") != event_id(e):
        problems.append(f"The id {e.get('id')!r} does not match the event's content (expected {event_id(e)!r}); the event was changed after it was made.")
    return problems


# ---- media identity ---------------------------------------------------------------------------------------------------------------------------

def media_identity(*, name: str | None, duration: float | None, checksum: str | None = None, file_id: int | None = None) -> dict[str, Any]:
    """A key for a piece of footage that survives the project being moved. With a checksum (ingest verifies every file by SHA-256) the key is exact and `stable` is True.
    Without one it is the file's name plus its duration to 0.01 s: good enough to recognise a clip, never proof, so `stable` is False.
    The name is the file's basename: the folder it sat in at the time says nothing about which clip it is."""
    base = _basename(name)
    if checksum:
        digest = checksum[len("sha256:"):] if checksum.lower().startswith("sha256:") else checksum
        key = f"sha256:{digest}"
    else:
        key = f"name:{base.lower()}|dur:{duration:.2f}" if duration is not None else f"name:{base.lower()}|dur:unknown"
    return {"key": key, "stable": bool(checksum), "name": base or None, "duration": duration, "file_id": file_id}


def match_media(name: str, duration: float | None, known: list[dict]) -> tuple[dict | None, str]:
    """Finds the known file (`known` items carry name / duration / checksum / file_id) that a name in a saved project refers to. Returns (item, "observed") when the match is
    certain and (None, "uncertain") when it is not.

    Matching is by BASENAME (case-insensitive) and DURATION, never by full path: the card, drive or folder a file sat in when the project was saved is not what identifies it,
    and a renamed or relocated file keeps its name and its length. Rules:
      - one file with that name and a duration within 0.05 s (or, when no duration is given, the only file with that name): a match;
      - several files with that name: the one within 0.05 s of the duration, if exactly one is;
      - no file with that name, a different duration (the file may have been re-exported), or more than one file that fits: uncertain."""
    wanted = _basename(name).lower()
    same_name = [k for k in known if _basename(k.get("name")).lower() == wanted] if wanted else []
    if not same_name:
        return None, "uncertain"
    if duration is None:
        return (same_name[0], "observed") if len(same_name) == 1 else (None, "uncertain")
    close = [k for k in same_name if _is_number(k.get("duration")) and abs(k["duration"] - duration) <= MEDIA_DURATION_TOLERANCE + 1e-9]
    if len(close) == 1:
        return close[0], "observed"
    return None, "uncertain"


# ---- the store --------------------------------------------------------------------------------------------------------------------------------

def _read_lines(path: Path) -> Iterable[dict[str, Any]]:
    """Every line of the file that is a JSON object, in order. Blank and corrupt lines are skipped without comment."""
    if not path.exists():
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def _lacks_final_newline(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        with open(path, "rb") as fh:
            fh.seek(size - 1)
            return fh.read(1) != b"\n"
    except OSError:
        return False


def append_events(path: Path, events: list[dict[str, Any]]) -> int:
    """Appends events to a JSON-lines file and returns how many were actually written. Every event is validated FIRST and a bad one raises ValueError (listing all problems)
    before anything is written, so a bad batch never lands half-way. Events whose id is already in the file (or repeated within the batch) are skipped: appending the same
    event twice stores it once. Each line goes out in ONE unbuffered write, so a crash can leave at most a missing final newline, which the next append repairs."""
    path = Path(path)
    problems = [f"event {i}: {p}" for i, e in enumerate(events) for p in validate_event(e)]
    if problems:
        raise ValueError("Cannot append invalid learning events:\n- " + "\n- ".join(problems))
    have = {row["id"] for row in _read_lines(path) if isinstance(row.get("id"), str)}
    fresh: list[dict[str, Any]] = []
    for e in events:
        if e["id"] not in have:
            have.add(e["id"])
            fresh.append(e)
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    repair = _lacks_final_newline(path)
    with open(path, "ab", buffering=0) as fh:
        if repair:
            fh.write(b"\n")
        for e in fresh:
            fh.write((json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8"))
    return len(fresh)


def record_for_job(edit_dir: Path, events: list[dict[str, Any] | None]) -> int:
    """Appends a producer's events to the job's EVENTS_FILE. Never raises: a learning record must never break the click or the build that produced it, so a failure
    is logged and reported as -1. Empty or None entries are dropped (the importers return [] for a record they can't convert)."""
    events = [e for e in events if e]
    if not events:
        return 0
    try:
        written = append_events(Path(edit_dir) / EVENTS_FILE, events)
    except (OSError, ValueError) as exc:
        _log.warning("learning events not recorded in %s: %s", edit_dir, exc)
        return -1
    if _is_real_job_folder(edit_dir):
        try:
            append_events(CENTRAL_EVENTS, events)   # same ids, so the mirror never doubles anything
        except (OSError, ValueError) as exc:
            _log.warning("learning events not mirrored to %s: %s", CENTRAL_EVENTS, exc)
    return written


def _is_real_job_folder(edit_dir: Path) -> bool:
    """False for a folder in the system's temporary space: that is a test, and a test must never write into his real learning store."""
    import tempfile
    here = os.path.realpath(str(edit_dir))
    return not any(here.startswith(os.path.realpath(t) + os.sep) for t in {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders"})


def load_events(path: Path) -> list[dict[str, Any]]:
    """Every valid event in the file, in the order written. Blank lines, corrupt lines and events that do not pass validate_event (including events of a schema version
    this code does not read) are skipped without comment: they stay in the file untouched."""
    return [row for row in _read_lines(Path(path)) if not validate_event(row)]


# ---- importers from the logs that already exist -----------------------------------------------------------------------------------------------
# Pure functions over one record (one line of a log, or one feedback file). They never read files. A record that cannot become a valid event (no ts or job_id, an action
# they do not know, a window that makes no sense) yields no events rather than raising, so one bad line cannot stop a bulk import. The record's own ts is kept,
# so importing the same log twice produces the same ids and append_events stores each event once.

def _importable(rec: dict[str, Any]) -> bool:
    return _is_int(rec.get("job_id")) and isinstance(rec.get("ts"), str) and bool(rec["ts"])


def _try_event(**kwargs: Any) -> dict[str, Any] | None:
    try:
        return make_event(**kwargs)
    except ValueError:
        return None


def _clean_window(start: Any, end: Any) -> tuple[float | None, float | None]:
    """(source_in, source_out) when they form a real window, else (None, None): a log line with a nonsense window still says WHICH clip, so it is kept without one."""
    if _is_number(start) and _is_number(end) and end > start >= 0:
        return round(float(start), 3), round(float(end), 3)
    return None, None


def _review_candidate(c: Any) -> dict[str, Any] | None:
    """A candidate of review_log.jsonl ({id, file_id, name, source_in, seconds, kind, punch, ...}) in the event's shape; its window is source_in + seconds."""
    if not isinstance(c, dict):
        return None
    start, seconds = c.get("source_in"), c.get("seconds")
    a, b = _clean_window(start, start + seconds if _is_number(start) and _is_number(seconds) else None)
    if a is None and _is_number(start) and start >= 0:
        a = round(float(start), 3)   # no usable length, but the start still says where in the clip
    return {"candidate_id": c.get("id"), "file_id": c.get("file_id"), "name": c.get("name"), "source_in": a, "source_out": b,
            "kind": c.get("kind"), "punch": c.get("punch"), "speed": c.get("speed")}


def _review_slot(slot: Any) -> dict[str, Any] | None:
    if not isinstance(slot, dict) or not _is_int(slot.get("index")):
        return None
    return {"index": slot["index"], "role": slot.get("role"), "seconds": slot.get("seconds"), "cut_at": slot.get("cut_at_seconds", slot.get("cut_at"))}


def from_review_record(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """One line of review_log.jsonl -> events. Josh clicked on the review page, so everything here is explicit feedback and 'confirmed'.
    An approval (or a swap that kept the current moment) is one 'approved' event whose planned candidate is the moment he accepted. A swap is one 'swapped' event: planned is
    the candidate that was in the slot (the passed-over one whose origin is 'current', if the log has it) and replacement is what he chose.
    If a future log line carries `reasons` (known codes only) or a `note`, they are passed through; unknown codes are dropped."""
    if not isinstance(rec, dict) or not _importable(rec) or not isinstance(rec.get("chosen"), dict) or rec.get("action") not in ("swap", "approve"):
        return []
    reasons = [r for r in (rec.get("reasons") if isinstance(rec.get("reasons"), list) else []) if isinstance(r, str) and r in REASON_CODES]
    common: dict[str, Any] = {"category": "explicit_feedback", "confidence": "confirmed", "source": "importer", "job_id": rec["job_id"], "ts": rec["ts"], "slot": _review_slot(rec.get("slot")),
                              "reasons": reasons, "note": rec.get("note") if isinstance(rec.get("note"), str) else None,
                              "context": {"style": rec.get("style"), "imported_from": "review_log", "planned_by_you": bool(rec.get("current_was_yours"))}}
    chosen = _review_candidate(rec["chosen"])
    if rec["action"] == "approve" or rec.get("kept_current"):
        event = _try_event(outcome="approved", planned=chosen, **common)
    else:
        current = next((c for c in rec.get("passed_over") or [] if isinstance(c, dict) and c.get("origin") == "current"), None)
        # the same moment nudged earlier or later: the moment was right, only its timing moved, so it is 'moved' (not a vote against that kind of moment)
        nudged = rec["chosen"].get("origin") in ("earlier", "later")
        event = _try_event(outcome="moved" if nudged else "swapped", planned=_review_candidate(current), replacement=chosen, **common)
    return [event] if event else []


def from_speed_record(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """One line of review_speed_log.jsonl -> events. 'slow' becomes a 'slowed' event. 'normal' (he put a slowed shot back to real time) becomes a 'kept' event with
    context {"speed": 1.0, "was": ...}. Both are explicit and 'confirmed'.
    The moment's kind goes in context["moment"], NOT in planned.kind, on purpose: a speed decision says nothing about whether he liked the MOMENT, so it must not count as a
    vote for or against a kind of moment in kind_evidence (a 'kept' from undoing a slow-motion would otherwise look like approval of the moment)."""
    if not isinstance(rec, dict) or not _importable(rec) or rec.get("action") not in ("slow", "normal"):
        return []
    clip = rec.get("clip") if isinstance(rec.get("clip"), dict) else {}
    name = clip.get("name")
    speed, was = rec.get("speed"), rec.get("was")
    event = _try_event(
        category="explicit_feedback", confidence="confirmed", outcome="slowed" if rec["action"] == "slow" else "kept", source="importer", job_id=rec["job_id"], ts=rec["ts"],
        slot=_review_slot(rec.get("slot")), planned={"name": name, "speed": was}, replacement={"name": name, "speed": speed},
        context={"style": rec.get("style"), "imported_from": "review_speed_log", "speed": speed, "was": was, "moment": rec.get("moment"),
                 "clip_fps": clip.get("fps"), "clip_seconds": clip.get("seconds"), "clip_position": rec.get("clip_position")})
    return [event] if event else []


_EVENT_KIND = re.compile(r"\bevent \(([a-z_]+)\)")


def _kind_from_moment(moment: Any) -> str | None:
    """The plan's own words for a shot's moment ('event (hero): ...', 'steadiest window around an event (reveal): ...', 'picked in review -- event (hero): ...') name its kind;
    other wording ('hand-set pick', 'composition pick') names none."""
    m = _EVENT_KIND.search(moment) if isinstance(moment, str) else None
    return m.group(1) if m else None


def _plan_shot_candidate(ps: dict[str, Any]) -> dict[str, Any]:
    a, b = _clean_window(ps.get("source_in"), ps.get("source_out"))
    return {"candidate_id": None, "file_id": None, "name": ps.get("name"), "source_in": a, "source_out": b, "kind": _kind_from_moment(ps.get("moment")), "punch": None, "speed": ps.get("speed")}


def _his_shot_candidate(shot: dict[str, Any]) -> dict[str, Any]:
    a, b = _clean_window(shot.get("source_in"), shot.get("source_out"))
    ev = shot.get("event") if isinstance(shot.get("event"), dict) else {}
    return {"candidate_id": None, "file_id": None, "name": shot.get("name"), "source_in": a, "source_out": b, "kind": ev.get("kind"), "punch": ev.get("punch"), "speed": shot.get("speed")}


def _centre(c: dict[str, Any]) -> float | None:
    a, b = c.get("source_in"), c.get("source_out")
    return (a + b) / 2.0 if _is_number(a) and _is_number(b) else None


def from_learn_record(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """One Learn From My Edit / auto-save record -> events, all category 'observed_edit'. Per PLANNED shot: kept -> 'kept'; different_moment -> 'replaced' (the replacement is his
    shot of the same clip, from his shots marked 'other_moment', nearest in source time, if there is one); dropped -> 'dropped'. His shots the plan never had -> 'added'. His shots
    retimed by more than 5% -> an extra 'slowed' or 'sped_up' event.
    Confidence is 'observed' ONLY when plan_basis is 'matched' and the plan is not flagged stale: it was compared with the plan the sequence was actually built from. Any other
    basis gives 'uncertain' (and so never a taste signal), with the reason in context["why_uncertain"]. The kind of a planned moment is read from the plan's own wording."""
    if not isinstance(rec, dict) or not _importable(rec):
        return []
    basis = rec.get("plan_basis") if rec.get("plan_basis") in PLAN_BASES else None
    stale = bool(rec.get("stale_plan"))
    observed = basis == "matched" and not stale
    context: dict[str, Any] = {"style": rec.get("plan_style"), "shoot": rec.get("shoot"), "imported_from": "learn_record", "stale_plan": stale}
    if not observed:
        context["why_uncertain"] = (f"the timeline was compared with a plan (basis {basis!r}) that is not known to be the one it was built from" if basis != "matched"
                                    else "the saved plan is flagged as stale")
    common: dict[str, Any] = {"category": "observed_edit", "confidence": "observed" if observed else "uncertain", "source": "learn_button" if rec.get("source") == "button" else "autosave_watch",
                              "job_id": rec["job_id"], "ts": rec["ts"], "project": rec.get("sequence") if isinstance(rec.get("sequence"), str) else None,
                              "plan_ref": {"file": None, "made_at": rec.get("plan_made_at"), "basis": basis}}
    plan_shots = [p for p in rec.get("plan_shots") or [] if isinstance(p, dict)]
    his_shots = [s for s in rec.get("his_shots") or [] if isinstance(s, dict)]
    plan_by_index = {p["index"]: p for p in plan_shots if _is_int(p.get("index"))}
    events: list[dict[str, Any] | None] = []

    outcome_for = {"kept": "kept", "different_moment": "replaced", "dropped": "dropped"}
    for ps in plan_shots:
        outcome = outcome_for.get(ps.get("state"))
        if outcome is None:
            continue
        planned = _plan_shot_candidate(ps)
        speed = ps.get("speed") if _is_number(ps.get("speed")) and ps["speed"] > 0 else 1.0
        slot = {"index": ps["index"], "role": None, "seconds": round((planned["source_out"] - planned["source_in"]) / speed, 3) if planned["source_in"] is not None and planned["source_out"] is not None else None,
                "cut_at": None} if _is_int(ps.get("index")) else None
        replacement = None
        if outcome == "replaced":
            mine = [c for c in (_his_shot_candidate(s) for s in his_shots if s.get("status") == "other_moment" and _basename(s.get("name")).lower() == _basename(ps.get("name")).lower())
                    if _centre(c) is not None]
            here = _centre(planned)
            if mine and here is not None:
                replacement = min(mine, key=lambda c: abs(_centre(c) - here))   # type: ignore[operator]
            elif len(mine) == 1:
                replacement = mine[0]   # the plan's own window is unusable, but there is only one candidate for what he used instead
        events.append(_try_event(outcome=outcome, slot=slot, planned=planned, replacement=replacement, context=context, **common))

    for shot in his_shots:
        mine = _his_shot_candidate(shot)
        extra = {"order": shot.get("order")}
        if shot.get("status") == "not_in_plan":
            events.append(_try_event(outcome="added", replacement=mine, context={**context, **extra}, **common))
        speed = shot.get("speed")
        if _is_number(speed) and speed > 0 and (speed < SLOWED_BELOW or speed > SPED_UP_ABOVE):
            index = shot.get("plan_slot") if _is_int(shot.get("plan_slot")) else None
            planned_shot = plan_by_index.get(index) if index is not None else None
            events.append(_try_event(outcome="slowed" if speed < SLOWED_BELOW else "sped_up", slot={"index": index, "role": None, "seconds": None, "cut_at": None} if index is not None else None,
                                     planned=_plan_shot_candidate(planned_shot) if planned_shot else None, replacement=mine, context={**context, **extra}, **common))

    # The shots he KEPT (same moment as planned): did he trim or lengthen them on the timeline, and did he move them to another place in the edit? Extra events,
    # never votes: the moment was right; only its length or position changed.
    kept_plan = {p["index"]: p for p in plan_shots if p.get("state") == "kept" and _is_int(p.get("index"))}
    his_for: dict[int, dict[str, Any]] = {}
    for shot in his_shots:
        slot_i = shot.get("plan_slot")
        if shot.get("status") == "same_moment" and _is_int(slot_i) and slot_i in kept_plan and slot_i not in his_for:
            his_for[slot_i] = shot
    for index, shot in sorted(his_for.items()):
        ps = kept_plan[index]
        planned = _plan_shot_candidate(ps)
        speed = ps.get("speed") if _is_number(ps.get("speed")) and ps["speed"] > 0 else 1.0
        his_seconds = shot.get("timeline_seconds")
        if planned["source_in"] is None or planned["source_out"] is None or not _is_number(his_seconds):
            continue
        planned_seconds = (planned["source_out"] - planned["source_in"]) / speed
        diff = his_seconds - planned_seconds
        if abs(diff) >= max(TRIM_MIN_SECONDS, TRIM_SHARE * planned_seconds):
            events.append(_try_event(outcome="shortened" if diff < 0 else "extended", slot={"index": index, "role": None, "seconds": round(planned_seconds, 3), "cut_at": None},
                                     planned=planned, replacement=_his_shot_candidate(shot),
                                     context={**context, "planned_seconds": round(planned_seconds, 3), "his_seconds": round(float(his_seconds), 3)}, **common))
    in_plan_order = [(index, his_for[index].get("order")) for index in sorted(his_for) if _is_int(his_for[index].get("order"))]
    keep_order = _longest_increasing([order for _, order in in_plan_order])
    for k, (index, order) in enumerate(in_plan_order):
        if k not in keep_order:   # the fewest shots whose moving explains his order: the rest stayed in the plan's order
            events.append(_try_event(outcome="moved", slot={"index": index, "role": None, "seconds": None, "cut_at": None}, planned=_plan_shot_candidate(kept_plan[index]),
                                     replacement=_his_shot_candidate(his_for[index]), context={**context, "plan_position": index, "his_position": order}, **common))
    return [e for e in events if e]


TRIM_MIN_SECONDS = 0.08   # two frames at 25 fps: anything smaller is frame rounding, not a trim
TRIM_SHARE = 0.10         # ... and at least a tenth of the planned length


def _longest_increasing(values: list[int]) -> set[int]:
    """Positions of one longest strictly increasing subsequence of `values` (patience sorting, O(n log n)). Shots outside it are the ones he moved."""
    import bisect
    tails: list[int] = []
    tail_pos: list[int] = []
    prev = [-1] * len(values)
    for i, v in enumerate(values):
        j = bisect.bisect_left(tails, v)
        if j == len(tails):
            tails.append(v)
            tail_pos.append(i)
        else:
            tails[j] = v
            tail_pos[j] = i
        prev[i] = tail_pos[j - 1] if j > 0 else -1
    keep: set[int] = set()
    i = tail_pos[-1] if tail_pos else -1
    while i >= 0:
        keep.add(i)
        i = prev[i]
    return keep


# ---- processing: counting, nothing else -------------------------------------------------------------------------------------------------------

def _count(values: Iterable[Any], vocabulary: Iterable[str]) -> dict[str, int]:
    counts = {v: 0 for v in vocabulary}
    for v in values:
        if isinstance(v, str):
            counts[v] = counts.get(v, 0) + 1
    return counts


def _reasons_of(e: dict[str, Any]) -> list[str]:
    r = e.get("reasons")
    return [x for x in r if isinstance(x, str)] if isinstance(r, (list, tuple)) else []


def _is_taste(e: dict[str, Any]) -> bool:
    """Recomputed from confidence and reasons rather than read from the stored flag, so a hand-built dict with a wrong flag cannot slip into the evidence."""
    return _taste_signal(e.get("confidence"), _reasons_of(e))


def _explained_away(events: list[dict[str, Any]]) -> set[str]:
    """Ids of events that a LATER 'reasoned' event explains with a reason that says nothing about taste (a client's request). On the review page the reason chip is
    clicked after the swap, so it is its own event naming the swap in context["explains"]; without this the swap would still count as his taste."""
    return {e["context"]["explains"] for e in events
            if e.get("outcome") == "reasoned" and isinstance(e.get("context"), dict) and isinstance(e["context"].get("explains"), str)
            and any(r in NOT_TASTE_REASONS for r in _reasons_of(e))}


def _taste_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    away = _explained_away(events)
    return [e for e in events if _is_taste(e) and e.get("id") not in away]


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by category, confidence, outcome and reason, and how many events are taste signals. Every known value appears (with 0) so the shape never changes."""
    return {
        "total": len(events),
        "by_category": _count((e.get("category") for e in events), CATEGORIES),
        "by_confidence": _count((e.get("confidence") for e in events), CONFIDENCE),
        "by_outcome": _count((e.get("outcome") for e in events), OUTCOMES),
        "by_reason": _count((r for e in events for r in _reasons_of(e)), REASON_CODES),
        "taste_signals": len(_taste_events(events)),     # trustworthy events that MAY say something about taste (incl. locks, choices, reasons)
        "taste_votes": len(_kind_votes(events, True)),   # the ones that actually vote for or against a kind of moment: what ranking_adjustments counts
    }


def reason_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    """How often each reason code was given, over EXPLICIT feedback only (a reason is something Josh said; an observed edit has none). Only codes that occur are listed."""
    counts: dict[str, int] = {}
    for e in events:
        if e.get("category") == "explicit_feedback":
            for r in _reasons_of(e):
                counts[r] = counts.get(r, 0) + 1
    return counts


def _decision_key(e: dict[str, Any]) -> tuple | None:
    """What identifies 'the same decision about the same planned shot', so only the latest counts. An observed edit: the job, the sequence, the plan it was compared
    with, the slot and the planned stretch (the auto-save watch sees an unfinished edit again and again). An explicit keep or change: the job, the slot and the planned
    stretch (clicking "Keep this" three times is one decision; keep then swap is the swap). None for anything else."""
    planned = e.get("planned")
    if e.get("category") == "explicit_feedback" and e.get("outcome") in (*_KEPT_OUTCOMES, *_CHANGED_OUTCOMES) and isinstance(planned, dict):
        slot = e.get("slot") if isinstance(e.get("slot"), dict) else {}
        name = planned.get("name")
        return ("explicit", e.get("job_id"), slot.get("index"), planned.get("candidate_id"), name.lower() if isinstance(name, str) else None,
                _round(planned.get("source_in")), _round(planned.get("source_out")))
    if e.get("category") != "observed_edit" or not e.get("project") or e.get("outcome") not in (*_KEPT_OUTCOMES, *_CHANGED_OUTCOMES) or not isinstance(planned, dict):
        return None
    name = planned.get("name")
    if not isinstance(name, str) and planned.get("candidate_id") is None:
        return None
    slot = e.get("slot") if isinstance(e.get("slot"), dict) else {}
    made_at = (e.get("plan_ref") or {}).get("made_at") if isinstance(e.get("plan_ref"), dict) else None
    return (e.get("job_id"), "".join(str(e["project"]).split()).lower(), made_at, slot.get("index"), planned.get("candidate_id"),
            name.lower() if isinstance(name, str) else None, _round(planned.get("source_in")), _round(planned.get("source_out")))


def latest_per_decision(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapses repeated decisions about one planned shot, so it votes once. The auto-save watch writes a new record every time he saves, so the same planned shot is
    observed again and again while he works; and on the review page he can press "Keep this" on a shot several times. For each key of _decision_key only the LATEST
    (by ts) is kept. Everything else (other outcomes, events with nothing to key on) passes through untouched, in order. Same idea as post_learn.aggregate()."""
    keys = [_decision_key(e) for e in events]
    latest: dict[tuple, int] = {}
    for i, (e, k) in enumerate(zip(events, keys)):
        if k is not None and (k not in latest or str(e.get("ts") or "") >= str(events[latest[k]].get("ts") or "")):
            latest[k] = i
    return [e for i, (e, k) in enumerate(zip(events, keys)) if k is None or latest[k] == i]


def _shrunk(kept: int, changed: int) -> float:
    """Keep rate pulled toward 50% by a Beta(2,2) prior: (kept + 2) / (kept + changed + 4)."""
    return (kept + PRIOR_KEPT) / (kept + changed + PRIOR_KEPT + PRIOR_CHANGED)


def _kind_votes(events: list[dict[str, Any]], collapse_repeats: bool) -> list[tuple[str, bool]]:
    """(kind of the planned moment, was it kept?) for every taste-signal event that is a keep or a change of a planned moment with a known kind (a swap he later said the
    client asked for is not one: see _explained_away)."""
    trusted = [e for e in _taste_events(events) if not (isinstance(e.get("context"), dict) and e["context"].get("planned_by_you"))]   # his own pick is not the planner's
    if collapse_repeats:
        trusted = latest_per_decision(trusted)
    votes = []
    for e in trusted:
        planned = e.get("planned")
        kind = planned.get("kind") if isinstance(planned, dict) else None
        if not isinstance(kind, str) or not kind:
            continue
        if e.get("outcome") in _KEPT_OUTCOMES:
            votes.append((kind, True))
        elif e.get("outcome") in _CHANGED_OUTCOMES:
            votes.append((kind, False))
    return votes


def kind_evidence(events: list[dict[str, Any]], *, collapse_repeats: bool = True) -> dict[str, dict[str, Any]]:
    """Per KIND of planned moment (hero, reveal, camera_move, ...): how often the planned moment was kept (outcome kept or approved) against changed (replaced, swapped or dropped).
    Uses ONLY taste-signal events: uncertain events and client_request events are ignored. Each kind gets {"kept", "changed", "n", "keep_rate"}, where keep_rate is shrunk toward 50%:
    (kept + 2) / (kept + changed + 4), so three examples never look like a rule. `collapse_repeats` counts a shot seen in several auto-saves once (see latest_per_decision)."""
    tally: dict[str, list[int]] = {}
    for kind, kept in _kind_votes(events, collapse_repeats):
        row = tally.setdefault(kind, [0, 0])
        row[0 if kept else 1] += 1
    return {k: {"kept": v[0], "changed": v[1], "n": v[0] + v[1], "keep_rate": round(_shrunk(v[0], v[1]), 4)} for k, v in sorted(tally.items())}


def ranking_adjustments(events: list[dict[str, Any]], min_events: int = DEFAULT_MIN_EVENTS) -> dict[str, Any] | None:
    """A PROPOSED nudge per kind of moment, or None when there is not enough evidence yet (fewer than `min_events` keep-or-change votes from taste-signal events on planned
    moments of a known kind). The nudge for a kind is its shrunk keep rate minus the overall shrunk keep rate, clipped to [-0.15, 0.15]: a kind he keeps more than average
    moves up, one he changes more than average moves down. Result: {"by_kind": {kind: adjustment}, "overall_keep_rate", "support": votes, "computed_at", "schema"}.

    This only PROPOSES. The planner must still put any learned ordering behind its held-out adoption gate (learning/taste.py) before it changes a plan; nothing here is
    allowed to reorder anything by itself."""
    votes = _kind_votes(events, True)
    if len(votes) < min_events:
        return None
    return _adjustments_from(votes, events)


ADOPTABLE_KINDS = ("action", "reaction", "camera_move", "reveal", "hero", "hold")


def adopted_preferences(path: Path | None = None) -> dict[str, float] | None:
    """The per-kind nudges the planner applies, or None (the normal case until enough of his decisions exist). Meant to be written only by learning/adopt_preferences.py
    AFTER its held-out gate passed; anything else -- missing, unreadable, another schema, a gate not marked met, an unknown kind, a value that isn't a finite number
    within +-0.15 -- is ignored, so a broken file can never steer a plan. (It is a local file: someone editing it by hand, gate and all, could; the planner says
    in every plan when a nudge was applied.)"""
    try:
        data = json.loads(Path(path or ADOPTED_PREFERENCES).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != EVENT_SCHEMA_VERSION or not isinstance(data.get("gate"), dict) or data["gate"].get("met") is not True:
        return None
    by_kind = data.get("by_kind")
    if not isinstance(by_kind, dict) or not by_kind or any(k not in ADOPTABLE_KINDS or not _is_number(v) or not math.isfinite(v) or abs(v) > ADJUSTMENT_LIMIT + 1e-9
                                                         for k, v in by_kind.items()):
        return None
    return {k: float(v) for k, v in by_kind.items()}


def _adjustments_from(votes: list[tuple[str, bool]], events: list[dict[str, Any]]) -> dict[str, Any]:
    kept_total = sum(1 for _, kept in votes if kept)
    overall = _shrunk(kept_total, len(votes) - kept_total)
    evidence = kind_evidence(events)
    by_kind = {k: round(max(-ADJUSTMENT_LIMIT, min(ADJUSTMENT_LIMIT, v["keep_rate"] - overall)), 4) for k, v in evidence.items()}
    return {"by_kind": by_kind, "overall_keep_rate": round(overall, 4), "support": len(votes), "computed_at": _now(), "schema": EVENT_SCHEMA_VERSION}
