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

from app.finance import compute_concentration_metrics
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


async def _concentration_summary_lines() -> list[str]:
    """Composed here, not inside finance_db.py's own summarize() --
    compute_concentration_metrics() lives in finance.py, which already
    imports FROM finance_db.py, so calling it back from there would be a
    real circular import. finance_tools.py sits above both, so this is
    the right layer to combine them for Frank's system prompt."""
    metrics = await compute_concentration_metrics()
    if not metrics["zar_accounts"] and not metrics["luno_holdings"]:
        return []
    lines = ["Finance concentration (two separate views, never blended into one total):"]
    if metrics["zar_accounts"]:
        lines.append(f"  - ZAR accounts (R{metrics['zar_total']:,.2f} combined):")
        for row in sorted(metrics["zar_accounts"], key=lambda r: r["balance"], reverse=True):
            pct = f"{row['percent_of_total']:.0%}" if row["percent_of_total"] is not None else "n/a"
            lines.append(f"    - {row['account']}: R{row['balance']:,.2f} ({pct})")
    if metrics["luno_holdings"]:
        top = metrics["luno_holdings"][0]
        pct = f"{top['percent_of_total']:.0%}" if top["percent_of_total"] is not None else "n/a"
        lines.append(
            f"  - Luno's largest holding: {top['asset']}, an estimated R{top['estimated_zar_value']:,.2f} "
            f"({pct} of Luno's ~R{metrics['luno_total_estimate']:,.2f} estimated total)"
        )
    return lines


async def build_finance_block() -> str:
    snapshot = await summarize()
    concentration_lines = await _concentration_summary_lines()
    if not snapshot and not concentration_lines:
        return ""
    body = snapshot
    if concentration_lines:
        body = f"{body}\n" + "\n".join(concentration_lines) if body else "\n".join(concentration_lines)
    return f"\n\n## Finance (Josh's personal investments -- track and display only, never advise)\n{body}"


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
