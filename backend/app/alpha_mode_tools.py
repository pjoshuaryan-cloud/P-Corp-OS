"""
Frank's tools for Alpha Mode Media's business data (app/alpha_mode_db.py) —
same shape as app/memory.py's save_memory/forget_memory: narrow, hardcoded
actions via the plain SDK's tool-use, not general agentic capability.
Classified "regular" under SECURITY.md's permission model — local-only,
reversible (status is just overwritten, nothing destroyed), no external
effect, same reasoning as the memory tools.

Five tools, not one per possible action: add_client/add_project/
add_invoice/add_deliverable cover creation, and a single generic
update_status covers every "mark this done/paid/completed" case rather
than four separate update tools — kept small deliberately, this is a
brand-new system with no real usage history yet to justify more.

Real approval gating added 2026-09-06 (systems audit §19 sweep) for the
three paths that write directly to Alpha Mode Media's real production
Supabase (add_project, add_invoice, update_alpha_mode_status for
entity_type project/invoice) -- SECURITY.md's own 2026-08-10 entry names
this exact gap and records a deliberate decision to keep auto-execute and
rely on audit logging instead, "revisit only if this becomes an actual
problem in practice." Revisited now that three other propose_*/approval-
card flows exist (calendar, Engineering Agent file edits, automations) --
none did when that call was made. client/deliverable/crew/equipment
writes stay auto-executing exactly as before -- local-only, already
correctly classified "regular" per the same audit.

Mirrors calendar_tools.py's/automation_tools.py's _request_approval shape
exactly (own request_id, blocks on websocket.receive_text(), fails closed
on rejection/malformed reply) -- a fourth occurrence of a pattern this
codebase has now built three times independently. Deliberately shows the
raw proposed fields, not a pre-resolved lookup against the real Supabase
record -- matches propose_create_automation's own precedent (no separate
validation/resolution pass before showing the card); for add_project/
add_invoice there's nothing to resolve anyway (nothing exists yet).
"""

import json
import uuid

from fastapi import WebSocket

from app.alpha_mode_db import (
    add_client,
    add_crew_member,
    add_deliverable,
    add_equipment,
    log_client_contact,
    summarize,
    update_status,
)
from app.alpha_mode_supabase import create_invoice, create_project, set_invoice_status, set_project_stage

# entity_types whose update_alpha_mode_status branch writes to the real
# Supabase, per the reasoning above -- client/deliverable/crew/equipment
# stay auto-executing (local SQLite only).
_GATED_STATUS_ENTITY_TYPES = {"project", "invoice"}

ADD_CLIENT_TOOL = {
    "name": "add_client",
    "description": (
        "Record a new Alpha Mode Media client, or update notes on an existing one (matched by name). Joshua is a "
        "co-founder of Alpha Mode Media -- a client is someone Alpha Mode Media does business with. Never record "
        "\"Alpha Mode Media\" itself as a client."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Client name."},
            "notes": {"type": "string", "description": "Any relevant context about this client."},
        },
        "required": ["name"],
    },
}

ADD_PROJECT_TOOL = {
    "name": "add_project",
    "description": (
        "Create a new project directly in the real Alpha Mode Media Admin app (Supabase) -- it appears live in "
        "the app immediately, not a local copy. Ask Joshua for whatever key fields he hasn't already given you "
        "before calling this -- at minimum client and project name; ideally also type, discipline, and due date "
        "if the project has one. Don't guess values or silently leave fields blank -- ask."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "The client this project is for."},
            "project_name": {"type": "string", "description": "Name of the project."},
            "contact": {"type": "string", "description": "Client contact person/details for this project."},
            "type": {"type": "string", "description": "Client-facing project category, e.g. \"Corporate\", \"Brand\", \"Events\"."},
            "discipline": {"type": "string", "enum": ["video", "photo", "both"], "description": "Media discipline. Defaults to \"video\" if not given."},
            "stage": {
                "type": "string",
                "enum": ["briefed", "shooting", "editing", "review", "delivered", "client_revert", "final_delivered"],
                "description": "Production stage. Defaults to \"briefed\" if not given.",
            },
            "due_date": {"type": "string", "description": "e.g. \"2026-08-15\"."},
            "shoot_date": {"type": "string", "description": "e.g. \"2026-08-10\"."},
            "crew": {"type": "string", "description": "Crew assigned, free text."},
            "brief": {"type": "string", "description": "The project brief."},
            "notes": {"type": "string", "description": "Any other relevant context."},
        },
        "required": ["client_name", "project_name"],
    },
}

ADD_INVOICE_TOOL = {
    "name": "add_invoice",
    "description": (
        "Create a new invoice directly in the real Alpha Mode Media Admin app (Supabase), tied to an existing "
        "project. The project must already exist -- create it first with add_project if it doesn't. If the "
        "client has more than one project, give project_name to disambiguate; otherwise their most recent "
        "project is used."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "The client being invoiced."},
            "project_name": {"type": "string", "description": "The project this invoice is for -- disambiguates when a client has multiple projects."},
            "amount": {"type": "number", "description": "Invoice amount."},
            "due_date": {"type": "string", "description": "When it's due, e.g. \"2026-08-15\"."},
            "status": {"type": "string", "enum": ["not_invoiced", "invoiced", "paid"], "description": "Defaults to \"invoiced\"."},
        },
        "required": ["client_name", "amount"],
    },
}

