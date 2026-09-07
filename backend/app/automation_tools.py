"""
Frank's tool for creating a real automation rule conversationally
(2026-09-06). Mirrors calendar_tools.py's propose_ convention and blocking-
approval mechanics directly -- this is the third approval flow in this
codebase (after propose_file_edit and the three propose_*_calendar_event
tools), which calendar_tools.py's own comment already names as the point
to stop copy-pasting the *Swift-side* model/slot/method trio and finally
generalize it (done in BackendClient.swift). The *backend* mechanics still
get one more direct copy here, matching that same precedent exactly --
there's no backend-side pain from the duplication, only Swift-side.

Two different validation postures for the two fields that decide whether
a rule can ever actually do anything, and why they differ:
- `agent` is hard-validated against the live agents_registry.AGENTS list
  before any approval card is even shown. A bad agent id here means the
  rule would *silently never fire* once created (see automations.py's own
  handling of a missing agent) -- a worse failure mode than a normal
  fuzzy-match miss elsewhere in this codebase, which at least surfaces an
  error immediately. Not worth letting through.
- `trigger_tool` is deliberately NOT hard-validated -- Frank's own
  judgment about tool names is already trusted everywhere else in this
  codebase (Joshx's fuzzy project-name matching, calendar's fuzzy event-
  identifier matching). Hard-blocking here would mean this one tool
  importing and cross-checking every other tool module's *_TOOL_NAMES set
  just to reject bad input -- disproportionate for a conversational
  creation flow. Instead, an unrecognized trigger_tool still shows the
  approval card, but with an explicit warning appended so Josh sees the
  real risk (a rule that will just never fire) before approving, rather
  than a silently dead rule.
"""

import json
import uuid

from fastapi import WebSocket

from app.agents_registry import AGENTS
from app.automation_rules_db import create_rule
from app.tool_labels import ALL_TOOL_NAMES

VALID_AGENT_IDS = {agent["id"] for agent in AGENTS}

PROPOSE_CREATE_AUTOMATION_TOOL = {
    "name": "propose_create_automation",
    "description": (
        "Proposes a new automation rule: whenever a specific tool is successfully called, automatically consult "
        "a specialist agent with an instruction. Does NOT create it immediately -- sends Josh a real approval "
        "card and blocks until he approves or rejects. Use an exact existing tool name Frank actually has as "
        "trigger_tool (e.g. \"add_project\", \"propose_create_calendar_event\"), and an existing agent id from "
        "the Agents list (e.g. \"design\", \"operations\") as agent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short label, e.g. \"New project -> folder structure\"."},
            "description": {"type": "string", "description": "One sentence explaining what this rule does."},
            "trigger_tool": {"type": "string", "description": "The exact tool name that fires this rule when called."},
            "agent": {"type": "string", "description": "Which specialist agent id to consult when this fires."},
            "instruction": {"type": "string", "description": "What to ask that agent to do when this fires."},
        },
        "required": ["name", "description", "trigger_tool", "agent", "instruction"],
    },
}
AUTOMATION_TOOLS = [PROPOSE_CREATE_AUTOMATION_TOOL]
AUTOMATION_TOOL_NAMES = {tool["name"] for tool in AUTOMATION_TOOLS}


async def _request_approval(
    websocket: WebSocket, tool: str, name: str, description: str, trigger_tool: str, agent: str, instruction: str
) -> bool:
    """Mirrors calendar_tools.py's `_request_approval` mechanics exactly.
    Returns True only on an explicit, correctly-matched approval -- fails
    closed (False) on rejection, a stale/mismatched id, or any malformed
    reply, same as the other two approval flows."""
    request_id = str(uuid.uuid4())
    payload = json.dumps(
        {
            "id": request_id,
            "tool": tool,
            "name": name,
            "description": description,
            "trigger_tool": trigger_tool,
            "agent": agent,
            "instruction": instruction,
        }
    )
    await websocket.send_text(f"\n[automation_approval_request]{payload}")

    # Blocks here -- same single-in-flight-receive contract the other two
    # approval flows rely on: nothing else reads this socket while this
    # turn is in-flight. A WebSocketDisconnect while blocked here
    # propagates straight up through main.py's existing dispatch loop to
    # its outer `except WebSocketDisconnect: raise` -- no new handling
    # needed, and no rule is ever partially persisted, since create_rule()
    # below only runs after this returns True.
    raw = await websocket.receive_text()
    try:
        response = json.loads(raw)["approval_response"]
        return bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


async def execute_automation_tool_call(name: str, tool_input: dict, websocket: WebSocket) -> str:
    if name != "propose_create_automation":
        return f"Unknown tool: {name}"

    agent = tool_input["agent"]
    if agent not in VALID_AGENT_IDS:
        return (
            f"Can't create that automation -- \"{agent}\" isn't a real agent. "
            f"Valid agents: {', '.join(sorted(VALID_AGENT_IDS))}."
        )

    trigger_tool = tool_input["trigger_tool"]
    description = tool_input["description"]
    if trigger_tool not in ALL_TOOL_NAMES:
        description += f" (warning: no tool named \"{trigger_tool}\" currently exists -- this rule will never fire until one does.)"

    approved = await _request_approval(
        websocket, name, tool_input["name"], description, trigger_tool, agent, tool_input["instruction"]
    )
    if not approved:
        return f"Rejected by Josh: \"{tool_input['name']}\" was not created."

    rule_id = str(uuid.uuid4())
    await create_rule(
        id=rule_id,
        name=tool_input["name"],
        description=tool_input["description"],
        trigger_tool=trigger_tool,
        agent=agent,
        instruction=tool_input["instruction"],
    )
    await websocket.send_text(
        f"\n[notify]{json.dumps({'title': 'Automation created', 'body': tool_input['name']})}"
    )
    return f"Approved and created the automation \"{tool_input['name']}\"."
