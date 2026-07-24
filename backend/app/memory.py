"""
Frank's first tool. Deliberately one narrow, hardcoded action — save a typed
memory record to SQLite — via the plain `anthropic` SDK's tool-use (function
calling). This is NOT the Claude Agent SDK deferred elsewhere in the project:
no file access, no shell, no CLI dependency, just one fixed function Frank
can call, same risk category as any other backend code path. Confirmed
decision with Joshua (2026-07-24): Frank should be able to save memories
proactively, mid-conversation, without being asked — matching the founder
brief's "name patterns unprompted" mandate — rather than requiring Joshua to
trigger every save himself.
"""

from app.db import load_memory_records, save_memory_record

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Save a durable fact, preference, or piece of context about Joshua "
        "for future conversations — not routine conversational content. Use "
        "this proactively when you learn something worth remembering long-term, "
        "without waiting to be asked."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": (
                    "user: a durable fact or preference about Joshua. "
                    "feedback: guidance on how you should behave, given or confirmed by Joshua. "
                    "project: state of an ongoing initiative or goal. "
                    "reference: a pointer to where something lives in an external system."
                ),
            },
            "title": {
                "type": "string",
                "description": "Short label for this memory.",
            },
            "content": {
                "type": "string",
                "description": "The memory itself, written so it stands alone later.",
            },
            "sensitive": {
                "type": "boolean",
                "description": "True if this touches marriage, health, or finances.",
            },
        },
        "required": ["type", "title", "content"],
    },
}


async def build_memory_block() -> str:
    records = await load_memory_records()
    if not records:
        return ""
    lines = ["\n\n## What you already remember about Joshua"]
    for record in records:
        lines.append(f"- [{record['type']}] {record['title']}: {record['content']}")
    return "\n".join(lines)


async def execute_tool_call(name: str, tool_input: dict) -> str:
    if name == "save_memory":
        await save_memory_record(
            type=tool_input["type"],
            title=tool_input["title"],
            content=tool_input["content"],
            sensitive=tool_input.get("sensitive", False),
        )
        return "Saved."
    return f"Unknown tool: {name}"
