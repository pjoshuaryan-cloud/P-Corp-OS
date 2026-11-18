"""Tests for backend/app/festx_signals.py (FestX signals in the Trading tab): checking a chart reading, sizing in rand, the log and the warnings.
A temp SQLite file stands in for the shared database; no Claude call (readings are written by hand), no network (the FX rate is set)."""
import asyncio, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import festx_signals as fx

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

def reading(**sig):
    base = {"instrument": "EURUSD", "timeframe": "4H", "price_scale_legible": True, "current_price": 1.0850,
            "setups": [{"setup": "A", "applies": True, "met": ["BOS", "pullback to 61.8"], "missing": []}, {"setup": "Z", "applies": True}],
            "signal": {"setup": "A", "direction": "buy", "entry": 1.0850, "stop": 1.0830, "tp1": 1.0910, "tp2": 1.0950,
                       "confluences": ["fib_and_mitigation", "higher_timeframe_level", "made_up"], "why": "Higher low at 61.8."},
            "no_trade_reason": "", "watch_for": "A close below 1.0830."}
    if sig:
        base["signal"] = None if sig.get("none") else {**base["signal"], **sig}
    return "Here: " + json.dumps(base)

r = fx.parse_reading(reading())
s = r["signal"]
check("a consistent buy signal survives: setup A, entry/stop/targets kept, unknown setup and confluence dropped",
      s and s["setup"] == "A" and s["entry"] == 1.085 and [x["setup"] for x in r["setups"]] == ["A"] and s["confluences"] == ["fib_and_mitigation", "higher_timeframe_level"], r)
check("two named confluences make it strong; reward to risk 3.0 meets the FestX 1:3", s["strength"] == "strong" and s["reward_to_risk"] == 3.0 and not s["below_festx_minimum"])
check("every signal carries its setup's backtest record (A lost)", "LOST" in s["record"] and "-0.18R" in s["record"])
check("one confluence -> standard", fx.parse_reading(reading(confluences=["round_number"]))["signal"]["strength"] == "standard")
low = fx.parse_reading(reading(tp1=1.0880))["signal"]
check("a target under 1:3 is kept but flagged below the FestX minimum", low["reward_to_risk"] == 1.5 and low["below_festx_minimum"])
for bad, why in ((dict(stop=1.0870), "stop on the wrong side"), (dict(tp1=1.0800), "target on the wrong side"), (dict(entry=None), "no entry"),
                 (dict(direction="hold"), "no direction"), (dict(setup="D"), "NASDAQ-only setup on EURUSD"), (dict(setup="Q"), "unknown setup")):
    rr = fx.parse_reading(reading(**bad))
    check(f"an inconsistent signal is dropped, never repaired ({why})", rr["signal"] is None and rr["dropped"] and rr["no_trade_reason"], rr.get("dropped"))
nt = fx.parse_reading(reading(none=True))
check("no signal with no reason gets a plain default reason", nt["signal"] is None and "No FestX setup" in nt["no_trade_reason"])
check("gold's own setup G is accepted on gold", fx.parse_reading(reading(setup="G").replace('"EURUSD"', '"GOLD"'))["signal"]["setup"] == "G")
for bad in ("nothing", "{bad}"):
    try:
        fx.parse_reading(bad); ok = False
    except fx.FestxError:
        ok = True
    check(f"an unreadable reply is a plain error ({bad!r})", ok)

# sizing (R18/$ for round numbers)
SET = {**fx.DEFAULT_SETTINGS, "balance_zar": 243.03}
z = fx.size_trade(settings=SET, symbol="EURUSD", strength="standard", entry=1.0850, stop=1.0830, tp1=1.0910, tp2=None, usdzar=18.0)
check("EURUSD, 20-pip stop: smallest trade risks R36 (15% of R243), above the 5% budget, and it says so",
      z["lots"] == 0.01 and not z["fits_risk"] and z["risk_zar"] == 36.0 and z["smallest_trade_risk_pct"] == 14.8 and "smallest trade" in z["message"], z)
check("...with the possible win at the first target in rand", z["win_tp1_zar"] == 108.0)
SET2 = {**SET, "balance_zar": 5000.0}
z2 = fx.size_trade(settings=SET2, symbol="EURUSD", strength="strong", entry=1.0850, stop=1.0830, tp1=1.0910, tp2=1.0950, usdzar=18.0)
check("on R5,000 a strong signal risks 10% (R500): 0.13 lots (rounded DOWN), R468 risked, fits", z2["lots"] == 0.13 and z2["fits_risk"] and z2["risk_zar"] == 468.0
      and z2["risk_pct_chosen"] == 10.0 and z2["win_tp2_zar"] == 2340.0, z2)
