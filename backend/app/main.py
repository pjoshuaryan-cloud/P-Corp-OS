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

Frank does have exactly one tool (app/memory.py's `save_memory`) via the
plain SDK's tool-use/function-calling — a different, much smaller risk
category than the deferred Agent SDK: one hardcoded action, no file or shell
access, confirmed with Joshua specifically (2026-07-24) as distinct from the
general tool-use deferral above.

Conversation history persists in SQLite (app/db.py) — a single, ever-
continuing conversation, not multiple threads (confirmed decision: "there is
only ever one Frank"). Typed memory records (app/db.py, app/memory.py) now
persist too, separate from raw conversation history. Still NOT here:
semantic/vector search over memory, the full per-device-keypair auth,
SMAppService packaging.
"""

import os
from contextlib import asynccontextmanager

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.db import init_db, load_history, load_memory_records, save_message
from app.memory import SAVE_MEMORY_TOOL, build_memory_block, execute_tool_call
from app.personality import SYSTEM_PROMPT

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="P Corp OS Backend", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/memory")
async def memory() -> list[dict]:
    # Read-only view of what Frank has saved via the save_memory tool — the
    # desktop shell's "Frank" section reads this to make memory visible,
    # rather than it only being inspectable by querying SQLite directly.
    return await load_memory_records()


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        await websocket.send_text(
            "[backend error: ANTHROPIC_API_KEY not set. Copy backend/.env.example "
            "to backend/.env and add a real key.]"
        )
        await websocket.close()
        return

    client = AsyncAnthropic(api_key=api_key)
    # The one continuing conversation, loaded from disk — a fresh connection
    # (e.g. relaunching the desktop app) picks up where it left off, rather
    # than starting over, matching "there is only ever one Frank."
    history: list[dict[str, str]] = await load_history()

    try:
        while True:
            user_message = await websocket.receive_text()
            history.append({"role": "user", "content": user_message})
            await save_message("user", user_message)

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
            await save_message("assistant", assistant_reply)
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
            tools=[SAVE_MEMORY_TOOL],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
            final_message = await stream.get_final_message()

        if final_message.stop_reason != "tool_use":
            return assistant_text

        history.append({"role": "assistant", "content": final_message.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": await execute_tool_call(block.name, block.input),
            }
            for block in final_message.content
            if block.type == "tool_use"
        ]
        history.append({"role": "user", "content": tool_results})


def run() -> None:
    import uvicorn

    # 127.0.0.1 only, per TECH_STACK.md — never bind to 0.0.0.0 here.
    uvicorn.run(app, host="127.0.0.1", port=8731)


if __name__ == "__main__":
    run()
