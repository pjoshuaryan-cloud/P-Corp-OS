"""
Trading Division Agent -- Frank's specialist for the trading robot,
per TRADING_DIVISION.md's now-resolved integration boundary (2026-08-17):
read-only reporting/analysis over the trading robot's own existing
outputs, never deeper hooks into the EA codebase itself. See
trading_division.py's own docstring for the full reasoning on why this
was built now despite the trading robot itself still being early.

Same proven architecture as every other specialist (Operations, Alpha
Mode, Design, ...) -- a second, streamed Claude call using a distinct
system prompt, given the current real research.sqlite snapshot as
context, invoked as a tool from Frank's own turn.

Hard, structural constraint, not just a system-prompt instruction: this
agent has no write access to research.sqlite (opened read-only at the
SQLite level, see trading_division.py), no access to the EA source, and
no path to a live broker ACCOUNT ACTION anywhere in this codebase (no
trade, no order, no config change). The system prompt states this
explicitly too, as defense in depth, not as the actual safeguard.

Update (2026-09-18): three real, deliberate extensions, all asked for
directly by Josh in one request ("news events from forex factory...
how my open trades are doing... stocks doing well"), none guessed at:

1. Live account status -- this DOES relax the module's own former "never
   claim access to a live trading account" line, on purpose, confirmed
   directly with Josh first (account-level balance/equity/floating P&L
   only, not per-position -- see trading_division.py's
   live_account_summary() for why per-position was ruled out). The
   still-hard, unchanged boundary: no trade/order/account-action
   capability exists anywhere, regardless of what data can now be read.
2. Stock movers -- reuses market_movers.py's existing, already-proven
   non-advisory screener (check_stock_movers), same "X moved Y% since Z,
   never a recommendation" framing, restricted to stocks specifically.
3. Forex news -- real, LIVE external data (not from research.sqlite at
   all), via Anthropic's own server-executed web_search/web_fetch tools
   (same pair Research Agent already uses -- see web_tools.py's own
   docstring for why this needs zero client-side dispatch code). Both
   tools are needed together, not web_fetch alone -- found live, not
   assumed: a first attempt with only WEB_FETCH_TOOL failed every time
   with "blocked as not previously accessed," because Anthropic's
   web_fetch will only fetch a URL that's either explicitly given by the
   user or surfaced via a web_search result earlier in the same call, a
   real anti-SSRF safeguard on their side, not a bug here. Scoped to
   forexfactory.com specifically via the system prompt instruction
   below, not a general web-browsing grant.
"""

from anthropic import AsyncAnthropic

from app.market_movers import NOTABLE_MOVE_THRESHOLD_PCT
from app.trading_division import live_account_summary, stock_movers_summary, summarize
from app.web_tools import WEB_FETCH_TOOL, WEB_SEARCH_TOOL

TRADING_DIVISION_AGENT_SYSTEM_PROMPT = """You are the Trading Division Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for the trading robot and related markets, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

The trading robot (an MQL5 Expert Advisor plus a Python research/backtesting framework) is a completely separate project, built and run on its own -- it does not get rebuilt or reimplemented here. Your job is read-only reporting and analysis over: its real recorded outputs (backtests, walk-forward runs, Monte Carlo simulations), Josh's real live trading account status, and real stock/forex market data -- all given as context below, or fetchable live via your web_fetch tool.

When Josh asks about upcoming or recent forex news/economic releases, search for forexfactory.com's current economic calendar (web_search), then fetch the actual page (web_fetch) to read the real events -- use only the real fetched content, never invent an event or a time. If a search/fetch fails or comes back empty, say so plainly rather than fabricating calendar events.

HARD BOUNDARIES, non-negotiable:
- You never recommend, suggest, or imply a specific trade, entry, exit, or position size Joshua should actually take. Reporting "this backtest showed a 66.7% win rate" or "AAPL moved up 12% today" is fine; "you should go long NDX now" or "you should buy AAPL" is not, ever.
- You never claim to see individual open positions or trades -- only the real account-level balance/equity/floating P&L given to you as context (when available), which is real live data, not historical. If it's not in your context, say plainly that live account data isn't available right now rather than guessing.
- You never suggest or draft changes to the EA's actual code, and you have no path to place a trade, modify an order, or take any live account action -- you have no access to any of that and no business directing it.
- If the data you're given is sparse, empty, or unavailable (backtests, live account, stock movers, or a failed forex-news fetch), say so plainly rather than speculating or padding with generic trading commentary to fill the gap.

Within those boundaries: be a genuinely sharp quantitative analyst. Interpret profit factor, drawdown, win rate, and expectancy honestly -- a small sample size (e.g. 3 trades) is not statistically meaningful and you should say so directly rather than treating it as a real track record. Be direct and concise, matching Frank's own communication style."""


CONSULT_TRADING_DIVISION_AGENT_TOOL = {
    "name": "consult_trading_division_agent",
    "description": (
        "Delegate to the Trading Division Agent for: the trading robot's own recorded backtest/walk-forward/"
        "Monte Carlo results; Josh's real live trading account status (balance/equity/floating P&L -- "
        "account-level only, never individual open positions); real, factual stock-movers data (never a "
        "recommendation); or today's/upcoming forex economic calendar events (fetched live from "
        "ForexFactory). Read-only throughout -- never trade recommendations, never EA code changes, never any "
        "live account action."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Trading Division Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

TRADING_DIVISION_AGENT_TOOLS = [CONSULT_TRADING_DIVISION_AGENT_TOOL]
TRADING_DIVISION_AGENT_TOOL_NAMES = {tool["name"] for tool in TRADING_DIVISION_AGENT_TOOLS}


async def execute_trading_division_agent_tool_call(
    name: str, tool_input: dict, client: AsyncAnthropic, websocket, postgres_conn=None
) -> str:
    if name == "consult_trading_division_agent":
        results_context = await summarize()
        account_context = await live_account_summary(postgres_conn)
        movers_context = await stock_movers_summary(postgres_conn)
        system_prompt = TRADING_DIVISION_AGENT_SYSTEM_PROMPT
        if results_context:
            system_prompt += f"\n\n## Trading robot — current recorded results\n{results_context}"
        system_prompt += f"\n\n## Live trading account (account-level only)\n{account_context}"
        system_prompt += f"\n\n## Stock movers (last day, >{NOTABLE_MOVE_THRESHOLD_PCT:.0f}% moves only)\n{movers_context}"

        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": tool_input["request"]}],
            tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
