"""
Checks a just-executed tool call against real, persisted automation rules
(automation_rules_db.py) and fires every enabled match -- consults each
rule's own agent (non-streaming, since this runs alongside Frank's own
turn and shouldn't interleave unrelated output into his live reply), logs
each result (automations_db.py), and returns a notification payload for
main.py to push over the websocket the same way save_memory's notification
already works.

Generalized 2026-09-06 from a single hardcoded Python-list rule (see the
now-deleted automations_registry.py) to real, user-created rules of any
count, targeting any tool. Two real consequences of that generalization,
both deliberate:

- The old rule's prompt_template used `.format(project_name=..., ...)`
  placeholders specific to add_project's own input shape -- that doesn't
  generalize to an arbitrary trigger_tool. Replaced with a plain, generic
  suffix appending the actual tool call's raw input to the rule's own
  instruction text, which works identically regardless of what tool fired.
- The old code had no try/except around the agent consult -- a network
  failure would have propagated up and killed Frank's own turn. Fine when
  this could only ever fire on one specific tool; not fine once it can
  fire on any tool call matching any number of real rules. A failed
  consult now records a real FAILED run instead of taking the turn down,
  directly closing the audit's "no failure tracking" gap using data that
  already existed in automation_runs, just never surfaced per-rule before.

Real bug found live (2026-09-06), specific to generalizing past Design
Agent (the only agent the old single rule ever targeted): several agent
system prompts (Operations Agent's especially) describe real tool access
(read_file, list_directory, propose_file_edit, ...) that those agents
normally only have when consulted through run_agentic_loop's own tool-use
loop (consult_operations_agent's real path). This function calls a bare,
tool-less `client.messages.create` instead -- deliberately, per this
file's own docstring, since streaming a sub-agent's live reasoning into
Frank's own turn here would interleave unrelated output into his reply.
Confirmed live: Operations Agent, primed by its own system prompt to
believe it can call list_directory, emitted a garbled tool-call-shaped
JSON string as plain text instead of a real answer, since no actual tool
was wired into this call for it to invoke. `_NO_TOOLS_ADDENDUM` below is
appended to whichever system prompt is used here specifically, overriding
that mismatch for this one context -- the full fix (giving automation
firings real tool access via a non-streaming variant of run_agentic_loop)
is real, separate work, named here rather than silently worked around.
"""

from anthropic import AsyncAnthropic

from app.alpha_mode_agent import ALPHA_MODE_AGENT_SYSTEM_PROMPT
from app.automation_rules_db import list_enabled_rules_for_tool
from app.automations_db import record_run
from app.communications_agent import COMMUNICATIONS_AGENT_SYSTEM_PROMPT
from app.creative_director_agent import CREATIVE_DIRECTOR_AGENT_SYSTEM_PROMPT
from app.design_agent import DESIGN_AGENT_SYSTEM_PROMPT
from app.engineering_agent import ENGINEERING_AGENT_SYSTEM_PROMPT
from app.memory_agent import MEMORY_AGENT_SYSTEM_PROMPT
from app.operations_agent import OPERATIONS_AGENT_SYSTEM_PROMPT
from app.research_agent import RESEARCH_AGENT_SYSTEM_PROMPT
from app.trading_division_agent import TRADING_DIVISION_AGENT_SYSTEM_PROMPT

# Every real agent id (agents_registry.AGENTS) needs an entry here --
# automation_tools.py's propose_create_automation already hard-validates
# a new rule's `agent` against that same registry at creation time, so
# this dict missing an entry should only ever happen if an agent is later
# removed/renamed out from under an already-existing rule (see the
# `.get()` handling below for what happens then).
_AGENT_SYSTEM_PROMPTS = {
    "operations": OPERATIONS_AGENT_SYSTEM_PROMPT,
    "alpha_mode": ALPHA_MODE_AGENT_SYSTEM_PROMPT,
    "design": DESIGN_AGENT_SYSTEM_PROMPT,
    "creative_director": CREATIVE_DIRECTOR_AGENT_SYSTEM_PROMPT,
    "communications": COMMUNICATIONS_AGENT_SYSTEM_PROMPT,
    "memory": MEMORY_AGENT_SYSTEM_PROMPT,
    "research": RESEARCH_AGENT_SYSTEM_PROMPT,
    "trading_division": TRADING_DIVISION_AGENT_SYSTEM_PROMPT,
    "engineering": ENGINEERING_AGENT_SYSTEM_PROMPT,
}

