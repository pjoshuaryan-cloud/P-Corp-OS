"""
Real future-dated device notifications (2026-09-18) -- the closest
working substitute for "set an alarm" or "remind me at X." No third-party
app can create an actual system Alarm on iOS or macOS (a real Apple
platform restriction, not a P Corp scoping choice); this instead tells
whichever client is connected when Frank processes the request to
register a real UNUserNotificationCenter notification with the OS itself
(PCorpKit/ScheduledNotifications.swift), which then fires even if that
app isn't open or connected at the target time.

Same "regular" permission tier as save_memory/set_focus_objective
(SECURITY.md): local-only, reversible (nothing persists server-side --
once the sentinel is sent, the OS on the client device owns it), no
external effect.

Deliberately takes hour/minute/day_offset rather than an absolute ISO
datetime: Claude has no reliable way to know "today's real date" on its
own, so asking it to compute an absolute calendar date itself risks a
hallucinated one. Python computes the real fire_at against its own
datetime.now() instead, using only the small, low-risk pieces (time of
day, day offset) Claude actually needs to interpret from the user's
words.
"""

import json
from datetime import datetime, timedelta

SCHEDULE_NOTIFICATION_TOOL = {
    "name": "schedule_notification",
    "description": (
        "Schedule a real device notification (banner + sound) to fire at a specific future time on whichever "
        "device Joshua is talking to you on right now -- the closest real substitute for 'set an alarm' or "
        "'remind me at X', since no third-party app (including this one) can create an actual system Alarm on "
        "iOS or macOS. Registers directly with that device's own OS notification scheduler, so it fires even if "
        "the app isn't open or connected to you at the target time. Use this when Joshua asks to be woken up, "
        "reminded, or pinged at a specific time -- not for immediate confirmations, which are just a normal "
        "chat reply."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Notification title, e.g. \"Wake up\" or \"Call reminder\"."},
            "body": {"type": "string", "description": "Notification body text, e.g. \"It's 6:00 AM.\""},
            "hour": {"type": "integer", "description": "Hour of day to fire at, 24-hour format, 0-23 (6 = 6am, 18 = 6pm)."},
            "minute": {"type": "integer", "description": "Minute of the hour, 0-59. Use 0 if Joshua didn't specify one."},
            "day_offset": {
                "type": "integer",
                "description": (
                    "0 = today, 1 = tomorrow, 2 = the day after, etc. If Joshua names a time with no day (e.g. "
                    "\"wake me up at 6am\") and that time has already passed today, use 1, not 0."
                ),
            },
        },
        "required": ["title", "body", "hour", "minute", "day_offset"],
    },
}

SCHEDULED_NOTIFICATION_TOOLS = [SCHEDULE_NOTIFICATION_TOOL]
SCHEDULED_NOTIFICATION_TOOL_NAMES = {tool["name"] for tool in SCHEDULED_NOTIFICATION_TOOLS}


async def execute_scheduled_notification_tool_call(name: str, tool_input: dict, websocket) -> str:
    if name != "schedule_notification":
        return f"Unknown tool: {name}"

    hour = tool_input["hour"]
    minute = tool_input["minute"]
    day_offset = tool_input["day_offset"]

    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return f"Invalid time of day: {hour:02d}:{minute:02d} -- hour must be 0-23, minute 0-59."
    if day_offset < 0:
        return "day_offset can't be negative -- can't schedule a notification in the past."

    fire_at = (datetime.now() + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if fire_at <= datetime.now():
        return (
            f"{fire_at.strftime('%A, %b %d at %I:%M %p')} has already passed -- "
            f"try day_offset={day_offset + 1} if you meant the next day."
        )

    payload = json.dumps({"title": tool_input["title"], "body": tool_input["body"], "fire_at": fire_at.isoformat()})
    await websocket.send_text(f"\n[schedule_notification]{payload}")
    return f"Scheduled {tool_input['title']!r} for {fire_at.strftime('%A, %b %d at %I:%M %p')}."
