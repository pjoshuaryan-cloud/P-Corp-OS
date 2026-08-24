"""
Read/write access to the real macOS Calendar app for Frank's tools
(2026-08-24). Extends the read-only pattern already proven in
desktop/Sources/PCorpOS/SystemCalendar.swift -- AppleScript automation,
not EventKit (confirmed there 2026-07-26 that EventKit silently denies
access without a real app bundle/Info.plist, while AppleScript
automation doesn't need that same entitlement).

Runs server-side in the Python backend via subprocess, not through the
Swift desktop app -- no bridge needed, since the backend already runs
locally on Josh's own Mac as a supervised launchd service and can call
`osascript` directly. Confirmed live (2026-08-24) this works from the
backend's actual Python process with no Automation-permission block hit,
once Calendar.app is actually running -- AppleScript's own `launch`
command inside a single -e script wasn't reliably enough on its own; a
separate `open -a Calendar` beforehand, then a short wait, is the
sequence that's actually proven to work.

Scope, deliberately narrow: plain personal events only -- no attendees,
no invites. Adding attendees would mean Frank silently sending
notifications to other people, which is "send a message on Josh's
behalf" territory (this app's own standing permission boundary), not a
local reversible action like everything else Frank's tools do. If Josh
ever wants Frank scheduling meetings with other people, that's a real,
separate, later decision -- not implied by "update my calendar."

Dates are set/read via individual components (year/month/day/hour/
minute), never a parsed date string literal -- same technique already
proven necessary in the Swift read path (AppleScript's own date<->string
coercion is locale-dependent and was confirmed there to silently
mis-parse), just applied in both directions here.
"""

import asyncio
import subprocess
from datetime import datetime

DEFAULT_LOOKAHEAD_DAYS = 90
_RECORD_SEP = ""
_FIELD_SEP = ""


