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

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from app.auth import get_or_create_token
from app.db import (
    create_new_conversation,
    forget_memory_by_id,
    get_active_conversation_id,
    init_db,
    list_conversations,
    load_history,
    load_memory_records,
    save_message,
    set_active_conversation,
)
from app.memory import FORGET_MEMORY_TOOL, SAVE_MEMORY_TOOL, build_memory_block, execute_tool_call
from app.personality import SYSTEM_PROMPT

# Explicit path, not load_dotenv()'s default cwd-search — found directly
# (2026-07-28) while testing the SMAppService packaging shim, which can be
# launched from any working directory: load_dotenv() with no argument
# searches from the process's cwd, not from this file's own location, so it
# silently found no .env and left ANTHROPIC_API_KEY unset. Same class of bug
# as the Swift-side cwd assumptions fixed in ProjectPaths.swift — deriving
# from __file__ instead of cwd is the actual fix, not a workaround.
load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
AUTH_TOKEN = get_or_create_token()


def verify_token(token: str) -> None:
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="invalid or missing token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="P Corp OS Backend", lifespan=lifespan)


@app.get("/health")
async def health(_: None = Depends(verify_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/memory")
async def memory(_: None = Depends(verify_token)) -> list[dict]:
    # View of what Frank has saved via the save_memory tool, excluding
    # anything forgotten (app/db.py's deleted_at) — the desktop shell's
    # "Frank" section reads this to make memory visible, rather than it
    # only being inspectable by querying SQLite directly.
    return await load_memory_records()


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
async def conversations(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the conversation switcher — reopening an older chat needs a way
    # to find it. Each entry includes a preview (first message) and count
    # so the list is actually recognizable, not just bare IDs.
    return await list_conversations()


@app.post("/conversations/{conversation_id}/activate")
async def activate_conversation(conversation_id: int, _: None = Depends(verify_token)) -> dict[str, int]:
    # Reopening an older conversation — makes it active without needing to
    # be the newest row (that's the whole reason app_state exists instead
    # of just "active = newest").
    await set_active_conversation(conversation_id)
    return {"conversation_id": conversation_id}


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
    history: list[dict[str, str]] = await load_history(conversation_id)

    try:
        while True:
            user_message = await websocket.receive_text()
            history.append({"role": "user", "content": user_message})
            await save_message(conversation_id, "user", user_message)

            system_prompt = SYSTEM_PROMPT + await build_memory_block()

            try:
                assistant_reply = await run_claude_turn(
                    client, system_prompt, history, websocket
                )
            except Exception as error:
                await websocket.send_text(f"\n[backend error: {error}]")
                # Don't record a failed turn in memory or on disk — keeps
                # conversation state consistent for the next message.
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
) -> str:
    """Runs one user turn to completion, including any save_memory round
    trips — Frank may call the tool, see the result, then keep talking. Text
    streams to the websocket as it arrives, across every round. `history` is
    mutated in place with any intermediate tool_use/tool_result turns (valid
    context for the rest of this live connection); the caller is responsible
    for appending the single final assistant text turn once this returns,
    since that's the flat, plain-text form persisted to SQLite."""
    assistant_text = ""
    while True:
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=history,
            tools=[SAVE_MEMORY_TOOL, FORGET_MEMORY_TOOL],
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
            result = await execute_tool_call(block.name, block.input)
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
        history.append({"role": "user", "content": tool_results})


def run() -> None:
    import uvicorn

    # 127.0.0.1 only, per TECH_STACK.md — never bind to 0.0.0.0 here.
    uvicorn.run(app, host="127.0.0.1", port=8731)


if __name__ == "__main__":
    run()
