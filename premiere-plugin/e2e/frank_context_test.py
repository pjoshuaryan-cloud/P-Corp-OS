"""Frank's background information kept ready (2026-11-14): a message uses the ready copy instead of building it (~30 s on the
Mac); it's refreshed on a timer and straight after Frank uses a tool; the first message after startup waits for the first
build instead of starting a second one; a failed refresh keeps the last good copy; each refresh hands its connection back.
Made-up builders and connections only: no database, no Claude call.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python frank_context_test.py"""
import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.frank_context import FrankContext  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


state = {"version": 1, "builds": 0, "fail": False, "delay": 0.05, "open": 0, "returned": 0, "seen_conns": []}


async def memory(conn):
    state["builds"] += 1
    state["seen_conns"].append(conn)
    await asyncio.sleep(state["delay"])
    if state["fail"]:
        raise RuntimeError("database down")
    return f"[memory v{state['version']}]"


async def finance(conn):
    return "[finance]"


@asynccontextmanager
async def connect():
    state["open"] += 1
    try:
        yield "pool-conn"
    finally:
        state["returned"] += 1


async def main():
    ctx = FrankContext([memory, finance], refresh_seconds=0.3, max_age_seconds=5)
    runner = asyncio.create_task(ctx.run(connect))
    await asyncio.sleep(0)
    text = await ctx.get("message-conn")
    check("the first message after startup waits for the first build (no second build)", text == "[memory v1][finance]" and state["builds"] == 1, (text, state["builds"]))
    check("sections come in order", text.index("memory") < text.index("finance"))
    before = state["builds"]
    t = time.monotonic()
    for _ in range(5):
        await ctx.get("message-conn")
    check("later messages use the ready copy: no build, no wait", state["builds"] == before and time.monotonic() - t < 0.02, state["builds"])
    check("background builds use a borrowed pool connection, not the message's", all(c == "pool-conn" for c in state["seen_conns"]), state["seen_conns"])

    state["version"] = 2
    ctx.changed()
    await asyncio.sleep(0.15)
    check("after Frank uses a tool, the copy is refreshed straight away", (await ctx.get("message-conn")) == "[memory v2][finance]")

    state["version"] = 3
    await asyncio.sleep(0.45)
    check("and on the timer", (await ctx.get("message-conn")) == "[memory v3][finance]")

    state["fail"] = True
    ctx.changed()
    await asyncio.sleep(0.15)
    check("a failed refresh keeps the last good copy", (await ctx.get("message-conn")) == "[memory v3][finance]")
    state["fail"] = False

    state["delay"] = 0.2
    builds = state["builds"]
    ctx.changed(); ctx.changed(); ctx.changed()
    await asyncio.sleep(0.6)
    check("several changes during a refresh run at most one more refresh after it", state["builds"] - builds <= 3, state["builds"] - builds)
    state["delay"] = 0.05

    runner.cancel()
    await asyncio.sleep(0.3)
    check("every borrowed connection was handed back", state["open"] == state["returned"], (state["open"], state["returned"]))

    old = FrankContext([memory], refresh_seconds=100, max_age_seconds=0.1)
    old.text, old.built_at = "[ancient]", time.monotonic() - 1
    state["version"] = 9
    check("a copy far too old isn't trusted: the message builds its own on its own connection", (await old.get("message-conn")) == "[memory v9]" and state["seen_conns"][-1] == "message-conn")

    none = FrankContext([memory], refresh_seconds=100)
    check("with no refresher (scripts), a message builds it as before", (await none.get(None)) == "[memory v9]")

asyncio.run(main())
print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