gold = fx.size_trade(settings=SET, symbol="XAUUSD", strength="standard", entry=2650.0, stop=2642.0, tp1=2674.0, tp2=None, usdzar=18.0)
check("gold, $8 stop on R243: smallest trade risks R144 (59%)", gold["smallest_trade_risk_zar"] == 144.0 and gold["smallest_trade_risk_pct"] == 59.3 and not gold["fits_risk"])
capped = fx.size_trade(settings={**SET2, "strong_pct": 25}, symbol="NAS100", strength="strong", entry=21000, stop=20900, tp1=21300, tp2=None, usdzar=18.0)
check("a risk setting above 10% is capped at 10%", capped["risk_pct_chosen"] == 10.0)
for bad_settings, msg in (({**SET, "balance_zar": None}, "balance"), ({**SET, "symbols": {}}, "contract size")):
    try:
        fx.size_trade(settings=bad_settings, symbol="EURUSD", strength="standard", entry=1.085, stop=1.083, tp1=1.091, tp2=None, usdzar=18.0); ok = False
    except fx.FestxError as e:
        ok = msg in str(e)
    check(f"no {msg} -> a plain message", ok)

async def flow():
    fx._FX.update(rate=18.0, source="test", at=9e18)   # no network
    try:
        await fx.save_settings({"strong_pct": 30})
        ok = False
    except fx.FestxError as e:
        ok = "10%" in str(e)
    check("settings refuse more than 10% a trade", ok)
    st = await fx.save_settings({"balance_zar": 5000})
    check("settings saved and merged with the defaults", st["balance_zar"] == 5000 and st["standard_pct"] == 5.0 and "XAUUSD" in st["symbols"])
    row = await fx.record_reading(fx.parse_reading(reading()), note="test")
    check("a reading is logged as an open signal", row["status"] == "signal" and row["setup"] == "A" and row["strength"] == "strong")
    nrow = await fx.record_reading(fx.parse_reading(reading(none=True)))
    check("no-trade readings are logged too", nrow["status"] == "no_trade")
    for price, why in ((1.0825, "past the stop"), (1.0915, "past the target")):
        try:
            await fx.size_signal(row["id"], price); ok = False
        except fx.FestxError as e:
            ok = True
        check(f"sizing refuses when the price is already {why}", ok)
    sized = await fx.size_signal(row["id"], 1.0852)
    check("sizing uses the confirmed price, the balance and the strength", sized["sizing"]["entry_used"] == 1.0852 and sized["sizing"]["risk_pct_chosen"] == 10.0
          and sized["sizing"]["lots"] == 0.12 and sized["sizing"]["risk_zar"] == 475.2, sized["sizing"])
    try:
        await fx.log_outcome(row["id"], "won", exit_price=1.0910); ok = False
    except fx.FestxError:
        ok = True
    check("a result can't be logged before the trade is marked taken", ok)
    await fx.log_outcome(row["id"], "taken", fill_price=1.0853)
    done = await fx.log_outcome(row["id"], "lost", exit_price=1.0830)
    check("a loss is worked out from fill, exit and lots, in rand", done["result_zar"] == round(-(1.0853 - 1.0830) * 100000 * 0.12 * 18, 2), done["result_zar"])
    st = await fx.load_settings()
    check("...and taken off the balance, so the next size follows the account", st["balance_zar"] == round(5000 + done["result_zar"], 2), st["balance_zar"])
    try:
        await fx.log_outcome(row["id"], "won", exit_price=1.09); ok = False
    except fx.FestxError:
        ok = True
    check("a closed trade can't be logged again", ok)
    # second loss today -> warning
    r2 = await fx.record_reading(fx.parse_reading(reading()))
    await fx.size_signal(r2["id"], 1.0851)
    await fx.log_outcome(r2["id"], "taken", fill_price=1.0851)
    out = await fx.log_outcome(r2["id"], "lost", result_zar=-450.0)
    check("two losses today -> the stop-for-the-day warning", any("2 losing trades today" in w for w in out["warnings"]), out["warnings"])
    check("...and the day-down warning past 15%", any("Today is down" in w for w in out["warnings"]), out["warnings"])
    summ = await fx.summary()
    check("the summary shows each setup's live record next to its backtest", summ["live"]["A"]["trades"] == 2 and summ["live"]["A"]["wins"] == 0
          and summ["live"]["A"]["avg_r"] is not None and "LOST" in summ["backtest"]["A"]["record"] and summ["max_risk_pct"] == 10.0, summ["live"]["A"])
    sk = await fx.record_reading(fx.parse_reading(reading()))
    check("a signal can be skipped", (await fx.log_outcome(sk["id"], "skipped"))["status"] == "skipped")

