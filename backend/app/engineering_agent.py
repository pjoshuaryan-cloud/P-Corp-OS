"""
Engineering Agent -- the one helping build P Corp itself
(AGENTS_VISION.md, Technology Division). Genuinely different from every
other specialist agent: it can read real files and git history, and
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

Scoped narrowly, not the open-ended capability the original deferral
worried about:
  - Regular (auto-allowed): read_file, list_directory, git_log, git_diff,
    git_show, run_build_check -- all read-only, local-only, no write
    capability at all.
  - Needs explicit confirmation: propose_file_edit -- the ONLY tool that
    can touch disk, and it never writes directly. It sends an
    "\n[approval_request]" over the websocket and blocks on the client's
    answer; only writes on explicit approval. This is the first tool in
    the whole project needing a live, blocking, mid-turn human approval
    -- new infrastructure, not a reuse of Alpha Mode's auto-execute-plus-
    audit-log pattern (SECURITY.md, 2026-08-10 entry), which was a
    deliberate one-time decision, not a template for every future write.
  - Prohibited entirely, this version, not silently omitted: arbitrary
    shell execution, `git commit`/`git push`/any git write operation,
    editing .env/secrets, deleting files. No tool for any of these
    exists below at all.

Own inner tool-use loop (execute_engineering_agent_tool_call),
structurally mirroring main.py's own run_claude_turn but scoped to just
this small toolset and its own local `inner_history` -- Frank's own outer
history never sees the intermediate read_file/git_log/propose_file_edit
round trips, only the final accumulated text, same as every other
consult_X_agent tool's internals are invisible to Frank.

Scope for this first pass: Engineering Agent ONLY. Design/Operations/
Communications Agents are NOT wired into this approval mechanism yet --
a deliberate, explicit follow-up once this proves out end-to-end, not
bundled into this change.
"""

import asyncio
import difflib
import json
import uuid

from anthropic import AsyncAnthropic

from app.agent_file_safety import REPO_ROOT, UnsafePathError, resolve_repo_path
from app.audit_db import record_tool_call

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


# ---------------------------------------------------------------------------
# Inner tools -- private to this module's own tool-use loop. Never imported
# by main.py, never seen by Frank.
# ---------------------------------------------------------------------------

_READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a real file's full text content, path relative to the repo root (e.g. \"backend/app/main.py\").",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

_LIST_DIRECTORY_TOOL = {
    "name": "list_directory",
    "description": "List a real directory's contents, path relative to the repo root (use \".\" for the repo root itself).",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

_GIT_LOG_TOOL = {
    "name": "git_log",
    "description": "Real git commit history. Optionally scoped to one path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max commits to return. Defaults to 20."},
            "path": {"type": "string", "description": "Optional, relative to repo root -- scope history to one file/directory."},
        },
        "required": [],
    },
}

_GIT_DIFF_TOOL = {
    "name": "git_diff",
    "description": "Real git diff. Omit ref for the current working-tree diff, or pass a ref (e.g. \"HEAD~1\") to diff against it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Optional commit ref to diff against."},
            "path": {"type": "string", "description": "Optional, relative to repo root -- scope the diff to one file/directory."},
        },
        "required": [],
    },
}

_GIT_SHOW_TOOL = {
    "name": "git_show",
    "description": "Show a specific real commit's full diff and message.",
    "input_schema": {
        "type": "object",
        "properties": {"ref": {"type": "string", "description": "Commit SHA or ref, e.g. \"HEAD\" or \"a1b2c3d\"."}},
        "required": ["ref"],
    },
}

_RUN_BUILD_CHECK_TOOL = {
    "name": "run_build_check",
    "description": "Runs the real, fixed build-verification command for one platform. Not arbitrary shell -- only these two specific invocations exist.",
    "input_schema": {
        "type": "object",
        "properties": {"target": {"type": "string", "enum": ["desktop", "ios"]}},
        "required": ["target"],
    },
}

