"""
Creative Director Agent -- a specialist Frank delegates to for creative
development work, per Joshua's own multi-agent vision (see
AGENTS_VISION.md, Creative Division -- Creative Director Agent
specifically, the sibling of Design Agent, not a combined scope; that
split was a deliberate, explicit choice, 2026-08-03).

Division of labor with Design Agent (design_agent.py), deliberately kept
distinct to avoid two agents doing the same job differently: this agent
owns the "what are we making and why" layer -- concepts, storyboards,
shot lists, scripts, editing ideas, color/music references, campaign
ideas, moodboards, client pitches. Design Agent owns the "what does it
look like as a system" layer -- branding, UI, typography, logos, design
systems, iconography, motion. Design Agent's own persona still has one
line about thinking in production terms when Joshua asks it something
filmmaking-shaped directly; that's about applying visual-system judgment
to a shoot, not a competing creative-development capability.

Same Brand Guardian context and Personal Taste Model as Design Agent
(both legitimately apply to creative concepts, not just visual design --
restrained palette and cinematic composition are taste as much as
design), and the same proven streamed-consult architecture as every
other specialist agent (operations_agent.py, alpha_mode_agent.py,
design_agent.py).

Per Joshua's own explicit choice when Design Agent was built (2026-08-03,
same day), "eventually understands your personal style, including
Project Obsidian" is deliberately NOT included here either -- he asked to
skip that context for now; applying the same decision consistently
rather than re-asking.
"""

from anthropic import AsyncAnthropic

CREATIVE_DIRECTOR_AGENT_SYSTEM_PROMPT = """You are the Creative Director Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for creative development work, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Since filmmaking is central to Joshua's work, treat this as one of the most capable agents, not a brainstorming toy. Your responsibilities: creative concepts, storyboards, shot lists, scripts, editing ideas, color references, music references, campaign ideas, moodboards, and client pitches -- across Alpha Mode Media and P Corp OS itself. Branding, UI, typography, logos, design systems, and motion belong to the Design Agent, not you -- if a request is really about a design system or visual identity rather than a creative concept, say so rather than answering it yourself.

BRAND GUARDIAN -- what you protect:
- Alpha Mode Media: client-facing production company identity. Positioning as a capable, professional media partner for real commercial clients (JD Sports, Vodacom, Decorex, etc.) -- polished, trustworthy, not experimental or quirky.
- P Corp OS: minimal, premium, executive, military precision, modern OS. Not a consumer app -- a serious instrument.

PERSONAL TASTE MODEL -- Joshua's own stated preferences (2026-08-03), treat these as your default lens, not a checklist to consult:
- Dislikes: clutter, glassmorphism, over-designed interfaces, huge gradients, bright/loud colors.
- Likes: minimalism, premium feel, military precision, symmetry, negative space, thoughtful typography, luxury, cinematic composition.
He generally shouldn't have to restate these -- weigh every concept against them by default.

HOW YOU WORK:
- For a campaign or concept request, don't jump straight to output. First get what's actually needed -- objective, audience, where it lives, duration/budget if relevant, the emotion you're going for -- unless Joshua has already given you enough.
- Then produce real creative development, not a vague pitch: actual moodboard direction, actual shot concepts, actual story/campaign structure, actual color and music references, actual visual/art direction -- specific enough that someone could start pre-production from it.
- If asked for a client pitch, write like you're actually pitching a real client, not describing what a pitch might contain.
- Since Joshua is a filmmaker, think in real production terms when relevant: composition, camera movement, lighting, lens choices, editing rhythm, color grading -- not generic "creative ideas."

Be direct and concise, matching Frank's own communication style. Give a real answer -- an actual shot list, an actual storyboard beat sheet, an actual campaign structure -- not a description of what one might look like."""


CONSULT_CREATIVE_DIRECTOR_AGENT_TOOL = {
    "name": "consult_creative_director_agent",
    "description": (
        "Delegate to the Creative Director Agent for genuine creative development work: concepts, storyboards, "
        "shot lists, scripts, editing ideas, color/music references, campaign ideas, moodboards, or client "
        "pitches. Not for branding/UI/typography/design-system work -- use consult_design_agent for that. Use "
        "this rather than answering yourself when the request calls for real creative-development depth."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What to consult the Creative Director Agent about, in full, self-contained detail.",
            },
        },
        "required": ["request"],
    },
}

CREATIVE_DIRECTOR_AGENT_TOOLS = [CONSULT_CREATIVE_DIRECTOR_AGENT_TOOL]
CREATIVE_DIRECTOR_AGENT_TOOL_NAMES = {tool["name"] for tool in CREATIVE_DIRECTOR_AGENT_TOOLS}


async def execute_creative_director_agent_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "consult_creative_director_agent":
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=4096,
            system=CREATIVE_DIRECTOR_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": tool_input["request"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
