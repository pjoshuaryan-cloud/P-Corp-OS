"""
The first specialized agent Frank can delegate to — confirmed decision
(2026-07-31): Frank remains the only agent Joshua talks to directly; he
decides whether to answer a request himself or consult a specialist.
Operations is that first specialist, focused on the concrete COO-style
responsibilities Joshua named: SOPs, workflows, project planning, task
coordination, deadlines, checklists, documentation, spotting bottlenecks,
suggesting automations.

Architecturally the simplest version of "delegation" that's actually
useful: a second, non-streaming Claude call using a distinct system
prompt, given the current open-task snapshot as context, invoked as a
tool from Frank's own turn (same tool-use mechanism as save_memory and
the Alpha Mode tools) rather than a separate persistent conversation or
a nested agentic loop with its own tools -- that's real added complexity
this doesn't need yet. Only task tracking gets persistent storage
(operations_db.py); the rest of these responsibilities are advisory
output only for now, not saved anywhere unless Joshua asks Frank to
remember something via save_memory.
"""

from anthropic import AsyncAnthropic

from app.operations_db import add_task, summarize_open_tasks, update_task_status

OPERATIONS_AGENT_SYSTEM_PROMPT = """You are the Operations Agent inside P Corp OS -- a specialist Frank (the executive intelligence Joshua actually talks to) delegates to for operational work, not a persona Joshua addresses directly. You're being consulted mid-conversation; Frank will relay or incorporate what you say.

Your responsibilities: building SOPs, improving workflows, project planning, task coordination, deadlines, checklists, documentation, identifying bottlenecks, and suggesting automations. Think like a genuinely good COO -- concrete, practical, oriented toward what actually gets executed, not generic project-management platitudes.

Be direct and concise, matching Frank's own communication style. Give a real answer or a real draft (an actual SOP, an actual checklist), not a description of what one might look like."""


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

CONSULT_OPERATIONS_AGENT_TOOL = {
    "name": "consult_operations_agent",
    "description": (
        "Delegate to the Operations Agent for genuinely operational work: drafting an SOP, planning a project, "
        "identifying bottlenecks, suggesting workflow improvements or automations, building a checklist. Use this "
        "rather than answering yourself when the request calls for real operational depth, not a quick reply. "
        "Not for simple task tracking -- use add_task/update_task_status directly for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Operations Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

OPERATIONS_TOOLS = [ADD_TASK_TOOL, UPDATE_TASK_STATUS_TOOL, CONSULT_OPERATIONS_AGENT_TOOL]
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
    if name == "consult_operations_agent":
        task_context = await summarize_open_tasks()
        system_prompt = OPERATIONS_AGENT_SYSTEM_PROMPT
        if task_context:
            system_prompt += f"\n\n{task_context}"

        # Streamed straight to the websocket as it generates, not
        # buffered until finished -- real bug found 2026-07-31: a
        # non-streaming call here meant a genuinely long document (a full
        # SOP) sat completely silent for 60-70+ seconds before anything
        # appeared, confirmed directly via a timed, isolated API call.
        # Generation speed itself can't be sped up, but seeing text
        # arrive continuously (same as Frank's own replies) is the
        # actual fix for how "broken" that silence read.
        assistant_text = ""
        async with client.messages.stream(
            model="claude-sonnet-5",
            # Real bug found 2026-07-31: 1024 was truncating actual
            # multi-phase SOPs mid-document (confirmed directly in live
            # use, twice). This agent's whole job is producing real,
            # substantive drafts -- it needs real room, unlike Frank's
            # own default brevity.
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": tool_input["request"]}],
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
        return assistant_text
    return f"Unknown tool: {name}"
