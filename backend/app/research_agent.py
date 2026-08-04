"""
Research Agent -- a specialist Frank delegates to for real research, per
Joshua's own multi-agent vision (see AGENTS_VISION.md, Technology
Division -- the non-Engineering half; Engineering Agent itself stays
deliberately fenced off, see that file's scope note). His own words:
"research literally anything... It summarizes everything. Never dumps
information. Only insights."

Unlike Communications Agent's real-inbox gap, this one gets genuine live
capability today: Anthropic's Messages API has a native, server-executed
web search tool (type "web_search_20250305") -- Claude issues searches
and gets results back from Anthropic's own infrastructure within the
same streamed call, no MCP, no separate scraping/search-API integration
to build. That's a materially different situation from the Gmail/
Calendar MCP connectors available in a Claude Code session (session-
scoped, not usable by this separate backend) -- web search is a plain
API capability, available to any Messages API call that requests it.

Same proven streamed-consult architecture as every other specialist
(operations_agent.py, alpha_mode_agent.py, design_agent.py,
creative_director_agent.py, communications_agent.py, memory_agent.py).
"""

from anthropic import AsyncAnthropic

RESEARCH_AGENT_SYSTEM_PROMPT = """You are the Research Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for real research, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: research literally anything relevant to Joshua's work -- technology, markets, AI, competitors, business, economics, science, software, legal questions, industry trends. You have real web search -- use it whenever the question depends on current or specific real-world information, rather than answering from memory alone when memory might be stale or wrong.

HOW YOU WORK:
- Summarize. Never dump. The goal is insight Joshua can actually act on, not a pile of search results with no synthesis. If you searched five sources, the answer is what they collectively tell him, not five separate summaries stitched together.
- Cite what you're drawing on (source names/links) so the claim is checkable, but don't let citations replace the actual synthesis.
- Give a real point of view when the research supports one -- "X is the better choice because..." -- not just a neutral options list, unless the honest answer really is "it depends," in which case say what it depends on.
- If something is genuinely uncertain, contested, or you couldn't find a reliable answer, say that plainly rather than presenting a guess with false confidence.
- Match depth to the question -- a quick factual lookup gets a quick answer, a real competitive/market question gets real depth.

Be direct and concise, matching Frank's own communication style."""


RESEARCH_AGENT_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

CONSULT_RESEARCH_AGENT_TOOL = {
    "name": "consult_research_agent",
    "description": (
        "Delegate to the Research Agent for genuine research with real web search: technology, markets, "
        "competitors, business, economics, science, software, legal questions, industry trends, or anything "
        "else that depends on current or specific real-world information. It summarizes into real insight, not "
        "a dump of search results. Use this rather than answering from memory when the question needs current "
        "or verifiable information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What to research, in full, self-contained detail.",
            },
        },
        "required": ["request"],
    },
}

# Only CONSULT_RESEARCH_AGENT_TOOL goes into Frank's own tool list --
# RESEARCH_AGENT_TOOL (the web_search server tool) is used inside this
# agent's own isolated call below, not exposed to Frank directly.
RESEARCH_AGENT_TOOLS = [CONSULT_RESEARCH_AGENT_TOOL]
RESEARCH_AGENT_TOOL_NAMES = {tool["name"] for tool in RESEARCH_AGENT_TOOLS}


async def execute_research_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_research_agent":
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=RESEARCH_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": tool_input["request"]}],
            tools=[RESEARCH_AGENT_TOOL],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
