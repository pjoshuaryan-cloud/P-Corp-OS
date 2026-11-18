"""FestX signals in the Trading tab (2026-11-18). Josh drops in screenshots of EURUSD, gold or NASDAQ; Claude reads them against the setups from Clint's
FestX course (the rules written up in AMM - APP/docs/festx-strategy-rules.md, summarised here in our own words), and the tab shows a signal or "no trade"
with the reason, the setup's backtest record, the size in lots for Josh's rand account, and a log of what he took and how it went.

Honesty rules, built in (Josh chose to trade it with real money from the start, knowing the record):
  * Every signal carries its setup's BACKTEST record (docs/festx-setup-*-results.md). As of 2026-11-18 no setup has passed: A and C lost, G is about
    break-even, D narrowly failed on Black Crown prices and is in a frozen forward test (shown read-only as robot results, never mixed with his
    trades). The live log, next to it, records how each setup does on Josh's own trades.
  * Size comes from checkable facts, not from Claude feeling sure: "standard" = the setup's rules met (risk standard_pct, 5% by default); "strong" = the
    rules met PLUS at least two named FestX confluences (risk strong_pct, 10% by default, never above MAX_RISK_PCT).
  * The price read off a picture can be off, so the size is worked out only after Josh confirms the current price.
  * When even the broker's smallest trade risks more than the chosen percentage, it says so in rand and percent.
  * Warnings (never blocks): two losing trades today, the day 15% down, a setup whose live record is negative after 20+ trades.
  * Nothing here places, changes or closes an order. Josh trades in MT5 himself.
Storage: two small tables in the shared database (festx.signals, festx.settings), made on first use like the other phone-and-Mac features; SQLite when the
app runs on SQLite. No personal data leaves except the screenshots to Claude.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

READ_MODEL = "claude-sonnet-5-5"
DB_PATH = Path(__file__).parent.parent / "data" / "festx_signals.db"
MAX_RISK_PCT = 10.0
SAST = timezone(timedelta(hours=2))

DEFAULT_SETTINGS: dict[str, Any] = {
    "balance_zar": None,            # Josh's Black Crown balance; updated by logged results
    "standard_pct": 5.0,
    "strong_pct": 10.0,
    "daily_loss_trades": 2,
    "daily_loss_pct": 15.0,
    "usdzar_override": None,        # used when the live rate can't be fetched
    # Per symbol: US$ that 1.0 of price movement is worth on 1 lot, and the broker's smallest trade / step. CONFIRMED on Black Crown
    # (BlackCrownHoldings-Live, account 2005001) on 2026-11-18 with MT5's own profit calculation: EURUSD contract 100,000, XAUUSD 100 oz, NASDAQ =
    # .USTECH_x1. (US$1 a point; the x10/x100 versions are 10x/100x bigger). Black Crown's tick value for indices is wrong (unconverted), so never use it.
    "symbols": {
        "EURUSD": {"usd_per_point_per_lot": 100000.0, "min_lot": 0.01, "lot_step": 0.01, "confirmed": True},
        "XAUUSD": {"usd_per_point_per_lot": 100.0, "min_lot": 0.01, "lot_step": 0.01, "confirmed": True},
        "NAS100": {"usd_per_point_per_lot": 1.0, "min_lot": 0.01, "lot_step": 0.01, "confirmed": True},
    },
}
SYMBOL_ALIASES = {"EURUSD": "EURUSD", "EUR/USD": "EURUSD", "XAUUSD": "XAUUSD", "GOLD": "XAUUSD", "XAU/USD": "XAUUSD",
                  "NAS100": "NAS100", "NASDAQ": "NAS100", "USTECH": "NAS100", ".USTECH_X1.": "NAS100", "USTECH_X1": "NAS100", "US100": "NAS100", "USTEC": "NAS100", "USA100": "NAS100", "NDX": "NAS100"}

SETUPS: dict[str, dict[str, str]] = {
    "A": {"name": "Structure break + fib 61.8", "markets": "any",
          "record": "Backtest: LOST. US30 + NASDAQ: -0.18R a trade with your approved settings (profit factor 0.77), 2024-2026 unseen data. EURUSD, GBPUSD "
                    "+ gold: -0.17R (PF 0.78); about break-even even before overnight costs. Trades with 2+ confluences looked better in 2010-2018 "
                    "but were no better than the rest in 2019-2026 (test H)."},
    "C": {"name": "Range break + retest", "markets": "any",
          "record": "Backtest: LOST. -0.17R a trade (profit factor 0.79) on US30 and NASDAQ daily boxes; worst drop about 30%. A daily round-number "
                    "break + retest (test I) also lost: -0.14R."},
    "G": {"name": "Asian session break + retest (gold)", "markets": "XAUUSD",
          "record": "Backtest: about break-even. +0.06R a trade with your approved settings (profit factor 1.12) on gold, mid-2025 to 2026 unseen data; below the pass bar."},
    "D": {"name": "NASDAQ Asian range at the New York open", "markets": "NAS100",
          "record": "Backtest: NARROWLY FAILED on Black Crown prices. Best setting +0.15R a trade (profit factor 1.86) on 48 unseen trades, Aug 2025 to "
                    "Nov 2026, but under the 60 trades / +0.15R bar, and your approved settings lost (-0.03R). Most trades closed at the 16:45 New York "
                    "cut-off, not at a target. Stops are wide (~200 points). Being forward-tested on new data, checked monthly."},
}
CONFLUENCES = {
    "fib_and_mitigation": "the fib 61.8 zone lines up with the mitigation 50% of the candle that started the move",
    "higher_timeframe_level": "a support/resistance level from a higher timeframe (several reactions) at the entry",
    "reversal_candle": "a reversal candle in the zone (engulfing, shooting star, hammer/spinning top; not a doji)",
    "round_number": "a round number at the entry (e.g. x000, x250, x500, x750 on indices; .x000/.x500 on EURUSD)",
    "pattern": "a double top/bottom or head and shoulders at the entry",
    "liquidity_sweep": "a sweep beyond an obvious high/low followed by rejection",
}

SYSTEM_PROMPT = """You read trading chart screenshots for Josh against the setups from the FestX course he follows. You do not give advice and you never
tell him to trade; you say whether a setup's rules are met on the chart, and where its entry, stop and targets would be. He decides.