# Appended to whichever agent's system prompt is used for an automation
# firing -- see this file's own docstring for the real bug this closes
# (an agent primed by its own prompt to believe it has tool access
# emitting a garbled tool-call-shaped string as plain text instead of a
# real answer, since no tool was actually wired into this bare call).
_NO_TOOLS_ADDENDUM = (
    "\n\nImportant context for this specific consultation: you are being consulted automatically by an "
    "automation rule, NOT through your usual tool-enabled consultation path. You have NO tool access at all "
    "right now, regardless of what your instructions above say -- do not attempt to call read_file, "
    "list_directory, propose_file_edit, or any other tool. Respond with plain text analysis/advice only, based "
    "on the information given to you directly."
)


async def check_and_fire(
    tool_name: str, tool_input: dict, client: AsyncAnthropic, tool_result: str = "", postgres_conn=None
) -> dict | None:
    """Returns a notification dict ({"title", "body"}) for the LAST rule
    that fired this call, or None if nothing matched. Fires every enabled
    rule whose trigger_tool matches -- v1 still only pushes one [notify]
    per tool call (the last one) rather than one per rule; multiple real
    rules sharing one trigger_tool isn't yet an actual scenario, and every
    firing is recorded in automation_runs regardless, so nothing is lost,
    just not separately toasted.

    Real bug found live (2026-09-06, systems audit §19's Alpha Mode
    gating): this only ever checked whether a tool NAMED `tool_name` was
    called, never whether it actually did anything -- fine when every
    trigger_tool always succeeded once called, but no longer true now
    that add_project/add_invoice/update_alpha_mode_status can be
    rejected. Confirmed live: rejecting a proposed Alpha Mode Media
    project still fired "New project -> folder structure," consulting
    the Design Agent about folder structure for a project that was never
    created. `tool_result` lets this skip firing on a rejection, checked
    against the exact "Rejected by Josh"/"Rejected by Joshua" prefix
    every approval-gated tool in this codebase already returns -- a
    plain string check, not a new mechanism."""
    if tool_result.startswith("Rejected by Josh"):
        return None
    rules = await list_enabled_rules_for_tool(tool_name, postgres_conn)
    last_notification = None
    for rule in rules:
        system_prompt = _AGENT_SYSTEM_PROMPTS.get(rule["agent"])
        if system_prompt is None:
            # The agent this rule was created against no longer exists --
            # record a real FAILED run instead of silently skipping, so
            # it's actually visible in the UI's per-rule last-run status.
            await record_run(
                rule["id"],
                rule["name"],
                f"tool: {tool_name}",
                f"FAILED: agent \"{rule['agent']}\" no longer exists.",
                postgres_conn,
            )
            continue

        prompt = f"{rule['instruction']}\n\nThe triggering tool call was `{tool_name}` with input: {tool_input!r}"
        try:
            # Real bug found live (2026-09-06): this model does extended
            # thinking by default (a ThinkingBlock precedes the real
            # TextBlock in every response, confirmed via direct testing),
            # and the old max_tokens=1024 here -- carried forward
            # unchanged from the single hardcoded rule this engine
            # replaces -- was small enough that the thinking block alone
            # could exhaust the budget before any real text ever got
            # generated, producing a genuinely empty result silently
            # recorded as a "successful" run. main.py's own real Frank
            # turns already use 4096 for exactly this reason; matched
            # here now that this fires on far more tool calls than the
            # one rule that apparently never hit this in practice before.
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=4096,
                system=system_prompt + _NO_TOOLS_ADDENDUM,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = "".join(block.text for block in response.content if block.type == "text")
            if not result_text:
                result_text = f"FAILED: agent returned no text (stop_reason: {response.stop_reason})"
        except Exception as error:
            result_text = f"FAILED: {error}"

        await record_run(rule["id"], rule["name"], f"tool: {tool_name}", result_text, postgres_conn)
        last_notification = {"title": rule["name"], "body": result_text[:200]}
    return last_notification
