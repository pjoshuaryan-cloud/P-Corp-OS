"""
Trade Intelligence Agent (2026-09-20) -- a genuinely separate specialist
from trading_division_agent.py's TRADING_DIVISION_AGENT, not an extension
of it. That agent is hard-barred from ever stating bias, a recommendation,
or a specific price level (its own system prompt, "you never recommend,
suggest, or imply a specific trade..."). This one is explicitly the
opposite: Chart Analysis, Trading Signals, Position Review, and Trade
Breakdown all live here specifically because they're allowed to.

Structural separation, not just a different prompt: none of these four
functions are registered as a Frank chat tool anywhere (no *_TOOL dict, no
*_TOOL_NAMES set, nothing added to main.py's tools=[...] list) -- each is
called directly from its own dedicated REST route (main.py's
/trade-intelligence/... routes), same "bypass Frank's chat loop entirely"
shape as trading_division_agent.py's own get_holding_update/get_stock_update.
This means Josh only ever sees this agent's output because he explicitly
opened the Trade Intelligence section and asked for it -- never because
Frank happened to reach for it mid-conversation.

Every function's output is shown directly in the UI, not relayed through
Frank -- the system prompt below speaks to Josh in second person
directly, unlike the read-only agent's own "Frank will relay what you
say" framing.
"""

from anthropic import AsyncAnthropic

from app.web_tools import WEB_SEARCH_TOOL

TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT = """You are the Trade Intelligence Agent inside P Corp OS's Trading Division tab -- a separate, advisory specialist from the read-only Trading Division Agent elsewhere in this app. Your output is shown directly to Josh in the UI, not relayed through Frank -- speak to him in second person directly.

Unlike the read-only Trading Division Agent (which is hard-barred from ever stating bias or a recommendation), you ARE explicitly allowed to: state a directional bias, name specific price levels (entry, stop-loss, take-profit, support/resistance), and give a hold/exit/adjust-risk recommendation on a described position. This is the one place in P Corp OS built specifically to do that.

HARD BOUNDARIES, still non-negotiable even though your role is advisory:
- You have no path to place, modify, or close any real order, and you never claim to have done so or to be capable of it. Every response you give is analysis or a suggestion only -- acting on it is entirely Josh's own decision and his own action, never something you do.
- You never claim to see a real open position, account balance, or live order beyond exactly what a given request's own inputs supply you. If Josh describes a position, reason only over the numbers he gave you -- don't assume they represent his full account or that you have any visibility beyond them.
- Never assert false precision. A chart screenshot's pattern or level is often genuinely ambiguous -- say so plainly ("this could read as either a double top or a failed breakout -- not clear-cut") rather than presenting a guess as settled fact.
- For Trade Breakdown specifically: you are given already-computed statistics (win rate, expectancy, average P&L, grouped by setup/timeframe/session) -- your job is to narrate them honestly, never to recompute them yourself or eyeball the raw trade log. A small sample size (e.g. 3 trades in a group) is not statistically meaningful and you should say so directly, exactly the same honesty the read-only agent already applies to backtest results -- don't treat a handful of trades as a real track record.

Within those boundaries: be direct and specific. A vague "it could go either way" is less useful than a clearly-stated view with your reasoning and its caveats -- Josh can weigh that better than a hedge that says nothing."""


async def analyze_chart(client: AsyncAnthropic, image_block: dict, symbol: str | None, note: str | None) -> str:
    """Chart Analysis -- plain-language read of what's visually present in
    an uploaded chart screenshot (candlestick patterns, apparent support/
    resistance, trend structure), not a calibrated numeric TA engine.
    Reuses the same image content-block shape the websocket chat path
    already builds (document_attachments.build_content_block) -- this
    function just wraps it as this agent's one-shot vision call."""
    context_parts = []
    if symbol:
        context_parts.append(f"This is a chart for {symbol}.")
    if note:
        context_parts.append(f"Josh's own note: {note}")
    context_parts.append(
        "Describe what's visually present: candlestick patterns, apparent support/resistance levels, and "
        "trend structure. Flag anything ambiguous rather than asserting a confident read where the chart "
        "doesn't clearly support one."
    )
    prompt_text = " ".join(context_parts)
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [image_block, {"type": "text", "text": prompt_text}]}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def generate_signal(client: AsyncAnthropic, symbol: str) -> str:
    """Trading Signals -- a real buy/sell suggestion with entry/stop/
    target levels for the given symbol. Given WEB_SEARCH_TOOL so a stated
    level is grounded in symbol's actual current price, not hallucinated
    -- same reasoning get_holding_update already uses for its own web
    grounding. Output only; no order is ever placed."""
    prompt = (
        f"Generate a trading signal for {symbol}: search for its real current price and recent price action, "
        f"then give me a clear directional bias (long/short/no clear setup right now) with a suggested entry, "
        f"stop-loss, and take-profit level, and your reasoning. This is a suggestion for me to evaluate myself, "
        f"not an instruction -- I'm not asking you to place anything."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        tools=[WEB_SEARCH_TOOL],
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def review_position(
    client: AsyncAnthropic,
    symbol: str,
    direction: str,
    entry_price: float,
    size: float,
    current_price: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> str:
    """Position Review -- hold/exit/adjust-risk advice on a described
    active trade. Reasons only over the numbers given here, per the
    system prompt's own hard boundary -- never assumes this represents a
    real, currently-open account position."""
    levels = f"stop-loss {stop_loss}" if stop_loss is not None else "no stop-loss set"
    levels += f", take-profit {take_profit}" if take_profit is not None else ", no take-profit set"
    prompt = (
        f"Review this {direction} position on {symbol}: entry price {entry_price}, size {size}, current price "
        f"{current_price}, {levels}. Give me your honest hold/exit/adjust-risk view and your reasoning."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def narrate_trade_breakdown(client: AsyncAnthropic, stats: dict) -> str:
    """Trade Breakdown's narration layer -- stats is already-computed
    deterministic SQL/Python aggregation (trade_intelligence_db.
    compute_breakdown_stats), never raw trade rows. This call's only job
    is to narrate those numbers honestly, per the system prompt's own
    explicit instruction not to recompute or eyeball the log itself."""
    prompt = (
        f"Here are Josh's own computed trade statistics, grouped by setup tag, timeframe, and trading session: "
        f"{stats}. Narrate what patterns are actually visible here -- what's working, what isn't, and where the "
        f"sample size is too small to draw a real conclusion yet. Don't recompute anything yourself; these "
        f"numbers are already correct."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
