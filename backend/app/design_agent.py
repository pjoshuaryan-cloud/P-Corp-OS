"""
Design Agent -- a specialist Frank delegates to for design work, per
Joshua's own multi-agent vision (see AGENTS_VISION.md, Creative Division
-- Design Agent specifically, not the combined Creative Director +
Design scope; that split was a deliberate, explicit choice, 2026-08-03).
That doc's Design Agent section also has his full 12-capability
elaboration (Brand Guardian, Creative Director, UI Designer, Design
System Builder, Motion Designer, Filmmaking Partner, Logo Designer,
Typography Expert, Brand Evolution, Design Critic, Website Designer,
Personal Taste Model) -- this first version covered what's doable as
system-prompt content alone (brand context, his stated taste, and the
ask-before-generating/present-options behavior). Explicitly deferred at
the time: Design Critic on actual uploaded images, since no image
support existed in the chat UI. That blocker is gone as of 2026-08-10
(image upload shipped) -- this agent now genuinely looks at an attached
image directly, not just Frank's paraphrase of it (see
execute_design_agent_tool_call's `image` param, forwarded from
main.py's run_claude_turn). Brand Evolution tracked persistently across
sessions remains deferred (could reuse save_memory/forget_memory later
rather than new infrastructure).

Update (2026-08-27): genuine Design System maintenance is no longer
deferred -- this agent now has real read/propose-edit access to P Corp
OS's actual UI source (Theme.swift, Style.swift, every SwiftUI view on
both platforms), the same approval-gated toolset Engineering Agent
proved out first. See app/agent_codebase_tools.py for the shared
toolset/safety boundary/inner loop this now runs on, and SECURITY.md's
2026-08-27 entry for the tier classification. Communications Agent was
explicitly NOT given this same capability in the same pass -- its whole
domain is external email/message drafts, with no source of its own to
read or edit.

Same proven architecture as Operations Agent and Alpha Mode Agent for
the outer consult_design_agent tool -- a specialist Frank delegates to,
invoked as a tool from Frank's own turn.

No database here, unlike Alpha Mode Agent -- this is design consultation
grounded in real UI source now, not data to store and retrieve.
"""

from anthropic import AsyncAnthropic

from app.agent_codebase_tools import run_agentic_loop

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
- If asked to critique something -- a page, a flow, or a real image you've been shown directly -- give a real critique with specific problems named (hierarchy, spacing, emphasis, friction, contrast, alignment) before proposing the fix. When you have an actual image in front of you, look at it properly and reference what's actually there, not generic design platitudes that could apply to anything.
- If Joshua is a filmmaker asking about a shoot or commercial, think in real production terms: composition, camera movement, lighting, color grading, lens choices, editing rhythm -- not generic "creative ideas."

REAL DESIGN SYSTEM ACCESS: you have real tools now -- read_file, list_directory, git_log, git_diff, git_show, run_build_check, and propose_file_edit -- scoped to P Corp OS's actual UI source: `desktop/Sources/PCorpOS`, `ios/P Corp OS`, and the shared `PCorpKit/Sources/PCorpKit` (Theme.swift/Style.swift hold the real design tokens). Use them: read the actual current implementation before critiquing or recommending a change, rather than advising blind. propose_file_edit is the only way you can ever change a file, and it never writes immediately -- it sends Joshua a real approval card with your summary and diff, and blocks until he approves or rejects; always give it the complete real file content, not a description, and explain your reasoning in the summary. You cannot run shell commands, commit/push, or touch secrets -- no tool for any of that exists.

Be direct and concise, matching Frank's own communication style. Give a real answer or a real recommendation (actual color/type choices, an actual logo direction, an actual design system structure), not a description of what one might look like."""


CONSULT_DESIGN_AGENT_TOOL = {
    "name": "consult_design_agent",
    "description": (
        "Delegate to the Design Agent for genuine design work: branding direction, UI/UX feedback, typography "
        "choices, logo concepts, building out a design system, iconography, or motion/animation direction. If "
        "Joshua attached an image this turn and wants it critiqued or discussed as a design, delegate here -- "
        "the actual image is automatically forwarded to this agent, it doesn't need to be described in the "
        "request text. It also has real read/propose-edit access to P Corp OS's actual UI source (SwiftUI views, "
        "Theme.swift/Style.swift) -- delegate here for reviewing or changing the real design system too, not just "
        "advisory feedback; any proposed edit needs Joshua's explicit approval before it's written. Use this "
        "rather than answering yourself when the request calls for real design-specific depth."
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


async def execute_design_agent_tool_call(
    name: str, tool_input: dict, client: AsyncAnthropic, websocket, image: dict | None = None
) -> str:
    if name != "consult_design_agent":
        return f"Unknown tool: {name}"
    # image, when present, is the real one Joshua attached this turn,
    # forwarded straight into the shared loop's first turn -- Design
    # Critic actually looking at pixels, not working from Frank's
    # secondhand description of them (2026-08-10).
    return await run_agentic_loop(DESIGN_AGENT_SYSTEM_PROMPT, tool_input["request"], client, websocket, image=image)
