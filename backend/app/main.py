"""
P Corp OS backend. Proves the IPC contract decided in TECH_STACK.md (local
HTTP + WebSocket via FastAPI, bound to 127.0.0.1) and carries real Claude
reasoning through it — via the plain `anthropic` package, not the full
Claude Agent SDK.

That's a deliberate, confirmed scoping decision: the Agent SDK turned out to
require installing the actual Claude Code CLI and brings full tool-use
capabilities (file access, bash execution) with it. SECURITY.md's agent-
sandboxing/permission model doesn't exist yet, so giving Frank general
tool-use before that's designed would be running ahead of an unresolved
decision, not just a technical step.

Frank has two tools (app/memory.py's `save_memory` and `forget_memory`) via
the plain SDK's tool-use/function-calling — a different, much smaller risk
category than the deferred Agent SDK: hardcoded actions, no file or shell
access, confirmed with Joshua specifically (2026-07-24) as distinct from the
general tool-use deferral above. `forget_memory` is a soft-delete
(app/db.py's `deleted_at`), not a real DELETE — that reversibility is what
keeps it in the same "regular" permission tier as save_memory.

Conversation history persists in SQLite (app/db.py) as real conversations —
reopened from the earlier "one continuous conversation" decision based on
real usage (Joshua wanted to start fresh chats once he actually used the
thread). Durable memory (app/memory.py), not the transcript, is what now
carries "there is only ever one Frank" forward — see app/db.py's docstring.
Every route now checks a local auth token (app/auth.py) — SECURITY.md's
first concrete fix, closing the "any local process can connect" gap.

Notifications (Layer 1's responsibility per FOUNDER_BRIEF.md, TECH_STACK.md's
already-decided "WebSocket carries unprompted push notifications from Frank
to the UI") ride the same WebSocket as chat text, via a "\n[notify]" sentinel
— same pattern as the existing "\n[done]" end-of-turn marker, not a new
message envelope. Triggered by the one thing Frank already does
deterministically (save_memory firing), not a new "should Frank decide to
notify" policy — that's a bigger, fuzzier design question for later.

Still NOT here: semantic/vector search over memory, the full per-device-
keypair auth, SMAppService packaging.
"""

import asyncio
import base64
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.alpha_mode_agent import (
    ALPHA_MODE_AGENT_TOOL_NAMES,
    ALPHA_MODE_AGENT_TOOLS,
    execute_alpha_mode_agent_tool_call,
)
from app.alpha_mode_db import init_alpha_mode_db
from app.alpha_mode_tools import ALPHA_MODE_TOOLS, build_alpha_mode_block, execute_alpha_mode_tool_call
from app.auth import get_or_create_token
from app.agents_registry import list_agents
from app.audit_db import init_audit_db, record_tool_call
from app.automations import check_and_fire as check_and_fire_automation
from app.automations_db import init_automations_db, list_runs as list_automation_runs
from app.automations_registry import AUTOMATIONS
from app.communications_agent import (
    COMMUNICATIONS_AGENT_TOOL_NAMES,
    COMMUNICATIONS_AGENT_TOOLS,
    execute_communications_agent_tool_call,
)
from app.creative_director_agent import (
    CREATIVE_DIRECTOR_AGENT_TOOL_NAMES,
    CREATIVE_DIRECTOR_AGENT_TOOLS,
    execute_creative_director_agent_tool_call,
)
from app.design_agent import DESIGN_AGENT_TOOL_NAMES, DESIGN_AGENT_TOOLS, execute_design_agent_tool_call
from app.memory_agent import MEMORY_AGENT_TOOL_NAMES, MEMORY_AGENT_TOOLS, execute_memory_agent_tool_call
from app.operations_agent import OPERATIONS_TOOL_NAMES, OPERATIONS_TOOLS, build_operations_block, execute_operations_tool_call
from app.research_agent import RESEARCH_AGENT_TOOL_NAMES, RESEARCH_AGENT_TOOLS, execute_research_agent_tool_call
from app.insights import compute_insights
from app.situation_room import compute_situation_room_alerts
from app.operations_db import init_operations_db, list_open_tasks
from app.db import (
    create_new_conversation,
    forget_memory_by_id,
    get_active_conversation_id,
    get_focus_objective,
    init_db,
    list_conversations,
    load_history,
    load_memory_records,
    log_activity,
    save_message,
    set_active_conversation,
)
from app.memory import FORGET_MEMORY_TOOL, SAVE_MEMORY_TOOL, build_memory_block, execute_tool_call
from app.focus import FOCUS_TOOL_NAMES, FOCUS_TOOLS, execute_focus_tool_call
from app.decision_journal import (
    DECISION_JOURNAL_TOOL_NAMES,
    DECISION_JOURNAL_TOOLS,
    execute_decision_journal_tool_call,
)
from app.memory_graph import MEMORY_GRAPH_TOOL_NAMES, MEMORY_GRAPH_TOOLS, execute_memory_graph_tool_call
from app.shadow_mode import SHADOW_MODE_TOOL_NAMES, SHADOW_MODE_TOOLS, execute_shadow_mode_tool_call
from app.personality import SYSTEM_PROMPT
from app.piper_tts import synthesize_wav_bytes

