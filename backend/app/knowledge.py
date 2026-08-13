"""
Backs the "Knowledge" nav section over HTTP -- desktop reads these same
project markdown docs directly off local disk (desktop/Sources/PCorpOS/
KnowledgeDocs.swift + ProjectPaths.swift), which only works because the
desktop app runs on the same Mac as the repo. The iOS app runs on a phone
with no filesystem access to this Mac at all, so it needs the exact same
docs served over the network instead -- this is that surface.

DOCS mirrors desktop's KnowledgeDocs.all by hand (same filename/title/
subtitle triples) rather than desktop importing this, since desktop's
version predates this file and already works; kept in sync manually, same
tradeoff already accepted for NavItem.items vs. desktop's PlaceholderData.
navItems on the iOS side.

Filenames are validated against this exact list before ever touching disk
-- never taken as a free-form path from the request, which would otherwise
be a real path-traversal opening (e.g. "../backend/.env").
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

DOCS = [
    {"filename": "FOUNDER_BRIEF.md", "title": "Founder Brief", "subtitle": "The authoritative source of truth"},
    {"filename": "ROADMAP.md", "title": "Roadmap", "subtitle": "Phased build sequence"},
    {"filename": "TECH_STACK.md", "title": "Tech Stack", "subtitle": "Platform decisions and trade-offs"},
    {"filename": "ARCHITECTURE.md", "title": "Architecture", "subtitle": "Three-layer system design"},
    {"filename": "PERSONALITY_SPEC.md", "title": "Personality Spec", "subtitle": "Frank's character model"},
    {"filename": "MEMORY_SYSTEM.md", "title": "Memory System", "subtitle": "How Frank remembers"},
    {"filename": "SECURITY.md", "title": "Security", "subtitle": "Permission model and threat model"},
    {"filename": "UI_GUIDELINES.md", "title": "UI Guidelines", "subtitle": "Visual language decisions"},
    {"filename": "ENGINEERING_MANUAL.md", "title": "Engineering Manual", "subtitle": "Code review, workflow, tooling"},
    {"filename": "WAR_ROOM.md", "title": "War Room", "subtitle": "The home screen concept"},
    {"filename": "ALPHA_MODE.md", "title": "Alpha Mode", "subtitle": "Business integration plan"},
    {"filename": "TRADING_DIVISION.md", "title": "Trading Division", "subtitle": "Frank's role with the robot"},
    {"filename": "MASTER_SPEC.md", "title": "Master Spec", "subtitle": "Top-level project spec"},
    {"filename": "README.md", "title": "README", "subtitle": "Repo overview"},
    {"filename": "CHANGELOG.md", "title": "Changelog", "subtitle": "Full build history"},
]

_ALLOWED_FILENAMES = {doc["filename"] for doc in DOCS}


async def list_docs() -> list[dict]:
    return DOCS


async def read_doc(filename: str) -> str:
    if filename not in _ALLOWED_FILENAMES:
        return f"Unknown document: {filename}"
    path = REPO_ROOT / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return f"Couldn't read {filename}."
