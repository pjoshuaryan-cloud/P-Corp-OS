"""
Checks a just-executed tool call against automations_registry.py's rules
and fires any match -- consults the named agent (non-streaming, since
this runs alongside Frank's own turn and shouldn't interleave unrelated
output into his live reply), logs the result (automations_db.py), and
returns a notification payload for main.py to push over the websocket
the same way save_memory's notification already works (see TECH_STACK.md:
the WebSocket carries unprompted pushes from Frank -- this is the same
mechanism, just triggered by a rule instead of Frank's own judgment).
"""

from anthropic import AsyncAnthropic

from app.automations_db import record_run
from app.automations_registry import AUTOMATIONS
from app.design_agent import DESIGN_AGENT_SYSTEM_PROMPT

# Only agents referenced by a registered rule need a system prompt here --
# add an entry when a new rule targets a different agent.
_AGENT_SYSTEM_PROMPTS = {
    "design": DESIGN_AGENT_SYSTEM_PROMPT,
}


async def check_and_fire(tool_name: str, tool_input: dict, client: AsyncAnthropic) -> dict | None:
    """Returns a notification dict ({"title", "body"}) if a rule fired and
    ran successfully, else None. Only ever matches the FIRST rule for a
    given trigger_tool -- fine at one rule total; revisit if multiple
    rules ever share a trigger."""
    for rule in AUTOMATIONS:
        if rule["trigger_tool"] != tool_name:
            continue

        type_suffix = f" ({tool_input['type']})" if tool_input.get("type") else ""
        prompt = rule["prompt_template"].format(
            client_name=tool_input.get("client_name", "an existing client"),
            project_name=tool_input.get("project_name", "this project"),
            type_suffix=type_suffix,
        )

        response = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            system=_AGENT_SYSTEM_PROMPTS[rule["agent"]],
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = "".join(block.text for block in response.content if block.type == "text")

        trigger_summary = f"{tool_input.get('project_name', '?')} for {tool_input.get('client_name', '?')}"
        await record_run(rule["id"], rule["name"], trigger_summary, result_text)

        return {"title": rule["name"], "body": result_text[:200]}
    return None
