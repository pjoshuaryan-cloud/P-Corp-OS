"""
The first specialized agent Frank can delegate to — confirmed decision
(2026-07-31): Frank remains the only agent Joshua talks to directly; he
decides whether to answer a request himself or consult a specialist.
Operations is that first specialist, focused on the concrete COO-style
responsibilities Joshua named: SOPs, workflows, project planning, task
coordination, deadlines, checklists, documentation, spotting bottlenecks,
suggesting automations.

Architecturally: a second, streamed Claude call using a distinct system
prompt, given the current open-task snapshot as context, invoked as a
tool from Frank's own turn (same tool-use mechanism as save_memory and
the Alpha Mode tools). Task tracking gets its own persistent storage
(operations_db.py) via the add_task/update_task_status/delete_task tools
below -- those are Frank-level direct tools, untouched by and unrelated
to consult_operations_agent's own inner loop.

Update (2026-08-27): consult_operations_agent now runs on the same
approval-gated real-codebase toolset Engineering Agent proved out first
(app/agent_codebase_tools.py) -- what was "a nested agentic loop with its
own tools, real added complexity this doesn't need yet" when this file
was first written is no longer a speculative cost, since Engineering
Agent already built and verified the whole mechanism (see SECURITY.md's
2026-08-27 entry). Real value here: this agent can now read and propose
actual edits to backend/app/automations_registry.py (genuinely adding or
modifying an automation rule) or draft a real new Knowledge doc, rather
than only ever giving advisory text Joshua has to implement by hand.
"""

from anthropic import AsyncAnthropic

from app.agent_codebase_tools import run_agentic_loop
from app.operations_db import add_task, delete_task, summarize_open_tasks, update_task_status

OPERATIONS_AGENT_SYSTEM_PROMPT = """You are the Operations Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for operational work, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: building SOPs, improving workflows, project planning, task coordination, deadlines, checklists, documentation, identifying bottlenecks, and suggesting automations. Think like a genuinely good COO -- concrete, practical, oriented toward what actually gets executed, not generic project-management platitudes.

REAL CAPABILITY, not just advice: you have real tools -- read_file, list_directory, git_log, git_diff, git_show, run_build_check, and propose_file_edit. When a workflow improvement or automation suggestion is genuinely actionable in this codebase, don't just describe it -- read `backend/app/automations_registry.py` first, then propose_file_edit a real new or modified automation rule. Same for a genuinely useful new SOP: read a couple of existing docs (list them via list_directory on the repo root, or read_file one of the *.md files) to match their real tone/structure, then propose_file_edit the actual new file. propose_file_edit never writes immediately -- it sends Joshua a real approval card with your summary and diff, and blocks until he approves or rejects; always give it the complete real content, not a description. You cannot run shell commands, commit/push, or touch secrets -- no tool for any of that exists.

Be direct and concise, matching Frank's own communication style. Give a real answer or a real draft (an actual SOP, an actual checklist, or a real proposed edit), not a description of what one might look like."""


ADD_TASK_TOOL = {
    "name": "add_task",
    "description": (
        "Record a new task -- general, not tied to any one business. Use when Joshua mentions something "
        "that needs doing, or when operational planning surfaces concrete next steps."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What needs to get done."},
            "area": {"type": "string", "description": "Which business/area this belongs to, e.g. \"Alpha Mode Media\", \"Trading Robot\", \"Personal\". Omit if unclear."},
            "due_date": {"type": "string", "description": "When it's due, e.g. \"2026-08-15\"."},
            "notes": {"type": "string", "description": "Any relevant context."},
        },
        "required": ["title"],
    },
}

UPDATE_TASK_STATUS_TOOL = {
    "name": "update_task_status",
    "description": "Update an existing task's status -- e.g. mark it done, blocked, or in progress. Matches by title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The task's title, or a close match."},
            "new_status": {"type": "string", "description": "e.g. \"done\", \"blocked\", \"in progress\"."},
        },
        "required": ["identifier", "new_status"],
    },
}

DELETE_TASK_TOOL = {
    "name": "delete_task",
    "description": (
        "Remove a task that shouldn't have existed at all -- test data, a mistaken entry, a duplicate. "
        "Matches by title. Not for tasks that are simply finished or no longer relevant -- use "
        "update_task_status for those (e.g. mark it \"done\" or \"cancelled\"), since this is for genuinely "
        "bad rows, not real tasks reaching a real end state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The task's title, or a close match."},
        },
        "required": ["identifier"],
    },
}

CONSULT_OPERATIONS_AGENT_TOOL = {
    "name": "consult_operations_agent",
    "description": (
        "Delegate to the Operations Agent for genuinely operational work: drafting an SOP, planning a project, "
        "identifying bottlenecks, suggesting workflow improvements or automations, building a checklist. It also "
        "has real read/propose-edit access to this codebase -- delegate here to actually add or modify a real "
        "automation rule (backend/app/automations_registry.py) or draft a real new Knowledge doc, not just "
        "advisory text; any proposed edit needs Joshua's explicit approval before it's written. Use this rather "
        "than answering yourself when the request calls for real operational depth, not a quick reply. Not for "
        "simple task tracking -- use add_task/update_task_status directly for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Operations Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

OPERATIONS_TOOLS = [ADD_TASK_TOOL, UPDATE_TASK_STATUS_TOOL, DELETE_TASK_TOOL, CONSULT_OPERATIONS_AGENT_TOOL]
OPERATIONS_TOOL_NAMES = {tool["name"] for tool in OPERATIONS_TOOLS}


async def build_operations_block() -> str:
    snapshot = await summarize_open_tasks()
    if not snapshot:
        return ""
    return f"\n\n## Current tasks\n{snapshot}"


async def execute_operations_tool_call(name: str, tool_input: dict, client: AsyncAnthropic, websocket) -> str:
    if name == "add_task":
        result = await add_task(
            tool_input["title"], tool_input.get("area"), tool_input.get("due_date"), tool_input.get("notes")
        )
        return f"Added task: {result}"
    if name == "update_task_status":
        updated = await update_task_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated task status to {tool_input['new_status']}."
        return f"No matching task found for \"{tool_input['identifier']}\"."
    if name == "delete_task":
        deleted_title = await delete_task(tool_input["identifier"])
        if deleted_title:
            return f"Deleted task: {deleted_title}"
        return f"No matching task found for \"{tool_input['identifier']}\"."
    if name == "consult_operations_agent":
        task_context = await summarize_open_tasks()
        system_prompt = OPERATIONS_AGENT_SYSTEM_PROMPT
        if task_context:
            system_prompt += f"\n\n{task_context}"
        return await run_agentic_loop(system_prompt, tool_input["request"], client, websocket)
    return f"Unknown tool: {name}"
