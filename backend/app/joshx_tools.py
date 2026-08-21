"""
Frank's tools for Joshx (app/joshx_db.py) -- same shape as personal_tools.py/
memory.py's save_memory/forget_memory: narrow, hardcoded actions via the
plain SDK's tool-use, not general agentic capability. "Regular" permission
tier under SECURITY.md's model -- local-only, reversible (status is
overwritten or soft-deleted, nothing destroyed), no external effect. No
auto-sending, no auto-invoicing, no contacting clients -- same "flags/
records, never acts on Josh's behalf" boundary as every other domain here.

Deliberately no consult_joshx_agent, same call already made for Personal
and the same reasoning: a persona giving commentary on Josh's own
freelance business risks drifting into unsolicited advice, which isn't
what Phase 1 asked for. build_joshx_block() folds current clients/leads/
projects into Frank's own system prompt directly.
"""

from app.joshx_db import (
    add_client,
    add_lead,
    add_project,
    log_client_contact,
    summarize,
    update_client_status,
    update_lead_stage,
    update_project_status,
)

ADD_JOSHX_CLIENT_TOOL = {
    "name": "add_joshx_client",
    "description": "Record a new client/prospect for Josh's independent freelance creative business (Joshx) -- video editing, videography, photography. Never Alpha Mode Media -- that's a separate business with its own tools.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Client's name."},
            "company": {"type": "string"},
            "contact_name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "instagram": {"type": "string"},
            "website": {"type": "string"},
            "industry": {"type": "string"},
            "client_type": {"type": "string"},
            "lead_source": {"type": "string", "description": "How this client found Josh, e.g. \"referral\", \"Instagram\"."},
            "notes": {"type": "string"},
        },
        "required": ["name"],
    },
}

UPDATE_JOSHX_CLIENT_STATUS_TOOL = {
    "name": "update_joshx_client_status",
    "description": "Update a Joshx client's status -- e.g. lead, prospect, active, past_client, dormant, lost. Matches by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The client's name, or a close match."},
            "new_status": {"type": "string"},
        },
        "required": ["identifier", "new_status"],
    },
}

LOG_JOSHX_CLIENT_CONTACT_TOOL = {
    "name": "log_joshx_client_contact",
    "description": "Log that Josh made contact with a Joshx client today (or a given date) -- e.g. a call, email, DM. Matches by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The client's name, or a close match."},
            "contact_date": {"type": "string", "description": "e.g. \"2026-08-21\". Omit to use today."},
        },
        "required": ["identifier"],
    },
}

ADD_JOSHX_LEAD_TOOL = {
    "name": "add_joshx_lead",
    "description": "Record a new freelance opportunity for Joshx -- a potential video/photo project someone's inquired about.",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "Who the opportunity is with."},
            "project_description": {"type": "string"},
            "service": {"type": "string", "description": "e.g. \"videography\", \"video editing\", \"photography\"."},
            "estimated_value": {"type": "number"},
            "budget": {"type": "number"},
            "lead_source": {"type": "string"},
            "probability": {"type": "integer", "description": "0-100, chance of booking."},
            "follow_up_date": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["client_name"],
    },
}

UPDATE_JOSHX_LEAD_STAGE_TOOL = {
    "name": "update_joshx_lead_stage",
    "description": "Move a Joshx lead through the pipeline -- new, contacted, discovery, quoted, negotiating, booked, lost. Matches by client name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The lead's client name, or a close match."},
            "new_stage": {"type": "string"},
        },
        "required": ["identifier", "new_stage"],
    },
}

ADD_JOSHX_PROJECT_TOOL = {
    "name": "add_joshx_project",
    "description": "Record a new Joshx freelance project -- a booked video/photo job, once a lead converts (or a project starting directly).",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string"},
            "project_name": {"type": "string"},
            "project_type": {
                "type": "string",
                "description": "e.g. \"video_editing\", \"videography\", \"photography\", \"creative_direction\", \"content_creation\", \"spec_shoot\", \"personal_project\".",
            },
            "brief": {"type": "string"},
            "start_date": {"type": "string"},
            "due_date": {"type": "string"},
            "shoot_date": {"type": "string"},
            "budget": {"type": "number"},
            "priority": {"type": "string"},
            "deliverables": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["client_name", "project_name"],
    },
}

UPDATE_JOSHX_PROJECT_STATUS_TOOL = {
    "name": "update_joshx_project_status",
    "description": "Move a Joshx project through its workflow -- brief, pre_production, production, post_production, client_review, revision, delivery, paid, archived. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
            "new_status": {"type": "string"},
        },
        "required": ["identifier", "new_status"],
    },
}

JOSHX_TOOLS = [
    ADD_JOSHX_CLIENT_TOOL,
    UPDATE_JOSHX_CLIENT_STATUS_TOOL,
    LOG_JOSHX_CLIENT_CONTACT_TOOL,
    ADD_JOSHX_LEAD_TOOL,
    UPDATE_JOSHX_LEAD_STAGE_TOOL,
    ADD_JOSHX_PROJECT_TOOL,
    UPDATE_JOSHX_PROJECT_STATUS_TOOL,
]
JOSHX_TOOL_NAMES = {tool["name"] for tool in JOSHX_TOOLS}


async def build_joshx_block() -> str:
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## Joshx (Josh's independent freelance creative business -- separate from Alpha Mode Media)\n{snapshot}"


async def execute_joshx_tool_call(name: str, tool_input: dict) -> str:
    if name == "add_joshx_client":
        fields = {k: v for k, v in tool_input.items() if k != "name"}
        result = await add_client(tool_input["name"], **fields)
        return f"Added Joshx client: {result}"
    if name == "update_joshx_client_status":
        updated = await update_client_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated Joshx client status to {tool_input['new_status']}."
        return f"No matching Joshx client found for \"{tool_input['identifier']}\"."
    if name == "log_joshx_client_contact":
        logged = await log_client_contact(tool_input["identifier"], tool_input.get("contact_date"))
        if logged:
            return "Logged contact."
        return f"No matching Joshx client found for \"{tool_input['identifier']}\"."
    if name == "add_joshx_lead":
        fields = {k: v for k, v in tool_input.items() if k != "client_name"}
        result = await add_lead(tool_input["client_name"], **fields)
        return f"Added Joshx lead: {result}"
    if name == "update_joshx_lead_stage":
        updated = await update_lead_stage(tool_input["identifier"], tool_input["new_stage"])
        if updated:
            return f"Updated Joshx lead stage to {tool_input['new_stage']}."
        return f"No matching Joshx lead found for \"{tool_input['identifier']}\"."
    if name == "add_joshx_project":
        fields = {k: v for k, v in tool_input.items() if k not in ("client_name", "project_name")}
        result = await add_project(tool_input["client_name"], tool_input["project_name"], **fields)
        return f"Added Joshx project: {result}"
    if name == "update_joshx_project_status":
        updated = await update_project_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated Joshx project status to {tool_input['new_status']}."
        return f"No matching Joshx project found for \"{tool_input['identifier']}\"."
    return f"Unknown tool: {name}"
