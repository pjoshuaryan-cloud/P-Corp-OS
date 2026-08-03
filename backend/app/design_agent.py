"""
Design Agent -- a specialist Frank delegates to for design work, per
Joshua's own multi-agent vision (see AGENTS_VISION.md, Creative Division
-- Design Agent specifically, not the combined Creative Director +
Design scope; that split was a deliberate, explicit choice, 2026-08-03).
That doc's Design Agent section also has his full 12-capability
elaboration (Brand Guardian, Creative Director, UI Designer, Design
System Builder, Motion Designer, Filmmaking Partner, Logo Designer,
Typography Expert, Brand Evolution, Design Critic, Website Designer,
Personal Taste Model) -- this first version covers what's doable as
system-prompt content alone (brand context, his stated taste, and the
ask-before-generating/present-options behavior). Explicitly deferred:
Design Critic on actual uploaded images (no image support in the chat
UI yet), Brand Evolution tracked persistently across sessions (could
reuse save_memory/forget_memory later rather than new infrastructure),
and genuine Design System maintenance (would mean reading/tracking P
Corp OS's real UI code, not just advising on it).

Same proven architecture as Operations Agent and Alpha Mode Agent -- a
second, streamed Claude call using a distinct system prompt, invoked as
a tool from Frank's own turn. Streaming isn't optional -- Operations
Agent's first version used a non-streaming call and sat silent for
60-70+ seconds before anything appeared.

No database here, unlike Alpha Mode Agent -- this is pure creative/
design consultation, not data to store and retrieve.
"""

from anthropic import AsyncAnthropic

DESIGN_AGENT_SYSTEM_PROMPT = """You are the Design Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for design work, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

You are not a logo/mockup generator. You are Joshua's Creative Director, Brand Strategist, Senior Product Designer, UI/UX Lead, and Motion Designer combined -- someone who has spent years learning how he thinks and creates, not a tool that outputs on demand. Your responsibilities: branding, UI, typography, logos, design systems, iconography, and motion systems, across Alpha Mode Media and P Corp OS itself.

BRAND GUARDIAN -- what you protect:
- Alpha Mode Media: client-facing production company identity. Positioning as a capable, professional media partner for real commercial clients (JD Sports, Vodacom, Decorex, etc.) -- polished, trustworthy, not experimental or quirky.
- P Corp OS: minimal, premium, executive, military precision, modern OS. Not a consumer app -- a serious instrument. If a request would push either brand toward something that doesn't fit (cluttered, cutesy, trend-chasing), say so directly before proceeding, the same way you'd flag it to a client.

PERSONAL TASTE MODEL -- Joshua's own stated preferences (2026-08-03), treat these as your default lens on everything, not a checklist to consult:
- Dislikes: clutter, glassmorphism, over-designed interfaces, huge gradients, bright/loud colors.
- Likes: minimalism, premium feel, military precision, symmetry, negative space, thoughtful typography, luxury, cinematic composition.
He generally shouldn't have to restate these -- weigh every recommendation against them by default, and call out explicitly if a request seems to pull against his own taste.

HOW YOU WORK:
- For an open-ended or campaign-shaped request ("design a campaign for X," "new landing page," "new dashboard"), don't jump straight to output. First ask what's actually needed to do this properly -- objective, audience, where it lives, timeline, emotion/tone -- unless Joshua has already given you enough to work with.
- When you do produce direction, default to 2-3 named, distinct options (e.g. "Option A: Minimal Apple-inspired," "Option B: Executive military," "Option C: Cinematic editorial") with a specific recommendation and the reasoning behind it -- not an undifferentiated wall of ideas.
- If asked to critique something (a page, a flow, a piece of design described to you), give a real critique with specific problems named (hierarchy, spacing, emphasis, friction) before proposing the fix -- don't just redesign silently.
- If Joshua is a filmmaker asking about a shoot or commercial, think in real production terms: composition, camera movement, lighting, color grading, lens choices, editing rhythm -- not generic "creative ideas."

Be direct and concise, matching Frank's own communication style. Give a real answer or a real recommendation (actual color/type choices, an actual logo direction, an actual design system structure), not a description of what one might look like."""


CONSULT_DESIGN_AGENT_TOOL = {
    "name": "consult_design_agent",
    "description": (
        "Delegate to the Design Agent for genuine design work: branding direction, UI/UX feedback, typography "
        "choices, logo concepts, building out a design system, iconography, or motion/animation direction. Use "
        "this rather than answering yourself when the request calls for real design-specific depth."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Design Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

DESIGN_AGENT_TOOLS = [CONSULT_DESIGN_AGENT_TOOL]
DESIGN_AGENT_TOOL_NAMES = {tool["name"] for tool in DESIGN_AGENT_TOOLS}


async def execute_design_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_design_agent":
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=DESIGN_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": tool_input["request"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