# Explicit path, not load_dotenv()'s default cwd-search — found directly
# (2026-07-28) while testing the SMAppService packaging shim, which can be
# launched from any working directory: load_dotenv() with no argument
# searches from the process's cwd, not from this file's own location, so it
# silently found no .env and left ANTHROPIC_API_KEY unset. Same class of bug
# as the Swift-side cwd assumptions fixed in ProjectPaths.swift — deriving
# from __file__ instead of cwd is the actual fix, not a workaround.
load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-sonnet-5"
# Real bug found 2026-07-31: 1024 was cutting off longer replies mid-
# generation (confirmed directly -- a multi-phase SOP relayed from the
# Operations Agent got truncated, twice, in real use). Raising the
# ceiling doesn't undo personality.py's brevity instruction for ordinary
# replies -- that's a soft prompt-level default, not a hard token cap --
# it just stops hard-truncating the genuinely longer replies (relaying a
# drafted document, etc.) that need more room.
MAX_TOKENS = 4096
AUTH_TOKEN = get_or_create_token()

# Uploaded chat images land here (2026-08-05) -- filenames only in
# messages.image_path, not the bytes themselves, keeps that column cheap
# regardless of image size. Not synced/backed up anywhere yet, same as
# every other local SQLite data in this project so far.
ATTACHMENTS_DIR = Path(__file__).parent.parent / "data" / "attachments"

# Optional — cloud text-to-speech (see .env.example). Confirmed decision
# (2026-07-29): tried free-tier ElevenLabs first, which turned out to
# block API access to Voice Library voices entirely; then a genuinely
# free local fallback (Piper, app/piper_tts.py); then Joshua decided the
# specific stylized "dark and tough" character voice was worth actually
# paying for. Both paths are kept, not because the free one is a
# placeholder, but because we've already hit two different real
# ElevenLabs failures in one sitting (missing permission, then payment
# required) — /speak below tries ElevenLabs first when configured, and
# falls back to Piper on ANY failure, so Frank never just goes silent.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID")


ALPHA_MODE_TOOL_NAMES = {tool["name"] for tool in ALPHA_MODE_TOOLS}


class SpeakRequest(BaseModel):
    text: str


class ActivityLogRequest(BaseModel):
    app_name: str


def verify_token(token: str) -> None:
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="invalid or missing token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_alpha_mode_db()
    await init_operations_db()
    await init_automations_db()
    await init_audit_db()
    # A single reused httpx client, not one per /speak call — real bug
    # found and fixed 2026-07-30: creating a fresh AsyncClient() per
    # request meant paying a full DNS+TLS handshake to ElevenLabs every
    # single time, confirmed directly (curl timing showed the exact same
    # request taking 4.9s cold vs 1.1s with a warm connection). One
    # long-lived client with connection keep-alive removes that entirely.
    app.state.elevenlabs_client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.elevenlabs_client.aclose()