The building blocks:
- Swing highs/lows only count where two or three wicks cluster at about the same price; one spike is not a swing.
- Bullish structure = higher highs + higher lows; bearish = lower highs + lower lows. Buy only in bullish structure at a higher low; sell only in bearish
  structure at a lower high. A break of structure (BOS) = a close beyond the last higher low (uptrend) or lower high (downtrend).
- The fib: from the swing that started the move to its extreme; the entry zone is a box around 61.8. Anchor on wick clusters / candle bodies.
  If an entry-timeframe candle has closed well beyond the 61.8 zone with no reversal sign, there is no trade.
- Mitigation: the 50% level of the candle that started the move. Stops go beyond the swing or signal candle. Targets at least 1:3.
- Higher-timeframe support/resistance needs several reactions; don't take a trade straight into a strong higher-timeframe level.

The setups (check every one that can apply to this market):
A. Structure break + fib 61.8 (daily/4-hour structure, entry on 4-hour/1-hour): a BOS, then the pullback forming the lower high (sell) or higher low (buy)
   into the 61.8 zone of the leg; enter on a reversal candle in the zone; stop beyond the swing that started the move; targets the fib extensions
   (-27% and -61.8%) or the next structure level.
C. Range break + retest (4-hour/daily): a sideways range (several days) with clear edges; a candle CLOSES outside it, then price comes back to the broken
   edge; enter on the retest; stop beyond the retest candle; target = the height of the move into the range, projected from the entry.
G. Gold only, Asian session break + retest (15/30-minute): the Asian range is 02:00-09:00 South African time; the first 30-minute candle that CLOSES beyond
   its high or low sets the side; enter when price comes back to touch that broken edge; stop on the far side of the range or its middle; 1:3 target.
D. NASDAQ only, Asian range at the New York open (15-minute), as tested: mark the high and low of the 15-minute candles from 02:00 to 09:00 South
   African time. The side is set by the close of the 15-minute candle ending at the real 09:30 New York open (15:30 South African time while the US is on
   summer time, 16:30 in US winter): above the Asian high = buys only, below the low = sells only, inside = no trade. Then price must pull back to within a
   quarter of the Asian range of the broken edge; a 15-minute close more than halfway back inside the range cancels the day. For a sell: after the pullback
   high, a lower 15-minute swing high, then a 15-minute close below the lowest low between them (buys mirror). Enter at the next candle's open; stop beyond
   the pullback extreme; no new entry after 15:00 New York; anything open is closed at the 16:45 New York candle. In the test the target was almost never
   reached, so give tp1 as at least 3x the risk and say the trade is usually closed at the cut-off.