_PROPOSE_FILE_EDIT_TOOL = {
    "name": "propose_file_edit",
    "description": (
        "Proposes writing new_content to path. Does NOT write immediately -- sends Joshua a real approval card "
        "(path, your summary, and a real diff against the current file) and blocks until he approves or rejects. "
        "Only writes to disk on explicit approval. new_content must be the complete, real file content, not a "
        "description of the change."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative to repo root. Parent directory must already exist."},
            "new_content": {"type": "string", "description": "The complete new content of the file."},
            "summary": {"type": "string", "description": "A short, real explanation of what this change does and why."},
        },
        "required": ["path", "new_content", "summary"],
    },
}

_ENGINEERING_INNER_TOOLS = [
    _READ_FILE_TOOL,
    _LIST_DIRECTORY_TOOL,
    _GIT_LOG_TOOL,
    _GIT_DIFF_TOOL,
    _GIT_SHOW_TOOL,
    _RUN_BUILD_CHECK_TOOL,
    _PROPOSE_FILE_EDIT_TOOL,
]

_MAX_READ_FILE_BYTES = 200_000  # guards against blowing the inner call's context on a huge/binary file


async def _run_git(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_ROOT), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return f"git error: {stderr.decode(errors='replace').strip()}"
    return stdout.decode(errors="replace")


async def _execute_inner_tool(name: str, tool_input: dict, websocket) -> str:
    try:
        if name == "read_file":
            resolved = resolve_repo_path(tool_input["path"])
            if not resolved.is_file():
                return f"Not a file: {tool_input['path']}"
            if resolved.stat().st_size > _MAX_READ_FILE_BYTES:
                return f"Refused: {tool_input['path']} is too large to read in full ({resolved.stat().st_size} bytes)."
            content = resolved.read_text(encoding="utf-8", errors="replace")
            # Real bug found live (2026-08-27): asked to read a 924-line
            # file and report its exact line count, the model answered
            # 578 -- LLMs are unreliable at precisely counting lines from
            # raw dumped text, the same way they're unreliable at exact
            # character counts. Prepending a Python-computed, actually
            # correct count means any question about a file's size is
            # answered from real data, not the model's own eyeballing.
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"[{line_count} lines]\n{content}"

        if name == "list_directory":
            resolved = resolve_repo_path(tool_input["path"])
            if not resolved.is_dir():
                return f"Not a directory: {tool_input['path']}"
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in resolved.iterdir())
            return "\n".join(entries) if entries else "(empty directory)"

        if name == "git_log":
            args = ["log", f"-n{tool_input.get('limit', 20)}", "--oneline"]
            if tool_input.get("path"):
                resolve_repo_path(tool_input["path"])  # boundary-check even though git only uses it to filter history
                args += ["--", tool_input["path"]]
            return await _run_git(*args)

        if name == "git_diff":
            args = ["diff"]
            if tool_input.get("ref"):
                args.append(tool_input["ref"])
            if tool_input.get("path"):
                resolve_repo_path(tool_input["path"])
                args += ["--", tool_input["path"]]
            return await _run_git(*args)

        if name == "git_show":
            return await _run_git("show", tool_input["ref"])

        if name == "run_build_check":
            return await _run_build_check(tool_input["target"])

        if name == "propose_file_edit":
            return await _propose_file_edit(tool_input, websocket)

        return f"Unknown tool: {name}"
    except UnsafePathError as error:
        return str(error)


async def _run_build_check(target: str) -> str:
    if target == "desktop":
        argv, cwd = ["swift", "build"], REPO_ROOT / "desktop"
    elif target == "ios":
        argv = [
            "xcodebuild", "-project", str(REPO_ROOT / "ios" / "P Corp OS.xcodeproj"),
            "-scheme", "P Corp OS", "-destination", "generic/platform=iOS Simulator", "build",
        ]
        cwd = REPO_ROOT / "ios"
    else:
        return f"Unknown build target: {target}"

    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout + stderr).decode(errors="replace")
    status = "SUCCEEDED" if proc.returncode == 0 else "FAILED"
    return f"Build {status} ({target}):\n{output[-4000:]}"  # tail-truncated, a full xcodebuild log is huge


