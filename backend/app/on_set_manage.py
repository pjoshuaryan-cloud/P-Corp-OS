"""Making and changing on-set shot lists from a phone, with no Mac (2026-11-04).

Runs on the cloud backend, so the Mac can be off. A list made here lives in the shared database, and crew open it with the same kind of phone link as one made on the Mac. When the Mac is next on it brings
the list into Coverage Plans (post_coverage.import_phone_list), where the footage check and report happen.

Only the owner's phone reaches this, with its own login (on_set_db.claim_setup). That login can make and change shot lists and nothing else: no plans, footage, costs or other P Corp data.

It can also draft a list from a brief, the one thing here that spends money, because he asked to be able to do that with no Mac. A login on a phone can be lost, so drafts have a daily ceiling in the config, counted
in the shared database, which stops them before a call is made. The prompt and its handling are the Mac's own (post_coverage), where a brief is information and never instructions. A brief isn't kept here."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from app import on_set_db as db

_CONFIG = json.loads((Path(__file__).parent / "shoot_log_config.json").read_text())
_COVERAGE = _CONFIG["coverage"]
_ON_SET = _COVERAGE["on_set"]
LABELS: dict[str, str] = _CONFIG["labels"]
PRIORITIES: dict[str, str] = _COVERAGE["priorities"]
SIZES = ("any", *_CONFIG["vocabulary"]["shot_size"])
MAX_ITEMS = 300
MAX_DRAFT_BODY_BYTES = 24 * 1024 * 1024
MAX_DRAFTS_AT_ONCE = 2
_DRAFTS: dict[str, dict[str, Any]] = {}


class ListError(ValueError):
    """Something a person can fix, with words saying how."""


def clean_date(raw: Any) -> str:
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except ValueError:
        raise ListError("Pick the shoot date.") from None


def clean_item(fields: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """A shot in the form phones get, from what a person typed or a template holds."""
    item = dict(existing or {"id": "p" + secrets.token_hex(5), "moment": "", "time": "", "description": "", "size": "any", "priority": "should", "owner": ""})
    names = {"shot_size": "size"}
    for field, value in fields.items():
        key = names.get(field, field)
        if key in ("moment", "time", "description", "size", "priority", "owner") and value is not None:
            if not isinstance(value, str):
                raise ListError(f"{key} has to be text.")
            item[key] = db._clean_text(value, 200)
    item["moment"] = item["moment"][:60] or "General"
    item["time"] = item["time"][:12]
    item["owner"] = item["owner"][:40]
    if not item["description"]:
        raise ListError("A shot needs a description.")
    if item["size"] not in SIZES:
        raise ListError("That shot size isn't one of the choices.")
    if item["priority"] not in PRIORITIES:
        raise ListError("That priority isn't one of the choices.")
    item["size_label"] = "" if item["size"] == "any" else LABELS.get(item["size"], item["size"])
    item["priority_label"] = PRIORITIES[item["priority"]]
    return item


async def templates(conn: Any = None) -> list[dict[str, Any]]:
    """The Mac's saved lists once it has copied them up. Until then, the starter lists, which ship with the code."""
    return await db.load_templates(conn) or [{"id": t["id"], "name": t["name"], "items": t["items"]} for t in _COVERAGE.get("starter_templates", [])]


def list_view(link: dict[str, Any], events: list[dict[str, Any]], share: dict[str, Any] | None) -> dict[str, Any]:
    """A list as the owner's phone sees it."""
    ticks = db.current_ticks(events)
    done = {k for k, v in ticks.items() if v["done"]}
    ids = {i["id"] for i in link["items"]}
    expired = link["expires_at"] <= db.now_iso()
    return {"id": link["plan_id"], "name": link["name"], "client": link["client"], "shoot_date": link["shoot_date"], "items": link["items"], "version": link["list_version"], "ticks": {k: v for k, v in ticks.items() if k in ids},
            "done": len(done & ids), "total": len(ids), "must_left": sum(1 for i in link["items"] if i["priority"] == "must" and i["id"] not in done), "stopped": bool(link["revoked_at"]), "expired": expired,
            "live": not link["revoked_at"] and not expired, "expires_at": link["expires_at"], "token": share["token"] if share else None, "source": share["source"] if share else None}


