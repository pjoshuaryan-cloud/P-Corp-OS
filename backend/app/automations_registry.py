"""
Automations registry -- the single source of truth for "when X happens,
do Y," mirroring agents_registry.py's shape (a small, hand-kept list,
not derived from anything else). Confirmed decision (2026-08-04): starts
with exactly one real rule, Joshua's own example, rather than several
speculative ones -- same "don't build ahead of real usage" reasoning
applied everywhere else in this project (alpha_mode_db.py, memory.py,
etc.). Add a rule here to add an automation; no other code needs
touching to register it, same "keeps updating" design as the Agents
registry.

Each rule fires when its trigger_tool is successfully called by Frank
(checked in main.py's tool-dispatch loop, matched against automations.py
here), consults the named agent with a prompt built from the tool
call's actual input. The result is logged (automations_db.py) and
pushed as a real notification -- deliberately NOT streamed into the
current chat turn, which would awkwardly interleave unrelated agent
output into Frank's own live reply.
"""

AUTOMATIONS = [
    {
        "id": "new_project_folder_structure",
        "trigger_tool": "add_project",
        "name": "New project -> folder structure",
        "description": (
            "When a new Alpha Mode Media project is added, ask the Design Agent to suggest a real folder/asset "
            "structure for it."
        ),
        "agent": "design",
        "prompt_template": (
            'A new Alpha Mode Media project was just created: "{project_name}" for {client_name}{type_suffix}. '
            "Suggest a real, concrete folder/asset structure for organizing this project's files (raw footage, "
            "project files, deliverables, etc.) -- specific folder names for this project, not generic advice."
        ),
    },
]
