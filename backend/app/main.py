"""
First real slice of the P Corp OS backend — proves the IPC contract decided
in TECH_STACK.md actually works (local HTTP + WebSocket via FastAPI, bound
to 127.0.0.1), before any real intelligence exists.

Deliberately NOT here yet, per explicit scoping: Claude Agent SDK / real
Frank reasoning, SQLite/memory, the full per-device-keypair auth, SMAppService
packaging. The /ws endpoint echoes messages back in streamed chunks — real
streaming mechanics, canned content — so the plumbing (connection handling,
chunked delivery, error cases) can be proven independently of an LLM.
"""

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="P Corp OS Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_echo(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            # Streams the echo back word-by-word with a small delay between
            # chunks, simulating token-by-token delivery — proves the
            # streaming mechanism itself, not just request/response.
            words = message.split(" ")
            for index, word in enumerate(words):
                prefix = "" if index == 0 else " "
                await websocket.send_text(f"{prefix}{word}")
                await asyncio.sleep(0.05)
            await websocket.send_text("\n[done]")
    except WebSocketDisconnect:
        pass


def run() -> None:
    import uvicorn

    # 127.0.0.1 only, per TECH_STACK.md — never bind to 0.0.0.0 here.
    uvicorn.run(app, host="127.0.0.1", port=8731)


if __name__ == "__main__":
    run()