def _escape(text: str) -> str:
    """AppleScript string literal escaping -- backslash and double-quote
    are the only characters that break a "..." literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


async def _run_osascript(script: str) -> tuple[bool, str]:
    subprocess.run(["open", "-a", "Calendar"], capture_output=True)
    await asyncio.sleep(1)
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return False, stderr.decode("utf-8", errors="replace")
    return True, stdout.decode("utf-8", errors="replace")


def _set_date_components(var_name: str, dt: datetime) -> str:
    return (
        f"set {var_name} to current date\n"
        f"set year of {var_name} to {dt.year}\n"
        f"set month of {var_name} to {dt.month}\n"
        f"set day of {var_name} to {dt.day}\n"
        f"set hours of {var_name} to {dt.hour}\n"
        f"set minutes of {var_name} to {dt.minute}\n"
        f"set seconds of {var_name} to 0\n"
    )


def _find_target_snippet(identifier: str, lookahead_days: int) -> str:
    """Shared by update/delete -- searches every calendar for events
    whose title contains `identifier`, within a forward-looking window
    (never matches a stale past event by title collision), and selects
    the single soonest match. Leaves `target` set if found, and
    `targetCal` set to its calendar (deletion needs the calendar
    reference, not just the event). Callers check `if target is missing
    value` first."""
    return (
        "set matchStart to current date\n"
        f"set matchEnd to matchStart + ({lookahead_days} * days)\n"
        "set target to missing value\n"
        "set targetCal to missing value\n"
        "repeat with cal in calendars\n"
        "try\n"
        f'set calMatches to (every event of cal whose summary contains "{_escape(identifier)}" '
        "and start date ≥ matchStart and start date ≤ matchEnd)\n"
        "repeat with e in calMatches\n"
        "if target is missing value or start date of e < start date of target then\n"
        "set target to e\n"
        "set targetCal to cal\n"
        "end if\n"
        "end repeat\n"
        "end try\n"
        "end repeat\n"
    )


async def create_event(
    title: str,
    start: datetime,
    end: datetime,
    calendar_name: str | None = None,
    location: str | None = None,
) -> bool:
    # Real thing found live (2026-08-24): Calendar.app's AppleScript
    # dictionary has no "default calendar" property at all -- confirmed
    # directly (`tell application "Calendar" to get name of default
    # calendar` fails with "A class name can't go after this
    # identifier"). `item 1 of calendars` is the real, confirmed-working
    # fallback when Josh doesn't name a specific calendar.
    calendar_ref = f'calendar "{_escape(calendar_name)}"' if calendar_name else "item 1 of calendars"
    location_line = f'set location of newEvent to "{_escape(location)}"\n' if location else ""
    script = (
        'tell application "Calendar"\n'
        + _set_date_components("startDate", start)
        + _set_date_components("endDate", end)
        + f"tell {calendar_ref}\n"
        f'set newEvent to make new event with properties {{summary:"{_escape(title)}", '
        "start date:startDate, end date:endDate}\n" + location_line + "end tell\nend tell\n"
    )
    ok, _ = await _run_osascript(script)
    return ok


async def update_event(
    identifier: str,
    new_title: str | None = None,
    new_start: datetime | None = None,
    new_end: datetime | None = None,
) -> bool:
    """Finds the soonest upcoming event whose title contains `identifier`
    and applies only the fields actually given -- leaves everything else
    on the event untouched."""
    if new_title is None and new_start is None and new_end is None:
        return False
    set_lines = ""
    if new_title is not None:
        set_lines += f'set summary of target to "{_escape(new_title)}"\n'
    if new_start is not None and new_end is not None:
        # Real error found live (2026-08-24): Calendar.app validates
        # start < end on every single property write, not just the
        # final state -- setting start date to something after the
        # event's still-old end date fails outright ("The start date
        # must be before the end date"), even though the caller's final
        # values are perfectly valid together. A placeholder end date
        # far enough out that it's guaranteed to exceed newStart makes
        # every intermediate write valid, regardless of which direction
        # both dates are moving.
        set_lines += (
            _set_date_components("farEnd", new_end.replace(year=new_end.year + 5))
            + "set end date of target to farEnd\n"
            + _set_date_components("newStart", new_start)
            + "set start date of target to newStart\n"
            + _set_date_components("newEnd", new_end)
            + "set end date of target to newEnd\n"
        )
    elif new_start is not None:
        set_lines += _set_date_components("newStart", new_start) + "set start date of target to newStart\n"
    elif new_end is not None:
        set_lines += _set_date_components("newEnd", new_end) + "set end date of target to newEnd\n"
    script = (
        'tell application "Calendar"\n'
        + _find_target_snippet(identifier, DEFAULT_LOOKAHEAD_DAYS)
        + "if target is missing value then\nreturn \"NOT_FOUND\"\nend if\n"
        + set_lines
        + 'return "OK"\nend tell\n'
    )
    ok, output = await _run_osascript(script)
    return ok and "NOT_FOUND" not in output


async def delete_event(identifier: str) -> bool:
    script = (
        'tell application "Calendar"\n'
        + _find_target_snippet(identifier, DEFAULT_LOOKAHEAD_DAYS)
        + "if target is missing value then\nreturn \"NOT_FOUND\"\nend if\n"
        "delete target\n"
        'return "OK"\nend tell\n'
    )
    ok, output = await _run_osascript(script)
    return ok and "NOT_FOUND" not in output


def _parse_date_components(text: str) -> datetime | None:
    parts = text.split("-")
    if len(parts) != 5:
        return None
    try:
        year, month, day, hour, minute = (int(p) for p in parts)
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _parse_events(output: str) -> list[dict]:
    events = []
    for record in output.split(_RECORD_SEP):
        if not record.strip():
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) != 4:
            continue
        start = _parse_date_components(fields[1])
        end = _parse_date_components(fields[2])
        if start is None or end is None:
            continue
        events.append({"title": fields[0], "start": start.isoformat(), "end": end.isoformat(), "calendar": fields[3]})
    return sorted(events, key=lambda e: e["start"])


async def list_events(days: int = 7) -> list[dict]:
    """Same script shape as the Swift read path -- exists so Frank can
    check what's already on the calendar (avoid double-booking, find a
    real free slot) without needing the desktop app open."""
    script = (
        'tell application "Calendar"\n'
        "set startDate to current date\n"
        f"set endDate to startDate + ({days} * days)\n"
        'set output to ""\n'
        "repeat with cal in calendars\n"
        "try\n"
        "set calEvents to (every event of cal whose start date ≥ startDate and start date ≤ endDate)\n"
        "repeat with e in calEvents\n"
        "set sd to start date of e\n"
        "set ed to end date of e\n"
        'set output to output & (summary of e as string) & (ASCII character 1) & (year of sd) & "-" & '
        '(month of sd as integer) & "-" & (day of sd) & "-" & (hours of sd) & "-" & (minutes of sd) & '
        '(ASCII character 1) & (year of ed) & "-" & (month of ed as integer) & "-" & (day of ed) & "-" & '
        '(hours of ed) & "-" & (minutes of ed) & (ASCII character 1) & (name of cal as string) & (ASCII character 2)\n'
        "end repeat\n"
        "end try\n"
        "end repeat\n"
        "return output\n"
        "end tell\n"
    )
    ok, output = await _run_osascript(script)
    if not ok:
        return []
    return _parse_events(output)
