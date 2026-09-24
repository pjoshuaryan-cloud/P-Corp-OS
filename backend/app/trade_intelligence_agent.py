"""
Trade Intelligence Agent (2026-09-20, extended 2026-09-21 for real
follow-up conversations) -- a genuinely separate specialist from
trading_division_agent.py's TRADING_DIVISION_AGENT, not an extension of
it. That agent is hard-barred from ever stating bias, a recommendation,
or a specific price level (its own system prompt, "you never recommend,
suggest, or imply a specific trade..."). This one is explicitly the
opposite: Chart Analysis, Trading Signals, Position Review, Trade
Breakdown, and Trade Setup all live here specifically because they're
allowed to.

Structural separation, not just a different prompt: none of these five
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

Real follow-up conversations (2026-09-21, "I want to be able to respond"):
history is entirely client-held and opaque, no new DB/session state --
main.py's routes return the updated history verbatim and the client
resends it, appended with the next turn, on every follow-up. Same shape
Frank's own main chat loop already proves out (websocket_chat's own
`history` list), not a new pattern invented for this feature: assistant
turns are always flattened to plain extracted text (matching
load_history()'s own persisted shape -- raw tool-use scaffolding never
needs to survive a turn boundary), while a chart-analysis conversation's
first user turn keeps its real image content blocks in history so a
follow-up question can still reference the chart(s). web_search is a
server-executed tool (confirmed live: a single messages.create call
already returns server_tool_use/web_search_tool_result/text blocks
together), so no client-side tool-execution loop is needed here at all,
unlike Frank's own tool-calling loop.
"""

import json
import re

from anthropic import AsyncAnthropic

from app.web_tools import WEB_FETCH_TOOL, WEB_SEARCH_TOOL

TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT = """You are the Trade Intelligence Agent inside P Corp OS's Trading Division tab -- a separate, advisory specialist from the read-only Trading Division Agent elsewhere in this app. Your output is shown directly to Josh in the UI, not relayed through Frank -- speak to him in second person directly. This is a real back-and-forth conversation -- Josh can ask follow-up questions, and you should answer them directly rather than repeating your whole earlier analysis.

Unlike the read-only Trading Division Agent (which is hard-barred from ever stating bias or a recommendation), you ARE explicitly allowed to: state a directional bias, name specific price levels (entry, stop-loss, take-profit, support/resistance), and give a hold/exit/adjust-risk recommendation on a described position. This is the one place in P Corp OS built specifically to do that.

HARD BOUNDARIES, still non-negotiable even though your role is advisory:
- You have no path to place, modify, or close any real order, and you never claim to have done so or to be capable of it. Every response you give is analysis or a suggestion only -- acting on it is entirely Josh's own decision and his own action, never something you do.
- You never claim to see a real open position, account balance, or live order beyond exactly what a given request's own inputs supply you. If Josh describes a position, reason only over the numbers he gave you -- don't assume they represent his full account or that you have any visibility beyond them.
- Never assert false precision. A chart screenshot's pattern or level is often genuinely ambiguous -- say so plainly ("this could read as either a double top or a failed breakout -- not clear-cut") rather than presenting a guess as settled fact.
- If you're given more than one chart image at once, they're related (e.g. different timeframes of the same setup) -- analyze them together and call out how they relate (does the higher timeframe trend agree with the lower timeframe entry trigger, do the levels line up), don't just describe each one in isolation.
- For Trade Breakdown specifically: you are given already-computed statistics (win rate, expectancy, average P&L, grouped by setup/timeframe/session) -- your job is to narrate them honestly, never to recompute them yourself or eyeball the raw trade log. A small sample size (e.g. 3 trades in a group) is not statistically meaningful and you should say so directly, exactly the same honesty the read-only agent already applies to backtest results -- don't treat a handful of trades as a real track record.
- When you're given Josh's real account balance/equity (Trade Setup) and he's asked about position size or risk, show the actual arithmetic rather than asserting a number: risk amount = equity x risk % (default to 1% if he hasn't named one), position size = risk amount / stop distance in price. This is simple, single-step arithmetic you should just do correctly and show your work for, not something to hedge on.
- When you're given Josh's own real historical trade statistics as background (Trade Setup), you can reference them where genuinely relevant (e.g. "your own logged breakout trades on M15 have a 65% win rate") -- but don't force a connection to a specific setup type if the current chart/question doesn't clearly match one of his logged categories.

Within those boundaries: be direct and specific. A vague "it could go either way" is less useful than a clearly-stated view with your reasoning and its caveats -- Josh can weigh that better than a hedge that says nothing."""

