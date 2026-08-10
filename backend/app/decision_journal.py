"""
Decision Journal -- capture-only first pass (2026-08-10, from the
additive feature spec, scope confirmed with Joshua before building):
a real `log_decision` tool and its own table, nothing else. No UI view,
no automatic surfacing into Frank's context yet -- same shape as audit
logging's own first pass, deliberately: get real data flowing before
deciding what to do with it once there's some to look at.

Same "regular" permission tier as save_memory (SECURITY.md): local-only,
reversible, no external effect.
"""

from app.db import log_decision

LOG_DECISION_TOOL = {
    "name": "log_decision",
    "description": (
        "Record a real decision Joshua has just made, for a permanent journal. Use this when he tells you what "
        "he decided, or asks you to log a decision directly -- not for routine/reversible choices, but for things "
        "worth remembering he chose and why. Reasoning and alternatives are optional -- include them when he's "
        "actually stated them, don't invent them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "description": "What was decided, stated plainly."},
            "reasoning": {"type": "string", "description": "Why, if stated."},
            "alternatives": {"type": "string", "description": "What else was considered, if stated."},
        },
        "required": ["decision"],
    },
}

DECISION_JOURNAL_TOOLS = [LOG_DECISION_TOOL]
DECISION_JOURNAL_TOOL_NAMES = {tool["name"] for tool in DECISION_JOURNAL_TOOLS}


async def execute_decision_journal_tool_call(name: str, tool_input: dict) -> str:
    if name == "log_decision":
        await log_decision(tool_input["decision"], tool_input.get("reasoning"), tool_input.get("alternatives"))
        return f"Decision logged: {tool_input['decision']}"
    return f"Unknown tool: {name}"
