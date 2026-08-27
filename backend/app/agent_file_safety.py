"""
Shared file-boundary safety helper for any agent that touches real files on
disk -- currently only Engineering Agent (backend/app/engineering_agent.py),
but deliberately its own module, not inlined there, so a future file-
touching capability (e.g. Design Agent's still-deferred "Design System
maintenance," AGENTS_VISION.md) reuses this instead of reimplementing
boundary checks per agent.

Two independent checks, both required to pass:
1. The resolved path must stay inside REPO_ROOT (blocks ../ escapes --
   resolved via Path.resolve(), not just string prefix matching).
2. The resolved path must not match the denylist below, regardless of
   whether check 1 passed -- these are genuinely off-limits even though
   they're inside the repo (SECURITY.md's "Prohibited, regardless of
   confirmation" tier: credentials/secrets).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


class UnsafePathError(Exception):
    """Raised when a path fails the boundary or denylist check. Callers
    (engineering_agent.py's inner tool executors) catch this and return a
    plain-text refusal as the tool_result -- never let this propagate into
    an uncaught exception, since Claude still needs to see *some* result to
    keep reasoning."""


def resolve_repo_path(relative_path: str) -> Path:
    """Resolves relative_path against REPO_ROOT. Raises UnsafePathError if
    it escapes the repo root or hits the denylist. Every inner tool that
    takes a path argument (read_file, list_directory, propose_file_edit)
    must call this before touching disk -- no exceptions."""
    candidate = (REPO_ROOT / relative_path).resolve()
    try:
        rel = candidate.relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise UnsafePathError(f"Refused: '{relative_path}' resolves outside the repo root.")
    if _is_denied(rel):
        raise UnsafePathError(f"Refused: '{relative_path}' is on the denylist (secrets/internal data).")
    return candidate


def _is_denied(rel: Path) -> bool:
    parts = rel.parts
    if rel.name == ".env":
        return True
    if parts[:2] == ("backend", "data"):
        return True
    if ".git" in parts:
        return True
    if rel.suffix in (".pem", ".key"):
        return True
    return False