app = FastAPI(title="P Corp OS Backend", lifespan=lifespan)
# Just the apple-touch-icon for now (mobile.html's "Add to Home Screen"
# support) -- unauthenticated like /mobile itself, since it's a static
# icon with no sensitive content.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health(_: None = Depends(verify_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mobile")
async def mobile() -> Response:
    # Deliberately unauthenticated at the route level -- this is a static
    # page shell with no sensitive content of its own (see mobile.html);
    # it prompts for the real auth token client-side, which is what
    # actually gates the WebSocket/REST calls that matter. Reachable only
    # via this Mac's Tailscale IP (see run()/TAILSCALE_IP) or localhost,
    # never the public internet.
    html = (Path(__file__).parent / "mobile.html").read_text()
    return Response(content=html, media_type="text/html")


@app.get("/memory")
async def memory(_: None = Depends(verify_token)) -> list[dict]:
    # View of what Frank has saved via the save_memory tool, excluding
    # anything forgotten (app/db.py's deleted_at) — the desktop shell's
    # "Frank" section reads this to make memory visible, rather than it
    # only being inspectable by querying SQLite directly.
    return await load_memory_records()


@app.get("/operations/tasks")
async def operations_tasks(_: None = Depends(verify_token)) -> list[dict]:
    # Makes the "Agents" nav section's task list real, rather than only
    # visible to Frank himself via the system-prompt snapshot.
    return await list_open_tasks()


