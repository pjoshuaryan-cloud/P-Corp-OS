"""
The Proactive Triggers Layer's delivery channel (2026-09-07, replacing
email_digest.py per Joshua's own request: "instead of email, pop up as a
notification"). A real macOS notification via `osascript`, not
`UserNotifications` -- same reasoning as PCorpOSApp.swift's own
SystemNotification.poster: `osascript` needs no bundle identity or
entitlement, unlike UNUserNotificationCenter, which is documented in that
file as hard-crashing on this build. This backend's `launchd` job already
runs in the user's own GUI session, so `display notification` works here
exactly as it does from the desktop app's own process.

Fails loud, not soft, on purpose -- same explicit contract email_digest.py
stated: a digest that silently never shows would defeat the entire point
of this layer. triggers.py's run_daily_digest() depends on a raised
exception here to skip mark_notified, so a failed send is retried on the
next scheduler tick rather than recorded as done.
"""

import subprocess


def _apple_script_string(text: str) -> str:
    """Mirrors PCorpOSApp.swift's own appleScriptString exactly (escape
    backslashes first, then double-quotes) so a client/project name
    containing a quote can't break the AppleScript literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_digest_notification(title: str, body: str) -> None:
    script = f"display notification {_apple_script_string(body)} with title {_apple_script_string(title)}"
    subprocess.run(["/usr/bin/osascript", "-e", script], check=True, timeout=10)
