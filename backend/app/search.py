"""
Universal search -- backs the War Room top bar's magnifying-glass button
on both platforms, a genuine cross-domain "Spotlight for P Corp OS"
rather than the no-op it's been since first built ("reserved for future
search", never specced further until now). Separate from
GET /conversations?q=... (app/db.py's list_conversations), which searches
real message CONTENT within chat history -- this instead searches the
real named things across every domain (projects, clients, goals, docs,
etc.), and folds conversation results in as one more group alongside
them so a single search box covers both.

Reuses each domain's existing dashboard_snapshot()/list_*() function
rather than writing new SQL/Supabase queries per domain -- these already
assemble each domain's full real data for its own dashboard, so filtering
that same data in Python by substring match is strictly less surface
area than a second, parallel query path per domain that could drift out
of sync with what each dashboard itself actually shows.

Deliberately excludes: Memory (feeds Frank's system prompt only, no nav
section to land on), Operations tasks (no "Operations" NavItem to jump
to), Triggers (5 fixed rule types, toggle-only, not named things worth
searching), Trading Division (backtest run IDs, not named things), and
Calendar (EventKit/AppleScript-backed, a completely different data
source from every other domain here) -- confirmed decisions, not gaps.

RESULTS_PER_DOMAIN caps each domain (including Conversations) at 5
results, applied per-domain before results are concatenated -- so a
common word in one noisy domain can't bury results from every other
domain further down an unbounded flat list. Each domain's searcher runs
independently and fails soft (an exception in one never blanks the
rest), same "fail soft independently" reasoning already used throughout
this codebase.
"""

from app.alpha_mode_supabase import dashboard_snapshot as alpha_mode_dashboard_snapshot
from app.automations_registry import AUTOMATIONS
from app.db import list_conversations
from app.finance_db import dashboard_snapshot as finance_dashboard_snapshot
from app.joshx_db import dashboard_snapshot as joshx_dashboard_snapshot
from app.knowledge import list_docs as list_knowledge_docs
from app.personal_db import dashboard_snapshot as personal_dashboard_snapshot

RESULTS_PER_DOMAIN = 5


def _matches(query: str, *fields: str | None) -> bool:
    return any(field and query in field.lower() for field in fields)


async def _search_knowledge(query: str) -> list[dict]:
    docs = await list_knowledge_docs()
    hits = [
        {
            "domain": "Knowledge",
            "title": doc["title"],
            "subtitle": doc["subtitle"],
            "target_nav_title": "Knowledge",
            "conversation_id": None,
        }
        for doc in docs
        if _matches(query, doc["title"], doc["subtitle"])
    ]
    return hits[:RESULTS_PER_DOMAIN]


async def _search_alpha_mode(query: str) -> list[dict]:
    snapshot = await alpha_mode_dashboard_snapshot()
    hits: list[dict] = []
    for project in snapshot.get("projects", []):
        if _matches(query, project.get("project_name"), project.get("client")):
            hits.append({
                "domain": "Alpha Mode Media",
                "title": project.get("project_name") or "(untitled project)",
                "subtitle": f"{project.get('client', '?')} — {project.get('stage', '?')}",
                "target_nav_title": "Alpha Mode Media",
                "conversation_id": None,
            })
    for invoice in snapshot.get("invoices", []):
        proj = invoice.get("projects") or {}
        if _matches(query, proj.get("project_name"), proj.get("client"), invoice.get("status")):
            hits.append({
                "domain": "Alpha Mode Media",
                "title": proj.get("project_name") or "(untitled project)",
                "subtitle": (
                    f"Invoice — R{invoice.get('amount', 0):,.2f} for "
                    f"{proj.get('client', '?')} ({invoice.get('status', '?')})"
                ),
                "target_nav_title": "Alpha Mode Media",
                "conversation_id": None,
            })
    for lead in snapshot.get("leads", []):
        if _matches(query, lead.get("client")):
            hits.append({
                "domain": "Alpha Mode Media",
                "title": lead.get("client") or "(unnamed lead)",
                "subtitle": f"Lead — {lead.get('temperature', '?')}",
                "target_nav_title": "Alpha Mode Media",
                "conversation_id": None,
            })
    return hits[:RESULTS_PER_DOMAIN]


