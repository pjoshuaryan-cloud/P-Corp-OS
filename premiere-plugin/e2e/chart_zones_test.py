"""The simplified Trading tab (2026-11-15): screenshots in, buy and sell areas out. Checks the broker context (Black Crown
Markets, MT5, rand) reaches every Trade Intelligence prompt, the answer layout is asked for, and the route's first turn and
follow-ups. The model call is replaced: no Claude call, nothing written.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python chart_zones_test.py"""
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, trade_intelligence_agent as ti  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


check("every Trade Intelligence prompt knows the broker, the platform and the currency",
      all("Black Crown Markets" in p and "MetaTrader 5" in p and "rand" in p
          for p in (ti.TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT, ti.TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, ti.CHART_ZONES_SYSTEM_PROMPT)))
check("the Trading tab asks for the same short layout every time",
      all(label in ti.CHART_ZONES_SYSTEM_PROMPT for label in ("**Lean:**", "**Buy area:**", "**Sell area:**", "**Wrong if:**", "**Targets:**", "**Confidence:**")))
check("it is told not to invent prices it can't read", "isn't legible" in ti.CHART_ZONES_SYSTEM_PROMPT)
check("no proposal block on the simple tab", "trade-suggestion" not in ti.CHART_ZONES_SYSTEM_PROMPT)

calls = []


async def fake_turn(client, system_prompt, history, tools=None, max_tokens=8192):
    calls.append((system_prompt, [dict(m) if isinstance(m, dict) else m for m in history]))
    reply = "**Lean:** bullish -- higher lows.\n**Buy area:** 18,200-18,250"
    history.append({"role": "assistant", "content": reply})
    return reply


real_turn, real_ti_turn, real_token, real_key = main.run_conversational_turn, ti.run_conversational_turn, main.AUTH_TOKEN, os.environ.get("ANTHROPIC_API_KEY")
png = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
try:
    main.run_conversational_turn = ti.run_conversational_turn = fake_turn
    main.AUTH_TOKEN = "made-up"
    os.environ["ANTHROPIC_API_KEY"] = "made-up-key-never-used"
    web = TestClient(main.app)
    r = web.post("/trade-intelligence/chart-zones", params={"token": "made-up"},
                 json={"images": [{"media_type": "image/png", "filename": "a.png", "data": png}] * 2, "note": "thinking of a long"})
    body = r.json()
    check("screenshots in, an answer and the conversation back", r.status_code == 200 and body["reply"].startswith("**Lean:**") and len(body["history"]) == 2, r.text)
    first = calls[0][1][0]["content"]
    check("both screenshots and his note go to the model", sum(1 for b in first if b.get("type") == "image") == 2 and "thinking of a long" in first[-1]["text"], first[-1])
    check("with the Trading tab's own instructions", calls[0][0] == ti.CHART_ZONES_SYSTEM_PROMPT)
    r2 = web.post("/trade-intelligence/chart-zones", params={"token": "made-up"}, json={"history": body["history"], "message": "what about the 1-hour?"})
    check("a follow-up continues the same conversation", r2.status_code == 200 and calls[1][1][-1]["content"] == "what about the 1-hour?" and calls[1][0] == ti.CHART_ZONES_SYSTEM_PROMPT, r2.text)
    check("nothing dropped in: a clear message", (e := web.post("/trade-intelligence/chart-zones", params={"token": "made-up"}, json={})).status_code == 400 and "screenshot" in e.json()["detail"])
    check("more than 4: a clear message", web.post("/trade-intelligence/chart-zones", params={"token": "made-up"},
                                                    json={"images": [{"media_type": "image/png", "filename": "a.png", "data": png}] * 5}).status_code == 400)
    check("a follow-up needs a question", web.post("/trade-intelligence/chart-zones", params={"token": "made-up"}, json={"history": body["history"]}).status_code == 400)
    check("needs the token", web.post("/trade-intelligence/chart-zones", json={}).status_code in (403, 422))
finally:
    main.run_conversational_turn, ti.run_conversational_turn, main.AUTH_TOKEN = real_turn, real_ti_turn, real_token
    if real_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    else:
        os.environ["ANTHROPIC_API_KEY"] = real_key

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
