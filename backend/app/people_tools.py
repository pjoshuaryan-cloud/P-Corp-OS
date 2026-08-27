"""
Frank's tools for People/Relationships (app/people_db.py) -- same shape as
joshx_tools.py/personal_tools.py: narrow, hardcoded actions via the plain
SDK's tool-use, not general agentic capability. "Regular" permission tier
under SECURITY.md's model -- local-only, reversible, no external effect.
No auto-messaging, no auto-scheduling a follow-up -- this only ever
records and flags, matching the "never acts on Josh's behalf" boundary
already established for every other domain here.

Deliberately no consult_people_agent, same call already made for Personal
and Joshx: a persona commentating on Josh's own relationships risks
drifting into unsolicited advice, which isn't what this was scoped to
do. build_people_block() folds current people into Frank's own system
prompt directly.
"""

from app.people_db import (
    add_person,
    get_overdue_follow_ups,
    log_interaction,
    summarize,
    update_follow_up_cadence,
)

ADD_PERSON_TOOL = {
    "name": "add_person",
    "description": (
        "Record a person in Josh's real personal/professional relationship network -- family, friends, "
        "colleagues, mentors, or a real contact behind a business relationship. Deliberately separate from "
        "Joshx clients and Alpha Mode Media clients -- use linked_client_name only as a plain-text reference "
        "to a business record, never to merge the two. Calling this again for an existing person (matched by "
        "name) updates that person instead of creating a duplicate."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Person's name."},
            "relationship_type": {"type": "string", "description": "e.g. \"family\", \"friend\", \"colleague\", \"mentor\", \"business contact\"."},
            "company": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "linked_client_name": {"type": "string", "description": "Plain-text reference to a Joshx or Alpha Mode Media client name this person is the real contact behind, if any."},
            "next_follow_up_date": {"type": "string", "description": "e.g. \"2026-09-15\", if a specific follow-up is already planned."},
            "follow_up_cadence_days": {"type": "integer", "description": "How often to check in, e.g. 30 for monthly. Omit if there's no set cadence."},
            "notes": {"type": "string"},
        },
        "required": ["name"],
    },
}

LOG_INTERACTION_TOOL = {
    "name": "log_interaction",
    "description": (
        "Log a real contact event with someone in the relationship network -- a call, coffee, email, text, "
        "or meeting. Also updates that person's last-contact date automatically, so this is the one tool to "
        "use for recording contact, not a separate step."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "person_identifier": {"type": "string", "description": "The person's name, or a close match."},
            "interaction_date": {"type": "string", "description": "e.g. \"2026-08-27\"."},
            "channel": {"type": "string", "description": "e.g. \"call\", \"coffee\", \"email\", \"text\", \"meeting\"."},
            "summary": {"type": "string", "description": "What was actually discussed or happened."},
        },
        "required": ["person_identifier", "interaction_date"],
    },
}

UPDATE_FOLLOW_UP_CADENCE_TOOL = {
    "name": "update_follow_up_cadence",
    "description": "Set or change how often Josh wants to check in with someone, in days (e.g. 30 for monthly, 90 for quarterly). Matches by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "person_identifier": {"type": "string", "description": "The person's name, or a close match."},
            "cadence_days": {"type": "integer"},
        },
        "required": ["person_identifier", "cadence_days"],
    },
}

GET_OVERDUE_FOLLOW_UPS_TOOL = {
    "name": "get_overdue_follow_ups",
    "description": (
        "Real list of people Josh is overdue to follow up with, based on either an explicit next-follow-up "
        "date that's passed, or a set check-in cadence that's lapsed since last real contact. Use when asked "
        "who Josh should reach out to, or who he hasn't spoken to in a while."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

PEOPLE_TOOLS = [ADD_PERSON_TOOL, LOG_INTERACTION_TOOL, UPDATE_FOLLOW_UP_CADENCE_TOOL, GET_OVERDUE_FOLLOW_UPS_TOOL]
PEOPLE_TOOL_NAMES = {tool["name"] for tool in PEOPLE_TOOLS}


async def build_people_block() -> str:
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## People/Relationships (Josh's personal/professional network -- separate from Joshx and Alpha Mode Media clients)\n{snapshot}"


async def execute_people_tool_call(name: str, tool_input: dict) -> str:
    if name == "add_person":
        fields = {k: v for k, v in tool_input.items() if k != "name"}
        result = await add_person(tool_input["name"], **fields)
        return f"Added/updated person: {result}"
    if name == "log_interaction":
        logged = await log_interaction(
            tool_input["person_identifier"],
            tool_input["interaction_date"],
            tool_input.get("channel"),
            tool_input.get("summary"),
        )
        if logged:
            return "Logged interaction."
        return f"No matching person found for \"{tool_input['person_identifier']}\"."
    if name == "update_follow_up_cadence":
        updated = await update_follow_up_cadence(tool_input["person_identifier"], tool_input["cadence_days"])
        if updated:
            return f"Updated follow-up cadence to every {tool_input['cadence_days']} days."
        return f"No matching person found for \"{tool_input['person_identifier']}\"."
    if name == "get_overdue_follow_ups":
        overdue = await get_overdue_follow_ups()
        if not overdue:
            return "Nobody is currently overdue for a follow-up."
        lines = [
            f"- {p['name']} ({p['relationship_type'] or 'contact'}) — last contact {p['last_contact_date'] or 'never'}"
            for p in overdue
        ]
        return "People overdue for a follow-up:\n" + "\n".join(lines)
    return f"Unknown tool: {name}"
