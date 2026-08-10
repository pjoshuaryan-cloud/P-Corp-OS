"""
Shadow Mode -- passive activity awareness (2026-08-10, from the additive
feature spec, scope confirmed with Joshua before building over two
rounds: what it means at all, then how invasive the capture should be).

Capture happens client-side: ActivityTracker.swift observes NSWorkspace's
own frontmost-app-change notification (a public API, no permission
prompt -- deliberately not the AppleScript/Accessibility route, which
would trigger a TCC automation-permission dialog the same class of
problem as the earlier mic crash) and POSTs each change to
`POST /activity/log` in main.py, which just calls db.log_activity()
directly. That endpoint isn't a Frank tool -- it's a plain write path
from the Swift app, same shape as any other REST write endpoint.

This module is the other half: `get_recent_activity`, a genuine on-demand
recall tool, not auto-injected into every turn. Without this, the log
would be write-only and Frank could never reference it -- a real recall
tool is what makes "passive awareness" actually useful rather than an
inert table nobody reads. Scoped to app name only, on request -- no
proactive commentary, no window titles, no URLs, no file contents.

Same "regular" permission tier as save_memory (SECURITY.md): local-only,
reversible (the whole table can just be cleared), no external effect.
"""

from app.db import get_recent_activity

GET_RECENT_ACTIVITY_TOOL = {
    "name": "get_recent_activity",
    "description": (
        "Look up what apps Joshua has recently been using, most recent first. Use this only when he asks what "
        "he's been working on, or a similar direct question -- never proactively volunteer this unasked. Only "
        "app names are tracked, nothing about window contents."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent app-switch events to return. Defaults to 20.",
            },
        },
        "required": [],
    },
}

SHADOW_MODE_TOOLS = [GET_RECENT_ACTIVITY_TOOL]
SHADOW_MODE_TOOL_NAMES = {tool["name"] for tool in SHADOW_MODE_TOOLS}


async def execute_shadow_mode_tool_call(name: str, tool_input: dict) -> str:
    if name == "get_recent_activity":
        records = await get_recent_activity(tool_input.get("limit", 20))
        if not records:
            return "No activity recorded yet."
        return "\n".join(f"{r['started_at']} — {r['app_name']}" for r in records)
    return f"Unknown tool: {name}"
