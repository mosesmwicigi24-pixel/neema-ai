"""Outgoing mail — stdlib smtplib on a worker thread, STARTTLS by default,
SMTPS on port 465. Used for the password-reset link (services/password_reset).

`configured()` is the gate every caller checks first. `send()` raises
MailError with a plain reason — never the mail password, never the server's
banner. Tests replace `send` with a recorder; nothing here touches the
network at import time.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

_log = logging.getLogger("neema.mail")


class MailError(RuntimeError):
    """The mail could not go out; `str(exc)` is safe to show an admin."""


def configured() -> bool:
    return bool((settings.smtp_host or "").strip() and sender())


def sender() -> str:
    return (settings.smtp_from or settings.smtp_user or "").strip()


def build(to: list[str], subject: str, text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(("Neema · Bethany House", sender()))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(msg: EmailMessage, to: list[str]) -> None:
    ctx = ssl.create_default_context()
    host, port = settings.smtp_host.strip(), int(settings.smtp_port or 587)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg, from_addr=sender(), to_addrs=to)
        return
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.ehlo()
        if settings.smtp_starttls:
            s.starttls(context=ctx)
            s.ehlo()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg, from_addr=sender(), to_addrs=to)


async def send(to: list[str], subject: str, text: str, html: str | None = None) -> None:
    """One message to `to`. Raises MailError; the caller decides what the
    person sees."""
    if not configured():
        raise MailError("outgoing mail is not configured on the server (SMTP_HOST / SMTP_USER)")
    to = [t.strip() for t in to if t and t.strip()]
    if not to:
        raise MailError("no recipient")
    msg = build(to, subject, text, html)
    try:
        await asyncio.to_thread(_send_sync, msg, to)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("the mail server refused our login — check SMTP_USER / SMTP_PASSWORD") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"the mail server could not be reached ({exc.__class__.__name__})") from exc
    _log.info("mail sent: %r → %s", subject, ", ".join(to))
