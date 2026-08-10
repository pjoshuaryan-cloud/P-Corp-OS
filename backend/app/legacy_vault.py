"""
Legacy Vault (2026-08-10, from the additive feature spec, scope
confirmed with Joshua before building): succession/emergency
information meant for someone else if something happens to him --
instructions, account locations, who to contact, business continuity
notes. Never credentials, passwords, API keys, or account numbers
themselves -- the tool description below says so explicitly, and this
is the same hard line that governs every other part of this project.

Deliberately its own table (app/db.py's legacy_vault), not a new
memory_records type: regular memories get folded into every turn via
memory.py's build_memory_block, and vault entries must never do that --
they're meant to sit dormant until genuinely needed, not casually
surface in an unrelated conversation. save/list/delete are all real
tools here (unlike Decision Journal's capture-only first pass)
specifically because content this consequential needs to be reviewable,
not write-only.

Honest, named limitation (not solved here, confirmed with Joshua as
out of scope for this pass): this only makes Frank able to store and
recall vault entries on request. It does NOT solve actual access for
someone else if Joshua is incapacitated -- there's no multi-user access
model in P Corp OS at all, so a spouse or business partner still
couldn't open this app and ask Frank for it. Physically getting this
information to whoever needs it (export, printing, a lawyer) remains a
separate, harder, unsolved problem.

Same "regular" permission tier as save_memory (SECURITY.md): local-only,
reversible (soft delete, same as forget_memory), no external effect.
"""

from app.db import forget_legacy_entry, list_legacy_entries, save_legacy_entry

SAVE_TO_LEGACY_VAULT_TOOL = {
    "name": "save_to_legacy_vault",
    "description": (
        "Save succession/emergency information meant for someone else if something happens to Joshua -- "
        "instructions, where an account or document lives, who to contact, business continuity notes. "
        "NEVER a password, API key, account number, or any other credential -- if Joshua gives you one, "
        "decline and explain those can't be stored this way. Use this when he explicitly wants something "
        "recorded for this purpose, not for routine memories (use save_memory for those)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short label for this entry."},
            "content": {"type": "string", "description": "The instructions or information itself, written so it stands alone later."},
        },
        "required": ["title", "content"],
    },
}

LIST_LEGACY_VAULT_TOOL = {
    "name": "list_legacy_vault",
    "description": "List everything currently saved in the Legacy Vault. Use when Joshua asks what's in it or wants to review it.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

DELETE_FROM_LEGACY_VAULT_TOOL = {
    "name": "delete_from_legacy_vault",
    "description": "Remove an entry from the Legacy Vault that's outdated or no longer accurate. Matches by title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The entry's title, or a close match."},
        },
        "required": ["title"],
    },
}

LEGACY_VAULT_TOOLS = [SAVE_TO_LEGACY_VAULT_TOOL, LIST_LEGACY_VAULT_TOOL, DELETE_FROM_LEGACY_VAULT_TOOL]
LEGACY_VAULT_TOOL_NAMES = {tool["name"] for tool in LEGACY_VAULT_TOOLS}


async def execute_legacy_vault_tool_call(name: str, tool_input: dict) -> str:
    if name == "save_to_legacy_vault":
        await save_legacy_entry(tool_input["title"], tool_input["content"])
        return f"Saved to Legacy Vault: {tool_input['title']}"
    if name == "list_legacy_vault":
        entries = await list_legacy_entries()
        if not entries:
            return "Legacy Vault is empty."
        return "\n".join(f"[{e['id']}] {e['title']}: {e['content']}" for e in entries)
    if name == "delete_from_legacy_vault":
        deleted_title = await forget_legacy_entry(tool_input["title"])
        if deleted_title:
            return f"Deleted from Legacy Vault: {deleted_title}"
        return "No matching Legacy Vault entry found."
    return f"Unknown tool: {name}"
