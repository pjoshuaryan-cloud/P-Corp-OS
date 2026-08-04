"""
Memory Agent -- a specialist Frank delegates to for surfacing, connecting,
and synthesizing what's already known about Joshua, per his own
multi-agent vision (see AGENTS_VISION.md, Intelligence Division). His own
words: "This may become the most important agent after Frank... this is
the reason Frank gets smarter over time."

Deliberately NOT a duplicate of save_memory/forget_memory (app/memory.py)
-- those stay Frank's own direct tools for writing new memories
proactively mid-conversation. This agent is read/synthesis-only: given
the current, real memory_records as context (same data that already
backs GET /memory and Frank's own system-prompt memory block), it
answers things like "what do we already know about X," spots patterns
across past preferences/decisions, and flags when something new
conflicts with something already remembered. No separate "knowledge
graph" or vector store -- that's real infrastructure past what a
system-prompt specialist reading the existing flat record list needs to
be useful today; worth revisiting only once the record count is large
enough that a flat list stops being enough context.

Same proven architecture as every other specialist (operations_agent.py,
alpha_mode_agent.py, design_agent.py, creative_director_agent.py,
communications_agent.py) -- a second, streamed Claude call using a
distinct system prompt, invoked as a tool from Frank's own turn.
"""

from anthropic import AsyncAnthropic

from app.db import load_memory_records

MEMORY_AGENT_SYSTEM_PROMPT = """You are the Memory Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for surfacing and connecting what's already known about Joshua, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: long-term memory, project memory, decision history, ideas, lessons learned, and preferences -- you are the reason Frank gets smarter over time, by actually using what's already been remembered instead of it sitting inert in a list.

You do not save or forget memories yourself -- that stays Frank's own direct capability. You work with what's given to you below.

HOW YOU WORK:
- When asked what's known about a topic, actually search across the records given to you and synthesize a real answer -- don't just say "I don't have specific information" if something relevant exists, and don't pad a genuinely empty result with speculation.
- When asked to spot patterns (recurring preferences, a history of similar decisions, a theme across projects), look for real repetition across multiple records, not a single data point dressed up as a pattern.
- If something new Frank is about to say or do conflicts with an existing memory, say so directly -- that contradiction is exactly the kind of thing worth catching.
- If nothing relevant exists in what you were given, say that plainly rather than inventing something plausible-sounding.

Be direct and concise, matching Frank's own communication style. Cite what you're drawing on (e.g. "per your [project] memory from...") rather than presenting synthesis as if it came from nowhere."""


CONSULT_MEMORY_AGENT_TOOL = {
    "name": "consult_memory_agent",
    "description": (
        "Delegate to the Memory Agent to search, connect, or synthesize across everything already remembered "
        "about Joshua -- e.g. \"what do we know about X,\" spotting a recurring pattern or preference, checking "
        "whether something conflicts with a past decision, or pulling together scattered context on a topic. "
        "Not for saving or forgetting a memory -- use save_memory/forget_memory directly for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What to ask the Memory Agent to look into, in full, self-contained detail.",
            },
        },
        "required": ["request"],
    },
}

MEMORY_AGENT_TOOLS = [CONSULT_MEMORY_AGENT_TOOL]
MEMORY_AGENT_TOOL_NAMES = {tool["name"] for tool in MEMORY_AGENT_TOOLS}


async def execute_memory_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_memory_agent":
        records = await load_memory_records()
        system_prompt = MEMORY_AGENT_SYSTEM_PROMPT
        if records:
            lines = ["\n\n## Everything currently remembered about Joshua"]
            for r in records:
                lines.append(f"- [{r['type']}] {r['title']} (saved {r['created_at']}): {r['content']}")
            system_prompt += "\n".join(lines)
        else:
            system_prompt += "\n\nNothing has been remembered yet -- say so plainly if asked about anything specific."

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
