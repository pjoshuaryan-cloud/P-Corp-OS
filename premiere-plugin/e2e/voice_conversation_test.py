"""Conversational voice, backend half (2026-11-14): a spoken turn tells Frank to talk like he's on a call; a typed one doesn't;
and the "has he finished?" check stays off until Josh turns it on, and never raises. Fake Claude client and a made-up token:
no Claude call, no ElevenLabs call, and nothing is written (the chat socket's database calls are replaced for the test).
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python voice_conversation_test.py"""
import asyncio
import os
import sys
import types
from pathlib import Path

os.environ["DATA_BACKEND"] = "sqlite"
os.environ.pop("VOICE_TURN_CHECK_ENABLED", None)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, voice_conversation as vc  # noqa: E402

os.environ.pop("VOICE_TURN_CHECK_ENABLED", None)   # main loads backend/.env, which turns the check on (2026-11-14): start from off

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


# ---- the chat socket: a spoken turn gets the voice note, a typed one doesn't
seen_prompts: list[str] = []
saved: list[tuple] = []


async def fake_turn(client, system_prompt, history, websocket, conversation_id, postgres_conn, attachments=None):
    seen_prompts.append(system_prompt)
    return "Sure.", []


async def fake_save(*args, **kwargs):
    saved.append(args)


async def empty_block(*args, **kwargs):
    return ""


async def no_history(*args, **kwargs):
    return []


async def conversation_one(*args, **kwargs):
    return 1


patches = {
    "run_claude_turn": fake_turn, "save_message": fake_save, "load_history": no_history, "get_active_conversation_id": conversation_one,
}
originals = {name: getattr(main, name) for name in patches}
# Frank's background information comes from the ready copy (app/frank_context.py): give it made-up builders, so nothing is read.
real_builders, real_text = main.FRANK_CONTEXT.builders, main.FRANK_CONTEXT.text
main.FRANK_CONTEXT.builders, main.FRANK_CONTEXT.text = [empty_block], None
real_token, real_key = main.AUTH_TOKEN, os.environ.get("ANTHROPIC_API_KEY")
try:
    for name, fake in patches.items():
        setattr(main, name, fake)
    main.AUTH_TOKEN = "made-up"
    os.environ["ANTHROPIC_API_KEY"] = "made-up-key-never-used"
    web = TestClient(main.app)
    with web.websocket_connect("/ws?token=made-up") as ws:
        for payload in ({"text": "what's on today", "voice": True}, {"text": "what's on today"}, {"text": "hi", "voice": "yes"}):
            ws.send_json(payload)
            while True:
                if "[done]" in ws.receive_text():
                    break
    check("a spoken turn tells Frank to talk like he's on a call", len(seen_prompts) == 3 and "## This turn was spoken" in seen_prompts[0], len(seen_prompts))
    check("a typed turn doesn't", "This turn was spoken" not in seen_prompts[1])
    check("only a real true counts as spoken", "This turn was spoken" not in seen_prompts[2])
    check("the note is added at the end, the rest of Frank's instructions unchanged", seen_prompts[0] == seen_prompts[1] + vc.VOICE_STYLE_NOTE)
    check("what Josh said is saved as he said it (no note in his message)", all("spoken" not in str(a) for a in saved), saved)
finally:
    for name, original in originals.items():
        setattr(main, name, original)
    main.FRANK_CONTEXT.builders, main.FRANK_CONTEXT.text = real_builders, real_text
    main.AUTH_TOKEN = real_token
    if real_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    else:
        os.environ["ANTHROPIC_API_KEY"] = real_key

# ---- the "has he finished?" check
class FakeMessages:
    def __init__(self, reply="FINISHED", delay=0.0, error=None, stop_reason="end_turn"):
        self.reply, self.delay, self.error, self.stop_reason, self.calls = reply, delay, error, stop_reason, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return types.SimpleNamespace(stop_reason=self.stop_reason, content=[types.SimpleNamespace(type="text", text=self.reply)])


def fake_client(**kw):
    return types.SimpleNamespace(messages=FakeMessages(**kw))


off = fake_client()
check("off by default: no model call, no verdict", asyncio.run(vc.turn_check("book the venue", None, off)) == {"enabled": False, "verdict": None} and not off.messages.calls)
os.environ["VOICE_TURN_CHECK_ENABLED"] = "1"
try:
    c = fake_client(reply="FINISHED")
    check("on: 'FINISHED' -> finished", asyncio.run(vc.turn_check("book the venue for Friday", "What do you need?", c))["verdict"] == "finished")
    sent = c.messages.calls[0]
    check("it asks Haiku 5.5, thinking off, low effort, tiny answer", sent["model"] == "claude-haiku-5-5" and sent["thinking"] == {"type": "disabled"}
          and sent["output_config"] == {"effort": "low"} and sent["max_tokens"] <= 8, sent)
    check("it sees Frank's last line for context", "What do you need?" in sent["messages"][0]["content"])
    check("'MORE' -> unfinished", asyncio.run(vc.turn_check("and the other thing is", None, fake_client(reply="MORE")))["verdict"] == "unfinished")
    check("an odd answer -> no verdict", asyncio.run(vc.turn_check("hmm", None, fake_client(reply="Maybe?")))["verdict"] is None)
    check("an error -> no verdict, no exception", asyncio.run(vc.turn_check("hmm", None, fake_client(error=RuntimeError("boom"))))["verdict"] is None)
    check("a refusal -> no verdict", asyncio.run(vc.turn_check("hmm", None, fake_client(stop_reason="refusal")))["verdict"] is None)
    vc.TURN_CHECK_TIMEOUT_SECONDS, real_timeout = 0.1, vc.TURN_CHECK_TIMEOUT_SECONDS
    check("too slow -> no verdict (the app decides without it)", asyncio.run(vc.turn_check("hmm", None, fake_client(delay=1.0)))["verdict"] is None)
    vc.TURN_CHECK_TIMEOUT_SECONDS = real_timeout
    long = fake_client()
    asyncio.run(vc.turn_check("word " * 2000, None, long))
    check("a very long ramble is cut to its last part", len(long.messages.calls[0]["messages"][0]["content"]) < 1600)
    check("nothing said -> no call", asyncio.run(vc.turn_check("   ", None, (e := fake_client())))["verdict"] is None and not e.messages.calls)
finally:
    os.environ.pop("VOICE_TURN_CHECK_ENABLED", None)

real_token = main.AUTH_TOKEN
main.AUTH_TOKEN = "made-up"
try:
    web = TestClient(main.app)
    r = web.post("/voice/turn-check", params={"token": "made-up"}, json={"transcript": "book the venue"})
    check("the route answers (off -> enabled false)", r.status_code == 200 and r.json() == {"enabled": False, "verdict": None}, r.text)
    check("the route needs the token", web.post("/voice/turn-check", json={"transcript": "x"}).status_code in (403, 422))
finally:
    main.AUTH_TOKEN = real_token

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