async def _search_joshx(query: str) -> list[dict]:
    snapshot = await joshx_dashboard_snapshot()
    hits: list[dict] = []
    for client in snapshot.get("clients", []):
        if _matches(query, client.get("name"), client.get("company")):
            hits.append({
                "domain": "Joshx",
                "title": client["name"],
                "subtitle": f"Client — {client.get('company') or client.get('status', '?')}",
                "target_nav_title": "Joshx",
                "conversation_id": None,
            })
    for lead in snapshot.get("leads", []):
        if _matches(query, lead.get("client_name"), lead.get("project_description")):
            hits.append({
                "domain": "Joshx",
                "title": lead.get("client_name") or "(unnamed lead)",
                "subtitle": f"Lead — {lead.get('project_description') or lead.get('stage', '?')}",
                "target_nav_title": "Joshx",
                "conversation_id": None,
            })
    for project in snapshot.get("projects", []):
        if _matches(query, project.get("project_name"), project.get("client_name")):
            hits.append({
                "domain": "Joshx",
                "title": project.get("project_name") or "(untitled project)",
                "subtitle": f"{project.get('client_name', '?')} — {project.get('status', '?')}",
                "target_nav_title": "Joshx",
                "conversation_id": None,
            })
    return hits[:RESULTS_PER_DOMAIN]


async def _search_finance(query: str) -> list[dict]:
    snapshot = await finance_dashboard_snapshot()
    hits: list[dict] = []
    for account in snapshot.get("accounts", []):
        asset_names = [h.get("asset") for h in account.get("holdings", [])]
        if _matches(query, account.get("name"), account.get("account_type"), *asset_names):
            assets_summary = ", ".join(a for a in asset_names if a) or "no holdings logged"
            hits.append({
                "domain": "Finance",
                "title": account["name"],
                "subtitle": f"{account.get('account_type', '?')} — {assets_summary}",
                "target_nav_title": "Finance",
                "conversation_id": None,
            })
    return hits[:RESULTS_PER_DOMAIN]


async def _search_personal(query: str) -> list[dict]:
    snapshot = await personal_dashboard_snapshot()
    hits: list[dict] = []
    for goal in snapshot.get("goals", []):
        if _matches(query, goal.get("title"), goal.get("notes")):
            hits.append({
                "domain": "Personal",
                "title": goal["title"],
                "subtitle": f"Goal — {goal.get('status', '?')}",
                "target_nav_title": "Personal",
                "conversation_id": None,
            })
    for habit in snapshot.get("habits", []):
        if _matches(query, habit.get("title"), habit.get("notes")):
            hits.append({
                "domain": "Personal",
                "title": habit["title"],
                "subtitle": f"Habit — {habit.get('cadence', '?')}",
                "target_nav_title": "Personal",
                "conversation_id": None,
            })
    return hits[:RESULTS_PER_DOMAIN]


async def _search_automations(query: str) -> list[dict]:
    hits = [
        {
            "domain": "Automations",
            "title": rule["name"],
            "subtitle": rule["description"],
            "target_nav_title": "Automations",
            "conversation_id": None,
        }
        for rule in AUTOMATIONS
        if _matches(query, rule.get("name"), rule.get("description"))
    ]
    return hits[:RESULTS_PER_DOMAIN]


async def _search_conversations(query: str) -> list[dict]:
    conversations = await list_conversations(query=query)
    hits = [
        {
            "domain": "Conversations",
            "title": conversation.get("first_message") or "New conversation",
            "subtitle": (
                f"{conversation['message_count']} message"
                f"{'s' if conversation['message_count'] != 1 else ''}"
            ),
            "target_nav_title": None,
            "conversation_id": conversation["id"],
        }
        for conversation in conversations
    ]
    return hits[:RESULTS_PER_DOMAIN]


_DOMAIN_SEARCHERS = [
    _search_knowledge,
    _search_alpha_mode,
    _search_joshx,
    _search_finance,
    _search_personal,
    _search_automations,
    _search_conversations,
]


async def search_all(query: str) -> list[dict]:
    """Backs GET /search?q=... . Case-insensitive substring match against
    each domain's real name/title-like fields (see each _search_* helper
    above for exactly which fields), reusing each domain's own
    dashboard_snapshot()/list_*() rather than a second query path per
    domain. Each domain is tried independently -- one bad domain (a
    Supabase hiccup, a locked SQLite file) logs and is skipped rather than
    failing the whole search."""
    trimmed = query.strip().lower()
    if not trimmed:
        return []

    results: list[dict] = []
    for searcher in _DOMAIN_SEARCHERS:
        try:
            results += await searcher(trimmed)
        except Exception as exc:
            print(f"[search] {searcher.__name__} failed: {exc}")
    return results
