"""Plain SMTP sending (any provider: Gmail app password, Brevo, Resend, Amazon SES, Mailgun...)."""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from app.core.config import get_settings

log = logging.getLogger(__name__)


def configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def _send_sync(msg: EmailMessage) -> None:
    s = get_settings()
    context = ssl.create_default_context()
    if s.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
    with server:
        if s.smtp_security == "starttls":
            server.starttls(context=context)
        if s.smtp_username:
            server.login(s.smtp_username, s.smtp_password or "")
        server.send_message(msg)


async def send_email(
    to: str, subject: str, text: str, html: str | None = None, headers: dict[str, str] | None = None
) -> bool:
    """Send one email; True when the SMTP server accepted it. Never raises (callers run it in the background)."""
    s = get_settings()
    if not configured():
        if s.environment == "production":
            log.error("SMTP is not configured; email to %s not sent: %s", to, subject)
        else:
            log.warning("SMTP is not configured; email not sent.\nTo: %s\nSubject: %s\n\n%s", to, subject, text)
        return False
    try:
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = _one_line(subject)
        msg["Message-ID"] = make_msgid()
        for name, value in (headers or {}).items():
            msg[name] = _one_line(value)
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        await asyncio.to_thread(_send_sync, msg)
    except Exception:  # noqa: BLE001 - bad address or header, SMTP or network error: report, never raise
        log.exception("Sending email to %s failed", to)
        return False
    return True


def _one_line(value: str) -> str:
    """Header values come from user input (names, companies): a line break would be rejected or inject a header."""
    return " ".join(str(value).split())
