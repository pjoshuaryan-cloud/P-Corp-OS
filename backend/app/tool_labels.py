"""Friendly, present-tense labels for the "\n[tool_start]" sentinel (see
main.py's run_claude_turn) -- one label per *tool-name-group*, matching the
granularity of main.py's own if/elif dispatch chain, not per individual
tool (60+ individual tools is out of scope for this pass). Checked in the
same order as that dispatch chain.

consult_operations_agent is special-cased ahead of OPERATIONS_TOOL_NAMES:
unlike every other consult_X_agent tool, which each get their own dedicated
*_AGENT_TOOL_NAMES set, it ships bundled into OPERATIONS_TOOL_NAMES
alongside add_task/update_task_status/delete_task (confirmed via grep of
operations_agent.py) -- without this exception the actual agent delegation
would show the flat "Updating operations", losing the "Consulting the
Operations Agent" framing every other delegate gets.
"""

from app.alpha_mode_agent import ALPHA_MODE_AGENT_TOOL_NAMES
from app.alpha_mode_tools import ALPHA_MODE_TOOLS
from app.calendar_tools import CALENDAR_TOOL_NAMES
from app.communications_agent import COMMUNICATIONS_AGENT_TOOL_NAMES
from app.connected_apps import CONNECTED_APPS_TOOL_NAMES
from app.creative_director_agent import CREATIVE_DIRECTOR_AGENT_TOOL_NAMES
from app.data_analysis import DATA_ANALYSIS_TOOL_NAMES
from app.debate import DEBATE_TOOL_NAMES
from app.decision_journal import DECISION_JOURNAL_TOOL_NAMES
from app.design_agent import DESIGN_AGENT_TOOL_NAMES
from app.documents import DOCUMENTS_TOOL_NAMES
from app.email_tools import EMAIL_TOOL_NAMES
from app.engineering_agent import ENGINEERING_AGENT_TOOL_NAMES
from app.finance_tools import FINANCE_TOOL_NAMES
from app.focus import FOCUS_TOOL_NAMES
from app.joshx_tools import JOSHX_TOOL_NAMES
from app.legacy_vault import LEGACY_VAULT_TOOL_NAMES
from app.memory_agent import MEMORY_AGENT_TOOL_NAMES
from app.memory_graph import MEMORY_GRAPH_TOOL_NAMES
from app.operations_agent import OPERATIONS_TOOL_NAMES
from app.people_tools import PEOPLE_TOOL_NAMES
from app.personal_tools import PERSONAL_TOOL_NAMES
from app.research_agent import RESEARCH_AGENT_TOOL_NAMES
from app.shadow_mode import SHADOW_MODE_TOOL_NAMES
from app.trading_division_agent import TRADING_DIVISION_AGENT_TOOL_NAMES

# Mirrors main.py's own ALPHA_MODE_TOOL_NAMES derivation -- no such set is
# exported directly from alpha_mode_tools.py.
ALPHA_MODE_TOOL_NAMES = {tool["name"] for tool in ALPHA_MODE_TOOLS}

# The full real tool-name universe (2026-09-06, added for
# automation_tools.py's soft trigger_tool validation) -- every group this
# file's own label_for_tool already checks, unioned into one flat set,
# plus the two literal fallback names (save_memory/forget_memory) that
# match main.py's own final `else` branch rather than any named group.
ALL_TOOL_NAMES: frozenset[str] = frozenset().union(
    FOCUS_TOOL_NAMES,
    DECISION_JOURNAL_TOOL_NAMES,
    MEMORY_GRAPH_TOOL_NAMES,
    SHADOW_MODE_TOOL_NAMES,
    DEBATE_TOOL_NAMES,
    LEGACY_VAULT_TOOL_NAMES,
    ALPHA_MODE_TOOL_NAMES,
    OPERATIONS_TOOL_NAMES,
    ALPHA_MODE_AGENT_TOOL_NAMES,
    DESIGN_AGENT_TOOL_NAMES,
    CREATIVE_DIRECTOR_AGENT_TOOL_NAMES,
    COMMUNICATIONS_AGENT_TOOL_NAMES,
    MEMORY_AGENT_TOOL_NAMES,
    RESEARCH_AGENT_TOOL_NAMES,
    ENGINEERING_AGENT_TOOL_NAMES,
    TRADING_DIVISION_AGENT_TOOL_NAMES,
    PERSONAL_TOOL_NAMES,
    JOSHX_TOOL_NAMES,
    PEOPLE_TOOL_NAMES,
    FINANCE_TOOL_NAMES,
    DOCUMENTS_TOOL_NAMES,
    CALENDAR_TOOL_NAMES,
    EMAIL_TOOL_NAMES,
    DATA_ANALYSIS_TOOL_NAMES,
    CONNECTED_APPS_TOOL_NAMES,
    # Literal strings, not an import from automation_tools.py -- that
    # module itself imports ALL_TOOL_NAMES from this file (to validate a
    # proposed trigger_tool), so importing back from it here would be a
    # real circular import (confirmed live, breaks the whole backend).
    {"save_memory", "forget_memory", "propose_create_automation"},
)


