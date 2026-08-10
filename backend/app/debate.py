"""
AI Debate (2026-08-10, from the additive feature spec, scope confirmed
with Joshua before building): pressure-test a real decision he's
weighing, before he commits to it -- complementary to Decision Journal
(app/decision_journal.py), which records a decision after it's made.

Scoped to the version he picked: Frank argues the strongest case for,
then the strongest case against, then gives his own honest verdict --
not two persona agents debating each other back and forth over several
turns (a bigger, different feature, explicitly not chosen).

Same proven architecture as Operations/Design/Creative Director/
Communications/Memory/Research Agent -- a second, streamed Claude call
using a distinct system prompt, invoked as a tool from Frank's own turn.
Not registered as a specialist "agent" in agents_registry.py, though:
this isn't a domain of expertise Frank delegates to, it's a structured
response format applied to whatever decision Joshua names -- a real
architectural difference from every other consult_X_agent tool, not an
oversight.

No database here, same reasoning as Design Agent -- nothing to store or
retrieve, just a real answer generated on request. If a debated decision
lands somewhere real, Joshua can ask Frank to log_decision separately;
no special glue code links the two, since Frank already has both tools
available in the same turn.
"""

from anthropic import AsyncAnthropic

DEBATE_SYSTEM_PROMPT = """You are Frank's own rigorous devil's-advocate mode inside P Corp OS, invoked when Joshua wants a real decision pressure-tested before he commits to it -- not a persona Joshua addresses directly, and not a chance to hedge.

Structure your answer in exactly three labeled sections:

**The case for:** The strongest, most convincing argument in favor -- steelmanned, not a strawman. Argue it like you actually believe it and have to win.

**The case against:** The strongest, most convincing argument against -- equally steelmanned. Don't soften this to make the decision look easier than it is; the whole point is surfacing real risk and real counterarguments Joshua might not have weighed yet.

**My honest take:** Your own actual verdict, stated plainly -- which way you'd lean and why, given everything above. Not "it depends" or "both sides have merit" -- a real position, even though it's necessarily a judgment call. If the honest answer is "too close to call without more information," say that specifically, naming what information would tip it, rather than a vague non-answer.

Be direct and concise, matching Frank's own communication style throughout. This only works if both sides are argued with real intellectual honesty -- a debate where one side is obviously weaker than the other has failed at the one thing it's for."""


DEBATE_DECISION_TOOL = {
    "name": "debate_decision",
    "description": (
        "Pressure-test a real decision Joshua is weighing, before he commits to it -- argues the strongest case "
        "for, the strongest case against, then gives an honest verdict. Use this when he explicitly wants a "
        "decision debated, challenged, or pressure-tested, not for routine questions with an obvious answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "description": "The real decision or question to debate, in full, self-contained detail.",
            },
        },
        "required": ["decision"],
    },
}

DEBATE_TOOLS = [DEBATE_DECISION_TOOL]
DEBATE_TOOL_NAMES = {tool["name"] for tool in DEBATE_TOOLS}


async def execute_debate_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "debate_decision":
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=DEBATE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": tool_input["decision"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
