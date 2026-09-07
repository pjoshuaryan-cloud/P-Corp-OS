"""
Frank's direct web access (2026-09-06, P Corp OS systems audit §10): "Frank
can't search directly -- every web question costs a full extra round-trip
through consult_research_agent. There's no general 'fetch and read this
URL' tool at all."

Both tools here are Anthropic-native server tools, not client-side
functions -- Anthropic's own infrastructure runs the search/fetch and
injects results back into the same streamed response; this backend never
sees a tool_use block for either one and has nothing to dispatch or
execute. research_agent.py already proved web_search works this way with
zero client-side code; web_fetch (installed in the SDK, never previously
used anywhere in this codebase) closes the other half of §10.

No dispatch function, no *_TOOL_NAMES set -- there is nothing to add to
main.py's tool_use elif chain or to tool_labels.py's ALL_TOOL_NAMES union,
since neither of those code paths is ever reached by a server tool call.
SERVER_TOOL_LABELS exists purely for main.py's raw-event stream handling,
so a direct search/fetch still gets an honest "\n[tool_start]" indicator
instead of a silent pause -- the one real gap a naive "just add the tool"
version of this feature would have introduced.

No domain allow/block-list -- matches web_search's own existing no-
restriction precedent in research_agent.py; this is a single-user
assistant, not a multi-tenant surface.
"""

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

WEB_FETCH_TOOL = {
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    "max_uses": 5,
    # Caps one fetched page's contribution to input context -- a long
    # article or documentation page shouldn't silently eat a huge chunk
    # of the turn's context budget.
    "max_content_tokens": 8000,
    # Disabled by default per the API's own param docs -- turned on
    # (2026-09-06, deep research pipeline, systems audit §11) so fetched-
    # page text carries real url/title citation data on its own text
    # blocks. web_search attaches citations automatically with no config
    # needed; this is the one tool of the two that needs an explicit opt
    # in. Safe for Frank's own direct top-level use too -- an unhandled
    # event type in main.py's stream loop is silently skipped today.
    "citations": {"enabled": True},
}

WEB_TOOLS = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]

SERVER_TOOL_LABELS = {
    "web_search": "Searching the web",
    "web_fetch": "Reading a webpage",
}
