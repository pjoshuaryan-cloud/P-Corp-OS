"""
POST (2026-10-21) -- learn from the edit while Josh is making it, by reading the files Premiere already writes.

Premiere saves an auto-save copy of an open project every few minutes (and keeps only the newest handful). This watches the auto-save folder, and the saved project file
itself, of every POST shoot's Premiere project and keeps a compact snapshot of each sequence it finds: which clip, which part of it, where on the timeline. Two things come out:

  - a history of how an edit grew (what was added, trimmed, swapped, dropped), which is the one record of HOW he edits that nothing else keeps, and which Premiere deletes
    as its auto-saves rotate;
  - once a sequence has not changed for SETTLE_SECONDS, one automatic "Learn From My Edit" record (marked source "auto-save"): the finished edit compared with the plan it was
    built from, in the same feedback log the button writes to. No click needed.

What it never does: it never writes into Premiere's folders or changes any project or plan, never opens Premiere, calls no Claude and sends nothing anywhere (everything stays
in backend/data/learning/autosaves and .../feedback on this Mac). It only reads POST shoots' own projects -- nothing else in Premiere is looked at. It reads one file at a time,
only files Premiere finished writing, through the drive guard (a stuck or unplugged drive is skipped, never waited on), and it can be switched off (settings.json, or
POST /post/autosave-watch {"enabled": false}).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Callable

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "learning" / "autosaves"
SCAN_SECONDS = 90
FILES_PER_JOB_PER_TICK = 4        # a backfill of dozens of old auto-saves is spread over minutes, never a burst of disk reads
MIN_AGE_SECONDS = 20              # a file touched this recently may still be being written
SETTLE_SECONDS = 45 * 60          # a sequence unchanged this long counts as finished for the automatic record
MIN_SHOTS = 5                     # fewer shots on video 1 is not an edit
WHOLE_CLIP_SHARE = 0.8            # a sequence whose shots are mostly whole clips is a clip list (like the shoot's starting sequence), not an edit
MAX_HAND_SHOTS = 120              # a sequence he made by hand with more shots than this is a pool of selects, not a cut
MAX_FAILS = 3
AUTOSAVE_FOLDERS = ("Adobe Premiere Pro (Beta) Auto-Save", "Adobe Premiere Pro Auto-Save")
_STAMP = re.compile(r"-(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.prproj$")
_LOCK = threading.Lock()


def stamp_of(name: str) -> float | None:
    """When Premiere made an auto-save, from its name (local time): '...-2026-10-15_18-44-39.prproj'."""
    m = _STAMP.search(name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))
    except (OverflowError, ValueError):
        return None


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def list_sources(project_path: str) -> list[dict[str, Any]]:
    """The files that show the state of this project: its auto-saves and the saved project itself, oldest first. [{path, at, mtime, size, main}]."""
    project = Path(project_path)
    out = []
    for folder in AUTOSAVE_FOLDERS:
        d = project.parent / folder
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.suffix.lower() != ".prproj" or p.name.startswith("._") or not p.is_file():
                continue
            st = p.stat()
            out.append({"path": str(p), "at": stamp_of(p.name) or st.st_mtime, "mtime": st.st_mtime, "size": st.st_size, "main": False})
    if project.is_file():
        st = project.stat()
        out.append({"path": str(project), "at": st.st_mtime, "mtime": st.st_mtime, "size": st.st_size, "main": True})
    out.sort(key=lambda f: f["at"])
    return out


def snapshot_sequences(path: str, reader: Callable[[str], list[Any]] | None = None) -> list[dict[str, Any]]:
    """Every sequence in a saved project with enough footage on video 1 to be an edit: {sequence, built_at, seconds, whole_clip, shots: [[clip, in, out, start, length, speed, clip_seconds]]}."""
    from app.post_learn import built_at
    if reader is None:
        from learning import prproj
        reader = prproj.read_sequences
    out = []
    for seq in reader(path):
        shots = sorted((s for s in seq.delivered_shots() if s.track == 1 and s.src_in is not None and s.src_out is not None), key=lambda s: s.t0)
        if len(shots) < MIN_SHOTS:
            continue
        rows = [[os.path.basename(s.path or ""), round(s.src_in, 3), round(s.src_out, 3), round(s.t0, 3), round(s.length, 3), None if s.speed is None else round(s.speed, 3),
                 None if not s.src_duration else round(s.src_duration, 3)] for s in shots]
        shares = [(r[2] - r[1]) / r[6] for r in rows if r[6]]
        out.append({"sequence": seq.name.strip(), "built_at": built_at(seq.name), "seconds": round(sum(r[4] for r in rows), 2), "shots": rows,
                    "whole_clip": bool(shares) and statistics.median(shares) >= WHOLE_CLIP_SHARE})
    return out


def shots_hash(rows: list[list[Any]]) -> str:
    return hashlib.sha1(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()[:16]


class Store:
    """Snapshots and bookkeeping under DATA_DIR: state.json (what has been read, what has been logged, settings), job<id>.jsonl (one line per new state of a sequence)."""

    def __init__(self, directory: Path = DATA_DIR) -> None:
        self.dir = directory

    # ---- settings and state --------------------------------------------------------------------------------------------------------------
    def _read(self, name: str, default: Any) -> Any:
        try:
            return json.loads((self.dir / name).read_text())
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (name + ".part")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, self.dir / name)

    def enabled(self) -> bool:
        return bool(self._read("settings.json", {"enabled": True}).get("enabled", True))

    def set_enabled(self, value: bool) -> None:
        self._write("settings.json", {"enabled": bool(value)})

    # ---- projects that are NOT POST shoots, watched because he asked (Learn From My Edit on such a project adds it) -------------------------------------
    def projects(self) -> list[dict[str, Any]]:
        """[{path, added_at}] in projects.json (its own file, so switching the watch on or off can never drop it)."""
        rows = self._read("projects.json", [])
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("path"), str)] if isinstance(rows, list) else []

    def add_project(self, path: str) -> bool:
        """Watches another project. Returns whether it was new."""
        rows = self.projects()
        if any(os.path.normpath(r["path"]) == os.path.normpath(path) for r in rows):
            return False
        rows.append({"path": path, "added_at": _iso(time.time())})
        self._write("projects.json", rows)
        return True

    def remove_project(self, path: str) -> bool:
        rows = self.projects()
        keep = [r for r in rows if os.path.normpath(r["path"]) != os.path.normpath(path)]
        if len(keep) != len(rows):
            self._write("projects.json", keep)
        return len(keep) != len(rows)

    def state(self) -> dict[str, Any]:
        s = self._read("state.json", {})
        s.setdefault("processed", {}); s.setdefault("finals", {}); s.setdefault("last_scan", None)
        return s

    def save_state(self, s: dict[str, Any]) -> None:
        self._write("state.json", s)

    # ---- snapshots -----------------------------------------------------------------------------------------------------------------------
    def snapshots(self, job_id: int) -> list[dict[str, Any]]:
        f = self.dir / f"job{job_id}.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def append_snapshot(self, job_id: int, row: dict[str, Any]) -> bool:
        """Adds a state of a sequence unless it is identical to that sequence's latest one. Returns whether it was new."""
        last = next((r for r in reversed(self.snapshots(job_id)) if r["sequence"] == row["sequence"]), None)
        if last and last["hash"] == row["hash"]:
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / f"job{job_id}.jsonl", "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        return True


