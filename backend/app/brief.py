"""
"The Brief" (2026-08-20, Face-Lift item 09) -- Frank's daily executive
briefing. Deliberately NOT LLM-generated -- same "deterministic, no
hallucination risk, no ongoing cost" reasoning already applied to
insights.py/situation_room.py. "What Frank recommends"/"what matters"
here means "surfaced in a specific real bucket," not free-text generated
commentary -- every item is something the app already computes elsewhere,
just organized into the brief's four sections instead of invented fresh.

WHAT MATTERS -- Situation Room's existing escalated-severity alerts, plus
risk-category Insights.
WHAT CHANGED -- real logged tool calls (audit_db.py's existing audit
trail) since the last time this endpoint was actually viewed. Tracked via
a new `last_brief_viewed_at` column on app_state (db.py) -- the existing
singleton-row table already used for active_conversation_id/
current_objective, not a new table. Viewing the Brief updates that
timestamp, so "what changed" always means "since you last looked," not a
fixed window.
WHAT FRANK RECOMMENDS -- opportunity-category Insights (a warm lead, an
unanswered quote) -- genuinely worth acting on, not routine.
WHAT CAN WAIT -- follow_up-category Insights, the lowest-urgency tier
insights.py already categorizes.
"""

from app.audit_db import list_recent_calls
from app.db import get_brief_last_viewed_at, mark_brief_viewed
from app.insights import compute_insights
from app.situation_room import compute_situation_room_alerts

# Higher than the right rail's Insights card (limit=5, sized for a small
# always-visible card) -- the Brief is a dedicated, deliberately-opened
# view, so it can afford to show more without feeling cluttered the way
# cramming this many rows into War Room's persistent Insights card would.
INSIGHTS_LIMIT = 20
RECENT_CALLS_LIMIT = 50


def _normalize_situation_alert(alert: dict) -> dict:
    # Situation Room alerts (situation_room.py) only ever carry title/
    # detail -- no icon/category/target_nav_title, unlike Insights items.
    # Normalized into the same shape here so the frontend deals with one
    # consistent item type across all four sections, not two different
    # dict shapes silently mixed into one array.
    return {
        "title": alert["title"],
        "detail": alert["detail"],
        "target_nav_title": None,
        "icon": "exclamationmark.triangle.fill",
        "priority": 0,
        "category": "risk",
    }


async def compute_brief() -> dict:
    last_viewed = await get_brief_last_viewed_at()
    insights = await compute_insights(limit=INSIGHTS_LIMIT)
    situation_alerts = [_normalize_situation_alert(a) for a in await compute_situation_room_alerts()]

    what_matters = situation_alerts + [item for item in insights if item["category"] == "risk"]
    what_frank_recommends = [item for item in insights if item["category"] == "opportunity"]
    what_can_wait = [item for item in insights if item["category"] == "follow_up"]

    recent_calls = await list_recent_calls(limit=RECENT_CALLS_LIMIT)
    what_changed = (
        recent_calls if last_viewed is None else [c for c in recent_calls if c["created_at"] > last_viewed]
    )

    await mark_brief_viewed()

    return {
        "what_matters": what_matters,
        "what_changed": what_changed,
        "what_frank_recommends": what_frank_recommends,
        "what_can_wait": what_can_wait,
    }
