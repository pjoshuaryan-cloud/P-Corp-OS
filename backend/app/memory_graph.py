"""
Memory Graph -- linking-only first pass (2026-08-10, from the additive
feature spec, scope confirmed with Joshua before building): a real
`link_records` tool and its own edge table (`memory_links`), nothing
else. No traversal/query tool, no UI -- same capture-only shape as
Decision Journal's own first pass.

Frank never sees raw row IDs for memories or decisions (same reasoning
as forget_memory in memory.py), so both sides of a link are identified
by the text he already has -- a memory's title, or a decision's own
wording -- and resolved server-side the same way forget_memory_by_title
already does.

Same "regular" permission tier as save_memory (SECURITY.md): local-only,
reversible, no external effect.
"""

from app.db import link_records

LINK_RECORDS_TOOL = {
    "name": "link_records",
    "description": (
        "Connect two things already saved to memory or the decision journal with a labeled relationship (e.g. "
        "\"caused by\", \"led to\", \"related to\"). Use this when Joshua points out how two things connect, or "
        "you notice a real connection worth recording. Identify each side by the same title or wording you "
        "already have for it -- never a made-up ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "from_type": {"type": "string", "enum": ["memory", "decision"]},
            "from_text": {"type": "string", "description": "The memory's title, or the decision's own wording."},
            "to_type": {"type": "string", "enum": ["memory", "decision"]},
            "to_text": {"type": "string", "description": "The memory's title, or the decision's own wording."},
            "relationship": {
                "type": "string",
                "description": "How the two are related, stated plainly, e.g. \"caused by\".",
            },
        },
        "required": ["from_type", "from_text", "to_type", "to_text", "relationship"],
    },
}

MEMORY_GRAPH_TOOLS = [LINK_RECORDS_TOOL]
MEMORY_GRAPH_TOOL_NAMES = {tool["name"] for tool in MEMORY_GRAPH_TOOLS}


async def execute_memory_graph_tool_call(name: str, tool_input: dict) -> str:
    if name == "link_records":
        result = await link_records(
            tool_input["from_type"],
            tool_input["from_text"],
            tool_input["to_type"],
            tool_input["to_text"],
            tool_input["relationship"],
        )
        if result is None:
            return "Couldn't find one or both of those to link -- check the wording matches what was saved."
        return f"Linked: {result}"
    return f"Unknown tool: {name}"
