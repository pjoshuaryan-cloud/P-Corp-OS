"""
Frank's tools for goals/habits (app/personal_db.py) -- same shape as
app/memory.py's save_memory/forget_memory and app/operations_agent.py's
task tools: narrow, hardcoded actions via the plain SDK's tool-use, not
general agentic capability. Classified "regular" under SECURITY.md's
permission model -- local-only, reversible (status is overwritten or
soft-deleted, nothing destroyed), no external effect.

Deliberately no consult_personal_agent tool here, unlike Operations/
Alpha Mode -- see personal_db.py's own docstring for why. build_personal_block()
below folds the current goals/habits into Frank's own system prompt
directly (same mechanism as build_operations_block()), so Frank has
real context without needing a delegated specialist to relay it.
"""

from app.personal_db import add_goal, add_habit, delete_goal, delete_habit, summarize, update_goal_status

ADD_GOAL_TOOL = {
    "name": "add_goal",
    "description": "Record a new personal goal Joshua mentions -- not tied to any business.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The goal itself."},
            "target_date": {"type": "string", "description": "When it's targeted for, e.g. \"2026-12-31\". Omit if unclear."},
            "notes": {"type": "string", "description": "Any relevant context."},
        },
        "required": ["title"],
    },
}

UPDATE_GOAL_STATUS_TOOL = {
    "name": "update_goal_status",
    "description": "Update an existing goal's status -- e.g. mark it done or abandoned. Matches by title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The goal's title, or a close match."},
            "new_status": {"type": "string", "description": "e.g. \"done\", \"abandoned\", \"active\"."},
        },
        "required": ["identifier", "new_status"],
    },
}

DELETE_GOAL_TOOL = {
    "name": "delete_goal",
    "description": "Remove a goal that shouldn't have existed at all -- test data, a mistaken entry, a duplicate. Matches by title. Not for goals that are simply achieved or dropped -- use update_goal_status for those.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The goal's title, or a close match."},
        },
        "required": ["identifier"],
    },
}

ADD_HABIT_TOOL = {
    "name": "add_habit",
    "description": "Record a new habit Joshua wants to track -- not tied to any business.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The habit itself."},
            "cadence": {"type": "string", "description": "How often, e.g. \"daily\", \"weekly\". Omit if unclear."},
            "notes": {"type": "string", "description": "Any relevant context."},
        },
        "required": ["title"],
    },
}

DELETE_HABIT_TOOL = {
    "name": "delete_habit",
    "description": "Stop tracking a habit -- Joshua no longer wants it tracked, or it was a mistaken entry. Matches by title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The habit's title, or a close match."},
        },
        "required": ["identifier"],
    },
}

PERSONAL_TOOLS = [ADD_GOAL_TOOL, UPDATE_GOAL_STATUS_TOOL, DELETE_GOAL_TOOL, ADD_HABIT_TOOL, DELETE_HABIT_TOOL]
PERSONAL_TOOL_NAMES = {tool["name"] for tool in PERSONAL_TOOLS}


async def build_personal_block() -> str:
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## Goals & habits\n{snapshot}"


async def execute_personal_tool_call(name: str, tool_input: dict) -> str:
    if name == "add_goal":
        result = await add_goal(tool_input["title"], tool_input.get("target_date"), tool_input.get("notes"))
        return f"Added goal: {result}"
    if name == "update_goal_status":
        updated = await update_goal_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated goal status to {tool_input['new_status']}."
        return f"No matching goal found for \"{tool_input['identifier']}\"."
    if name == "delete_goal":
        deleted_title = await delete_goal(tool_input["identifier"])
        if deleted_title:
            return f"Deleted goal: {deleted_title}"
        return f"No matching goal found for \"{tool_input['identifier']}\"."
    if name == "add_habit":
        result = await add_habit(tool_input["title"], tool_input.get("cadence"), tool_input.get("notes"))
        return f"Added habit: {result}"
    if name == "delete_habit":
        deleted_title = await delete_habit(tool_input["identifier"])
        if deleted_title:
            return f"Stopped tracking habit: {deleted_title}"
        return f"No matching habit found for \"{tool_input['identifier']}\"."
    return f"Unknown tool: {name}"
