"""
Frank's tool for Finance (app/finance_db.py) -- same shape as
joshx_tools.py/personal_tools.py: narrow, hardcoded, "regular" permission
tier under SECURITY.md's model. Just one tool -- logging a balance Josh
tells Frank about -- since Luno's own balance is tracked automatically
(app/finance.py's daily snapshot job) and the other four accounts
(Liberty Stash, EasyEquities, Ashburton Stable Income Fund, Nasdaq /
Markets) have no real API to pull from, so a manual log is the only
honest way to record them.

No consult_finance_agent, same reasoning already applied to Personal and
Joshx -- and doubly so here: this system prompt explicitly forbids giving
personalized investment advice, so a persona commentating on Josh's
portfolio would risk crossing that line. Frank just records and displays
what it's told; "look for lucrative opportunities" is real, separately-
scoped future work, not something bolted onto this tool.
"""

from app.finance_db import log_balance, summarize

LOG_FINANCE_BALANCE_TOOL = {
    "name": "log_finance_balance",
    "description": (
        "Record a balance Josh just told you for one of his tracked investment accounts "
        "(Liberty Stash, EasyEquities, Ashburton Stable Income Fund, Nasdaq / Markets). "
        "Don't use this for Luno -- that account updates itself automatically."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "account_name": {
                "type": "string",
                "description": "Which account, e.g. \"EasyEquities\", \"Liberty Stash\".",
            },
            "balance": {"type": "number"},
            "asset": {"type": "string", "description": "Currency code, e.g. \"ZAR\", \"USD\". Defaults to ZAR."},
            "notes": {"type": "string"},
        },
        "required": ["account_name", "balance"],
    },
}

FINANCE_TOOLS = [LOG_FINANCE_BALANCE_TOOL]
FINANCE_TOOL_NAMES = {tool["name"] for tool in FINANCE_TOOLS}


async def build_finance_block() -> str:
    snapshot = await summarize()
    if not snapshot:
        return ""
    return f"\n\n## Finance (Josh's personal investments -- track and display only, never advise)\n{snapshot}"


async def execute_finance_tool_call(name: str, tool_input: dict) -> str:
    if name == "log_finance_balance":
        matched = await log_balance(
            tool_input["account_name"],
            tool_input["balance"],
            tool_input.get("asset", "ZAR"),
            tool_input.get("notes"),
        )
        if matched:
            return f"Logged {tool_input['balance']:,.2f} {tool_input.get('asset', 'ZAR')} for {matched}."
        return f"No matching Finance account found for \"{tool_input['account_name']}\"."
    return f"Unknown tool: {name}"