async def get_list(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    link = await db.get_link(plan_id, conn)
    if link is None:
        return None
    return {**list_view(link, await db.ticks_since(plan_id, 0, conn), await db.get_share(plan_id, conn)), "draft": draft_state(plan_id)}


async def overview(conn: Any = None) -> dict[str, Any]:
    lists = []
    for row in await db.all_lists(conn):
        view = list_view(row, await db.ticks_since(row["plan_id"], 0, conn), {"token": row["share_token"], "source": row["source"]} if row["share_token"] else None)
        lists.append({k: view[k] for k in ("id", "name", "client", "shoot_date", "done", "total", "must_left", "stopped", "expired", "live", "source")})
    return {"lists": lists, "templates": [{"id": t["id"], "name": t["name"], "shots": len(t["items"])} for t in await templates(conn)], "priorities": PRIORITIES, "sizes": [{"id": s, "label": "Any size" if s == "any" else LABELS.get(s, s)} for s in SIZES]}


async def create_list(name: str, client: str, shoot_date: str, template_id: str | None, conn: Any = None) -> dict[str, Any]:
    name = db._clean_text(name, 120)
    if not name:
        raise ListError("Give the list a name, such as the shoot's.")
    shoot_date = clean_date(shoot_date)
    items: list[dict[str, Any]] = []
    if template_id:
        chosen = next((t for t in await templates(conn) if t["id"] == template_id), None)
        if chosen is None:
            raise ListError("That template doesn't exist.")
        items = [clean_item(i) for i in chosen["items"]]
    await db.ensure_tables(conn)
    plan_id = "c" + uuid.uuid4().hex[:12]
    await db.publish(plan_id, db.new_token(), name, db._clean_text(client, 120), shoot_date, items, _ON_SET["settings"], db.expiry_for(shoot_date, _ON_SET["link_days_after_shoot"]), conn, source="phone")
    return await get_list(plan_id, conn)  # type: ignore[return-value]


async def _change(plan_id: str, change: Any, conn: Any) -> dict[str, Any] | None:
    return await get_list(plan_id, conn) if await db.change_list(plan_id, change, conn) else None


async def update_details(plan_id: str, fields: dict[str, Any], conn: Any = None) -> dict[str, Any] | None:
    def apply(link: dict[str, Any]) -> None:
        if fields.get("name") is not None:
            link["name"] = db._clean_text(fields["name"], 120)
            if not link["name"]:
                raise ListError("Give the list a name.")
        if fields.get("client") is not None:
            link["client"] = db._clean_text(fields["client"], 120)
        if fields.get("shoot_date") is not None:
            link["shoot_date"] = clean_date(fields["shoot_date"])
            if not link["revoked_at"] and link["expires_at"] > db.now_iso():   # a new date never brings a stopped or run-out link back to life
                link["expires_at"] = db.expiry_for(link["shoot_date"], _ON_SET["link_days_after_shoot"])
    return await _change(plan_id, apply, conn)


async def add_item(plan_id: str, fields: dict[str, Any], conn: Any = None) -> dict[str, Any] | None:
    def apply(link: dict[str, Any]) -> None:
        if len(link["items"]) >= MAX_ITEMS:
            raise ListError(f"A list can hold {MAX_ITEMS} shots.")
        link["items"].append(clean_item(fields))
    return await _change(plan_id, apply, conn)


async def update_item(plan_id: str, item_id: str, fields: dict[str, Any], conn: Any = None) -> dict[str, Any] | None:
    def apply(link: dict[str, Any]) -> None:
        for n, item in enumerate(link["items"]):
            if item["id"] == item_id:
                link["items"][n] = clean_item(fields, item)
                return
        raise ListError("That shot is no longer on the list.")
    return await _change(plan_id, apply, conn)


async def delete_item(plan_id: str, item_id: str, conn: Any = None) -> dict[str, Any] | None:
    def apply(link: dict[str, Any]) -> None:
        kept = [i for i in link["items"] if i["id"] != item_id]
        if len(kept) == len(link["items"]):
            raise ListError("That shot is no longer on the list.")
        link["items"] = kept
    return await _change(plan_id, apply, conn)


async def set_moment_time(plan_id: str, moment: str, when: str, conn: Any = None) -> dict[str, Any] | None:
    """A time for a whole moment: quicker on a phone than a time per shot."""
    when = db._clean_text(when, 12)

    def apply(link: dict[str, Any]) -> None:
        found = False
        for item in link["items"]:
            if item["moment"] == moment:
                item["time"] = when
                found = True
        if not found:
            raise ListError("That moment is no longer on the list.")
    return await _change(plan_id, apply, conn)


# ======================================================================================================================================= drafting from a brief
def draft_state(plan_id: str) -> dict[str, Any] | None:
    job = _DRAFTS.get(plan_id)
    return {k: job.get(k) for k in ("state", "message", "finished_at")} if job else None


async def start_draft(plan_id: str, manager: dict[str, Any], text: str, files: list[dict[str, Any]], client: Any, scope: Any, conn: Any = None) -> dict[str, Any] | None:
    """Starts drafting. Only from a person's tap: this spends money, and the brief goes to Anthropic. Everything that can be refused for free is refused here, before any call."""
    from app import post_coverage
    if await db.get_link(plan_id, conn) is None:
        return None
    if (_DRAFTS.get(plan_id) or {}).get("state") == "running":
        raise ListError("Already drafting this list. Give it a moment.")
    if sum(j.get("state") == "running" for j in _DRAFTS.values()) >= MAX_DRAFTS_AT_ONCE:
        raise ListError("Another draft is running. Give it a moment.")
    limits = _ON_SET["phone_drafts"]
    used = await db.drafts_last_day(conn)
    if used["count"] >= limits["per_day"] or used["usd"] >= limits["max_usd_per_day"]:
        raise ListError("That's the most drafts allowed from a phone in a day, so a lost phone can't run up a bill. Add shots by hand, start from a template, or draft on the Mac.")
    try:
        blocks = post_coverage.brief_blocks(text, files)
    except post_coverage.ShootLogError as exc:
        raise ListError(str(exc)) from None
    except ValueError as exc:
        raise ListError(f"That file can't be read: {str(exc)[:120]}") from None
    job = {"state": "running", "message": "Reading the brief", "finished_at": None}
    _DRAFTS[plan_id] = job
    job["task"] = asyncio.get_running_loop().create_task(_run_draft(plan_id, manager["id"], job, blocks, client, scope))
    return await get_list(plan_id, conn)


async def _run_draft(plan_id: str, manager_id: str, job: dict[str, Any], blocks: list[dict[str, Any]], client: Any, scope: Any) -> None:
    """Holds no database connection while Claude reads. The list only changes once there's a usable answer, so a failed draft leaves it as it was."""
    from app import post_coverage, post_moments
    usage: dict[str, int] = {}

    def finish(state: str, message: str) -> None:
        job.update({"state": state, "message": message, "finished_at": time.time()})
    try:
        parsed = await post_coverage._ask(client, post_coverage.DRAFT_PROMPT, [*blocks, {"type": "text", "text": "Write the shot list as instructed."}], post_coverage.CONFIG["draft_max_tokens"], usage, post_coverage.parse_draft)
        if parsed is None:
            finish("failed", "Claude's answer couldn't be used, so your list is unchanged. Try again, or add shots by hand.")
            return
        drafted, dropped = parsed

        def apply(link: dict[str, Any]) -> None:
            link["items"] = [clean_item(i) for i in drafted][:MAX_ITEMS]
        async with scope() as conn:
            await db.change_list(plan_id, apply, conn)
        finish("done", f"Drafted {len(drafted)} shots. Read them through and change what's wrong." + (f" {dropped} couldn't be used." if dropped else ""))
    except (post_moments.VisionUnavailableError, post_coverage.sl.ClaudeUnreachable) as exc:
        finish("failed", str(exc))
    except Exception as exc:  # a background task must never die silently
        print(f"[on set] draft failed: {type(exc).__name__}: {str(exc)[:200]}")
        finish("failed", "That didn't work, so your list is unchanged. Try again, or add shots by hand.")
    finally:
        job.pop("task", None)
        if usage.get("calls"):
            cost = post_moments.usd(post_coverage.MODEL, usage.get("in", 0), usage.get("out", 0))[0]
            try:
                async with scope() as conn:
                    await db.record_draft(manager_id, plan_id, cost, usage["calls"], conn)
            except Exception as exc:
                print(f"[on set] couldn't record a draft's cost: {type(exc).__name__}")


async def stop_link(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    if await db.get_link(plan_id, conn) is None:
        return None
    await db.revoke(plan_id, conn)
    return await get_list(plan_id, conn)


async def delete_list(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    """Takes a stopped list off the cloud and every phone. A phone's login reaches nothing on the Mac, so the Mac keeps its copy until it's deleted there."""
    if (_DRAFTS.get(plan_id) or {}).get("state") == "running":
        raise ListError("It's still drafting. Give it a moment.")
    gone = await db.delete_list(plan_id, conn)
    if gone is False:
        raise ListError("Stop the link first. A live list can't be deleted.")
    if gone is None:
        return None
    _DRAFTS.pop(plan_id, None)
    return {"ok": True}


async def turn_on(plan_id: str, conn: Any = None) -> dict[str, Any] | None:
    """Makes a list reachable again. After a stop that's a new address, because stopping a link has to mean the old one stays dead. A link that only ran out keeps its address."""
    link = await db.get_link(plan_id, conn)
    if link is None:
        return None
    expires = db.expiry_for(link["shoot_date"], _ON_SET["link_days_after_shoot"])
    if link["revoked_at"] or await db.get_share(plan_id, conn) is None:
        await db.ensure_tables(conn)
        token = db.new_token()
        await db.publish(plan_id, token, link["name"], link["client"], link["shoot_date"], link["items"], link["settings"], expires, conn)
    else:
        await db.set_expiry(plan_id, expires, conn)
    return await get_list(plan_id, conn)