Confluences you may list for a signal (only ones you can actually see): fib_and_mitigation, higher_timeframe_level, reversal_candle, round_number, pattern,
liquidity_sweep.

Read every price off the chart's own price scale and time axis. If the scale or the time axis needed for a setup isn't legible, say so and give no signal
rather than guessing numbers. Give AT MOST ONE signal: the setup whose rules are most completely met. No signal is a normal, good answer.

Reply with ONLY JSON:
{"instrument": "EURUSD|XAUUSD|NAS100|other", "timeframe": "e.g. 4H", "price_scale_legible": true/false, "current_price": number or null,
 "setups": [{"setup": "A|C|G|D", "applies": true/false, "met": ["rule met", ...], "missing": ["rule not met", ...]}],
 "signal": null or {"setup": "A|C|G|D", "direction": "buy|sell", "entry": number, "stop": number, "tp1": number, "tp2": number or null,
                    "confluences": ["..."], "why": "one or two sentences"},
 "no_trade_reason": "if no signal: the main reason in one sentence", "watch_for": "one sentence: what would change this"}"""


class FestxError(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------- reading a chart
def parse_reading(text: str) -> dict[str, Any]:
    """Validates Claude's JSON. A signal survives only if it is internally consistent (a real setup, the stop on the losing side of the entry, the first
    target on the winning side); otherwise it is dropped and the reason given, never repaired by guessing."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise FestxError("Couldn't read the chart reading. Try again, or with a clearer screenshot.")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise FestxError("Couldn't read the chart reading. Try again, or with a clearer screenshot.") from exc
    instrument = SYMBOL_ALIASES.get(str(data.get("instrument") or "").upper().replace(" ", ""), "other")
    reading = {"instrument": instrument, "timeframe": str(data.get("timeframe") or "")[:12], "price_scale_legible": bool(data.get("price_scale_legible")),
               "current_price": _num(data.get("current_price")), "setups": [], "signal": None,
               "no_trade_reason": str(data.get("no_trade_reason") or "")[:300], "watch_for": str(data.get("watch_for") or "")[:300], "dropped": None}
    for s in data.get("setups") or []:
        if isinstance(s, dict) and s.get("setup") in SETUPS:
            reading["setups"].append({"setup": s["setup"], "name": SETUPS[s["setup"]]["name"], "applies": bool(s.get("applies")),
                                      "met": [str(x)[:160] for x in (s.get("met") or [])][:8], "missing": [str(x)[:160] for x in (s.get("missing") or [])][:8]})
    sig = data.get("signal")
    if isinstance(sig, dict):
        problem = _signal_problem(sig, instrument)
        if problem:
            reading["dropped"] = problem
            reading["no_trade_reason"] = reading["no_trade_reason"] or problem
        else:
            entry, stop, tp1, tp2 = (_num(sig.get(k)) for k in ("entry", "stop", "tp1", "tp2"))
            confluences = [c for c in (sig.get("confluences") or []) if c in CONFLUENCES]
            risk = abs(entry - stop)
            reading["signal"] = {"setup": sig["setup"], "setup_name": SETUPS[sig["setup"]]["name"], "direction": sig["direction"], "entry": entry, "stop": stop,
                                 "tp1": tp1, "tp2": tp2, "confluences": confluences, "confluence_words": [CONFLUENCES[c] for c in confluences],
                                 "strength": "strong" if len(confluences) >= 2 else "standard", "why": str(sig.get("why") or "")[:400],
                                 "reward_to_risk": round(abs(tp1 - entry) / risk, 2), "record": SETUPS[sig["setup"]]["record"],
                                 "below_festx_minimum": abs(tp1 - entry) / risk < 3 - 1e-9}
    if reading["signal"] is None and not reading["no_trade_reason"]:
        reading["no_trade_reason"] = "No FestX setup's rules are met on this chart."
    return reading


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _signal_problem(sig: dict, instrument: str) -> str | None:
    setup = sig.get("setup")
    if setup not in SETUPS:
        return "The reading named no known FestX setup, so no signal is given."
    markets = SETUPS[setup]["markets"]
    if markets != "any" and instrument != markets:
        return f"Setup {setup} is only for {markets}; this chart is {instrument}."
    if sig.get("direction") not in ("buy", "sell"):
        return "The reading gave no clear direction, so no signal is given."
    entry, stop, tp1 = (_num(sig.get(k)) for k in ("entry", "stop", "tp1"))
    if None in (entry, stop, tp1):
        return "The reading couldn't give a full entry, stop and target, so no signal is given."
    buy = sig["direction"] == "buy"
    if (buy and not (stop < entry < tp1)) or (not buy and not (tp1 < entry < stop)):
        return "The levels read off the chart don't fit together (stop or target on the wrong side), so no signal is given."
    return None


