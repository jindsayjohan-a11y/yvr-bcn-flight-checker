"""Shared Gmail helpers for alerts and summaries."""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage

DEFAULT_EMAIL_TO = "bcw3bcw3@gmail.com"


def send_email(subject: str, body: str, to_addr: str | None = None) -> bool:
    """Send email via Gmail SMTP using GMAIL_USER + GMAIL_APP_PASSWORD."""
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    dest = (to_addr or os.environ.get("EMAIL_TO", DEFAULT_EMAIL_TO)).strip() or DEFAULT_EMAIL_TO

    if not user or not password:
        print(
            "Email skipped (set GMAIL_USER and GMAIL_APP_PASSWORD secrets to enable).",
            file=sys.stderr,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = dest
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"Email sent to {dest}: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Email failed: {exc}", file=sys.stderr)
        return False