ADD_DELIVERABLE_TOOL = {
    "name": "add_deliverable",
    "description": "Record a new deliverable for an existing Alpha Mode Media project. The project must already exist — create it first with add_project if it doesn't.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "The project this deliverable belongs to."},
            "description": {"type": "string", "description": "What the deliverable is."},
            "due_date": {"type": "string", "description": "When it's due, e.g. \"2026-08-15\"."},
            "status": {"type": "string", "description": "e.g. \"pending\", \"done\". Defaults to \"pending\"."},
        },
        "required": ["project_name", "description"],
    },
}

UPDATE_STATUS_TOOL = {
    "name": "update_alpha_mode_status",
    "description": (
        "Update the status of an existing client, project, invoice, deliverable, crew member, or piece of "
        "equipment. Project and invoice updates go live in the real Alpha Mode Media Admin app (Supabase); "
        "client/deliverable/crew/equipment update the local record. For project and invoice, identifier is the "
        "CLIENT name (not a project name) — pass project_name too if that client has more than one project. "
        "For a project, new_status should ideally be a real stage (briefed/shooting/editing/review/delivered/"
        "client_revert/final_delivered) — common words like \"done\"/\"completed\" map automatically; anything "
        "else is recorded as a free-text status tag instead of failing. For an invoice, new_status should be "
        "not_invoiced/invoiced/paid (\"unpaid\" maps to not_invoiced) — this matches their most recent invoice "
        "on that project. For deliverables, identifier can be a partial match on the description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_type": {"type": "string", "enum": ["client", "project", "invoice", "deliverable", "crew", "equipment"]},
            "identifier": {"type": "string", "description": "Name (client/crew/equipment), description (deliverable), or client name (project/invoice)."},
            "project_name": {"type": "string", "description": "Only used when entity_type is \"project\" or \"invoice\" and the client has more than one project."},
            "new_status": {"type": "string", "description": "The new status — see description for valid values per entity_type."},
        },
        "required": ["entity_type", "identifier", "new_status"],
    },
}

LOG_CLIENT_CONTACT_TOOL = {
    "name": "log_client_contact",
    "description": (
        "Record that a client was actually reached out to today (or on a given date) -- e.g. Joshua mentions "
        "calling, emailing, or meeting with them. This is what outreach-reminder insights are based on, so log it "
        "whenever a real contact happens, not just when explicitly asked to."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "The client who was contacted."},
            "contact_date": {"type": "string", "description": "When, e.g. \"2026-08-01\". Defaults to today if omitted."},
        },
        "required": ["client_name"],
    },
}

ADD_CREW_TOOL = {
    "name": "add_crew_member",
    "description": (
        "Record a new crew member Alpha Mode Media works with, or update role/contact/notes on an existing one "
        "(matched by name)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Crew member's name."},
            "role": {"type": "string", "description": "e.g. \"DP\", \"Sound\", \"Editor\", \"Gaffer\", \"PA\"."},
            "contact": {"type": "string", "description": "Phone, email, or however they're best reached."},
            "notes": {"type": "string", "description": "Any relevant context."},
        },
        "required": ["name"],
    },
}

ADD_EQUIPMENT_TOOL = {
    "name": "add_equipment",
    "description": (
        "Record a new piece of equipment Alpha Mode Media owns, or update category/notes on an existing one "
        "(matched by name). Defaults to \"available\" status."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "e.g. \"Sony FX6\", \"DJI Ronin RS3\"."},
            "category": {"type": "string", "description": "e.g. \"Camera\", \"Lighting\", \"Audio\", \"Grip\"."},
            "notes": {"type": "string", "description": "Any relevant context."},
        },
        "required": ["name"],
    },
}

ALPHA_MODE_TOOLS = [
    ADD_CLIENT_TOOL,
    ADD_PROJECT_TOOL,
    ADD_INVOICE_TOOL,
    ADD_DELIVERABLE_TOOL,
    UPDATE_STATUS_TOOL,
    LOG_CLIENT_CONTACT_TOOL,
    ADD_CREW_TOOL,
    ADD_EQUIPMENT_TOOL,
]


async def build_alpha_mode_block(postgres_conn=None) -> str:
    snapshot = await summarize(postgres_conn)
    if not snapshot:
        return ""
    return f"\n\n## Alpha Mode Media — current business snapshot\n{snapshot}"


async def _request_approval(websocket: WebSocket, tool: str, title: str, details: str) -> bool:
    """Mirrors automation_tools.py's/calendar_tools.py's _request_approval
    mechanics exactly. Returns True only on an explicit, correctly-matched
    approval -- fails closed (False) on rejection, a stale/mismatched id,
    or any malformed reply."""
    request_id = str(uuid.uuid4())
    payload = json.dumps({"id": request_id, "tool": tool, "title": title, "details": details})
    await websocket.send_text(f"\n[alpha_mode_approval_request]{payload}")

    raw = await websocket.receive_text()
    try:
        response = json.loads(raw)["approval_response"]
        return bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