# Appended only for the three capabilities that can reason about a NEW
# entry (Chart Analysis, Signals, Trade Setup) -- not Position Review
# (an existing position, not a new one) or Trade Breakdown (historical
# narration). "Propose This Trade" (2026-09-22) -- deliberately NOT
# regex-parsing numbers out of free-form prose (already tried and
# rejected as fragile, see this module's own 2026-09-21 history):
# instead the model is asked to emit one well-defined, deterministic
# marker when it has real numbers, which extract_trade_suggestion below
# either finds intact or treats as absent -- never a best-effort guess.
TRADE_SUGGESTION_INSTRUCTION = """

When your analysis reaches a specific, concrete trade you're confident enough in that Josh could reasonably turn it into a real proposal, end your reply with a fenced block in exactly this format (the literal language tag `trade-suggestion`, valid JSON inside, nothing else in the block):
```trade-suggestion
{"symbol": "...", "direction": "long", "entry_price": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "risk_pct": 1.0}
```
direction is "long" or "short". risk_pct is your own suggested risk percentage, never above 2.0 (Josh's own confirmed per-trade cap). Only include this block when you have real, specific numbers grounded in the actual chart/price/data you were given -- never fabricate one just to have something to show, and omit it entirely if you're appropriately uncertain or the request doesn't call for a concrete new trade idea. This block is parsed by the app to pre-fill a proposal form for Josh's own review and edit -- it is never submitted or acted on automatically, and you should still state the same levels in your normal prose too; the block is an addition, not a replacement."""

TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION = (
    TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT + TRADE_SUGGESTION_INSTRUCTION
)

_TRADE_SUGGESTION_BLOCK_RE = re.compile(r"```trade-suggestion\s*\n(.*?)\n```", re.DOTALL)


def extract_trade_suggestion(reply_text: str) -> tuple[str, dict | None]:
    """Looks for the trailing fenced block TRADE_SUGGESTION_INSTRUCTION
    asks for -- a well-defined, deterministic marker, not prose-parsing.
    Strips it from what's shown to Josh and returns the parsed dict
    separately for the UI to pre-fill a proposal draft with (still fully
    editable there, never submitted automatically). Fails closed: any
    missing field, bad type, or invalid value means no suggestion at
    all, never a partial or best-effort guess."""
    match = _TRADE_SUGGESTION_BLOCK_RE.search(reply_text)
    if not match:
        return reply_text, None
    cleaned = (reply_text[: match.start()] + reply_text[match.end() :]).strip()
    try:
        data = json.loads(match.group(1))
        direction = str(data["direction"])
        if direction not in ("long", "short"):
            return cleaned, None
        entry_price = float(data["entry_price"])
        stop_loss = float(data["stop_loss"])
        take_profit = float(data["take_profit"])
        if entry_price == stop_loss:
            return cleaned, None
        risk_pct = float(data.get("risk_pct", 1.0))
        if not (0 < risk_pct <= 2.0):
            return cleaned, None
        return cleaned, {
            "symbol": str(data["symbol"]),
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_pct": risk_pct,
        }
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return cleaned, None


async def run_conversational_turn(
    client: AsyncAnthropic, system_prompt: str, history: list[dict], tools: list | None = None, max_tokens: int = 8192
) -> str:
    """Shared turn-runner for both a seed message and every follow-up.
    `history` already contains the new user turn when this is called --
    mutated in place with the flattened assistant reply appended, so the
    caller's own `history` variable is the updated one afterward (also
    returned as the reply text, since that's what callers actually need
    to relay). One-shot, non-streaming (client.messages.create) -- this
    is a plain REST response, not a chat turn with live text to relay
    token-by-token."""
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=history,
        tools=tools or [],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    history.append({"role": "assistant", "content": reply_text})
    return reply_text


