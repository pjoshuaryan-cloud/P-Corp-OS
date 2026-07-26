"""
Frank's tools — narrow, hardcoded actions via the plain `anthropic` SDK's
tool-use (function calling). This is NOT the Claude Agent SDK deferred
elsewhere in the project: no file access, no shell, no CLI dependency, just
fixed functions Frank can call, same risk category as any other backend code
path. Confirmed decision with Joshua (2026-07-24): Frank should be able to
save memories proactively, mid-conversation, without being asked — matching
the founder brief's "name patterns unprompted" mandate — rather than
requiring Joshua to trigger every save himself.

Both tools classified under SECURITY.md's permission model as "regular"
(auto-allowed, no confirmation needed): local-only, reversible, no external
effect. forget_memory is a soft-delete (app/db.py's deleted_at), not a real
DELETE, which is exactly what keeps it reversible enough for this tier — a
genuinely irreversible delete tool would need "needs confirmation" instead.
Any future tool with a real external effect (a trading action, sending an
email, anything leaving this device) must be classified here before it
ships, not defaulted into "regular" just because that's what existed so far.
"""

from app.db import forget_memory_by_title, load_memory_records, save_memory_record

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

FORGET_MEMORY_TOOL = {
    "name": "forget_memory",
    "description": (
        "Forget a previously saved memory that's no longer accurate or relevant — "
        "e.g. Joshua corrects something, a project completes, a fact turns out wrong "
        "or was only ever a test. Matches by the memory's title, as close to the "
        "original as you recall. Soft-deleted, not destroyed, but shouldn't be used "
        "casually — only when something genuinely should stop being remembered."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The title of the memory to forget.",
            },
        },
        "required": ["title"],
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
    if name == "forget_memory":
        forgotten_title = await forget_memory_by_title(tool_input["title"])
        if forgotten_title:
            return f"Forgot: {forgotten_title}"
        return "No matching memory found to forget."
    return f"Unknown tool: {name}"