async def read_chart(client: Any, image_blocks: list[dict], note: str | None) -> tuple[dict[str, Any], dict[str, int]]:
    text = (f"Josh's note: {note}\n" if note else "") + "Check these screenshots against the FestX setups."
    try:
        response = await client.messages.create(model=READ_MODEL, max_tokens=4000, output_config={"effort": "medium"}, system=SYSTEM_PROMPT,
                                                messages=[{"role": "user", "content": [*image_blocks, {"type": "text", "text": text}]}])
    except Exception as exc:
        raise FestxError(f"Couldn't reach Claude ({type(exc).__name__}). Try again.") from exc
    if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
        raise FestxError("Claude couldn't finish reading that chart. Try again, or with fewer screenshots.")
    reply = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
    usage = getattr(response, "usage", None)
    return parse_reading(reply), {"in": int(getattr(usage, "input_tokens", 0) or 0), "out": int(getattr(usage, "output_tokens", 0) or 0)}


# ------------------------------------------------------------------------------------------------------------- sizing in rand
def size_trade(*, settings: dict[str, Any], symbol: str, strength: str, entry: float, stop: float, tp1: float, tp2: float | None, usdzar: float) -> dict[str, Any]:
    """Lots for the chosen risk on the current balance, rounded DOWN to the broker's step, and what that really risks and could win, in rand. Says so when
    even the smallest trade risks more than the chosen percentage."""
    spec = (settings.get("symbols") or {}).get(symbol)
    if spec is None:
        raise FestxError(f"No contract size set for {symbol}. Add it in the FestX settings.")
    balance = settings.get("balance_zar")
    if not balance or balance <= 0:
        raise FestxError("Set your account balance first (FestX settings), so the size can be worked out.")
    pct = min(float(settings["strong_pct"] if strength == "strong" else settings["standard_pct"]), MAX_RISK_PCT)
    risk_budget = balance * pct / 100.0
    zar_per_lot = abs(entry - stop) * float(spec["usd_per_point_per_lot"]) * usdzar   # rand lost per lot if the stop is hit
    if zar_per_lot <= 0:
        raise FestxError("The entry and stop are the same price.")
    step, min_lot = float(spec["lot_step"]), float(spec["min_lot"])
    lots = math.floor(risk_budget / zar_per_lot / step + 1e-9) * step
    lots = round(lots, 4)
    min_risk = min_lot * zar_per_lot
    fits = lots >= min_lot - 1e-12
    used = lots if fits else min_lot
    risk_zar = used * zar_per_lot
    win1 = used * abs(tp1 - entry) * float(spec["usd_per_point_per_lot"]) * usdzar
    win2 = used * abs(tp2 - entry) * float(spec["usd_per_point_per_lot"]) * usdzar if tp2 else None
    return {"symbol": symbol, "strength": strength, "risk_pct_chosen": pct, "balance_zar": round(balance, 2), "risk_budget_zar": round(risk_budget, 2),
            "lots": round(used, 4), "fits_risk": fits, "risk_zar": round(risk_zar, 2), "risk_pct_actual": round(100 * risk_zar / balance, 1),
            "smallest_trade_risk_zar": round(min_risk, 2), "smallest_trade_risk_pct": round(100 * min_risk / balance, 1),
            "win_tp1_zar": round(win1, 2), "win_tp2_zar": round(win2, 2) if win2 is not None else None, "usdzar": usdzar,
            "spec_confirmed": bool(spec.get("confirmed")),
            "message": None if fits else (f"Even the smallest trade ({min_lot:g} lot) risks R{min_risk:.2f}, {100 * min_risk / balance:.0f}% of your account, "
                                          f"more than your {pct:g}%. Shown at the smallest trade; decide whether to take it.")}


