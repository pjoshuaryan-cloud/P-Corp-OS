"""The Shoot Log (2026-11-02): turns the clips of a shoot into a logged Premiere project, so an edit starts from organised footage instead of hours of scrubbing.

  log:     the plugin sends the project's clips. This reads camera data (Sony's sidecar XML names the real gamma, ffprobe can't: it says bt709 on S-Log3), makes viewing
           frames, reads each clip for its checks (post_steady, the same read Plan Edit needs, so it is only done once) and writes a pass/check/reject for each clip.
  tag:     an explicit click that spends money: Claude sees frames from each clip and answers in a fixed vocabulary. A failed clip never stops the run; if Claude can't be
           reached the run stops, keeps what it has, and the same click carries on when there's signal.
  review:  static/shoot_log.html. His choices go in an append-only file of their own and always win; Claude's answers are never overwritten.
  apply:   the plugin's Apply Shoot Log asks for apply_plan and does the Premiere side: Selects and Rejects bins, tags in Log Note (the column Premiere's search bins read),
           markers, search bins by subject and shot size.

Nothing here ranks clips. The back-test on his real edits found sorting by Claude's rating no better than chance (learning/shoot_log_backtest.py), so Selects holds only what
he confirms. Nothing here deletes or changes footage. Reject means a clip goes in the Rejects bin, and the automatic reject is only for clips that can't be read or are black.

Everything lives in one folder per shoot, on this Mac for a project of his own or next to the plans for a POST shoot, so reviewing needs no cloud database."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app import post_media, post_moments, post_steady
from app.post_edit_plan import DESCRIBE_MODEL_FOR_ESTIMATES, edit_dir
from app.ssd_guard import DriveNotResponding, on_drive

CONFIG: dict[str, Any] = json.loads((Path(__file__).with_name("shoot_log_config.json")).read_text())
VOCAB: dict[str, list[str]] = CONFIG["vocabulary"]
CHECKS: dict[str, Any] = CONFIG["checks"]
MODEL = DESCRIBE_MODEL_FOR_ESTIMATES
DATA = Path(__file__).resolve().parents[1] / "data" / "shoot_logs"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".m4v", ".mts", ".avi"}
SINGLE_CHOICE = ("shot_size", "energy", "camera_move")
STATUSES = ("select", "reject", "none")
PARENT_BIN = "Shoot Log"
SELECTS_BIN, REJECTS_BIN = "Selects", "Rejects"
LOG_NOTE_PREFIX = "[Shoot Log]"
REVIEW_GAP_SECONDS = 300  # a gap between his choices longer than this is a break, not logging time


class ShootLogError(RuntimeError):
    pass


# ================================================================================================================================================= tags as Premiere sees them
def token_for(field: str, value: str) -> str:
    """The word that goes in Log Note for a tag, and that a search bin looks for. One unbroken word: real Premiere splits a search at an underscore and wants both halves anywhere on the
    clip, so "subject_detail" also found a clip with "shot_detail subject_product". It also matches parts of words, so no tag may sit inside another."""
    prefix = {"shot_size": "shot", "subjects": "subject", "energy": "energy", "camera_move": "move"}[field]
    return prefix + value.replace("_", "")


def label_for(value: str) -> str:
    return CONFIG["labels"].get(value, value)


# ================================================================================================================================================= camera data
def read_sidecar(path: str) -> dict[str, Any]:
    """What a Sony camera wrote next to the clip (C0001M01.XML): the real gamma, camera, lens and frame rate. {} when there is no sidecar, as with a phone or a copied clip."""
    stem = str(Path(path).with_suffix(""))
    text = None
    for candidate in (f"{stem}M01.XML", f"{stem}M01.xml"):
        try:
            text = Path(candidate).read_text(errors="ignore")
            break
        except OSError:
            continue
    if text is None:
        return {}

    def find(pattern: str) -> str | None:
        hit = re.search(pattern, text)
        return hit.group(1) if hit else None
    return {"gamma": find(r'CaptureGammaEquation" value="([^"]+)"'), "camera": find(r'<Device[^>]*modelName="([^"]+)"'), "lens": find(r'<Lens modelName="([^"]+)"'),
            "capture_fps": find(r'captureFps="([^"]+)"'), "codec_label": find(r'videoCodec="([^"]+)"'), "serial": find(r'<Device[^>]*serialNo="([^"]+)"')}


def gamma_profile(gamma: str | None) -> str:
    """Which limits and viewing curve a clip gets. Unknown means no sidecar said: no viewing curve, and S-Log3's limits because that's what he mostly shoots (they only ever say "check")."""
    g = (gamma or "").lower()
    if "s-log3" in g or "slog3" in g:
        return "slog3"
    if "709" in g:
        return "rec709"
    return "unknown"


async def probe(path: str, limiter: asyncio.Semaphore | None = None) -> dict[str, Any]:
    """The clip's facts. Never raises: `probe_error` says when it couldn't be read."""
    async def run() -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(post_media.FFPROBE_PATH, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        return proc.returncode or 0, out, err
    try:
        if limiter is not None:
            async with limiter:
                code, out, err = await run()
        else:
            code, out, err = await run()
    except OSError as exc:
        return {"probe_error": str(exc)[:200]}
    if code != 0:
        return {"probe_error": err.decode(errors="replace").strip()[:200] or f"ffprobe exited with code {code}"}
    try:
        data = json.loads(out)
    except ValueError:
        return {"probe_error": "ffprobe's reply couldn't be read"}
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        return {"probe_error": "no video in this file"}
    fmt = data.get("format", {})
    rotation = next((sd.get("rotation") for sd in video.get("side_data_list", []) if "rotation" in sd), None)
    num, _, den = str(video.get("r_frame_rate", "0/1")).partition("/")
    width, height = video.get("width"), video.get("height")
    upright = abs(int(rotation or 0)) % 180 == 90
    tags = [fmt.get("tags") or {}] + [s.get("tags") or {} for s in streams]
    return {"duration": round(float(fmt.get("duration") or 0), 3), "fps": round(float(num) / float(den or 1), 3), "width": width, "height": height, "rotation": rotation,
            "vertical": bool(width and height and ((height > width) != upright)), "codec": video.get("codec_name"), "pixel_format": video.get("pix_fmt"),
            "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None, "created": (fmt.get("tags") or {}).get("creation_time"),
            "timecode": next((t["timecode"] for t in tags if t.get("timecode")), None), "reel": next((t["reel_name"] for t in tags if t.get("reel_name")), None), "probe_error": None}


# ================================================================================================================================================= the checks
def raw_thumbs(m: dict[str, Any]) -> np.ndarray | None:
    """Per-second 16x9 thumbnails with their real brightness kept (0..1), unlike post_steady.decode_thumbs, which removes it to compare pictures."""
    raw, n = m.get("thumbs"), m.get("thumb_n")
    if not raw or not n:
        return None
    return np.frombuffer(base64.b64decode(raw), dtype=np.uint8).reshape(int(n), post_steady.THUMB_H, post_steady.THUMB_W).astype(np.float32) / 255.0


def _share_beyond(m: dict[str, Any], side: str, level: float) -> float:
    """How much of the picture sits above (hi) or below (lo) a level. Clips read since 2026-11-02 carry the measured share; older reads estimate it from their small thumbnails."""
    measured = (m.get("levels") or {}).get(f"{side}{int(round(level * 100)):02d}")
    if measured:
        return float(np.mean(measured))
    thumbs = raw_thumbs(m)
    if thumbs is None:
        return 0.0
    return float((thumbs >= level).mean() if side == "hi" else (thumbs <= level).mean())


def clip_stats(m: dict[str, Any], profile: str = "slog3") -> dict[str, float]:
    """Numbers about one clip that don't depend on the rest of the shoot."""
    levels = CHECKS["levels"].get(profile, CHECKS["levels"]["slog3"])
    luma, motion = np.asarray(m["luma"], float), np.asarray(m["motion"], float)
    return {"black_share": float((luma < levels["black"]).mean()), "under_share": float((luma < levels["under"]).mean()), "over_share": float((luma > levels["over"]).mean()),
            "sharp": float(np.percentile(m["sharp"], 90)), "jerk": float(np.median(np.abs(np.diff(motion)))) if len(motion) > 1 else 0.0, "motion": float(motion.mean()),
            "blown": _share_beyond(m, "hi", levels["clip"]), "crushed": _share_beyond(m, "lo", levels["crushed"])}


