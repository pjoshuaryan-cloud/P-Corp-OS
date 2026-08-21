"""
The Proactive Triggers Layer's one delivery channel (2026-08-21), chosen
over Slack/push per Joshua's own call: no new account/app to register,
just an existing Gmail address + an app password — same "one API key in
.env, nothing this backend touches beyond reading os.environ" shape as
ELEVENLABS_API_KEY, not a new integration pattern. Plain smtplib over TLS;
no SDK needed for one outbound message a day.

Fails loud, not soft, on purpose — unlike alpha_mode_supabase.py's
fail-soft reads (a blank dashboard card is harmless), a digest that
silently never sends would defeat the entire point of this layer. Callers
(triggers.py) let a raised exception stop mark_digest_sent from being
called, so a failed send is retried on the next scheduler tick rather than
recorded as done.
"""

import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))


def send_digest_email(subject: str, body: str) -> None:
    user = os.environ["EMAIL_SMTP_USER"]
    app_password = os.environ["EMAIL_SMTP_APP_PASSWORD"]
    to_addr = os.environ.get("EMAIL_DIGEST_TO") or user

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(user, app_password)
        server.sendmail(user, [to_addr], msg.as_string())
