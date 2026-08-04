"""
Single source of truth for "what agents exist," read by GET /agents so the
desktop shell's Agents section can render a real, current list instead of a
hardcoded SwiftUI card per agent (fixed 2026-08-04 -- until now only
Operations Agent had a card at all; Alpha Mode Agent and Design Agent
weren't represented in the UI despite being real, working specialists).

Adding a new specialist agent module (like operations_agent.py,
alpha_mode_agent.py, design_agent.py) should mean adding exactly one entry
here -- the Agents tab picks it up on next fetch with no further UI code
changes. This is deliberately plain data, not derived by introspecting the
tool schemas in main.py's `tools=[...]` list -- those are shaped for
Claude's tool-use API (name/description/input_schema), not for a human-
readable card (icon, short tagline, longer explanation), and conflating the
two would make either worse.
"""

AGENTS = [
    {
        "id": "operations",
        "name": "Operations Agent",
        "icon": "checklist",
        "tagline": "SOPs, workflows, project planning, bottlenecks, automation",
        "detail": (
            "Ask Frank to draft an SOP, plan a project, spot a bottleneck, or suggest an automation -- he "
            "decides when to consult this agent rather than answering directly."
        ),
        "status": "active",
    },
    {
        "id": "alpha_mode",
        "name": "Alpha Mode Agent",
        "icon": "briefcase",
        "tagline": "CRM, projects, invoices, crew, equipment, marketing calendar",
        "detail": (
            "Ask Frank to add a project, update an invoice, draft a proposal, or plan the marketing calendar "
            "for Alpha Mode Media -- projects and invoices write live into the real Alpha Mode Media Admin app."
        ),
        "status": "active",
    },
    {
        "id": "design",
        "name": "Design Agent",
        "icon": "paintpalette",
        "tagline": "Branding, UI, typography, logos, design systems, motion",
        "detail": (
            "Ask Frank to direct a campaign, critique a design, choose typography, or build out a design "
            "system -- it asks clarifying questions first and applies your brand and taste context automatically."
        ),
        "status": "active",
    },
    {
        "id": "creative_director",
        "name": "Creative Director Agent",
        "icon": "film",
        "tagline": "Concepts, storyboards, shot lists, scripts, campaign ideas, client pitches",
        "detail": (
            "Ask Frank to develop a creative concept, storyboard a shoot, write a shot list, or draft a client "
            "pitch -- it asks what's actually needed first, then produces real creative development, not vague ideas."
        ),
        "status": "active",
    },
    {
        "id": "communications",
        "name": "Communications Agent",
        "icon": "envelope",
        "tagline": "Emails, messages, meeting notes, client replies, follow-ups, summaries",
        "detail": (
            "Ask Frank to draft an email, a client reply, meeting notes, or a follow-up -- it only writes drafts "
            "for you to review and send yourself, it never sends anything on its own."
        ),
        "status": "active",
    },
    {
        "id": "memory",
        "name": "Memory Agent",
        "icon": "brain",
        "tagline": "Long-term memory, decision history, patterns, preferences",
        "detail": (
            "Ask Frank what's already known about a topic, to spot a recurring pattern, or to check whether "
            "something conflicts with a past decision -- it searches everything actually remembered rather "
            "than guessing."
        ),
        "status": "active",
    },
]


async def list_agents() -> list[dict]:
    return AGENTS
