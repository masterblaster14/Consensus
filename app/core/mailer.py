"""Outbound email: magic links and invites.

Plain SMTP through the standard library, run in a worker thread so the event
loop is never blocked. Without SMTP_HOST nothing is sent: the message is
logged and the caller learns `sent=False` (dev mode also returns the link in
the API response, see app/api/auth.py).
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Returns True when handed to the SMTP server, False when not configured or failed."""
    s = get_settings()
    if not s.smtp_configured:
        log.info("email not sent (SMTP_HOST unset) to=%s subject=%r\n%s", to, subject, text)
        return False

    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    def _send() -> None:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)

    try:
        await asyncio.to_thread(_send)
        return True
    except Exception:
        log.exception("email send failed to=%s subject=%r", to, subject)
        return False


def magic_link_message(link: str, minutes: int) -> tuple[str, str, str]:
    subject = "Your Consensus sign-in link"
    text = (
        f"Sign in to Consensus with this link (valid for {minutes} minutes):\n\n{link}\n\n"
        "If you did not request it, ignore this email."
    )
    html = (
        f"<p>Sign in to Consensus with this link (valid for {minutes} minutes):</p>"
        f'<p><a href="{link}">{link}</a></p><p>If you did not request it, ignore this email.</p>'
    )
    return subject, text, html


def invite_message(org_name: str, url: str, inviter: str, role: str) -> tuple[str, str, str]:
    subject = f"{inviter} invited you to {org_name} on Consensus"
    text = f"{inviter} invited you to join {org_name} as {role}.\n\nAccept the invite:\n{url}\n"
    html = (
        f"<p>{inviter} invited you to join <b>{org_name}</b> as {role}.</p>"
        f'<p><a href="{url}">Accept the invite</a></p><p>{url}</p>'
    )
    return subject, text, html
