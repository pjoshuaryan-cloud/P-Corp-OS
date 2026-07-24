"""
P Corp OS backend. Proves the IPC contract decided in TECH_STACK.md (local
HTTP + WebSocket via FastAPI, bound to 127.0.0.1) and carries real Claude
reasoning through it — via the plain `anthropic` package, not the full
Claude Agent SDK.

That's a deliberate, confirmed scoping decision: the Agent SDK turned out to
require installing the actual Claude Code CLI and brings full tool-use
capabilities (file access, bash execution) with it. SECURITY.md's agent-
sandboxing/permission model doesn't exist yet, so giving Frank real tool-use
before that's designed would be running ahead of an unresolved decision, not
just a technical step. This uses real conversational intelligence only —
text in, real Claude reasoning out, real streaming — with tool-use deferred
until a permission model is actually built.

Conversation history now persists in SQLite (app/db.py) — a single, ever-
continuing conversation, not multiple threads (confirmed decision: "there is
only ever one Frank"). Still NOT here: typed memory records/semantic search,
the full per-device-keypair auth, SMAppService packaging.
"""

import os
from contextlib import asynccontextmanager

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.db import init_db, load_history, save_message
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

            assistant_reply = ""
            try:
                async with client.messages.stream(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=history,
                ) as stream:
                    async for text in stream.text_stream:
                        assistant_reply += text
                        await websocket.send_text(text)
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


def run() -> None:
    import uvicorn

    # 127.0.0.1 only, per TECH_STACK.md — never bind to 0.0.0.0 here.
    uvicorn.run(app, host="127.0.0.1", port=8731)


if __name__ == "__main__":
    run()
