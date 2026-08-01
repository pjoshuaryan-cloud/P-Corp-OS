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
"""

from app.alpha_mode_db import (
    add_client,
    add_deliverable,
    add_invoice,
    add_project,
    summarize,
    update_status,
)

ADD_CLIENT_TOOL = {
    "name": "add_client",
    "description": "Record a new Alpha Mode Media client, or update notes on an existing one (matched by name).",
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
    "description": "Record a new project for an Alpha Mode Media client. Creates the client first if they don't already exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "The client this project is for."},
            "project_name": {"type": "string", "description": "Name of the project."},
            "status": {"type": "string", "description": "e.g. \"in progress\", \"on hold\", \"completed\". Defaults to \"in progress\"."},
            "notes": {"type": "string", "description": "Any relevant context about this project."},
        },
        "required": ["client_name", "project_name"],
    },
}

ADD_INVOICE_TOOL = {
    "name": "add_invoice",
    "description": "Record a new invoice for an Alpha Mode Media client. Creates the client first if they don't already exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "The client being invoiced."},
            "amount": {"type": "number", "description": "Invoice amount."},
            "due_date": {"type": "string", "description": "When it's due, e.g. \"2026-08-15\"."},
            "project_name": {"type": "string", "description": "The project this invoice is for, if applicable."},
            "status": {"type": "string", "description": "e.g. \"unpaid\", \"paid\". Defaults to \"unpaid\"."},
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
        "Update the status of an existing client, project, invoice, or deliverable — e.g. mark an invoice paid, "
        "a deliverable done, a project completed. For invoices, identifier is the client name (matches their most "
        "recent unpaid invoice). For deliverables, identifier can be a partial match on the description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_type": {"type": "string", "enum": ["client", "project", "invoice", "deliverable"]},
            "identifier": {"type": "string", "description": "Name (client/project), description (deliverable), or client name (invoice)."},
            "new_status": {"type": "string", "description": "The new status, e.g. \"paid\", \"done\", \"completed\", \"inactive\"."},
        },
        "required": ["entity_type", "identifier", "new_status"],
    },
}

ALPHA_MODE_TOOLS = [ADD_CLIENT_TOOL, ADD_PROJECT_TOOL, ADD_INVOICE_TOOL, ADD_DELIVERABLE_TOOL, UPDATE_STATUS_TOOL]


async def build_alpha_mode_block() -> str:
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## Alpha Mode Media — current business snapshot\n{snapshot}"


async def execute_alpha_mode_tool_call(name: str, tool_input: dict) -> str:
    if name == "add_client":
        result = await add_client(tool_input["name"], tool_input.get("notes"))
        return f"Added client: {result}"
    if name == "add_project":
        result = await add_project(
            tool_input["client_name"],
            tool_input["project_name"],
            tool_input.get("status", "in progress"),
            tool_input.get("notes"),
        )
        return f"Added project: {result}"
    if name == "add_invoice":
        result = await add_invoice(
            tool_input["client_name"],
            tool_input["amount"],
            tool_input.get("due_date"),
            tool_input.get("project_name"),
            tool_input.get("status", "unpaid"),
        )
        return f"Added invoice: {result}"
    if name == "add_deliverable":
        result = await add_deliverable(
            tool_input["project_name"],
            tool_input["description"],
            tool_input.get("due_date"),
            tool_input.get("status", "pending"),
        )
        if result is None:
            return f"No project found named \"{tool_input['project_name']}\" — add the project first."
        return f"Added deliverable: {result}"
    if name == "update_alpha_mode_status":
        updated = await update_status(tool_input["entity_type"], tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated {tool_input['entity_type']} status to {tool_input['new_status']}."
        return f"No matching {tool_input['entity_type']} found for \"{tool_input['identifier']}\"."
    return f"Unknown tool: {name}"