_FX: dict[str, Any] = {}


async def usd_to_zar(override: float | None) -> tuple[float, str]:
    """The live USD/ZAR rate (European Central Bank reference, via frankfurter.app; cached for 6 hours), else the override in settings, else 18.0."""
    if _FX.get("at") and time.time() - _FX["at"] < 6 * 3600:
        return _FX["rate"], _FX["source"]
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.get("https://api.frankfurter.app/latest", params={"from": "USD", "to": "ZAR"})
            rate = float(r.json()["rates"]["ZAR"])
        _FX.update(rate=rate, source=f"ECB reference rate {r.json().get('date', '')}", at=time.time())
        return rate, _FX["source"]
    except Exception:
        if override:
            return float(override), "your rate in settings"
        return 18.0, "an assumed R18 per dollar (the live rate couldn't be fetched)"


# ------------------------------------------------------------------------------------------------------------- storage + log
_COLUMNS = ("id", "created_at", "symbol", "setup", "direction", "entry", "stop", "tp1", "tp2", "strength", "status", "reading_json", "sizing_json",
            "fill_price", "exit_price", "result_zar", "closed_at", "note")
OPEN, FINAL = ("signal", "taken"), ("won", "lost", "breakeven", "skipped", "no_trade")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _table(conn: Any, name: str) -> str:
    return f"festx.{name}" if conn is not None else f"festx_{name}"


async def _run(conn: Any, sql: str, params: tuple = ()) -> list[tuple]:
    if conn is not None:
        async with conn.cursor() as cur:
            await cur.execute(sql.replace("?", "%s"), params)
            rows = await cur.fetchall() if cur.description else []
        await conn.commit()
        return rows
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        await db.commit()
        return [tuple(r) for r in rows]