def label_for_tool(tool_name: str) -> str:
    if tool_name == "consult_operations_agent":
        return "Consulting the Operations Agent"
    # Literal check, not a AUTOMATION_TOOL_NAMES import -- automation_tools.py
    # itself imports ALL_TOOL_NAMES from this file, so importing back from
    # it here would be a real circular import (confirmed live).
    if tool_name == "propose_create_automation":
        return "Proposing an automation"
    if tool_name in FOCUS_TOOL_NAMES:
        return "Updating your focus list"
    if tool_name in DECISION_JOURNAL_TOOL_NAMES:
        return "Logging a decision"
    if tool_name in MEMORY_GRAPH_TOOL_NAMES:
        return "Updating memory"
    if tool_name in SHADOW_MODE_TOOL_NAMES:
        return "Running a shadow-mode check"
    if tool_name in DEBATE_TOOL_NAMES:
        return "Running a debate"
    if tool_name in LEGACY_VAULT_TOOL_NAMES:
        return "Updating the Legacy Vault"
    if tool_name in ALPHA_MODE_TOOL_NAMES:
        return "Updating Alpha Mode Media"
    if tool_name in OPERATIONS_TOOL_NAMES:
        return "Updating operations"
    if tool_name in ALPHA_MODE_AGENT_TOOL_NAMES:
        return "Consulting the Alpha Mode Agent"
    if tool_name in DESIGN_AGENT_TOOL_NAMES:
        return "Consulting the Design Agent"
    if tool_name in CREATIVE_DIRECTOR_AGENT_TOOL_NAMES:
        return "Consulting the Creative Director"
    if tool_name in COMMUNICATIONS_AGENT_TOOL_NAMES:
        return "Consulting the Communications Agent"
    if tool_name in MEMORY_AGENT_TOOL_NAMES:
        return "Consulting the Memory Agent"
    if tool_name in RESEARCH_AGENT_TOOL_NAMES:
        return "Researching that"
    if tool_name in ENGINEERING_AGENT_TOOL_NAMES:
        return "Consulting the Engineering Agent"
    if tool_name in TRADING_DIVISION_AGENT_TOOL_NAMES:
        return "Consulting the Trading Division Agent"
    if tool_name in PERSONAL_TOOL_NAMES:
        return "Updating your personal info"
    if tool_name in JOSHX_TOOL_NAMES:
        return "Updating Joshx"
    if tool_name in PEOPLE_TOOL_NAMES:
        return "Updating your contacts"
    if tool_name in FINANCE_TOOL_NAMES:
        return "Updating your finances"
    if tool_name in DOCUMENTS_TOOL_NAMES:
        return "Generating a document"
    if tool_name in CALENDAR_TOOL_NAMES:
        return "Checking your calendar"
    if tool_name in EMAIL_TOOL_NAMES:
        return "Checking your email"
    if tool_name in DATA_ANALYSIS_TOOL_NAMES:
        return "Analyzing the data"
    if tool_name in CONNECTED_APPS_TOOL_NAMES:
        return "Checking your connected apps"
    return "Remembering that"  # save_memory / forget_memory fallback, matches main.py's own final `else`