def scan_job(store: Store, job: dict[str, Any], *, now: float | None = None, budget: int = FILES_PER_JOB_PER_TICK, reader: Callable[[str], list[Any]] | None = None) -> dict[str, Any]:
    """Reads the next few unread auto-saves (and the project file, if saved again) of one shoot, oldest first, and records new states. Synchronous: callers run it through on_drive."""
    from app.ssd_guard import require_connected
    now = time.time() if now is None else now
    project = job.get("premiere_project_path")
    result = {"read": 0, "new_states": 0, "failed": 0, "pending": 0}
    if not project:
        return result
    require_connected(project)
    with _LOCK:
        state = store.state()
        todo = []
        for src in list_sources(project):
            seen = state["processed"].get(src["path"])
            if seen and seen.get("mtime") == src["mtime"] and (seen.get("ok") or seen.get("fails", 0) >= MAX_FAILS):
                continue
            if now - src["mtime"] < MIN_AGE_SECONDS:
                continue
            todo.append(src)
        result["pending"] = max(len(todo) - budget, 0)
        for src in todo[:budget]:
            entry = {"mtime": src["mtime"], "ok": False, "fails": (state["processed"].get(src["path"]) or {}).get("fails", 0)}
            try:
                sequences = snapshot_sequences(src["path"], reader)
                for seq in sequences:
                    new = store.append_snapshot(job["id"], {"file": os.path.basename(src["path"]), "main": src["main"], "at": _iso(src["at"]), "sequence": seq["sequence"], "built_at": seq["built_at"],
                                                            "seconds": seq["seconds"], "n": len(seq["shots"]), "whole_clip": seq["whole_clip"], "hash": shots_hash(seq["shots"]), "shots": seq["shots"]})
                    result["new_states"] += new
                entry["ok"] = True
                result["read"] += 1
            except Exception as exc:   # a half-written or odd file must never stop the watch: it is retried a few times, then left alone
                entry["fails"] += 1
                result["failed"] += 1
                print(f"[post_autosave] couldn't read {os.path.basename(src['path'])} ({exc!r}); attempt {entry['fails']}")
            state["processed"][src["path"]] = entry
        state["last_scan"] = _iso(now)
        store.save_state(state)
    return result