@app.get("/agents")
async def agents_endpoint(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Agents" section's list of specialist cards -- see
    # agents_registry.py's docstring for why this is a small hand-kept
    # list rather than introspecting main.py's tool-use schemas.
    return await list_agents()


@app.get("/automations/rules")
async def automations_rules(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Automations" section's list of configured rules --
    # same hand-kept-registry reasoning as GET /agents.
    return AUTOMATIONS


@app.get("/automations/runs")
async def automations_runs(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Automations" section's real firing history -- makes
    # automations visible when they happen, not something silent.
    return await list_automation_runs()


@app.get("/focus")
async def focus_endpoint(_: None = Depends(verify_token)) -> dict:
    # Backs the War Room's Mission Status card's "Focus: ..." line --
    # see db.py's get_focus_objective docstring for the deliberately
    # minimal scope (just this one line, no on/off mode, no automatic
    # deprioritization).
    return await get_focus_objective()


@app.post("/activity/log")
async def activity_log_endpoint(body: ActivityLogRequest, _: None = Depends(verify_token)) -> dict:
    # Shadow Mode's write path -- called by ActivityTracker.swift whenever
    # the frontmost app changes, not a Frank tool. See shadow_mode.py's
    # docstring for why capture and recall are split this way.
    await log_activity(body.app_name)
    return {"status": "ok"}


@app.get("/insights")
async def insights_endpoint(_: None = Depends(verify_token)) -> list[dict]:
    # Real data behind the right rail's "Frank's Insights" card -- was
    # literal placeholder text before (see app/insights.py's docstring).
    return await compute_insights()


@app.get("/situation-room")
async def situation_room_endpoint(_: None = Depends(verify_token)) -> list[dict]:
    # Backs War Room's escalated alert banner -- see
    # app/situation_room.py's docstring for how this differs from the
    # routine /insights list.
    return await compute_situation_room_alerts()


@app.delete("/memory/{memory_id}")
async def forget_memory(memory_id: int, _: None = Depends(verify_token)) -> dict[str, bool]:
    # Manual forgetting from the UI — same soft-delete Frank's own
    # forget_memory tool uses, just addressed by ID instead of title since
    # the UI already has it.
    forgotten = await forget_memory_by_id(memory_id)
    return {"forgotten": forgotten}


@app.get("/history")
async def history(_: None = Depends(verify_token)) -> list[dict]:
    # The active conversation's transcript — always the most recently
    # created one (app/db.py's get_active_conversation_id). This is what
    # backs the real chat thread built into WarRoomView.
    conversation_id = await get_active_conversation_id()
    return await load_history(conversation_id)


@app.post("/conversations")
async def new_conversation(_: None = Depends(verify_token)) -> dict[str, int]:
    # "New chat" — memory (app/memory.py) still carries continuity forward;
    # this just starts a fresh transcript, and becomes the active one.
    conversation_id = await create_new_conversation()
    return {"conversation_id": conversation_id}


@app.get("/conversations")
async def conversations(q: str | None = None, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the conversation history browser — reopening an older chat
    # needs a way to find it, indefinitely, as history accumulates over
    # time. `q`, when given, searches real message content across each
    # conversation, not just its preview.
    return await list_conversations(query=q)


@app.post("/conversations/{conversation_id}/activate")
async def activate_conversation(conversation_id: int, _: None = Depends(verify_token)) -> dict[str, int]:
    # Reopening an older conversation — makes it active without needing to
    # be the newest row (that's the whole reason app_state exists instead
    # of just "active = newest").
    await set_active_conversation(conversation_id)
    return {"conversation_id": conversation_id}


async def _speak_via_elevenlabs(client: httpx.AsyncClient, text: str) -> bytes:
    """Raises on any failure — caller decides what that means (fall back
    to Piper, in this case). Not swallowing errors here since the caller
    needs to distinguish "ElevenLabs not configured" (skip straight to
    Piper) from "ElevenLabs configured but the call itself failed" (also
    falls back, but worth knowing which happened if this ever needs
    debugging). Takes the shared client (app.state.elevenlabs_client) as a
    parameter rather than opening its own — a fresh connection per call
    was a real, confirmed latency bug (see lifespan's comment)."""
    response = await client.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_turbo_v2_5"},
    )
    response.raise_for_status()
    return response.content


@app.post("/speak")
async def speak(request: SpeakRequest, http_request: Request, _: None = Depends(verify_token)) -> Response:
    # ElevenLabs first (genuinely human, stylized voice — the reason it's
    # worth paying for), Piper as the always-available fallback (free,
    # local, no account to lapse) — see the ELEVENLABS_API_KEY comment
    # above for why both paths are kept rather than picking one. Any
    # ElevenLabs failure (missing permission, quota, payment issue,
    # network) falls through silently from Frank's perspective — he still
    # speaks, just via the fallback voice — logged server-side so it's
    # debuggable without being surfaced as a hard error to the UI.
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        try:
            audio = await _speak_via_elevenlabs(http_request.app.state.elevenlabs_client, request.text)
            return Response(content=audio, media_type="audio/mpeg")
        except Exception as error:
            print(f"[speak] ElevenLabs failed, falling back to Piper: {error}")

    audio = await asyncio.to_thread(synthesize_wav_bytes, request.text)
    return Response(content=audio, media_type="audio/wav")


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    if websocket.query_params.get("token") != AUTH_TOKEN:
        await websocket.send_text("[backend error: invalid or missing auth token]")
        await websocket.close()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        await websocket.send_text(
            "[backend error: ANTHROPIC_API_KEY not set. Copy backend/.env.example "
            "to backend/.env and add a real key.]"
        )
        await websocket.close()
        return

    client = AsyncAnthropic(api_key=api_key)
    # Whichever conversation is active as of connect time — a client that
    # started a new chat right before reconnecting picks up the fresh one.
    conversation_id = await get_active_conversation_id()
    # image_path is dropped here, deliberately -- load_history() includes it
    # for GET /history's benefit (the UI's "📎 image attached" placeholder for
    # an old message), but Claude's own `messages=` list only accepts
    # role/content, and reloading old history should show a past image was
    # attached, not re-send it as real vision context on every reconnect
    # (confirmed decision 2026-08-05 -- see load_history()'s docstring).
    history: list[dict[str, str]] = [
        {"role": row["role"], "content": row["content"]} for row in await load_history(conversation_id)
    ]

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
                user_text = payload.get("text", "")
                image = payload.get("image")
            except json.JSONDecodeError:
                user_text = raw_message
                image = None

            image_path = None
            if image and image.get("data") and image.get("media_type"):
                ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
                extension = "png" if "png" in image["media_type"] else "jpg"
                image_path = f"{uuid.uuid4()}.{extension}"
                (ATTACHMENTS_DIR / image_path).write_bytes(base64.b64decode(image["data"]))
                user_content = [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": image["media_type"], "data": image["data"]},
                    },
                    {"type": "text", "text": user_text},
                ]
            else:
                user_content = user_text

            history.append({"role": "user", "content": user_content})
            await save_message(conversation_id, "user", user_text, image_path=image_path)

            system_prompt = (
                SYSTEM_PROMPT + await build_memory_block() + await build_alpha_mode_block() + await build_operations_block()
            )

            try:
                assistant_reply = await run_claude_turn(
                    client, system_prompt, history, websocket, image=image
                )
            except Exception as error:
                # A client-initiated stop (BackendClient.stopGenerating())
                # closes the socket mid-stream, which is exactly what
                # causes this branch to fire in the first place -- trying
                # to report the error back over an already-closed socket
                # would just raise a second, noisier exception, so that
                # attempt is best-effort only.
                try:
                    await websocket.send_text(f"\n[backend error: {error}]")
                except Exception:
                    pass
                # Don't record a failed/interrupted turn in memory or on
                # disk — keeps conversation state consistent for the next
                # message (or the reconnect stopGenerating() makes).
                history.pop()
                continue

            history.append({"role": "assistant", "content": assistant_reply})
            await save_message(conversation_id, "assistant", assistant_reply)
            await websocket.send_text("\n[done]")
    except WebSocketDisconnect:
        pass


async def run_claude_turn(
    client: AsyncAnthropic,
    system_prompt: str,
    history: list,
    websocket: WebSocket,
    image: dict | None = None,
) -> str:
    """Runs one user turn to completion, including any save_memory round
    trips — Frank may call the tool, see the result, then keep talking. Text
    streams to the websocket as it arrives, across every round. `history` is
    mutated in place with any intermediate tool_use/tool_result turns (valid
    context for the rest of this live connection); the caller is responsible
    for appending the single final assistant text turn once this returns,
    since that's the flat, plain-text form persisted to SQLite.

    image (2026-08-10, Design Critic) is this turn's raw attachment, if
    any -- Frank already sees it directly (it's part of `history`'s own
    content blocks), but a delegated specialist's own isolated Claude
    call doesn't share that history, so if Frank delegates to a
    vision-aware agent (currently just Design Agent), the same image is
    forwarded to it directly. Only ever the image from *this* turn, not
    an earlier one in the same conversation -- same "don't re-inject an
    old image" reasoning as reopening a past conversation."""
    assistant_text = ""
    while True:
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=history,
            tools=[
                SAVE_MEMORY_TOOL,
                FORGET_MEMORY_TOOL,
                *FOCUS_TOOLS,
                *DECISION_JOURNAL_TOOLS,
                *MEMORY_GRAPH_TOOLS,
                *SHADOW_MODE_TOOLS,
                *ALPHA_MODE_TOOLS,
                *OPERATIONS_TOOLS,
                *ALPHA_MODE_AGENT_TOOLS,
                *DESIGN_AGENT_TOOLS,
                *CREATIVE_DIRECTOR_AGENT_TOOLS,
                *COMMUNICATIONS_AGENT_TOOLS,
                *MEMORY_AGENT_TOOLS,
                *RESEARCH_AGENT_TOOLS,
            ],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
            final_message = await stream.get_final_message()

        if final_message.stop_reason != "tool_use":
            return assistant_text

        history.append({"role": "assistant", "content": final_message.content})
        tool_results = []
        for block in final_message.content:
            if block.type != "tool_use":
                continue
            if block.name in FOCUS_TOOL_NAMES:
                result = await execute_focus_tool_call(block.name, block.input)
            elif block.name in DECISION_JOURNAL_TOOL_NAMES:
                result = await execute_decision_journal_tool_call(block.name, block.input)
            elif block.name in MEMORY_GRAPH_TOOL_NAMES:
                result = await execute_memory_graph_tool_call(block.name, block.input)
            elif block.name in SHADOW_MODE_TOOL_NAMES:
                result = await execute_shadow_mode_tool_call(block.name, block.input)
            elif block.name in ALPHA_MODE_TOOL_NAMES:
                result = await execute_alpha_mode_tool_call(block.name, block.input)
            elif block.name in OPERATIONS_TOOL_NAMES:
                result = await execute_operations_tool_call(block.name, block.input, client, websocket)
                if block.name == "consult_operations_agent":
                    # This was already streamed live to the websocket
                    # inside execute_operations_tool_call -- append it to
                    # the persisted transcript too, or reopening this
                    # conversation later would be missing exactly what
                    # was shown on screen, keeping only Frank's own
                    # follow-up remark.
                    assistant_text += result
            elif block.name in ALPHA_MODE_AGENT_TOOL_NAMES:
                result = await execute_alpha_mode_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in DESIGN_AGENT_TOOL_NAMES:
                result = await execute_design_agent_tool_call(block.name, block.input, client, websocket, image=image)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in CREATIVE_DIRECTOR_AGENT_TOOL_NAMES:
                result = await execute_creative_director_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in COMMUNICATIONS_AGENT_TOOL_NAMES:
                result = await execute_communications_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in MEMORY_AGENT_TOOL_NAMES:
                result = await execute_memory_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in RESEARCH_AGENT_TOOL_NAMES:
                result = await execute_research_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            else:
                result = await execute_tool_call(block.name, block.input)
            # Real audit trail (2026-08-10, SECURITY.md's flagged gap) --
            # every tool call, regardless of which branch above produced
            # it, logged at this one point so no individual agent module
            # needed touching. See audit_db.py's own docstring for why
            # there's no "who" column.
            await record_tool_call(block.name, block.input, result)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )
            if block.name == "save_memory":
                notification = json.dumps(
                    {
                        "title": "Frank remembered something",
                        "body": block.input.get("title", "New memory saved"),
                    }
                )
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "forget_memory" and result.startswith("Forgot:"):
                notification = json.dumps(
                    {"title": "Frank forgot something", "body": result.removeprefix("Forgot: ")}
                )
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "set_focus_objective":
                notification = json.dumps({"title": "Focus updated", "body": block.input.get("objective", "")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "log_decision":
                notification = json.dumps({"title": "Decision logged", "body": block.input.get("decision", "")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "link_records" and result.startswith("Linked:"):
                notification = json.dumps({"title": "Memories linked", "body": result.removeprefix("Linked: ")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name in ALPHA_MODE_TOOL_NAMES:
                notification = json.dumps({"title": "Alpha Mode Media updated", "body": result})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name in ("add_task", "update_task_status", "delete_task"):
                notification = json.dumps({"title": "Task updated", "body": result})
                await websocket.send_text(f"\n[notify]{notification}")

            automation_notification = await check_and_fire_automation(block.name, block.input, client)
            if automation_notification:
                # Deliberately a separate notification, not folded into
                # the block above -- this is a rule firing as a real
                # side effect of the tool call, not the tool call's own
                # result, and the two shouldn't be conflated in the UI.
                await websocket.send_text(f"\n[notify]{json.dumps(automation_notification)}")
        history.append({"role": "user", "content": tool_results})


def run() -> None:
    import uvicorn

    # 127.0.0.1 always, regardless of Tailscale — the desktop app must keep
    # working with zero dependency on Tailscale being installed, running,
    # or configured. Confirmed decision (2026-07-31): mobile access adds a
    # SECOND listener on this Mac's Tailscale-assigned IP (not 0.0.0.0,
    # which SECURITY.md already ruled out — that would also expose this to
    # the regular Wi-Fi/Ethernet interface, reachable by anyone else on the
    # same network). TAILSCALE_IP is optional in .env — if unset, this
    # behaves exactly as before, single listener, no behavior change.
    tailscale_ip = os.environ.get("TAILSCALE_IP")
    if not tailscale_ip:
        uvicorn.run(app, host="127.0.0.1", port=8731)
        return

    asyncio.run(_run_dual(tailscale_ip))


async def _run_dual(tailscale_ip: str) -> None:
    import uvicorn

    local_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8731))
    tailscale_server = uvicorn.Server(uvicorn.Config(app, host=tailscale_ip, port=8731))
    await asyncio.gather(local_server.serve(), tailscale_server.serve())


if __name__ == "__main__":
    run()