def rejected(stats: dict[str, float] | None) -> bool:
    """The only automatic reject: it can't be read, or it is black for nearly its whole length. In his real edits this hid none of the 232 clips he used."""
    return stats is None or stats["black_share"] >= CHECKS["black_share"]


def clip_flags(clips: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """{clip id: [{"type", "reason"}]} for one shoot's clips, each {"id", "name", "duration", "m", "profile"}. A flag only ever says "check": across his finished HAUS cut they fired
    about as often on clips he used (23%) as on ones he left out (30%). Sharpness and shake are judged within clips of the same gamma, because flat Log has far less contrast."""
    out: dict[str, list[dict[str, str]]] = {c["id"]: [] for c in clips}
    readable = [(c, clip_stats(c["m"], c.get("profile") or "slog3")) for c in clips if c.get("m")]
    groups: dict[str, list[tuple[dict[str, Any], dict[str, float]]]] = {}
    for c, s in readable:
        groups.setdefault(c.get("profile") or "slog3", []).append((c, s))
    for group in groups.values():
        typical = float(np.median([s["sharp"] for _, s in group]))
        shaky_from = float(np.percentile([s["jerk"] for _, s in group], 100 * (1 - CHECKS["shaky_top_share"]))) if len(group) >= CHECKS["shaky_min_clips"] else None
        for c, s in group:
            flags = out[c["id"]]
            if typical > 0 and s["sharp"] < CHECKS["soft_ratio"] * typical:
                flags.append({"type": "soft", "reason": f"Soft, or very little detail in the picture: its sharpest moments reach {s['sharp'] / typical:.0%} of this shoot's typical sharpness."})
            if s["under_share"] >= CHECKS["half_the_clip"]:
                flags.append({"type": "under", "reason": f"Dark for {s['under_share']:.0%} of the clip."})
            if s["over_share"] >= CHECKS["half_the_clip"]:
                flags.append({"type": "over", "reason": f"Very bright for {s['over_share']:.0%} of the clip."})
            if s["blown"] >= CHECKS["blown_share"]:
                flags.append({"type": "blown", "reason": f"Highlights clipping across about {s['blown']:.0%} of the picture."})
            if s["crushed"] >= CHECKS["crushed_share"]:
                flags.append({"type": "crushed", "reason": f"Shadows crushed across about {s['crushed']:.0%} of the picture."})
            if shaky_from is not None and s["jerk"] > shaky_from:
                flags.append({"type": "shaky", "reason": "Among the shakiest tenth of this shoot, which may be intentional."})
    for c in clips:
        if c.get("duration") is not None and c["duration"] < CHECKS["short_seconds"]:
            out[c["id"]].append({"type": "short", "reason": f"Only {c['duration']:.1f} s long."})
    return out


def near_duplicate_groups(clips: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{clip id: {"group", "of"}} for clips that look like an earlier one (clips given in recording order); "of" names the first of the group. Takes are worth seeing together, so this
    groups them and never hides one."""
    seen: list[tuple[np.ndarray, str, str]] = []
    out: dict[str, dict[str, Any]] = {}
    for c in clips:
        thumbs = post_steady.decode_thumbs(c["m"]) if c.get("m") else None
        if thumbs is None or not len(thumbs):
            continue
        match = next((first for other, first, _ in seen if post_steady.similarity(thumbs, other) >= CHECKS["near_duplicate"]), None)
        if match is None:
            seen.append((thumbs, c["id"], c["name"]))
        else:
            first_name = next(name for _, first, name in seen if first == match)
            out[c["id"]] = {"group": match, "of": first_name}
            out.setdefault(match, {"group": match, "of": None})
    return out


def check_results(clips: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{clip id: {"result": pass|check|reject, "flags": [...], "group": ...}} for clips that were read. Clips read fully are judged; a clip longer than the reader's limit says so."""
    flags, groups = clip_flags(clips), near_duplicate_groups(clips)
    out: dict[str, dict[str, Any]] = {}
    for c in clips:
        cid = c["id"]
        if not c.get("m"):
            continue
        items = list(flags.get(cid, []))
        group = groups.get(cid)
        if group and group["of"]:
            items.append({"type": "near_duplicate", "reason": f"Looks like {group['of']}."})
        stats = clip_stats(c["m"], c.get("profile") or "slog3")
        result = "reject" if rejected(stats) else ("check" if items else "pass")
        note = "Black for nearly its whole length." if result == "reject" else None
        if c.get("duration") and c["duration"] > post_steady.MAX_ANALYSED_SECONDS + 0.5:
            items.append({"type": "long", "reason": f"Only the first {int(post_steady.MAX_ANALYSED_SECONDS // 60)} minutes were checked."})
        out[cid] = {"result": result, "flags": items, "reject_reason": note, "group": group["group"] if group else None}
    return out


# ================================================================================================================================================= Claude's tags
def _tag_prompt() -> str:
    moments = post_moments.MOMENTS_SYSTEM_PROMPT.split("Reply with ONLY JSON")[0].rstrip()
    v = VOCAB
    return f"""You are logging footage for an editor of event recaps, brand activations, campaigns and commercials. {moments}
Then describe the clip as a whole, choosing ONLY from these words:
- shot_size: {" | ".join(v["shot_size"])}. Judge the main subject: extreme_wide shows a whole venue or street, wide shows whole people in their setting, medium is waist up, close is a face or an object filling the frame, detail is a small part of something.
- subjects: every one that really matters in the clip, most important first, from {", ".join(v["subjects"])}. speaker_mc is someone addressing an audience. talent is a featured person, not a passer-by. branding_signage is a logo or sign you can read. bts means crew or equipment are the point of the shot.
- energy: {" | ".join(v["energy"])}. calm is quiet and still, building is activity rising, peak is the height of the action.
- camera_move: {" | ".join(v["camera_move"])}. Compare the frames over time. static is locked off with no movement. pan, tilt, push or pull is one clear deliberate move. gimbal is smooth floating movement with no single direction. handheld is visibly unsteady with no single deliberate move. drone is aerial.
- vertical_crop_ok: if the clip is horizontal, could it be cropped to 9:16 and keep its subject? If it is already vertical, true.
- description: one short line a person would write in a log, under 12 words, naming what is actually seen.
- quality_note: only if something is plainly wrong, such as out of focus, badly framed or a lens obstruction; otherwise an empty string.
Reply with ONLY JSON: {{"shot_size":"","subjects":[],"energy":"","camera_move":"","vertical_crop_ok":true,"description":"","quality_note":"","scene":"3-6 word label","people":true,"events":[{{"t":seconds,"kind":"action|reaction|camera_move|reveal|hero","punch":0-10,"what":"max 10 words"}}]}} -- at most 5 events, best first, "t" exactly as labelled or between two labels, and "events" may be empty."""


TAG_SYSTEM_PROMPT = _tag_prompt()
TAG_PROMPT_VERSION = hashlib.sha1(TAG_SYSTEM_PROMPT.encode()).hexdigest()[:10]


def parse_tag_reply(text: str, duration: float) -> dict[str, Any] | None:
    """{"tags": {...}, "moments": {...}} when every tag is one of the fixed words, else None (the caller tries once more)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for field in SINGLE_CHOICE:
        if data.get(field) not in VOCAB[field]:
            return None
    subjects = data.get("subjects")
    if not isinstance(subjects, list) or not subjects or any(s not in VOCAB["subjects"] for s in subjects):
        return None
    description = data.get("description")
    if not isinstance(description, str) or not description.strip() or not isinstance(data.get("vertical_crop_ok"), bool):
        return None
    tags = {"shot_size": data["shot_size"], "subjects": list(dict.fromkeys(subjects)), "energy": data["energy"], "camera_move": data["camera_move"],
            "vertical_crop_ok": data["vertical_crop_ok"], "description": description.strip()[:160], "quality_note": str(data.get("quality_note") or "").strip()[:160]}
    moments = post_moments.parse_moments_reply(text, duration) or {"scene": str(data.get("scene") or "")[:60], "people": bool(data.get("people")), "events": []}
    return {"tags": tags, "moments": moments}


def viewing_filter(profile: str, height: int) -> str:
    curve = CONFIG["viewing_curve"].get(profile)
    return f"scale=-2:{height}" + (f",{curve}" if curve else "")


async def _still(path: str, at_seconds: float, vf: str, limiter: asyncio.Semaphore) -> bytes | None:
    async with limiter:
        try:
            proc = await asyncio.create_subprocess_exec(post_media.FFMPEG_PATH, "-hide_banner", "-v", "error", "-threads", "2", "-ss", f"{at_seconds:.3f}", "-i", path, "-frames:v", "1",
                                                        "-vf", vf, "-q:v", "4", "-f", "mjpeg", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return None
        out, _ = await proc.communicate()
    return out if proc.returncode == 0 and out else None


async def tag_clip(client: Any, clip: dict[str, Any], usage: dict[str, int]) -> dict[str, Any] | None:
    """One clip's tags and moments, or None if no valid answer came back in the allowed tries. Raises what post_moments treats as systemic, so a run stops rather than failing clip after clip."""
    times = post_moments._frame_times(clip["duration"])
    limiter = asyncio.Semaphore(6)
    vf = viewing_filter(clip.get("profile") or "unknown", post_media.STILL_MAX_HEIGHT)
    stills = await asyncio.gather(*(_still(clip["path"], t, vf, limiter) for t in times))
    content: list[dict[str, Any]] = []
    for t, jpeg in zip(times, stills):
        if jpeg:
            content += [{"type": "text", "text": f"t={t}s"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}}]
    if not content:
        return None
    orientation = "vertical" if clip.get("vertical") else "horizontal"
    content.append({"type": "text", "text": f"This clip is {orientation} and {clip['duration']:.1f} seconds long. Log it as instructed."})
    for _ in range(CONFIG["tagging"]["tries"]):
        try:
            response = await client.messages.create(model=MODEL, max_tokens=CONFIG["tagging"]["max_tokens"], system=TAG_SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
        except Exception as exc:
            print(f"[post_shoot_log] vision call failed: {type(exc).__name__}: {str(exc)[:200]}")
            if post_moments._is_systemic_failure(exc):
                raise post_moments.VisionUnavailableError("Claude is unavailable (API credit balance too low, or the API key was rejected). Fix that, then click Tag again.")
            if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
                raise ClaudeUnreachable("Couldn't reach Claude. Every clip tagged so far is saved; click Tag again once there's signal.")
            continue
        usage["in"] = usage.get("in", 0) + response.usage.input_tokens
        usage["out"] = usage.get("out", 0) + response.usage.output_tokens
        usage["calls"] = usage.get("calls", 0) + 1
        parsed = parse_tag_reply("".join(b.text for b in response.content if getattr(b, "type", "") == "text"), clip["duration"])
        if parsed is not None:
            return parsed
    return None


class ClaudeUnreachable(RuntimeError):
    pass


# ================================================================================================================================================= files
def index_path() -> Path:
    return DATA / "index.json"


def load_index() -> dict[str, Any]:
    try:
        return json.loads(index_path().read_text())
    except (OSError, ValueError):
        return {}


def save_index(index: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    _atomic_write(index_path(), json.dumps(index, indent=1))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text)
    tmp.replace(path)


def find_context(key: str) -> dict[str, Any] | None:
    """A shoot's entry, or None. Keys only ever come out of this index, so a request can't name a folder of its own."""
    entry = load_index().get(key)
    return {"key": key, **entry} if entry else None


def context_for_project(project_path: str) -> dict[str, Any] | None:
    target = os.path.normpath(project_path)
    return next(({"key": k, **v} for k, v in load_index().items() if os.path.normpath(v["project_path"]) == target), None)


def new_context(project_path: str, job: dict[str, Any] | None) -> dict[str, Any]:
    """Registers a shoot. A POST shoot keeps its log beside its plans and shares their clip reads and ids; any other project of his gets a local workspace (learning.transfer_cut's)."""
    if job is not None:
        key, shape = f"j{job['id']}", {k: job.get(k) for k in ("id", "shoot_name", "profile", "destination_root", "premiere_project_path")}
    else:
        from learning.transfer_cut import workspace
        shape = workspace(project_path)
        key = f"p{abs(shape['id'])}"
    entry = {"project_path": project_path, "name": Path(project_path).stem, "job": shape, "folder": str(edit_dir(shape) / "shoot_log"), "is_shoot": job is not None}
    index = load_index()
    index[key] = entry
    save_index(index)
    return {"key": key, **entry}


def folder_of(ctx: dict[str, Any]) -> Path:
    return Path(ctx["folder"])


def load_log(ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads((folder_of(ctx) / "shoot_log.json").read_text())
    except (OSError, ValueError):
        return {"version": 1, "project_path": ctx["project_path"], "name": ctx["name"], "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "clips": {}, "order": []}


def _save_log(ctx: dict[str, Any], log: dict[str, Any]) -> None:
    _atomic_write(folder_of(ctx) / "shoot_log.json", json.dumps(log))


def load_overrides(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    path = folder_of(ctx) / "overrides.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def load_applied(ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads((folder_of(ctx) / "applied.json").read_text())
    except (OSError, ValueError):
        return {}


def thumb_path(ctx: dict[str, Any], clip_id: str, i: int) -> Path:
    return folder_of(ctx) / "thumbs" / f"{clip_id}_{i}.jpg"


# ================================================================================================================================================= his choices
def validate_override(field: str, value: Any) -> Any:
    """The value to store, or ShootLogError saying what's wrong."""
    if field == "status":
        if value not in STATUSES:
            raise ShootLogError("Status has to be select, reject or none.")
        return value
    if field in SINGLE_CHOICE:
        if value not in VOCAB[field]:
            raise ShootLogError(f"{field} has to be one of: {', '.join(VOCAB[field])}.")
        return value
    if field == "subjects":
        if not isinstance(value, list) or any(s not in VOCAB["subjects"] for s in value):
            raise ShootLogError(f"subjects has to be a list from: {', '.join(VOCAB['subjects'])}.")
        return list(dict.fromkeys(value))
    if field == "vertical_crop_ok":
        if not isinstance(value, bool):
            raise ShootLogError("vertical_crop_ok has to be true or false.")
        return value
    if field in ("description", "quality_note"):
        if not isinstance(value, str):
            raise ShootLogError(f"{field} has to be text.")
        return value.strip()[:200]
    raise ShootLogError(f"Unknown field: {field}.")


def add_override(ctx: dict[str, Any], clip_id: str, field: str, value: Any) -> dict[str, Any]:
    log = load_log(ctx)
    if clip_id not in log["clips"]:
        raise ShootLogError("That clip isn't in this shoot's log.")
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "clip": clip_id, "field": field, "value": validate_override(field, value)}
    folder_of(ctx).mkdir(parents=True, exist_ok=True)
    with open(folder_of(ctx) / "overrides.jsonl", "a") as fh:
        fh.write(json.dumps(line) + "\n")
    return line


def fold_overrides(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        out.setdefault(line["clip"], {})[line["field"]] = line["value"]
    return out


def effective_clip(clip: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    """The clip as it now stands: his choices over Claude's answers, with Claude's kept alongside under ai_tags."""
    ai = clip.get("tags") or {}
    tags = {**ai, **{k: v for k, v in choices.items() if k != "status"}}
    auto_reject = (clip.get("checks") or {}).get("result") == "reject"
    status = choices.get("status", "reject" if auto_reject else "none")
    return {**clip, "tags": tags, "ai_tags": ai, "status": status, "yours": sorted(choices), "reviewed": bool(choices)}


def review_minutes(lines: list[dict[str, Any]]) -> float:
    """How long he spent choosing: the time between his choices, leaving out breaks. For the spec's "logging time per hour of footage"."""
    stamps = sorted(time.mktime(time.strptime(line["at"], "%Y-%m-%dT%H:%M:%S")) for line in lines if line.get("at"))
    return round(sum(b - a for a, b in zip(stamps, stamps[1:]) if b - a <= REVIEW_GAP_SECONDS) / 60.0, 1)


def tags_kept(clips: list[dict[str, Any]], folded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Of the clips he has reviewed, how many of Claude's tags he left as they were, per field. Only useful once he has been correcting tags: on Birkenstock he only chose Select or Reject,
    which scored 140 of 140 and said nothing about whether the tags were right."""
    per_field: dict[str, list[int]] = {f: [0, 0] for f in (*SINGLE_CHOICE, "subjects", "vertical_crop_ok")}
    for clip in clips:
        choices = folded.get(clip["id"])
        ai = clip.get("tags")
        if not choices or not ai:
            continue
        for field, tally in per_field.items():
            tally[1] += 1
            if field not in choices or choices[field] == ai.get(field) or (field == "subjects" and set(choices[field]) == set(ai.get(field) or [])):
                tally[0] += 1
    kept, total = sum(t[0] for t in per_field.values()), sum(t[1] for t in per_field.values())
    return {"kept": kept, "total": total, "share": round(kept / total, 3) if total else None, "per_field": {f: {"kept": t[0], "total": t[1]} for f, t in per_field.items()}}


def tag_candidates(log: dict[str, Any], folded: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Clips still needing tags, in recording order: readable, not rejected by him or by the checks, and not already tagged with this prompt."""
    out = []
    for cid in log["order"]:
        clip = log["clips"][cid]
        if clip.get("probe_error") or effective_clip(clip, folded.get(cid, {}))["status"] == "reject":
            continue
        if (clip.get("tag_provenance") or {}).get("prompt") == TAG_PROMPT_VERSION and clip.get("tags"):
            continue
        out.append(clip)
    return out


def tag_estimate(count: int) -> dict[str, Any]:
    est = post_moments.estimate_cost(count, MODEL)
    usd = float(est.get("usd_list_price", est["usd_at_most"]))
    cap = round(min(max(usd * CONFIG["tagging"]["cap_multiple"], 0.25), CONFIG["tagging"]["hard_cap_usd"]), 2)
    return {"clips": count, "usd": round(usd, 2), "cap_usd": cap, "basis": est.get("list_price_basis", est["assumption"])}


def view(ctx: dict[str, Any]) -> dict[str, Any]:
    """Everything the review page shows."""
    log = load_log(ctx)
    lines = load_overrides(ctx)
    folded = fold_overrides(lines)
    clips = [effective_clip(log["clips"][cid], folded.get(cid, {})) for cid in log["order"] if cid in log["clips"]]
    gammas: dict[str, int] = {}
    for c in clips:
        gammas[c.get("gamma") or "unknown"] = gammas.get(c.get("gamma") or "unknown", 0) + 1
    counts = {"clips": len(clips), "selects": sum(c["status"] == "select" for c in clips), "rejects": sum(c["status"] == "reject" for c in clips), "reviewed": sum(c["reviewed"] for c in clips),
              "tagged": sum(bool(c.get("ai_tags")) for c in clips), "minutes_of_footage": round(sum(c.get("duration") or 0 for c in clips) / 60.0, 1),
              "pass": sum((c.get("checks") or {}).get("result") == "pass" for c in clips), "check": sum((c.get("checks") or {}).get("result") == "check" for c in clips)}
    todo = tag_candidates(log, folded)
    return {"key": ctx["key"], "name": ctx["name"], "project_path": ctx["project_path"], "is_shoot": ctx.get("is_shoot", False), "clips": clips, "counts": counts, "gammas": gammas,
            "kept": tags_kept([log["clips"][c] for c in log["order"] if c in log["clips"]], folded), "review_minutes": review_minutes(lines), "run": run_state(ctx["key"]), "estimate": tag_estimate(len(todo)),
            "spent": post_moments.usage_summary(folder_of(ctx)), "vocabulary": VOCAB, "labels": CONFIG["labels"], "applied_at": load_applied(ctx).get("at"), "thumb_count": len(CONFIG["thumbs"]["positions"]), "preview_seconds": CONFIG["preview"]["seconds"]}


# ================================================================================================================================================= running it
_RUNS: dict[str, dict[str, Any]] = {}  # per shoot, in this process: a restart forgets a run but not what it finished, and clicking again carries on


def run_state(key: str) -> dict[str, Any] | None:
    run = _RUNS.get(key)
    if run is None:
        return None
    out = {k: v for k, v in run.items() if k not in ("task", "stop", "stage_started")}
    if run["state"] == "running" and run.get("done") and run.get("total"):
        out["seconds_left_in_stage"] = round((time.time() - run["stage_started"]) / run["done"] * (run["total"] - run["done"]))
    return out


def request_stop(key: str) -> dict[str, Any] | None:
    run = _RUNS.get(key)
    if run is not None and run["state"] == "running":
        run["stop"] = True
    return run_state(key)


def _begin(key: str, kind: str) -> dict[str, Any]:
    existing = _RUNS.get(key)
    if existing is not None and existing["state"] == "running":
        raise ShootLogError("This shoot is already being worked on.")
    run = {"kind": kind, "state": "running", "stage": None, "done": 0, "total": 0, "message": None, "failed": [], "stop": False, "stage_started": time.time(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished_at": None}
    _RUNS[key] = run
    return run


def _stage(run: dict[str, Any], name: str, total: int) -> None:
    run.update(stage=name, done=0, total=total, stage_started=time.time())


def _finish(run: dict[str, Any], state: str, message: str) -> None:
    run.update(state=state, message=message, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def clip_id_for(path: str, known: dict[str, int] | None = None) -> int:
    """A POST shoot's own file id when it has one, so its clip reads and descriptions are shared; otherwise stable for this path (camera file names repeat across cards)."""
    if known and path in known:
        return int(known[path])
    return int(hashlib.sha1(os.path.normpath(path).encode()).hexdigest()[:12], 16)


def merge_clips(log: dict[str, Any], incoming: list[dict[str, Any]], file_ids: dict[str, int] | None = None) -> list[str]:
    """Brings the log in line with the project's clips and returns the file names skipped as not video. Clips already logged keep everything they have."""
    clips: dict[str, Any] = {}
    skipped = []
    for item in incoming:
        path = item["path"]
        if Path(path).suffix.lower() not in VIDEO_EXTENSIONS:
            skipped.append(item.get("name") or Path(path).name)
            continue
        fid = clip_id_for(path, file_ids)
        cid = str(fid)
        clips[cid] = log["clips"].get(cid) or {"id": cid, "file_id": fid, "name": item.get("name") or Path(path).name, "path": path}
    log["clips"] = clips
    log["order"] = list(clips)
    return skipped


def _recording_order(log: dict[str, Any]) -> None:
    log["order"] = sorted(log["clips"], key=lambda cid: (log["clips"][cid].get("created") or "", log["clips"][cid]["name"]))


async def _make_thumbs(ctx: dict[str, Any], clip: dict[str, Any], limiter: asyncio.Semaphore) -> None:
    conf = CONFIG["thumbs"]
    vf = viewing_filter(clip.get("profile") or "unknown", conf["height"])
    for i, share in enumerate(conf["positions"]):
        out = thumb_path(ctx, clip["id"], i)
        if await on_drive(out.exists):
            continue
        jpeg = await _still(clip["path"], max(0.0, (clip.get("duration") or 0) * share), vf, limiter)
        if jpeg:
            await on_drive(_write_bytes, out, jpeg, writing=True)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def _run_local(ctx: dict[str, Any], run: dict[str, Any]) -> None:
    """The free part: camera data, viewing frames, the checks. Stopping or a restart loses nothing: each stage skips what it has done."""
    key = ctx["key"]
    try:
        log = await on_drive(load_log, ctx)
        clips = [log["clips"][c] for c in log["order"]]
        _stage(run, "Reading camera data", len(clips))
        limiter = asyncio.Semaphore(8)

        async def camera(clip: dict[str, Any]) -> None:
            if "duration" not in clip or clip.get("probe_error"):
                clip.update(await probe(clip["path"], limiter))
                side = await on_drive(read_sidecar, clip["path"], timeout=30.0)
                clip.update({"gamma": side.get("gamma"), "camera": side.get("camera"), "lens": side.get("lens"), "capture_fps": side.get("capture_fps"), "codec_label": side.get("codec_label"), "profile": gamma_profile(side.get("gamma"))})
            run["done"] += 1
        await asyncio.gather(*(camera(c) for c in clips))
        _recording_order(log)
        await on_drive(_save_log, ctx, log, writing=True)
        readable = [log["clips"][c] for c in log["order"] if not log["clips"][c].get("probe_error")]

        _stage(run, "Making viewing frames", len(readable))
        thumb_limit = asyncio.Semaphore(CONFIG["thumbs"]["concurrency"])

        async def thumbs(clip: dict[str, Any]) -> None:
            if not run["stop"]:
                await _make_thumbs(ctx, clip, thumb_limit)
            run["done"] += 1
        await asyncio.gather(*(thumbs(c) for c in readable))

        _stage(run, "Checking every clip", len(readable))
        reads = [{"file_id": c["file_id"], "path": c["path"], "id": c["id"]} for c in readable]

        def progress() -> None:
            run["done"] += 1
        counts = await post_steady.analyse_clips(reads, ctx["job"], progress=progress, should_stop=lambda: run["stop"])
        series = {r["id"]: r.get("steady") for r in reads}
        results = check_results([{"id": c["id"], "name": c["name"], "duration": c.get("duration"), "profile": c.get("profile"), "m": series.get(c["id"])} for c in readable])
        for clip in log["clips"].values():
            if clip.get("probe_error"):
                clip["checks"] = {"result": "reject", "flags": [], "reject_reason": f"Couldn't be read: {clip['probe_error']}", "group": None}
            elif clip["id"] in results:
                clip["checks"] = results[clip["id"]]
            elif counts["unreadable"] and not run["stop"]:
                clip["checks"] = {"result": "reject", "flags": [], "reject_reason": "Couldn't be decoded.", "group": None}
        await on_drive(_save_log, ctx, log, writing=True)
        if run["stop"]:
            _finish(run, "stopped", "Stopped. Everything done so far is kept; click Log This Shoot to carry on.")
        else:
            _finish(run, "done", f"Logged {len(readable)} clips. {counts['analysed']} read now, {counts['cached']} already read.")
    except DriveNotResponding as exc:
        _finish(run, "stopped", exc.message)
    except Exception as exc:  # a background task must never die silently
        _finish(run, "failed", f"{type(exc).__name__}: {str(exc)[:200]}")
        print(f"[post_shoot_log] {key}: {run['message']}")


def start_logging(ctx: dict[str, Any], incoming: list[dict[str, Any]], file_ids: dict[str, int] | None = None) -> dict[str, Any]:
    """Starts the free part in the background and returns at once; poll view() or run_state()."""
    run = _begin(ctx["key"], "log")
    log = load_log(ctx)
    skipped = merge_clips(log, incoming, file_ids)
    _save_log(ctx, log)
    run["skipped"] = skipped
    run["task"] = asyncio.get_running_loop().create_task(_run_local(ctx, run))
    return {"clips": len(log["clips"]), "skipped": skipped, "run": run_state(ctx["key"])}


async def _run_tagging(ctx: dict[str, Any], run: dict[str, Any], client: Any, clips: list[dict[str, Any]], cap_usd: float) -> None:
    usage: dict[str, int] = {}
    per_clip = tag_estimate(1)["usd"]
    sem = asyncio.Semaphore(CONFIG["tagging"]["concurrency"])
    stop_for: list[str] = []
    log = await on_drive(load_log, ctx)
    saving = asyncio.Lock()   # clips finish at the same time, and the snapshot is taken here so no clip changes the log while it is being written

    def spent() -> float:
        return post_moments.usd(MODEL, usage.get("in", 0), usage.get("out", 0))[0]

    in_flight = [0]

    async def one(clip: dict[str, Any]) -> None:
        async with sem:
            if run["stop"] or stop_for:
                return
            if spent() + per_clip * (in_flight[0] + 1) > cap_usd:   # clips still on their way to Claude count too, or several together would overshoot the limit
                stop_for.append(f"Stopped at the ${cap_usd:.2f} limit. Every clip tagged so far is saved; click Tag again to carry on.")
                return
            in_flight[0] += 1
            try:
                result = await tag_clip(client, clip, usage)
            except (post_moments.VisionUnavailableError, ClaudeUnreachable) as exc:
                stop_for.append(str(exc))
                return
            finally:
                in_flight[0] -= 1
            if result is None:
                run["failed"].append(clip["name"])
            else:
                entry = log["clips"].get(clip["id"])
                if entry is not None:
                    entry.update(result, tag_provenance={"model": MODEL, "prompt": TAG_PROMPT_VERSION, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                    async with saving:
                        await on_drive(_atomic_write, folder_of(ctx) / "shoot_log.json", json.dumps(log), writing=True)
            run["done"] += 1

    try:
        _stage(run, "Tagging with Claude", len(clips))
        await asyncio.gather(*(one(c) for c in clips))
        tail = f" {len(run['failed'])} couldn't be tagged: {', '.join(run['failed'][:8])}." if run["failed"] else ""
        if stop_for:
            _finish(run, "stopped", stop_for[0] + tail)
        elif run["stop"]:
            _finish(run, "stopped", f"Stopped. {run['done']} clips done and kept.{tail}")
        else:
            _finish(run, "done", f"Tagged {run['done'] - len(run['failed'])} clips.{tail}")
    except DriveNotResponding as exc:
        _finish(run, "stopped", exc.message)
    except Exception as exc:  # a background task must never die silently
        _finish(run, "failed", f"{type(exc).__name__}: {str(exc)[:200]}")
        print(f"[post_shoot_log] {ctx['key']}: {run['message']}")
    finally:
        if usage.get("calls"):
            line = post_moments.record_usage(folder_of(ctx), job_id=ctx["job"]["id"], operation="shoot_log_tags", model=MODEL, usage=usage, extra={"clips_tagged": run["done"] - len(run["failed"]), "state": run["state"]})
            run["usd"] = line["usd"]


def start_tagging(ctx: dict[str, Any], client: Any, cap_usd: float | None = None) -> dict[str, Any]:
    """Starts tagging the clips that need it. Only ever called from an explicit click: this spends money."""
    log = load_log(ctx)
    clips = tag_candidates(log, fold_overrides(load_overrides(ctx)))
    if not clips:
        return {"started": False, "message": "Every clip already has its tags.", "run": run_state(ctx["key"])}
    estimate = tag_estimate(len(clips))
    limit = min(float(cap_usd) if cap_usd else estimate["cap_usd"], CONFIG["tagging"]["hard_cap_usd"])
    run = _begin(ctx["key"], "tag")
    run["cap_usd"] = limit
    run["task"] = asyncio.get_running_loop().create_task(_run_tagging(ctx, run, client, clips, limit))
    return {"started": True, "estimate": estimate, "run": run_state(ctx["key"])}


_PREVIEW_LIMIT = asyncio.Semaphore(2)


async def render_preview(ctx: dict[str, Any], clip: dict[str, Any]) -> Path:
    """A small watchable copy with sound, made once when he first plays the clip, in the same viewing curve as the frames."""
    out = folder_of(ctx) / "previews" / f"{clip['id']}.mp4"
    if await on_drive(out.exists):
        return out
    await on_drive(lambda: out.parent.mkdir(parents=True, exist_ok=True), writing=True)
    tmp = out.with_suffix(".part.mp4")
    conf = CONFIG["preview"]
    async with _PREVIEW_LIMIT:
        if await on_drive(out.exists):
            return out
        proc = await asyncio.create_subprocess_exec(post_media.FFMPEG_PATH, "-hide_banner", "-v", "error", "-y", "-threads", "8", "-t", str(conf["seconds"]), "-i", clip["path"],
                                                    "-vf", viewing_filter(clip.get("profile") or "unknown", conf["height"]) + ",fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                                                    "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(tmp), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
    if proc.returncode != 0 or not await on_drive(tmp.exists):
        raise ShootLogError(f"Couldn't make the preview: {err.decode(errors='replace')[:160]}")
    await on_drive(tmp.replace, out, writing=True)
    return out


# ================================================================================================================================================= out to Premiere and elsewhere
def log_note_words(clip: dict[str, Any]) -> str:
    """What goes in Log Note. A rejected clip carries no searchable tags, because search bins look through the whole project and would otherwise show it."""
    if clip["status"] == "reject":
        return "rejected"
    tags = clip.get("tags") or {}
    words = [token_for("shot_size", tags["shot_size"])] if tags.get("shot_size") else []
    words += [token_for("subjects", s) for s in tags.get("subjects") or []]
    for field in ("energy", "camera_move"):
        if tags.get(field):
            words.append(token_for(field, tags[field]))
    words += ["check" + f["type"].replace("_", "") for f in (clip.get("checks") or {}).get("flags") or [] if f["type"] != "long"]
    return " ".join(words)


def search_bin_groups(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One search bin for each subject and shot size this shoot really has, in the vocabulary's order."""
    live = [c for c in clips if c["status"] != "reject"]
    subjects = {s for c in live for s in (c.get("tags") or {}).get("subjects") or []}
    sizes = {(c.get("tags") or {}).get("shot_size") for c in live}
    return [{"bin": "By Subject", "search": [{"name": label_for(v), "query": token_for("subjects", v)} for v in VOCAB["subjects"] if v in subjects]},
            {"bin": "By Shot Size", "search": [{"name": label_for(v), "query": token_for("shot_size", v)} for v in VOCAB["shot_size"] if v in sizes]}]


def apply_plan(ctx: dict[str, Any]) -> dict[str, Any]:
    """What Apply Shoot Log does in Premiere, clip by clip, matched by media path. `previous` is what the last Apply wrote, so it can tell his own edits in Premiere from its own."""
    data = view(ctx)
    applied = load_applied(ctx).get("clips", {})
    conf = CONFIG["apply"]
    clips = []
    for c in data["clips"]:
        events = [] if c["status"] == "reject" else (c.get("moments") or {}).get("events") or []
        clips.append({"id": c["id"], "name": c["name"], "path": c["path"], "status": c["status"], "note": log_note_words(c), "description": (c.get("tags") or {}).get("description") or "",
                      "previous": applied.get(c["id"], {}), "markers": [{"t": e["t"], "seconds": conf["marker_seconds"], "comment": e.get("what") or e.get("kind") or ""} for e in events[:conf["markers_per_clip"]]]})
    return {"key": ctx["key"], "name": ctx["name"], "bins": {"parent": PARENT_BIN, "selects": SELECTS_BIN, "rejects": REJECTS_BIN, "groups": search_bin_groups(data["clips"])},
            "note_prefix": LOG_NOTE_PREFIX, "clips": clips, "counts": data["counts"]}


def record_applied(ctx: dict[str, Any], report: dict[str, Any]) -> None:
    """Remembers what Apply wrote, so the next Apply replaces its own words and leaves his."""
    plan = apply_plan(ctx)
    applied = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "report": report, "clips": {c["id"]: {"status": c["status"], "description": c["description"]} for c in plan["clips"]}}
    _atomic_write(folder_of(ctx) / "applied.json", json.dumps(applied))


CSV_FIELDS = ("name", "status", "checks", "flags", "shot_size", "subjects", "energy", "camera_move", "vertical_crop_ok", "description", "quality_note", "duration", "fps", "width", "height", "vertical", "codec", "bit_rate",
              "camera", "lens", "gamma", "timecode", "reel", "created", "path")


def to_csv(ctx: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for c in view(ctx)["clips"]:
        tags = c.get("tags") or {}
        checks = c.get("checks") or {}
        row = {**c, **tags, "checks": checks.get("result"), "flags": "; ".join(f["reason"] for f in checks.get("flags") or []), "subjects": ", ".join(tags.get("subjects") or [])}
        # A cell starting with one of these is run as a formula by a spreadsheet, and clip names and descriptions are outside text.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in row.items()})
    return out.getvalue()