async def ensure_tables(conn: Any = None) -> None:
    identity = "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if conn is not None else "INTEGER PRIMARY KEY AUTOINCREMENT"
    if conn is not None:
        await _run(conn, "CREATE SCHEMA IF NOT EXISTS festx")
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "signals")} (
        id {identity}, created_at TEXT NOT NULL, symbol TEXT NOT NULL, setup TEXT, direction TEXT, entry DOUBLE PRECISION, stop DOUBLE PRECISION,
        tp1 DOUBLE PRECISION, tp2 DOUBLE PRECISION, strength TEXT, status TEXT NOT NULL, reading_json TEXT NOT NULL, sizing_json TEXT,
        fill_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, result_zar DOUBLE PRECISION, closed_at TEXT, note TEXT)""".replace(
        "DOUBLE PRECISION", "DOUBLE PRECISION" if conn is not None else "REAL"))
    await _run(conn, f"CREATE TABLE IF NOT EXISTS {_table(conn, 'settings')} (id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
    # Robot results (2026-11-18): the frozen setup D forward test from AMM - APP, imported by app/festx_robot_import.py. NEW tables only -- the signals
    # table is never altered, and robot rows never count in his live records, balance or warnings.
    await _run(conn, f"""CREATE TABLE IF NOT EXISTS {_table(conn, "robot_trades")} (
        setup TEXT NOT NULL, setting TEXT NOT NULL, day TEXT NOT NULL, direction TEXT, entry DOUBLE PRECISION, stop DOUBLE PRECISION,
        exit_price DOUBLE PRECISION, reason TEXT, r DOUBLE PRECISION, imported_at TEXT NOT NULL, PRIMARY KEY (setup, setting, day))""".replace(
        "DOUBLE PRECISION", "DOUBLE PRECISION" if conn is not None else "REAL"))
    await _run(conn, f"CREATE TABLE IF NOT EXISTS {_table(conn, 'robot_meta')} (setup TEXT PRIMARY KEY, report_json TEXT NOT NULL, updated_at TEXT NOT NULL)")


def _row(row: tuple) -> dict[str, Any]:
    out = dict(zip(_COLUMNS, row))
    out["reading"] = json.loads(out.pop("reading_json") or "{}")
    out["sizing"] = json.loads(out.pop("sizing_json")) if out.get("sizing_json") else None
    return out


async def load_settings(conn: Any = None) -> dict[str, Any]:
    await ensure_tables(conn)
    rows = await _run(conn, f"SELECT settings_json FROM {_table(conn, 'settings')} WHERE id = 1")
    saved = json.loads(rows[0][0]) if rows else {}
    merged = {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k != "symbols"}}
    merged["symbols"] = {**DEFAULT_SETTINGS["symbols"], **(saved.get("symbols") or {})}
    return merged


async def save_settings(changes: dict[str, Any], conn: Any = None) -> dict[str, Any]:
    current = await load_settings(conn)
    for key in ("balance_zar", "standard_pct", "strong_pct", "daily_loss_trades", "daily_loss_pct", "usdzar_override"):
        if key in changes and changes[key] is not None:
            value = float(changes[key])
            if value < 0 or (key.endswith("_pct") and key != "daily_loss_pct" and value > MAX_RISK_PCT):
                raise FestxError(f"{key.replace('_', ' ')} can't be {value:g}" + (f" (the most per trade is {MAX_RISK_PCT:g}%)." if key.endswith("_pct") else "."))
            current[key] = int(value) if key == "daily_loss_trades" else value
    for sym, spec in (changes.get("symbols") or {}).items():
        if sym in current["symbols"] and isinstance(spec, dict):
            current["symbols"][sym] = {**current["symbols"][sym], **{k: spec[k] for k in ("usd_per_point_per_lot", "min_lot", "lot_step", "confirmed") if k in spec}}
    await _run(conn, f"""INSERT INTO {_table(conn, 'settings')} (id, settings_json, updated_at) VALUES (1, ?, ?)
        ON CONFLICT (id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at""", (json.dumps(current), now_iso()))
    return current


async def record_reading(reading: dict[str, Any], conn: Any = None, note: str | None = None) -> dict[str, Any]:
    await ensure_tables(conn)
    sig = reading.get("signal")
    rows = await _run(conn, f"""INSERT INTO {_table(conn, 'signals')} (created_at, symbol, setup, direction, entry, stop, tp1, tp2, strength, status, reading_json, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                      (now_iso(), reading["instrument"], sig and sig["setup"], sig and sig["direction"], sig and sig["entry"], sig and sig["stop"], sig and sig["tp1"],
                       sig and sig["tp2"], sig and sig["strength"], "signal" if sig else "no_trade", json.dumps(reading), (note or "")[:300]))
    return await get_signal(int(rows[0][0]), conn)


async def get_signal(signal_id: int, conn: Any = None) -> dict[str, Any]:
    rows = await _run(conn, f"SELECT {', '.join(_COLUMNS)} FROM {_table(conn, 'signals')} WHERE id = ?", (signal_id,))
    if not rows:
        raise LookupError("That signal isn't there.")
    return _row(rows[0])


async def size_signal(signal_id: int, current_price: float, conn: Any = None) -> dict[str, Any]:
    """Josh confirmed the live price: size the signal on his current balance. A price that has already run past the stop or the first target says so."""
    s = await get_signal(signal_id, conn)
    if s["status"] not in OPEN or not s["setup"]:
        raise FestxError("Only a signal that's still open can be sized.")
    buy = s["direction"] == "buy"
    if (buy and current_price <= s["stop"]) or (not buy and current_price >= s["stop"]):
        raise FestxError("The price is already past the stop: this signal is no longer valid.")
    if (buy and current_price >= s["tp1"]) or (not buy and current_price <= s["tp1"]):
        raise FestxError("The price has already reached the first target: the move is gone.")
    settings = await load_settings(conn)
    rate, source = await usd_to_zar(settings.get("usdzar_override"))
    sizing = size_trade(settings=settings, symbol=s["symbol"], strength=s["strength"], entry=current_price, stop=s["stop"], tp1=s["tp1"], tp2=s["tp2"], usdzar=rate)
    sizing.update(entry_used=current_price, rate_source=source, reward_to_risk=round(abs(s["tp1"] - current_price) / abs(current_price - s["stop"]), 2))
    await _run(conn, f"UPDATE {_table(conn, 'signals')} SET sizing_json = ? WHERE id = ?", (json.dumps(sizing), signal_id))
    return {**await get_signal(signal_id, conn), "warnings": await warnings(conn)}


async def log_outcome(signal_id: int, status: str, conn: Any = None, *, fill_price: float | None = None, exit_price: float | None = None,
                      result_zar: float | None = None) -> dict[str, Any]:
    """taken / skipped, then won / lost / breakeven. A result is worked out from the fill, exit and lots when they're given (else his own rand figure), and
    added to the balance so the next size follows the account."""
    if status not in ("taken", "skipped", "won", "lost", "breakeven"):
        raise FestxError("Status must be taken, skipped, won, lost or breakeven.")
    s = await get_signal(signal_id, conn)
    if s["status"] in FINAL:
        raise FestxError(f"This signal is already {s['status']}.")
    if status in ("won", "lost", "breakeven") and s["status"] != "taken":
        raise FestxError("Mark it taken first (with your fill price), then its result.")
    sets, params = ["status = ?"], [status]
    if fill_price is not None:
        sets.append("fill_price = ?"); params.append(float(fill_price))
    if status in ("won", "lost", "breakeven"):
        if result_zar is None and exit_price is not None and s.get("sizing"):
            fill = fill_price or s.get("fill_price") or s["sizing"]["entry_used"]
            spec = (await load_settings(conn))["symbols"][s["symbol"]]
            sign = 1 if s["direction"] == "buy" else -1
            result_zar = round(sign * (float(exit_price) - fill) * float(spec["usd_per_point_per_lot"]) * s["sizing"]["lots"] * s["sizing"]["usdzar"], 2)
        if result_zar is None:
            raise FestxError("Give the exit price (or the rand result from MT5) to record the result.")
        if status == "breakeven":
            result_zar = round(result_zar, 2)
        sets += ["exit_price = ?", "result_zar = ?", "closed_at = ?"]
        params += [float(exit_price) if exit_price is not None else None, float(result_zar), now_iso()]
    await _run(conn, f"UPDATE {_table(conn, 'signals')} SET {', '.join(sets)} WHERE id = ?", (*params, signal_id))
    if status in ("won", "lost", "breakeven"):
        settings = await load_settings(conn)
        if settings.get("balance_zar") is not None:
            await save_settings({"balance_zar": round(float(settings["balance_zar"]) + float(result_zar), 2)}, conn)
    return {**await get_signal(signal_id, conn), "warnings": await warnings(conn)}


def _sast_day(iso: str) -> str:
    return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(SAST).strftime("%Y-%m-%d")


async def closed_trades(conn: Any = None) -> list[dict[str, Any]]:
    await ensure_tables(conn)
    rows = await _run(conn, f"SELECT {', '.join(_COLUMNS)} FROM {_table(conn, 'signals')} WHERE status IN ('won', 'lost', 'breakeven') ORDER BY id")
    return [_row(r) for r in rows]


def live_records(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for code in SETUPS:
        mine = [t for t in trades if t["setup"] == code]
        rs = []
        for t in mine:
            risk = (t.get("sizing") or {}).get("risk_zar")
            if risk:
                rs.append(float(t["result_zar"]) / float(risk))
        out[code] = {"trades": len(mine), "wins": sum(1 for t in mine if t["status"] == "won"), "result_zar": round(sum(float(t["result_zar"]) for t in mine), 2),
                     "avg_r": round(sum(rs) / len(rs), 2) if rs else None}
    return out


async def warnings(conn: Any = None) -> list[str]:
    """The guard rails: they warn, they never block."""
    settings = await load_settings(conn)
    trades = await closed_trades(conn)
    today = datetime.now(SAST).strftime("%Y-%m-%d")
    todays = [t for t in trades if _sast_day(t["closed_at"] or t["created_at"]) == today]
    out = []
    losses = sum(1 for t in todays if t["status"] == "lost")
    if losses >= int(settings["daily_loss_trades"]):
        out.append(f"{losses} losing trades today. Your rule is to stop at {int(settings['daily_loss_trades'])}.")
    day_result = sum(float(t["result_zar"]) for t in todays)
    balance = settings.get("balance_zar")
    if balance and day_result < 0:
        start = float(balance) - day_result
        if start > 0 and -day_result / start * 100 >= float(settings["daily_loss_pct"]):
            out.append(f"Today is down R{-day_result:.2f}, {(-day_result / start) * 100:.0f}% of the day's starting balance (your limit is {settings['daily_loss_pct']:g}%).")
    for code, rec in live_records(trades).items():
        if rec["trades"] >= 20 and (rec["avg_r"] or 0) < 0:
            out.append(f"Setup {code} ({SETUPS[code]['name']}) is losing on your own trades: {rec['avg_r']:+.2f}R a trade over {rec['trades']} trades.")
    return out


async def import_robot_report(setup: str, report: dict[str, Any], trades: list[dict[str, Any]], conn: Any = None) -> dict[str, Any]:
    """Store one forward-test report (run_festx_d_forward.py output). Idempotent: a day already stored is replaced, so re-importing is safe."""
    await ensure_tables(conn)
    stamp = now_iso()
    for t in trades:
        await _run(conn, f"""INSERT INTO {_table(conn, 'robot_trades')} (setup, setting, day, direction, entry, stop, exit_price, reason, r, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (setup, setting, day) DO UPDATE SET direction = excluded.direction, entry = excluded.entry,
            stop = excluded.stop, exit_price = excluded.exit_price, reason = excluded.reason, r = excluded.r, imported_at = excluded.imported_at""",
                   (setup, str(t["setting"]), str(t["day"])[:10], "buy" if int(t["dir"]) == 1 else "sell", float(t["entry"]), float(t["stop"]),
                    float(t["exit"]), str(t["reason"])[:20], float(t["r"]), stamp))
    def stats(d: Any) -> dict[str, Any] | None:   # only the numbers the tab shows; infinity (no losing trade yet) is not valid JSON -> None
        if not isinstance(d, dict):
            return None
        return {k: (float(d[k]) if isinstance(d.get(k), (int, float)) and math.isfinite(d[k]) else None) if k != "trades" else int(d.get("trades") or 0)
                for k in ("trades", "avg_r", "total_r", "profit_factor", "win_rate_pct")}
    keep = {k: report.get(k) for k in ("generated", "forward_period", "verdict")}
    sel = report.get("selected") or {}
    keep.update(forward=stats(sel.get("forward")), combined=stats(sel.get("forward_plus_run2_oos")),
                defaults_forward=stats((report.get("approved_defaults") or {}).get("forward")))
    await _run(conn, f"""INSERT INTO {_table(conn, 'robot_meta')} (setup, report_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT (setup) DO UPDATE SET report_json = excluded.report_json, updated_at = excluded.updated_at""", (setup, json.dumps(keep), stamp))
    return await robot_summary(conn)


async def robot_summary(conn: Any = None) -> dict[str, Any]:
    """Read-only robot results for the Trading tab: the latest forward-test report and its most recent trades (selected setting only)."""
    await ensure_tables(conn)
    out: dict[str, Any] = {}
    for setup, report_json, updated in await _run(conn, f"SELECT setup, report_json, updated_at FROM {_table(conn, 'robot_meta')}"):
        rows = await _run(conn, f"""SELECT day, direction, entry, stop, exit_price, reason, r FROM {_table(conn, 'robot_trades')}
            WHERE setup = ? AND setting = 'selected' ORDER BY day DESC LIMIT 10""", (setup,))
        out[setup] = {**json.loads(report_json), "updated_at": updated, "name": SETUPS.get(setup, {}).get("name", setup),
                      "recent": [dict(zip(("day", "direction", "entry", "stop", "exit", "reason", "r"), r)) for r in rows]}
    return out


async def summary(conn: Any = None) -> dict[str, Any]:
    settings = await load_settings(conn)
    rows = await _run(conn, f"SELECT {', '.join(_COLUMNS)} FROM {_table(conn, 'signals')} ORDER BY id DESC LIMIT 15")
    trades = await closed_trades(conn)
    return {"settings": settings, "recent": [_row(r) for r in rows], "live": live_records(trades),
            "backtest": {k: {"name": v["name"], "record": v["record"], "markets": v["markets"]} for k, v in SETUPS.items()},
            "warnings": await warnings(conn), "max_risk_pct": MAX_RISK_PCT, "robot": await robot_summary(conn)}