async def execute_alpha_mode_tool_call(name: str, tool_input: dict, websocket: WebSocket, postgres_conn=None) -> str:
    if name == "add_client":
        result = await add_client(tool_input["name"], tool_input.get("notes"), postgres_conn)
        return f"Added client: {result}"
    if name == "add_project":
        fields = {"client": tool_input["client_name"], "project_name": tool_input["project_name"]}
        for key in ("contact", "type", "discipline", "stage", "due_date", "shoot_date", "crew", "brief", "notes"):
            if tool_input.get(key):
                fields[key] = tool_input[key]
        details = "\n".join(f"{k}: {v}" for k, v in fields.items())
        approved = await _request_approval(
            websocket, name, f"Create Alpha Mode Media project: {fields['project_name']} for {fields['client']}", details
        )
        if not approved:
            return f"Rejected by Josh: project \"{fields['project_name']}\" was not created."
        result = await create_project(fields)
        return f"Created project in Alpha Mode Media Admin: {result['project_name']} for {result['client']}."
    if name == "add_invoice":
        amount = tool_input["amount"]
        client_name = tool_input["client_name"]
        details_lines = [f"Client: {client_name}", f"Amount: R{amount:,.2f}"]
        if tool_input.get("project_name"):
            details_lines.append(f"Project: {tool_input['project_name']}")
        if tool_input.get("due_date"):
            details_lines.append(f"Due: {tool_input['due_date']}")
        details_lines.append(f"Status: {tool_input.get('status', 'invoiced')}")
        approved = await _request_approval(
            websocket, name, f"Create Alpha Mode Media invoice: R{amount:,.2f} for {client_name}", "\n".join(details_lines)
        )
        if not approved:
            return f"Rejected by Josh: invoice for {client_name} was not created."
        result = await create_invoice(
            tool_input["client_name"],
            tool_input.get("project_name"),
            tool_input["amount"],
            tool_input.get("due_date"),
            tool_input.get("status", "invoiced"),
        )
        if result is None:
            return f"No project found for \"{tool_input['client_name']}\" — add the project first."
        return f"Added invoice in Alpha Mode Media Admin: R{result['amount']:,.2f} for {tool_input['client_name']} ({result['status']})."
    if name == "add_deliverable":
        result = await add_deliverable(
            tool_input["project_name"],
            tool_input["description"],
            tool_input.get("due_date"),
            tool_input.get("status", "pending"),
            postgres_conn,
        )
        if result is None:
            return f"No project found named \"{tool_input['project_name']}\" — add the project first."
        return f"Added deliverable: {result}"
    if name == "update_alpha_mode_status":
        entity_type = tool_input["entity_type"]
        identifier = tool_input["identifier"]
        new_status = tool_input["new_status"]
        project_name = tool_input.get("project_name")
        if entity_type in _GATED_STATUS_ENTITY_TYPES:
            details_lines = [f"Client: {identifier}"]
            if project_name:
                details_lines.append(f"Project: {project_name}")
            details_lines.append(f"New status: {new_status}")
            approved = await _request_approval(
                websocket, name, f"Update Alpha Mode Media {entity_type} status to \"{new_status}\"", "\n".join(details_lines)
            )
            if not approved:
                return f"Rejected by Josh: {entity_type} status for \"{identifier}\" was not changed."
        if entity_type == "project":
            result = await set_project_stage(identifier, project_name, new_status)
            if result is None:
                return f"No matching project found for \"{identifier}\"."
            return f"Updated {result['project_name']} for {result['client']} to \"{new_status}\" in Alpha Mode Media Admin."
        if entity_type == "invoice":
            result = await set_invoice_status(identifier, project_name, new_status)
            if result is None:
                return f"No matching invoice found for \"{identifier}\", or \"{new_status}\" isn't a valid invoice status (not_invoiced/invoiced/paid)."
            return f"Updated invoice for {identifier} to \"{result['status']}\" in Alpha Mode Media Admin."
        updated = await update_status(entity_type, identifier, new_status, postgres_conn)
        if updated:
            return f"Updated {entity_type} status to {new_status}."
        return f"No matching {entity_type} found for \"{identifier}\"."
    if name == "log_client_contact":
        result = await log_client_contact(tool_input["client_name"], tool_input.get("contact_date"), postgres_conn)
        return f"Logged contact with {result}"
    if name == "add_crew_member":
        result = await add_crew_member(
            tool_input["name"], tool_input.get("role"), tool_input.get("contact"), tool_input.get("notes"),
            postgres_conn,
        )
        return f"Added crew member: {result}"
    if name == "add_equipment":
        result = await add_equipment(tool_input["name"], tool_input.get("category"), tool_input.get("notes"), postgres_conn)
        return f"Added equipment: {result}"
    return f"Unknown tool: {name}"
