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
    add_joshx_invoice,
    add_lead,
    add_project,
    convert_lead_to_project,
    delete_client,
    delete_joshx_invoice,
    delete_joshx_project_expense,
    delete_lead,
    delete_project,
    log_client_contact,
    log_joshx_project_expense,
    record_joshx_invoice_payment,
    summarize,
    update_client_status,
    update_joshx_invoice_status,
    update_lead_stage,
    update_project_payment_status,
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

DELETE_JOSHX_CLIENT_TOOL = {
    "name": "delete_joshx_client",
    "description": "Remove a Joshx client record -- for a duplicate, a mistaken entry, or one Josh wants gone entirely. Matches by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The client's name, or a close match."},
        },
        "required": ["identifier"],
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

DELETE_JOSHX_LEAD_TOOL = {
    "name": "delete_joshx_lead",
    "description": (
        "Remove a dormant Joshx lead from the list -- for one that's stale, a duplicate, or already handled "
        "another way. Different from moving a lead to \"lost\" (a real closed outcome, stays visible in "
        "history) or booking it (use convert_joshx_lead_to_project when a tracked lead is actually turning "
        "into a real job -- that marks it booked and carries its details forward automatically; don't delete "
        "a lead just because it converted). Matches by client name. Reversible only at the database level, "
        "not from the UI -- ask Josh to confirm if there's any doubt which lead he means."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The lead's client name, or a close match."},
        },
        "required": ["identifier"],
    },
}

CONVERT_JOSHX_LEAD_TO_PROJECT_TOOL = {
    "name": "convert_joshx_lead_to_project",
    "description": (
        "Book a Joshx lead as a real project -- carries the lead's client_name, service (as project_type), "
        "budget, and notes forward automatically, marks the lead 'booked', and flips the client to 'active'. "
        "Use this instead of add_joshx_project when a tracked lead is what's converting; use add_joshx_project "
        "directly only for a project that never went through the leads pipeline."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lead_identifier": {"type": "string", "description": "The lead's client name, or a close match."},
            "project_name": {"type": "string", "description": "A lead has no project name -- this is required."},
            "start_date": {"type": "string"},
            "due_date": {"type": "string"},
            "shoot_date": {"type": "string"},
            "priority": {"type": "string"},
            "deliverables": {"type": "string"},
        },
        "required": ["lead_identifier", "project_name"],
    },
}

ADD_JOSHX_PROJECT_TOOL = {
    "name": "add_joshx_project",
    "description": "Record a new Joshx freelance project starting directly, with no prior tracked lead. If a real tracked lead is what's converting, use convert_joshx_lead_to_project instead -- it carries the lead's details forward automatically instead of you re-typing them from memory.",
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

UPDATE_JOSHX_PROJECT_PAYMENT_STATUS_TOOL = {
    "name": "update_joshx_project_payment_status",
    "description": (
        "Record whether a Joshx project's client has paid -- unpaid, partially_paid, or paid. Separate from the "
        "project's workflow status (a project can be at any production stage and still be paid or unpaid). "
        "Matches by project name. Once real Joshx invoices exist for this project, this manual value gets "
        "recalculated from invoice totals the next time an invoice is added or its status/payment changes -- "
        "use add_joshx_invoice/record_joshx_invoice_payment instead once real invoices are being tracked."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
            "new_payment_status": {"type": "string", "enum": ["unpaid", "partially_paid", "paid"]},
        },
        "required": ["identifier", "new_payment_status"],
    },
}

DELETE_JOSHX_PROJECT_TOOL = {
    "name": "delete_joshx_project",
    "description": "Remove a Joshx project record -- for a duplicate, a mistaken entry, or one that never actually happened. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
        },
        "required": ["identifier"],
    },
}

ADD_JOSHX_INVOICE_TOOL = {
    "name": "add_joshx_invoice",
    "description": "Record a new invoice for a Joshx project. Matches project by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_identifier": {"type": "string", "description": "The project's name, or a close match."},
            "amount": {"type": "number"},
            "amount_paid": {"type": "number"},
            "status": {"type": "string", "enum": ["draft", "sent", "partially_paid", "paid", "overdue"]},
            "issued_date": {"type": "string"},
            "due_date": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["project_identifier", "amount"],
    },
}

UPDATE_JOSHX_INVOICE_STATUS_TOOL = {
    "name": "update_joshx_invoice_status",
    "description": "Update the status of a Joshx project's most recent invoice -- draft, sent, partially_paid, paid, overdue. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
            "new_status": {"type": "string", "enum": ["draft", "sent", "partially_paid", "paid", "overdue"]},
        },
        "required": ["identifier", "new_status"],
    },
}

RECORD_JOSHX_INVOICE_PAYMENT_TOOL = {
    "name": "record_joshx_invoice_payment",
    "description": "Record the total amount paid so far against a Joshx project's most recent invoice -- the full running total, not an increment. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
            "amount_paid": {"type": "number"},
        },
        "required": ["identifier", "amount_paid"],
    },
}

DELETE_JOSHX_INVOICE_TOOL = {
    "name": "delete_joshx_invoice",
    "description": "Remove a Joshx project's most recent invoice record -- for a duplicate or a mistaken entry. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
        },
        "required": ["identifier"],
    },
}

LOG_JOSHX_PROJECT_EXPENSE_TOOL = {
    "name": "log_joshx_project_expense",
    "description": "Record a new expense against a Joshx project -- props, fuel, crew meals, gear rental, etc. Matches project by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_identifier": {"type": "string", "description": "The project's name, or a close match."},
            "amount": {"type": "number"},
            "description": {"type": "string", "description": "What the expense was for, e.g. \"props\", \"fuel\", \"crew meal\"."},
            "incurred_date": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["project_identifier", "amount"],
    },
}