async def _propose_file_edit(tool_input: dict, websocket) -> str:
    resolved = resolve_repo_path(tool_input["path"])
    if not resolved.parent.is_dir():
        return f"Refused: parent directory of {tool_input['path']} doesn't exist -- this tool won't create new directories implicitly."

    old_content = resolved.read_text(encoding="utf-8", errors="replace") if resolved.is_file() else ""
    diff = "".join(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        tool_input["new_content"].splitlines(keepends=True),
        fromfile=f"a/{tool_input['path']}", tofile=f"b/{tool_input['path']}",
    ))

    request_id = str(uuid.uuid4())
    approval_request = json.dumps({
        "id": request_id,
        "tool": "propose_file_edit",
        "path": tool_input["path"],
        "summary": tool_input["summary"],
        "diff": diff or "(new file, no existing content)",
    })
    await websocket.send_text(f"\n[approval_request]{approval_request}")

    # Blocks here -- nothing else reads this socket while this turn is
    # in-flight (main.py's /ws handler awaits run_claude_turn synchronously
    # inside its own single receive loop iteration). A client disconnect
    # raises WebSocketDisconnect right here, which propagates up through
    # this call, through execute_engineering_agent_tool_call, through
    # run_claude_turn's dispatch loop, to main.py's own outer handling --
    # no special-casing needed here.
    raw = await websocket.receive_text()
    try:
        payload = json.loads(raw)
        response = payload["approval_response"]
        approved = bool(response["approved"]) and response["id"] == request_id
    except (json.JSONDecodeError, KeyError, TypeError):
        return "Rejected: received an unexpected response instead of an approval decision -- no changes written."

    if not approved:
        return f"Rejected by Joshua: {tool_input['path']} (no changes written)."

    resolved.write_text(tool_input["new_content"], encoding="utf-8")
    await websocket.send_text(f"\n[notify]{json.dumps({'title': 'File edit approved', 'body': tool_input['path']})}")
    return f"Approved and written: {tool_input['path']}"


async def execute_engineering_agent_tool_call(
    name: str, tool_input: dict, client: AsyncAnthropic, websocket
) -> str:
    if name != "consult_engineering_agent":
        return f"Unknown tool: {name}"

    inner_history: list = [{"role": "user", "content": tool_input["request"]}]
    assistant_text = ""
    while True:
        async with client.messages.stream(
            model="claude-sonnet-5",
            # Real bug found live (2026-08-27): every other single-shot
            # consult_X_agent uses max_tokens=4096 with no explicit
            # thinking config, fine for their short, context-light
            # requests. Engineering Agent's rounds carry full read_file
            # dumps and git log/diff output into context -- confirmed
            # live that a round can burn an unbounded amount of thinking
            # reasoning over a large file dump and hit stop_reason
            # "max_tokens" with zero visible text, even at max_tokens as
            # high as 20000. The older `thinking={"type": "enabled",
            # "budget_tokens": N}` shape isn't valid for this model
            # (confirmed via a real 400: "not supported for this model.
            # Use thinking.type.adaptive and output_config.effort").
            # Fixed with the model's actual adaptive-thinking controls --
            # bounds reasoning to a real effort level instead of an
            # unbounded budget, with max_tokens raised well past what
            # thinking + a real answer (or a full propose_file_edit
            # new_content) actually needs.
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=ENGINEERING_AGENT_SYSTEM_PROMPT,
            messages=inner_history,
            tools=_ENGINEERING_INNER_TOOLS,
        ) as stream:
            async for text in stream.text_stream:
                assistant_text += text
                await websocket.send_text(text)
            final_message = await stream.get_final_message()

        if final_message.stop_reason != "tool_use":
            return assistant_text

        inner_history.append({"role": "assistant", "content": final_message.content})
        tool_results = []
        for block in final_message.content:
            if block.type != "tool_use":
                continue
            result = await _execute_inner_tool(block.name, block.input, websocket)
            # Real audit trail for each individual inner action (read_file,
            # git_log, propose_file_edit, etc.) -- main.py's own dispatch
            # loop only ever sees and logs the single outer
            # "consult_engineering_agent" call, so without this,
            # SECURITY.md's audit-logging guarantee would have a blind
            # spot for exactly the new tool that most needs granular
            # logging (which file, what was proposed, approved or not).
            await record_tool_call(block.name, block.input, result)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        inner_history.append({"role": "user", "content": tool_results})