with tempfile.TemporaryDirectory() as d:
    fx.DB_PATH = Path(d) / "festx.db"
    asyncio.run(flow())

# ---- the routes, with a fake Claude, a temp database and no audit writes ----
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import main
class FakeClaude:
    calls = 0
    def __init__(self, api_key=None):
        self.messages = SimpleNamespace(create=self.create)
    async def create(self, **kw):
        FakeClaude.calls += 1
        assert any(b.get("type") == "image" for b in kw["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reading())], stop_reason="end_turn", usage=SimpleNamespace(input_tokens=3000, output_tokens=500))
async def no_audit(*a, **k):
    return None
real = (main.AsyncAnthropic, main.record_tool_call, main.DATA_BACKEND, main._require_api_key)
main.AsyncAnthropic, main.record_tool_call, main.DATA_BACKEND, main._require_api_key = FakeClaude, no_audit, "sqlite", (lambda: "k")
main.app.dependency_overrides[main.verify_token] = lambda: None
try:
    with tempfile.TemporaryDirectory() as d:
        fx.DB_PATH = Path(d) / "festx_routes.db"
        fx._FX.update(rate=18.0, source="test", at=9e18)
        c = TestClient(main.app)
        check("no screenshot -> a plain 400 and no Claude call", c.post("/trading/festx/read", json={"images": []}).status_code == 400 and FakeClaude.calls == 0)
        img = {"media_type": "image/png", "filename": "c.png", "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}
        r = c.post("/trading/festx/read", json={"images": [img], "note": "4H"})
        sig = r.json().get("signal", {})
        check("a read returns the logged signal with its backtest record, and the summary", r.status_code == 200 and FakeClaude.calls == 1 and sig.get("status") == "signal"
              and "LOST" in sig["reading"]["signal"]["record"] and "A" in r.json()["summary"]["backtest"], r.text[:300])
        r = c.post(f"/trading/festx/signals/{sig['id']}/size", json={"current_price": 1.0851})
        check("sizing without a balance is a plain 400 telling him to set it", r.status_code == 400 and "balance" in r.json()["detail"], r.text[:200])
        r = c.put("/trading/festx/settings", json={"balance_zar": 243.03})
        check("settings save the balance", r.status_code == 200 and r.json()["settings"]["balance_zar"] == 243.03)
        r = c.post(f"/trading/festx/signals/{sig['id']}/size", json={"current_price": 1.0851})
        z = r.json()["signal"]["sizing"]
        check("sizing on R243: the smallest EURUSD trade, flagged as over the chosen risk", r.status_code == 200 and z["lots"] == 0.01 and not z["fits_risk"], z)
        r = c.post(f"/trading/festx/signals/{sig['id']}/log", json={"status": "taken", "fill_price": 1.0851})
        check("logging taken works", r.status_code == 200 and r.json()["signal"]["status"] == "taken")
        r = c.post(f"/trading/festx/signals/{sig['id']}/log", json={"status": "won", "exit_price": 1.0910})
        check("a win is worked out and added to the balance", r.status_code == 200 and r.json()["signal"]["result_zar"] == round((1.0910 - 1.0851) * 100000 * 0.01 * 18, 2)
              and r.json()["summary"]["settings"]["balance_zar"] == round(243.03 + (1.0910 - 1.0851) * 100000 * 0.01 * 18, 2), r.text[:300])
        check("a signal that isn't there is a 404", c.post("/trading/festx/signals/999/size", json={"current_price": 1.0}).status_code == 404)
        check("the read route is a slow route (no pooled connection held across the Claude call)", main._is_slow_route("POST", "/trading/festx/read"))
finally:
    main.AsyncAnthropic, main.record_tool_call, main.DATA_BACKEND, main._require_api_key = real
    main.app.dependency_overrides.clear()

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