DELETE_JOSHX_PROJECT_EXPENSE_TOOL = {
    "name": "delete_joshx_project_expense",
    "description": "Remove a Joshx project's most recent expense record -- for a duplicate or a mistaken entry. Matches by project name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "The project's name, or a close match."},
        },
        "required": ["identifier"],
    },
}

JOSHX_TOOLS = [
    ADD_JOSHX_CLIENT_TOOL,
    UPDATE_JOSHX_CLIENT_STATUS_TOOL,
    DELETE_JOSHX_CLIENT_TOOL,
    LOG_JOSHX_CLIENT_CONTACT_TOOL,
    ADD_JOSHX_LEAD_TOOL,
    UPDATE_JOSHX_LEAD_STAGE_TOOL,
    DELETE_JOSHX_LEAD_TOOL,
    CONVERT_JOSHX_LEAD_TO_PROJECT_TOOL,
    ADD_JOSHX_PROJECT_TOOL,
    UPDATE_JOSHX_PROJECT_STATUS_TOOL,
    UPDATE_JOSHX_PROJECT_PAYMENT_STATUS_TOOL,
    DELETE_JOSHX_PROJECT_TOOL,
    ADD_JOSHX_INVOICE_TOOL,
    UPDATE_JOSHX_INVOICE_STATUS_TOOL,
    RECORD_JOSHX_INVOICE_PAYMENT_TOOL,
    DELETE_JOSHX_INVOICE_TOOL,
    LOG_JOSHX_PROJECT_EXPENSE_TOOL,
    DELETE_JOSHX_PROJECT_EXPENSE_TOOL,
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
    if name == "delete_joshx_client":
        deleted = await delete_client(tool_input["identifier"])
        if deleted:
            return f"Deleted Joshx client: {deleted}."
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
    if name == "delete_joshx_lead":
        deleted = await delete_lead(tool_input["identifier"])
        if deleted:
            return f"Deleted Joshx lead: {deleted}."
        return f"No matching Joshx lead found for \"{tool_input['identifier']}\"."
    if name == "convert_joshx_lead_to_project":
        result = await convert_lead_to_project(
            tool_input["lead_identifier"],
            tool_input["project_name"],
            **{k: v for k, v in tool_input.items() if k not in ("lead_identifier", "project_name")},
        )
        if result:
            return (
                f"Converted lead into project: {result['project_name']} for {result['client_name']} "
                f"(from lead #{result['lead_id']})."
            )
        return f"No matching Joshx lead found for \"{tool_input['lead_identifier']}\"."
    if name == "add_joshx_project":
        fields = {k: v for k, v in tool_input.items() if k not in ("client_name", "project_name")}
        result = await add_project(tool_input["client_name"], tool_input["project_name"], **fields)
        return f"Added Joshx project: {result}"
    if name == "update_joshx_project_status":
        updated = await update_project_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated Joshx project status to {tool_input['new_status']}."
        return f"No matching Joshx project found for \"{tool_input['identifier']}\"."
    if name == "update_joshx_project_payment_status":
        updated = await update_project_payment_status(tool_input["identifier"], tool_input["new_payment_status"])
        if updated:
            return f"Updated Joshx project payment status to {tool_input['new_payment_status']}."
        return f"No matching Joshx project found for \"{tool_input['identifier']}\"."
    if name == "delete_joshx_project":
        deleted = await delete_project(tool_input["identifier"])
        if deleted:
            return f"Deleted Joshx project: {deleted}."
        return f"No matching Joshx project found for \"{tool_input['identifier']}\"."
    if name == "add_joshx_invoice":
        fields = {k: v for k, v in tool_input.items() if k not in ("project_identifier", "amount")}
        result = await add_joshx_invoice(tool_input["project_identifier"], tool_input["amount"], **fields)
        if result:
            return f"Added invoice for R{result['amount']:,.2f} to {result['project_name']} ({result['client_name']})."
        return f"No matching Joshx project found for \"{tool_input['project_identifier']}\"."
    if name == "update_joshx_invoice_status":
        updated = await update_joshx_invoice_status(tool_input["identifier"], tool_input["new_status"])
        if updated:
            return f"Updated invoice status to {tool_input['new_status']}."
        return f"No matching Joshx project/invoice found for \"{tool_input['identifier']}\"."
    if name == "record_joshx_invoice_payment":
        updated = await record_joshx_invoice_payment(tool_input["identifier"], tool_input["amount_paid"])
        if updated:
            return f"Recorded R{tool_input['amount_paid']:,.2f} paid so far."
        return f"No matching Joshx project/invoice found for \"{tool_input['identifier']}\"."
    if name == "delete_joshx_invoice":
        deleted = await delete_joshx_invoice(tool_input["identifier"])
        if deleted:
            return f"Deleted the invoice for {deleted['project_name']}."
        return f"No matching Joshx project/invoice found for \"{tool_input['identifier']}\"."
    if name == "log_joshx_project_expense":
        fields = {k: v for k, v in tool_input.items() if k not in ("project_identifier", "amount")}
        result = await log_joshx_project_expense(tool_input["project_identifier"], tool_input["amount"], **fields)
        if result:
            return f"Logged R{result['amount']:,.2f} expense against {result['project_name']} ({result['client_name']})."
        return f"No matching Joshx project found for \"{tool_input['project_identifier']}\"."
    if name == "delete_joshx_project_expense":
        deleted = await delete_joshx_project_expense(tool_input["identifier"])
        if deleted:
            return f"Deleted the most recent expense for {deleted['project_name']}."
        return f"No matching Joshx project/expense found for \"{tool_input['identifier']}\"."
    return f"Unknown tool: {name}"
