"""
Alpha Mode Agent -- Frank's second delegated specialist (Operations was
the first, 2026-07-31). Dedicated entirely to Alpha Mode Media, per
Joshua's own multi-agent vision (see AGENTS_VISION.md): CRM, clients,
proposals, invoices, crew, equipment, suppliers, shoots, deliverables,
marketing calendar, reporting.

Same proven architecture as Operations Agent -- a second, streamed
Claude call using a distinct system prompt, given the current Alpha
Mode Media business snapshot as context, invoked as a tool from Frank's
own turn. Streaming isn't optional here: Operations Agent's first
version used a non-streaming call and a real multi-phase document sat
completely silent for 60-70+ seconds before anything appeared -- built
correctly from the start this time rather than repeating that bug.

The concrete CRUD tools (add_client, log_client_contact, etc.) live in
alpha_mode_tools.py, not here -- this file is purely the consult/
delegation half, mirroring how operations_agent.py's own two roles
(data tools vs. the consult tool) split conceptually even though that
file keeps both in one place.
"""

from anthropic import AsyncAnthropic

from app.alpha_mode_db import summarize

ALPHA_MODE_AGENT_SYSTEM_PROMPT = """You are the Alpha Mode Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for Alpha Mode Media business work, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: CRM, clients, proposals, invoices, crew, equipment, suppliers, shoots, deliverables, marketing calendar, and reporting for Alpha Mode Media specifically -- Joshua's media production business. Think like a genuinely capable producer/account manager -- concrete, practical, oriented toward what actually gets executed and what actually wins/retains a client, not generic business platitudes.

CRITICAL FRAMING, confirmed directly by Joshua (2026-08-02): he is a co-founder of Alpha Mode Media, not an outside party dealing with it, and not the company itself. You act ON HIS BEHALF as a co-founder running the business -- never as a neutral third party, and never treating Alpha Mode Media itself as a client, vendor, or counterparty to be managed. Every "client" is someone Alpha Mode Media does business with; Alpha Mode Media is never its own client.

Be direct and concise, matching Frank's own communication style. Give a real answer or a real draft (an actual proposal outline, an actual outreach message, an actual report), not a description of what one might look like."""


CONSULT_ALPHA_MODE_AGENT_TOOL = {
    "name": "consult_alpha_mode_agent",
    "description": (
        "Delegate to the Alpha Mode Agent for genuine Alpha Mode Media business work: drafting a proposal, "
        "planning the marketing calendar, writing a client report, thinking through crew/equipment/supplier "
        "logistics for a shoot, or drafting outreach copy for a specific client. Use this rather than answering "
        "yourself when the request calls for real business-specific depth. Not for simple record-keeping -- use "
        "add_client/add_project/add_invoice/add_deliverable/log_client_contact directly for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Alpha Mode Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

ALPHA_MODE_AGENT_TOOLS = [CONSULT_ALPHA_MODE_AGENT_TOOL]
ALPHA_MODE_AGENT_TOOL_NAMES = {tool["name"] for tool in ALPHA_MODE_AGENT_TOOLS}


async def execute_alpha_mode_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_alpha_mode_agent":
        business_context = await summarize()
        system_prompt = ALPHA_MODE_AGENT_SYSTEM_PROMPT
        if business_context:
            system_prompt += f"\n\n## Alpha Mode Media — current business snapshot\n{business_context}"

        # Streamed live, same reasoning as Operations Agent -- see this
        # file's module docstring.
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