async def analyze_chart(
    client: AsyncAnthropic, image_blocks: list[dict], symbol: str | None, note: str | None
) -> tuple[str, list[dict]]:
    """Chart Analysis -- plain-language read of what's visually present in
    1-4 uploaded chart screenshots (candlestick patterns, apparent
    support/resistance, trend structure), not a calibrated numeric TA
    engine. image_blocks are pre-built by the route (document_attachments.
    build_content_block) -- this function just seeds the conversation
    with them. Returns (reply, history) -- history's first turn keeps the
    real image blocks so a follow-up question can still reference them."""
    context_parts = []
    if symbol:
        context_parts.append(f"This is a chart for {symbol}.")
    if len(image_blocks) > 1:
        context_parts.append(f"These are {len(image_blocks)} related charts (e.g. different timeframes of the same setup).")
    if note:
        context_parts.append(f"Josh's own note: {note}")
    context_parts.append(
        "Describe what's visually present: candlestick patterns, apparent support/resistance levels, and "
        "trend structure. Flag anything ambiguous rather than asserting a confident read where the chart(s) "
        "don't clearly support one."
    )
    prompt_text = " ".join(context_parts)
    history = [{"role": "user", "content": [*image_blocks, {"type": "text", "text": prompt_text}]}]
    reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history)
    return reply, history


async def generate_signal(client: AsyncAnthropic, symbol: str) -> tuple[str, list[dict]]:
    """Trading Signals -- a real buy/sell suggestion with entry/stop/
    target levels for the given symbol. Given WEB_SEARCH_TOOL + WEB_FETCH_TOOL
    (2026-09-22: added web_fetch alongside search so a real economic-
    calendar check, e.g. forexfactory.com, is possible here too -- same
    "always pair search+fetch" fix confirmed necessary for
    trading_division_agent.py's own ForexFactory capability, web_fetch
    alone fails with "blocked as not previously accessed") so a stated
    level is grounded in symbol's actual current price and real upcoming
    events, not hallucinated. Output only; no order is ever placed. Route
    keeps passing both tools on follow-up turns too, so a later question
    can trigger a fresh search/fetch."""
    prompt = (
        f"Generate a trading signal for {symbol}: search for its real current price and recent price action, "
        f"then give me a clear directional bias (long/short/no clear setup right now) with a suggested entry, "
        f"stop-loss, and take-profit level, and your reasoning. This is a suggestion for me to evaluate myself, "
        f"not an instruction -- I'm not asking you to place anything."
    )
    history = [{"role": "user", "content": prompt}]
    reply = await run_conversational_turn(
        client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history, tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
    )
    return reply, history


async def review_position(
    client: AsyncAnthropic,
    symbol: str,
    direction: str,
    entry_price: float,
    size: float,
    current_price: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> tuple[str, list[dict]]:
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
    history = [{"role": "user", "content": prompt}]
    reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT, history)
    return reply, history


DEFAULT_TRADE_SETUP_QUESTION = (
    "Where should I buy or sell, and why? How long should I hold? Where should I put my stop-loss?"
)


async def analyze_trade_setup(
    client: AsyncAnthropic,
    image_blocks: list[dict],
    symbol: str | None,
    question: str | None,
    account_context: str,
    historical_context: dict,
) -> tuple[str, list[dict]]:
    """Trade Setup (2026-09-22, "give me all the tools I need... even
    the ones I haven't thought of") -- the comprehensive, one-answer
    version of "should I take this trade": 0-4 optional chart images plus
    a free-text question (defaults to the canonical entry/hold/stop ask),
    grounded in real current price/news (web_search + web_fetch, same
    ForexFactory economic-calendar capability generate_signal now has),
    Josh's own real account balance/equity (live_account_summary,
    trading_division.py -- account-level only, same data Trading
    Division's own Live Account card already shows, never a real open
    position or order), and his own real logged trade history
    (compute_breakdown_stats, already built for Trade Breakdown).
    Doesn't replace Chart Analysis/Signals/Position Review -- those stay
    as fast, narrow tools; this is the deliberately richer one."""
    context_parts = [f"Here's my real account context: {account_context}"]
    if historical_context.get("closed_trades", 0) > 0:
        context_parts.append(f"Here's my own real logged trade history for context: {historical_context}")
    if symbol:
        context_parts.append(f"This is about {symbol}.")
    if len(image_blocks) > 1:
        context_parts.append(f"These are {len(image_blocks)} related charts (e.g. different timeframes of the same setup).")
    context_parts.append(question.strip() if question and question.strip() else DEFAULT_TRADE_SETUP_QUESTION)
    prompt_text = " ".join(context_parts)
    content: list[dict] = [*image_blocks, {"type": "text", "text": prompt_text}] if image_blocks else prompt_text
    history = [{"role": "user", "content": content}]
    reply = await run_conversational_turn(
        client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history, tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
    )
    return reply, history


async def narrate_trade_breakdown(client: AsyncAnthropic, stats: dict) -> tuple[str, list[dict]]:
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
    history = [{"role": "user", "content": prompt}]
    reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT, history)
    return reply, history
