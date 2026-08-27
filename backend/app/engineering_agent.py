"""
Engineering Agent -- the one helping build P Corp itself
(AGENTS_VISION.md, Technology Division). Genuinely different from most
other specialist agents: it can read real files and git history, and
PROPOSE file edits Joshua must explicitly approve before anything is
written to disk.

AGENTS_VISION.md's own scope note deliberately deferred this agent from
day one: "this is the general agentic tool-use capability... already
deliberately deferred... because SECURITY.md's permission/sandboxing
model for that doesn't exist yet. Building this agent would silently
undo that deferral." That blocker is what this file, plus the new
"\n[approval_request]" websocket sentinel (main.py) and the approval-card
UI (WarRoomView.swift, both platforms), resolves -- see SECURITY.md's
2026-08-27 entry for the full tier classification and reasoning.

The actual toolset, safety boundary, and inner tool-use loop live in
app/agent_codebase_tools.py (extracted 2026-08-27 once Design Agent and
Operations Agent needed the exact same real file/git access behind the
exact same approval-gated write path) -- this file now only owns the
outer consult_engineering_agent tool and this agent's own system prompt.
"""

from anthropic import AsyncAnthropic

from app.agent_codebase_tools import run_agentic_loop

ENGINEERING_AGENT_SYSTEM_PROMPT = """You are the Engineering Agent inside P Corp OS -- a specialist Frank delegates to for real engineering work on P Corp OS's own codebase: code review, architecture, refactoring, documentation, testing, git history, APIs, databases, and security. You're being consulted mid-conversation; Frank will relay or incorporate what you say. Eventually you become the lead engineer of P Corp (AGENTS_VISION.md) -- this is a first, deliberately narrow version.

You have real tools: read_file, list_directory, git_log, git_diff, git_show, run_build_check, and propose_file_edit. Use them -- don't guess at what a file contains or what git history shows when you can just look. read_file's result is prefixed with "[N lines]" -- a real, computed count. If asked how long a file is, report that exact number verbatim; don't count lines yourself from the dumped text, since that's unreliable for anything but a very short file.

Hard limits, not preferences -- these tools genuinely don't exist, don't imply you have a workaround, and say so plainly if a request needs one:
- No shell execution of any kind.
- No git write operations -- no commit, no push, nothing that changes repo state via git.
- No editing .env files, secrets, keys, or credentials.
- No deleting files.
- run_build_check only runs the exact fixed build command for "desktop" or "ios" -- nothing else.

propose_file_edit is the only way you can ever change a file, and it never writes immediately -- it sends Joshua an approval card with your summary and the diff, and blocks until he approves or rejects. Always give propose_file_edit the complete, real new file content, not a description of a change -- and always explain your reasoning in the summary before proposing it, the same way you'd explain a real code review comment. If Joshua rejects a proposal, accept that plainly and ask what he'd prefer instead, rather than re-proposing the same thing.

Be direct and concise, matching Frank's own communication style. Give a real, specific answer grounded in what you actually read from the files or git history, not a generic best-practices answer that could apply to any codebase."""


CONSULT_ENGINEERING_AGENT_TOOL = {
    "name": "consult_engineering_agent",
    "description": (
        "Delegate to the Engineering Agent for real engineering work on P Corp OS's own codebase: code review, "
        "architecture questions, refactoring suggestions, documentation, testing guidance, or inspecting real git "
        "history/diffs. It reads actual files and git history directly (not from memory or Frank's paraphrase), "
        "and if it proposes an actual file edit, Joshua sees an approval card and must explicitly approve before "
        "anything is written -- it never writes without approval, and it cannot run shell commands, commit/push, "
        "or touch secrets. Use this rather than answering yourself when the request needs to see real, current "
        "code or git history."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What to consult the Engineering Agent about, in full, self-contained detail."},
        },
        "required": ["request"],
    },
}

ENGINEERING_AGENT_TOOLS = [CONSULT_ENGINEERING_AGENT_TOOL]
ENGINEERING_AGENT_TOOL_NAMES = {tool["name"] for tool in ENGINEERING_AGENT_TOOLS}


async def execute_engineering_agent_tool_call(
    name: str, tool_input: dict, client: AsyncAnthropic, websocket
) -> str:
    if name != "consult_engineering_agent":
        return f"Unknown tool: {name}"
    return await run_agentic_loop(ENGINEERING_AGENT_SYSTEM_PROMPT, tool_input["request"], client, websocket)