def worth_logging(name: str, row: dict[str, Any], summary: dict[str, Any], states: int) -> bool:
    """Whether a settled sequence is HIS edit, not machine output or a pile of clips. Machine rough cuts never are. A sequence Assemble Edit built counts only if the auto-saves
    SHOW him changing it (two or more different states) and it no longer matches its plan: a single state can't tell an edit from an abandoned build, and for builds from before
    plans were archived the plan it came from may be gone, so "differs from the plan" alone proves nothing. One he made by hand counts if it is the size of a cut."""
    if row["whole_clip"] or "rough cut" in name.lower():
        return False
    if row.get("built_at"):
        return states >= 2 and not (summary["his_shots"] == summary["plan_shots"] and summary["his_shots_same_moment"] == summary["his_shots"])
    return MIN_SHOTS <= row["n"] <= MAX_HAND_SHOTS


def settle_job(store: Store, job: dict[str, Any], *, now: float | None = None) -> list[str]:
    """Writes the automatic learn record for every sequence of this shoot that has stopped changing (and was not already logged in this state). Returns what it logged."""
    from app.post_edit_plan import edit_dir
    from app.post_learn import _write_log, compare_with_plan, moments_by_clip_name
    from app.post_moments import load_moments
    from app.post_plan_history import plan_for_build_time
    from learning import prproj
    now = time.time() if now is None else now
    rows = store.snapshots(job["id"])
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        latest[r["sequence"]] = r
    logged: list[str] = []
    with _LOCK:
        state = store.state()
        state.setdefault("logged", {})
        for name, row in latest.items():
            key = f"{job['id']}:{name}"
            if row["whole_clip"] or row["n"] < MIN_SHOTS or state["finals"].get(key) == row["hash"]:
                continue
            last_at = time.mktime(time.strptime(row["at"], "%Y-%m-%dT%H:%M:%S"))
            if now - last_at < SETTLE_SECONDS:
                continue
            if job.get("no_plan"):   # a project he started himself: his cut as it is, logged when it settles and is the size of a cut
                if row.get("built_at"):   # a sequence P Corp built in his project: never his cut (Learn From My Edit compares it with its learned plan)
                    state["finals"][key] = row["hash"]
                    continue
                from app.post_learn import analyse_unplanned, write_unplanned_log
                shots = [prproj.Shot(t0=r[3], t1=r[3] + r[4], src_in=r[1], src_out=r[2], path=r[0], name=r[0], track=1, src_duration=r[6]) for r in row["shots"]]
                state["finals"][key] = row["hash"]
                if "rough cut" not in name.lower() and MIN_SHOTS <= row["n"] <= MAX_HAND_SHOTS:
                    write_unplanned_log(job["premiere_project_path"], name, analyse_unplanned(shots), source="auto-save")
                    state["logged"][key] = row["hash"]
                    logged.append(name)
                continue
            folder = edit_dir(job)
            plan, _file, basis, made_at = plan_for_build_time(folder, row.get("built_at"))
            if plan is None:
                continue
            shots = [prproj.Shot(t0=r[3], t1=r[3] + r[4], src_in=r[1], src_out=r[2], path=r[0], name=r[0], track=1, src_duration=r[6]) for r in row["shots"]]
            result = compare_with_plan(name, shots, plan, basis, made_at, moments_by_clip_name(load_moments(folder)))
            state["finals"][key] = row["hash"]   # looked at in this state, logged or not: not looked at again until it changes
            if worth_logging(name, row, result["summary"], sum(1 for r in rows if r["sequence"] == name)):
                _write_log(job, name, plan.get("style"), result, source="auto-save")
                state["logged"][key] = row["hash"]
                logged.append(name)
        store.save_state(state)
    return logged


