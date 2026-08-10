"""
Focus Lock -- a real, settable "current objective," deliberately scoped
small (2026-08-10, from the additive feature spec's Focus Lock section,
confirmed scope with Joshua before building): just makes War Room's
"Focus: ..." line real instead of a static placeholder. No on/off mode,
no context-switch detection, no automatic deprioritization of anything
-- those need Frank's own reasoning to change based on this state, real
behavioral scope well beyond "make one line real," and the
context-switch-detection half overlaps with Shadow Mode's much harder,
still-unscoped observation problem.

Same "regular" permission tier as save_memory (SECURITY.md): local-only,
reversible, no external effect -- setting a new objective just
overwrites the old one, nothing is lost or hard to undo.
"""

from app.db import set_focus_objective

SET_FOCUS_OBJECTIVE_TOOL = {
    "name": "set_focus_objective",
    "description": (
        "Set Joshua's current primary objective, shown on the War Room's Mission Status card. Use this when he "
        "tells you what he's focused on right now, or asks you to set/update it directly. Always overwrites "
        "whatever objective was set before -- there's no history, just the current one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "The current primary objective, stated plainly, e.g. \"Finish trading robot V1\"."},
        },
        "required": ["objective"],
    },
}

FOCUS_TOOLS = [SET_FOCUS_OBJECTIVE_TOOL]
FOCUS_TOOL_NAMES = {tool["name"] for tool in FOCUS_TOOLS}


async def execute_focus_tool_call(name: str, tool_input: dict) -> str:
    if name == "set_focus_objective":
        await set_focus_objective(tool_input["objective"])
        return f"Focus set: {tool_input['objective']}"
    return f"Unknown tool: {name}"
