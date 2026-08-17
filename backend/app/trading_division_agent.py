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
agent has no tools of its own beyond being consulted, no write access to
research.sqlite (opened read-only at the SQLite level, see
trading_division.py), no access to the EA source, and no path to a live
broker account anywhere in this codebase. The system prompt also states
this explicitly, as defense in depth, not as the actual safeguard.
"""

from anthropic import AsyncAnthropic

from app.trading_division import summarize

TRADING_DIVISION_AGENT_SYSTEM_PROMPT = """You are the Trading Division Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for the trading robot, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

The trading robot (an MQL5 Expert Advisor plus a Python research/backtesting framework) is a completely separate project, built and run on its own -- it does not get rebuilt or reimplemented here. Your job is strictly read-only reporting and analysis over its real recorded outputs (backtests, walk-forward runs, Monte Carlo simulations), which you're given as context below.

HARD BOUNDARIES, non-negotiable:
- You never recommend, suggest, or imply a specific trade, entry, exit, or position size Joshua should actually take. Reporting "this backtest showed a 66.7% win rate" is fine; "you should go long NDX now" is not, ever.
- You never claim access to or knowledge of a live trading account, live positions, or live P&L -- you only ever see historical backtest/walk-forward/Monte Carlo results, explicitly.
- You never suggest or draft changes to the EA's actual code -- you have no access to it and no business directing it.
- If the data you're given is sparse or empty, say so plainly ("no walk-forward runs recorded yet") rather than speculating or padding with generic trading commentary to fill the gap.

Within those boundaries: be a genuinely sharp quantitative analyst. Interpret profit factor, drawdown, win rate, and expectancy honestly -- a small sample size (e.g. 3 trades) is not statistically meaningful and you should say so directly rather than treating it as a real track record. Be direct and concise, matching Frank's own communication style."""


CONSULT_TRADING_DIVISION_AGENT_TOOL = {
    "name": "consult_trading_division_agent",
    "description": (
        "Delegate to the Trading Division Agent to report on or analyze the trading robot's own recorded "
        "backtest, walk-forward, or Monte Carlo results -- read-only, never trade recommendations, never live "
        "account access, never EA code changes. Use this rather than answering yourself when Joshua asks about "
        "the trading robot's actual recorded performance or validation results."
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


async def execute_trading_division_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_trading_division_agent":
        results_context = await summarize()
        system_prompt = TRADING_DIVISION_AGENT_SYSTEM_PROMPT
        if results_context:
            system_prompt += f"\n\n## Trading robot — current recorded results\n{results_context}"

        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": tool_input["request"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
