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

import asyncio
import json

from anthropic import AsyncAnthropic

from app.web_tools import WEB_FETCH_TOOL

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
        "Delegate to the Research Agent for genuine, deep research with real web search: technology, markets, "
        "competitors, business, economics, science, software, legal questions, industry trends, or anything "
        "else that depends on current or specific real-world information and needs synthesis across multiple "
        "sources. It summarizes into real insight, not a dump of search results. For a quick single fact-check "
        "or reading a specific URL Josh just gave you, use your own direct web_search/web_fetch instead -- "
        "don't round-trip a simple lookup through this agent. It already breaks a broad or multi-part request "
        "into sub-angles and researches them internally, in one call -- give it the whole scope in a single, "
        "complete `request` (e.g. a full multi-option comparison), don't call it separately per option or "
        "per facet yourself; that duplicates its own internal decomposition and multiplies real wait time for "
        "no benefit."
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



# Deep research pipeline (2026-09-06, systems audit §11): "no code-level
# sub-question decomposition, no cross-checking logic, no structured
# citation output. It's one prompted call, not an engineered pipeline."
# Three real, code-orchestrated steps replace what used to be a single
# client.messages.stream() call -- decompose, research each angle
# concurrently with real citation extraction, then synthesize with
# explicit cross-checking. consult_research_agent's own schema is
# unchanged; this is purely an internal upgrade to how it's fulfilled.

_MAX_SUB_QUESTIONS = 4

_DECOMPOSE_TOOL = {
    "name": "sub_questions",
    "description": (
        "Break the research request into up to 4 concrete, independently-researchable sub-questions that "
        "together cover it well. A genuinely narrow request can legitimately produce just one sub-question, "
        "equal to the original -- don't pad it out to fill 4."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": _MAX_SUB_QUESTIONS,
            }
        },
        "required": ["questions"],
    },
}


async def _decompose(client: AsyncAnthropic, request: str) -> list[str]:
    """Fails soft to a single sub-question (the original request) on any
    error -- a broken decomposition should degrade to today's old
    single-pass behavior, never crash the whole research turn."""
    try:
        response = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=512,
            system=(
                "Break the research request into up to 4 concrete, independently-researchable sub-questions "
                "that together cover it well. A genuinely narrow request can legitimately produce just one "
                "sub-question, equal to the original -- don't pad it out to fill 4."
            ),
            messages=[{"role": "user", "content": request}],
            tools=[_DECOMPOSE_TOOL],
            tool_choice={"type": "tool", "name": "sub_questions"},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "sub_questions":
                questions = block.input.get("questions")
                if questions and isinstance(questions, list) and all(isinstance(q, str) for q in questions):
                    return questions[:_MAX_SUB_QUESTIONS]
    except Exception:
        pass
    return [request]


def _extract_citations(content_blocks) -> list[dict]:
    """Real, structured citation data straight off the API response
    (TextBlock.citations) -- never the model's own recollection of what
    it read. Deduplicated by URL since the same source can be cited
    across multiple text blocks in one response."""
    citations: list[dict] = []
    seen_urls: set[str] = set()
    for block in content_blocks:
        if block.type != "text" or not block.citations:
            continue
        for citation in block.citations:
            url = getattr(citation, "url", None)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            citations.append({"url": url, "title": getattr(citation, "title", None)})
    return citations


async def _research_sub_question(client: AsyncAnthropic, question: str) -> dict:
    """One non-streaming research pass per sub-question -- not streamed to
    the user, since this is an intermediate result the synthesis step
    below still needs to combine and cross-check before Frank ever sees
    anything. A failure here (network error, etc.) is caught and reported
    honestly to synthesis rather than taking the whole pipeline down --
    same per-part fail-soft discipline as automations.py's own per-rule
    FAILED recording."""
    try:
        response = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=RESEARCH_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
            tools=[RESEARCH_AGENT_TOOL, WEB_FETCH_TOOL],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return {"question": question, "answer": text, "citations": _extract_citations(response.content), "error": None}
    except Exception as error:
        return {"question": question, "answer": "", "citations": [], "error": str(error)}