def scan_and_settle(store: Store, job: dict[str, Any], budget: int = FILES_PER_JOB_PER_TICK) -> dict[str, Any]:
    """One pass for one shoot: read a few new files, then log any finished edits. Skips quietly when the shoot has no Premiere project yet."""
    result = scan_job(store, job, budget=budget)
    result["logged"] = settle_job(store, job) if job.get("premiere_project_path") else []
    return result


def status(store: Store, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """For the status route: on/off, when it last looked, and per shoot what it has seen."""
    state = store.state()
    out_jobs = []
    for job in jobs:
        if not job.get("premiere_project_path"):
            continue
        rows = store.snapshots(job["id"])
        seqs: dict[str, dict[str, Any]] = {}
        for r in rows:
            s = seqs.setdefault(r["sequence"], {"sequence": r["sequence"], "states": 0, "first_at": r["at"], "last_at": r["at"], "shots_now": r["n"], "whole_clip": r["whole_clip"], "logged": False})
            s["states"] += 1; s["last_at"] = r["at"]; s["shots_now"] = r["n"]; s["whole_clip"] = r["whole_clip"]
            s["logged"] = state.get("logged", {}).get(f"{job['id']}:{r['sequence']}") == r["hash"]
        out_jobs.append({"job_id": job["id"], "shoot": job["shoot_name"], "files_read": sum(1 for k in state["processed"] if str(k).startswith(str(Path(job["premiere_project_path"]).parent))),
                         "sequences": list(seqs.values())})
    projects = []
    for proj in store.projects():
        pj = project_job(proj["path"])
        seqs = {}
        for r in store.snapshots(pj["id"]):
            sq = seqs.setdefault(r["sequence"], {"sequence": r["sequence"], "states": 0, "last_at": r["at"], "shots_now": r["n"], "logged": False})
            sq["states"] += 1; sq["last_at"] = r["at"]; sq["shots_now"] = r["n"]
            sq["logged"] = state.get("logged", {}).get(f"{pj['id']}:{r['sequence']}") == r["hash"]
        projects.append({"project": proj["path"], "added_at": proj.get("added_at"), "id": pj["id"], "sequences": list(seqs.values())})
    return {"enabled": store.enabled(), "last_scan": state["last_scan"], "settle_minutes": SETTLE_SECONDS // 60, "jobs": out_jobs, "projects": projects}


def project_job(path: str) -> dict[str, Any]:
    """A watched project that is not a POST shoot, in the shape scan_job / settle_job take: a stable negative id, no plan."""
    from app.post_learn import project_key
    return {"id": project_key(path), "premiere_project_path": path, "shoot_name": Path(path).stem, "no_plan": True}


async def autosave_watch_loop(app) -> None:
    """The background loop: every SCAN_SECONDS, one small pass per shoot that has a Premiere project, and per project he asked to have watched, if the watch is on."""
    import asyncio
    from app.main import _pooled_postgres_conn  # local import -- avoids a circular import at module load time
    from app.post_db import list_post_jobs
    from app.ssd_guard import DriveNotResponding, on_drive
    store = Store()
    while True:
        try:
            if store.enabled():
                async with _pooled_postgres_conn() as postgres_conn:
                    jobs = await list_post_jobs(None, postgres_conn)
                shoots = {os.path.normpath(j["premiere_project_path"]) for j in jobs if j.get("premiere_project_path")}
                extra = [project_job(p["path"]) for p in store.projects() if os.path.normpath(p["path"]) not in shoots]   # a shoot's own project is watched as the shoot
                for job in [*jobs, *extra]:
                    if not job.get("premiere_project_path"):
                        continue
                    try:
                        await on_drive(scan_and_settle, store, job, timeout=120.0)
                    except DriveNotResponding:
                        continue   # unplugged or stuck: leave it, try again next time
        except Exception as exc:
            print(f"[post_autosave] loop iteration failed: {exc!r}")
        await asyncio.sleep(SCAN_SECONDS)
