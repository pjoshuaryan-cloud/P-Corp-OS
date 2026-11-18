"""Tests for the phone relay of Describe an edit (backend/app/post_chat_relay.py and main._edit_chat_relay_pass; reel autopilot 6b). A temp SQLite file stands in for
the cloud database (the same SQL runs on both), and the Mac's understand / start-run / run-state are fakes: no Claude call, no cloud, no plan."""
import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from fastapi import HTTPException
from app import main, post_chat_edit, post_chat_relay as relay

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

CARD = {"id": "c1", "ready": True, "usd_cap": 1.0, "usd_total": 0.07, "steps": [{"step": "plan", "what": "Plan", "usd": 0.0}]}

async def scenario():
    out = await relay.latest(None)
    check("before anything is sent there are no tables, no request, and the Mac counts as offline", out == {"request": None, "mac_online": False, "mac_seen_at": None}, out)
    for bad in ("   ", "x" * 501):
        try:
            await relay.submit(bad); ok = False
        except ValueError:
            ok = True
        check(f"an empty or too-long sentence is refused ({len(bad)} chars)", ok)
    r1 = await relay.submit("Rabit Haus recap of the JD shoot")
    check("a sentence is stored as new (the tables are made on first use)", r1["status"] == "new" and r1["text"] == "Rabit Haus recap of the JD shoot")
    r2 = await relay.submit("actually 30 seconds")
    check("a newer sentence replaces one still waiting", (await relay._get(None, r1["id"]))["status"] == "replaced" and r2["status"] == "new")
    check("the Mac counts as offline until it beats", (await relay.latest(None))["mac_online"] is False)

    # the Mac's pass, with fakes for what it calls
    calls = {"understand": [], "start": []}
    async def fake_understand(text):
        calls["understand"].append(text)
        if "mystery" in text:
            return {"card": None, "message": "I couldn't tell which shoot."}
        return {"card": dict(CARD), "message": None}
    async def fake_start(card_id):
        calls["start"].append(card_id)
        if card_id == "gone":
            raise HTTPException(status_code=404, detail="That card has expired.")
        return {"run": {"state": "running"}}
    run = {"state": "running", "steps": [], "spent_usd": 0.0, "message": None, "result": None}
    real = (main._understand_edit_text, main._start_edit_chat_run, post_chat_edit.run_state)
    main._understand_edit_text, main._start_edit_chat_run, post_chat_edit.run_state = fake_understand, fake_start, (lambda: dict(run))
    try:
        state = {"running_id": None}
        await main._edit_chat_relay_pass(None, state)
        latest = await relay.latest(None)
        req = latest["request"]
        check("the Mac beats (the phone sees it online) and understands the newest sentence only", latest["mac_online"] and calls["understand"] == ["actually 30 seconds"])
        check("the card is written back for the phone, status understood", req["status"] == "understood" and req["card"]["id"] == "c1", req)
        try:
            await relay.cancel(9999); ok = False
        except LookupError:
            ok = True
        check("cancel of a request that isn't there is a LookupError", ok)
        gone = await relay.press_go(req["id"])
        check("Go on the phone marks it go", gone["status"] == "go")
        try:
            await relay.press_go(req["id"]); ok = False
        except ValueError:
            ok = True
        check("pressing Go twice is refused", ok)
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        check("the Mac starts that card's run and follows it", calls["start"] == ["c1"] and req["status"] == "running" and state["running_id"] == req["id"], req)
        try:
            await relay.cancel(req["id"]); ok = False
        except ValueError as e:
            ok = "running on the Mac" in str(e)
        check("a running edit can't be cancelled from the phone, and says why", ok)
        run.update(state="done", message="Planned. Spent $0.070.", result={"shots": 48})
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        check("when the run ends, its result and message reach the phone", req["status"] == "done" and req["run"]["result"] == {"shots": 48} and "Planned" in req["message"]
              and state["running_id"] is None, req)

        r3 = await relay.submit("mystery thing")
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        check("a sentence the Mac can't place comes back unclear with its message", req["status"] == "unclear" and "which shoot" in req["message"])
        try:
            await relay.press_go(req["id"]); ok = False
        except ValueError:
            ok = True
        check("Go on an unclear request is refused", ok)

        r4 = await relay.submit("Rabit Haus recap")
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        await relay.update(req["id"], None, card=dict(CARD, id="gone"))
        await relay.press_go(req["id"])
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        check("a card the Mac no longer holds fails with a plain message, nothing runs", req["status"] == "failed" and "Describe it again" in req["message"], req)

        r5 = await relay.submit("Rabit Haus recap")
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        await relay.update(req["id"], None, card=dict(CARD, ready=False))
        try:
            await relay.press_go(req["id"]); ok = False
        except ValueError:
            ok = True
        check("Go on a card that isn't ready (over its cap) is refused", ok)
        c = await relay.cancel(req["id"])
        check("a waiting card can be cancelled", c["status"] == "cancelled")

        r6 = await relay.submit("old one")
        await relay._run(None, f"UPDATE {relay._table(None, 'requests')} SET created_at = ? WHERE id = ?", (relay._ago(60), r6["id"]))
        await relay.expire_stale(None)
        check("a sentence the Mac didn't pick up in 15 minutes expires with a message", (await relay._get(None, r6["id"]))["status"] == "expired")
        r7 = await relay.submit("Rabit Haus recap")
        await main._edit_chat_relay_pass(None, state)
        req = (await relay.latest(None))["request"]
        await relay._run(None, f"UPDATE {relay._table(None, 'requests')} SET updated_at = ? WHERE id = ?", (relay._ago(45), req["id"]))
        try:
            await relay.press_go(req["id"]); ok = False
        except ValueError as e:
            ok = "half an hour" in str(e)
        check("Go on a card older than half an hour is refused", ok)
        await relay._run(None, f"UPDATE {relay._table(None, 'worker')} SET seen_at = ? WHERE id = 1", (relay._ago(5),))
        check("no beat for a while -> the phone sees the Mac as offline", (await relay.latest(None))["mac_online"] is False)
    finally:
        main._understand_edit_text, main._start_edit_chat_run, post_chat_edit.run_state = real

with tempfile.TemporaryDirectory() as d:
    relay.DB_PATH = Path(d) / "relay.db"
    asyncio.run(scenario())

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
