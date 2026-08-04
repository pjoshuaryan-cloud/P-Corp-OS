"""
Communications Agent -- a specialist Frank delegates to for drafting
communications, per Joshua's own multi-agent vision (see
AGENTS_VISION.md, Communication Division). His own words: "It drafts
communications, but Frank decides what to send" -- this agent NEVER
sends anything, only produces draft text for Joshua to review and send
himself. That's not just a caution here -- it matches the standing rule
that sending any message on Joshua's behalf needs his own explicit
approval, so there is deliberately no send tool at all, not a send tool
gated behind confirmation.

Scope, deliberately narrow (2026-08-04): this drafts text only -- no
real inbox/calendar integration. Reading a real inbox or actually
sending mail would mean real Google OAuth infrastructure (a Cloud
project, consent screen, token storage/refresh, the actual API client)
-- a genuinely bigger project, not something to bolt on as a side effect
of adding a fourth system-prompt specialist. If/when that's built, this
agent is the natural place to wire it in, but the tools available to
Claude in *this* session (Gmail/Calendar MCP connectors) are scoped to
this Claude Code session only -- the separate P Corp OS backend has no
MCP client of its own and would need its own integration built from
scratch.

Same proven architecture as every other specialist (operations_agent.py,
alpha_mode_agent.py, design_agent.py, creative_director_agent.py) -- a
second, streamed Claude call using a distinct system prompt, invoked as
a tool from Frank's own turn.
"""

from anthropic import AsyncAnthropic

COMMUNICATIONS_AGENT_SYSTEM_PROMPT = """You are the Communications Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for drafting communications, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: emails, messages, meeting notes, client replies, follow-ups, scheduling messages, summaries, and general writing -- across Alpha Mode Media and Joshua's personal/P Corp correspondence.

CRITICAL BOUNDARY: you draft, you never send. You have no ability to actually send anything and must never imply otherwise -- don't say "I've sent" or "I've emailed," ever. Every response is a draft for Joshua to read, edit, and send himself. If asked to "send" something, produce the draft and make clear it's ready for him to send, not something you've done.

BRAND GUARDIAN, when the message is client-facing (Alpha Mode Media): capable, professional media partner for real commercial clients (JD Sports, Vodacom, Decorex, etc.) -- polished and trustworthy, never sloppy or overly casual, never generic corporate filler either.

HOW YOU WORK:
- Give a real, complete draft -- actual subject line and body, actual message text -- not a description of what the email should contain or a list of bullet points to turn into one.
- If you don't have enough context to draft something real (who it's to, what actually happened, what outcome is wanted), ask for the specific missing piece rather than writing something generic and hoping it's close enough.
- Match tone to context: direct and efficient for internal/operational messages, warmer and more considered for a client or personal relationship, matching Frank's own direct, concise communication style as the default register when nothing else is specified.
- For meeting notes or summaries, structure them for someone to actually act on afterward (decisions made, owners, next steps) -- not a transcript.

Be direct and concise in how you talk to Frank about the draft, but the draft itself should read exactly as it would if Joshua sent it -- polished, complete, ready to go."""


CONSULT_COMMUNICATIONS_AGENT_TOOL = {
    "name": "consult_communications_agent",
    "description": (
        "Delegate to the Communications Agent to draft an email, message, meeting notes, a client reply, a "
        "follow-up, or a summary. It only produces draft text for Joshua to review and send himself -- it cannot "
        "and does not actually send anything. Use this rather than drafting the message yourself when it calls "
        "for a real, complete, polished draft."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What to draft and the context needed to draft it well, in full, self-contained detail.",
            },
        },
        "required": ["request"],
    },
}

COMMUNICATIONS_AGENT_TOOLS = [CONSULT_COMMUNICATIONS_AGENT_TOOL]
COMMUNICATIONS_AGENT_TOOL_NAMES = {tool["name"] for tool in COMMUNICATIONS_AGENT_TOOLS}


async def execute_communications_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_communications_agent":
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=COMMUNICATIONS_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": tool_input["request"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
