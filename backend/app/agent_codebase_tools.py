"""
Shared codebase-access toolset and inner agentic loop -- extracted
(2026-08-27) from engineering_agent.py once a second and third agent
(Design, Operations) needed the exact same real file/git access behind
the exact same approval-gated write path. Rule of three: the first
version lived inline in Engineering Agent since it was the only
consumer; duplicating it a second and third time would have been the
wrong call.

Same scope as when this only served Engineering Agent -- see
SECURITY.md's 2026-08-27 entry for the full tier classification:
  - Regular (auto-allowed): read_file, list_directory, git_log, git_diff,
    git_show, run_build_check -- all read-only, local-only, no write
    capability at all.
  - Needs explicit confirmation: propose_file_edit -- the ONLY tool that
    can touch disk, and it never writes directly. It sends an
    "\n[approval_request]" over the websocket and blocks on the client's
    answer; only writes on explicit approval.
  - Prohibited entirely, not silently omitted: arbitrary shell execution,
    `git commit`/`git push`/any git write operation, editing
    .env/secrets, deleting files. No tool for any of these exists.

`run_agentic_loop` is the shared inner tool-use loop -- structurally
mirrors main.py's own run_claude_turn, but scoped to just this toolset
and its own local `inner_history` per call, so whichever specialist
agent's outer conversation (Frank's) never sees the intermediate
read_file/git_log/propose_file_edit round trips, only the final
accumulated text -- same as every other consult_X_agent tool's internals
are invisible to Frank. Takes an optional `image` for Design Agent's own
multimodal first-turn need (Design Critic actually looking at attached
pixels); every other caller omits it.
"""

import asyncio
import difflib
import json
import uuid

from anthropic import AsyncAnthropic

from app.agent_file_safety import REPO_ROOT, UnsafePathError, resolve_repo_path
from app.audit_db import record_tool_call

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a real file's full text content, path relative to the repo root (e.g. \"backend/app/main.py\").",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

LIST_DIRECTORY_TOOL = {
    "name": "list_directory",
    "description": "List a real directory's contents, path relative to the repo root (use \".\" for the repo root itself).",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

GIT_LOG_TOOL = {
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

GIT_DIFF_TOOL = {
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

GIT_SHOW_TOOL = {
    "name": "git_show",
    "description": "Show a specific real commit's full diff and message.",
    "input_schema": {
        "type": "object",
        "properties": {"ref": {"type": "string", "description": "Commit SHA or ref, e.g. \"HEAD\" or \"a1b2c3d\"."}},
        "required": ["ref"],
    },
}

RUN_BUILD_CHECK_TOOL = {
    "name": "run_build_check",
    "description": "Runs the real, fixed build-verification command for one platform. Not arbitrary shell -- only these two specific invocations exist.",
    "input_schema": {
        "type": "object",
        "properties": {"target": {"type": "string", "enum": ["desktop", "ios"]}},
        "required": ["target"],
    },
}

PROPOSE_FILE_EDIT_TOOL = {
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

CODEBASE_TOOLS = [
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    GIT_LOG_TOOL,
    GIT_DIFF_TOOL,
    GIT_SHOW_TOOL,
    RUN_BUILD_CHECK_TOOL,
    PROPOSE_FILE_EDIT_TOOL,
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


async def execute_codebase_tool(name: str, tool_input: dict, websocket) -> str:
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
    # this call, through run_agentic_loop, through run_claude_turn's
    # dispatch loop, to main.py's own outer handling (its dedicated
    # `except WebSocketDisconnect: raise` ahead of the generic turn-error
    # catch) -- no special-casing needed here.
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


async def run_agentic_loop(
    system_prompt: str,
    initial_request: str,
    client: AsyncAnthropic,
    websocket,
    image: dict | None = None,
) -> str:
    """Shared inner tool-use loop for any specialist agent that needs real
    codebase access. `image` mirrors design_agent.py's own multimodal
    content-block construction -- only meaningful on the first turn, never
    on later tool-result rounds."""
    if image and image.get("data") and image.get("media_type"):
        initial_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image["media_type"], "data": image["data"]},
            },
            {"type": "text", "text": initial_request},
        ]
    else:
        initial_content = initial_request

    inner_history: list = [{"role": "user", "content": initial_content}]
    assistant_text = ""
    while True:
        async with client.messages.stream(
            model="claude-sonnet-5",
            # Real bug found live (2026-08-27, while this lived in
            # engineering_agent.py): every other single-shot consult_X_agent
            # uses max_tokens=4096 with no explicit thinking config, fine
            # for their short, context-light requests. A codebase-access
            # round can carry full read_file dumps and git log/diff output
            # into context -- confirmed live that a round can burn an
            # unbounded amount of thinking reasoning over a large file dump
            # and hit stop_reason "max_tokens" with zero visible text, even
            # at max_tokens as high as 20000. The older `thinking={"type":
            # "enabled", "budget_tokens": N}` shape isn't valid for this
            # model (confirmed via a real 400: "not supported for this
            # model. Use thinking.type.adaptive and output_config.effort").
            # Fixed with the model's actual adaptive-thinking controls.
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=system_prompt,
            messages=inner_history,
            tools=CODEBASE_TOOLS,
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
            result = await execute_codebase_tool(block.name, block.input, websocket)
            # Real audit trail for each individual inner action (read_file,
            # git_log, propose_file_edit, etc.) -- main.py's own dispatch
            # loop only ever sees and logs the single outer consult_X_agent
            # call, so without this, SECURITY.md's audit-logging guarantee
            # would have a blind spot for exactly the actions that most
            # need granular logging (which file, what was proposed,
            # approved or not).
            await record_tool_call(block.name, block.input, result)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        inner_history.append({"role": "user", "content": tool_results})