async def _research_sub_questions_with_progress(
    client: AsyncAnthropic, sub_questions: list[str], websocket
) -> list[dict]:
    """Progress-signal fix (2026-09-07): a blind asyncio.gather() left the
    single "Researching N angles" label static for the entire parallel
    phase, no matter how long it actually took. Sends one incremental
    update per sub-question as it actually finishes -- only when there's
    more than one, since a single sub-question's own "Researching that
    angle" label already covers the no-parallelism case, and a "1 of 1"
    message here would just be a redundant extra flash right before
    synthesis starts.

    Results are written back by original index, not completion order --
    asyncio.as_completed() only tells us WHEN something finished, not
    which one, and _format_sub_answers_for_synthesis()'s "Angle 1/2/3..."
    numbering depends on the original decomposition order being
    preserved, not the (nondeterministic) order sub-questions happen to
    resolve in."""
    if len(sub_questions) == 1:
        return [await _research_sub_question(client, sub_questions[0])]

    async def _indexed(index: int, question: str) -> tuple[int, dict]:
        return index, await _research_sub_question(client, question)

    tasks = [asyncio.create_task(_indexed(i, q)) for i, q in enumerate(sub_questions)]
    sub_answers: list[dict | None] = [None] * len(tasks)
    completed = 0
    for coro in asyncio.as_completed(tasks):
        index, result = await coro
        sub_answers[index] = result
        completed += 1
        label = f"Researched {completed} of {len(tasks)} angles"
        await websocket.send_text(f"\n[tool_start]{json.dumps({'label': label})}")
    return sub_answers


def _format_sub_answers_for_synthesis(sub_answers: list[dict]) -> str:
    parts = []
    for i, sub in enumerate(sub_answers, start=1):
        if sub["error"]:
            parts.append(f"### Angle {i}: {sub['question']}\n[This angle failed: {sub['error']}]")
            continue
        sources = "\n".join(f"  - {c['title'] or c['url']}: {c['url']}" for c in sub["citations"]) or "  (no sources cited)"
        parts.append(f"### Angle {i}: {sub['question']}\n{sub['answer']}\n\nReal sources cited for this angle:\n{sources}")
    return "\n\n".join(parts)


_SYNTHESIS_SYSTEM_PROMPT = RESEARCH_AGENT_SYSTEM_PROMPT + """

You're now in the final synthesis step of a multi-angle research pipeline. You've already been given real research findings for each angle below, each with real sources actually cited during that research -- don't re-research, don't invent new findings, and don't cite a source that isn't listed under one of the angles. Your job:
1. Synthesize the angles into one coherent, insight-first answer -- not the angles stitched together as separate sections.
2. If any angles genuinely contradict each other, say so explicitly and explain the discrepancy -- don't silently pick one and ignore the conflict.
3. Close with a real "Sources" list built only from the actual URLs given to you above."""


async def execute_research_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name != "consult_research_agent":
        return f"Unknown tool: {name}"

    request = tool_input["request"]

    await websocket.send_text(f"\n[tool_start]{json.dumps({'label': 'Breaking down the research'})}")
    sub_questions = await _decompose(client, request)

    label = "Researching that angle" if len(sub_questions) == 1 else f"Researching {len(sub_questions)} angles"
    await websocket.send_text(f"\n[tool_start]{json.dumps({'label': label})}")
    sub_answers = await _research_sub_questions_with_progress(client, sub_questions, websocket)

    await websocket.send_text(f"\n[tool_start]{json.dumps({'label': 'Cross-checking and synthesizing'})}")
    synthesis_prompt = (
        f"Original request: {request}\n\n"
        f"Research findings by angle:\n\n{_format_sub_answers_for_synthesis(sub_answers)}"
    )
    assistant_text = ""
    async with client.messages.stream(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=_SYNTHESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": synthesis_prompt}],
    ) as stream:
        async for text in stream.text_stream:
            assistant_text += text
            await websocket.send_text(text)
    return assistant_text
