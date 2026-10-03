"""Outbound email.

RMS sent no email at all before this. The transport is stdlib smtplib rather
than a dependency: sending happens synchronously inside a Celery worker, where
an async client buys nothing, and stdlib gives full control over STARTTLS
versus implicit TLS.

Two rules govern everything here:

1. **Fail open.** A send failure is logged and swallowed, never raised. The
   booking is already committed by the time we try to send; a booking must not
   be lost, or a request 500, because an SMTP host is unreachable.
2. **Render in the request, send in the worker.** `render_email` returns
   plain strings, so the Celery task carries no ORM objects and needs no
   database.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import get_settings
from app.core.i18n import _load_translations, get_default_language
from app.core.templating import templates

logger = logging.getLogger(__name__)


def render_email(template_stem: str, *, lang: str | None = None, **context) -> tuple[str, str, str]:
    """Render ``(subject, html, text)`` for one email in ``lang``.

    The Jinja ``_`` global is bound to the request via ``@pass_context``, and
    there is no request here, so it would silently fall back to the server
    default language. We overlay the environment with ``_`` rebound to the
    catalogue for the language this recipient actually used -- which is why
    booking_requests stores it.

    A plain-text sibling is rendered alongside the HTML rather than derived
    from it: it lands better with spam filters, and translators can read it.
    """
    language = (lang or get_default_language()).strip().lower()
    translations = _load_translations(language)

    env = templates.env.overlay()
    env.globals = dict(templates.env.globals)
    env.globals["_"] = translations.gettext
    env.globals["current_language"] = language

    settings = get_settings()
    full_context = {
        "public_base_url": settings.public_base_url.rstrip("/"),
        "app_name": settings.app_name,
        "lang": language,
        **context,
    }

    subject = env.get_template(f"email/{template_stem}.subject.txt").render(**full_context).strip()
    html = env.get_template(f"email/{template_stem}.html").render(subject=subject, **full_context)
    text = env.get_template(f"email/{template_stem}.txt").render(subject=subject, **full_context)
    return subject, html, text


def send_email_now(to: list[str], subject: str, html: str, text: str) -> bool:
    """Send synchronously. Returns whether it went out; never raises."""
    settings = get_settings()
    recipients = [address for address in to if address]
    if not recipients:
        return False

    if not settings.mail_enabled:
        logger.info("[mail disabled] to=%s subject=%r", ", ".join(recipients), subject)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (
        formataddr((settings.mail_from_name, settings.mail_from))
        if settings.mail_from_name
        else settings.mail_from
    )
    message["To"] = ", ".join(recipients)
    if settings.mail_reply_to:
        message["Reply-To"] = settings.mail_reply_to
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        if settings.mail_use_ssl:
            server = smtplib.SMTP_SSL(settings.mail_host, settings.mail_port, timeout=settings.mail_timeout_s)
        else:
            server = smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=settings.mail_timeout_s)
        with server:
            if settings.mail_use_tls and not settings.mail_use_ssl:
                server.starttls()
            if settings.mail_username:
                server.login(settings.mail_username, settings.mail_password)
            server.send_message(message)
    except Exception as exc:
        # Deliberately broad and deliberately swallowed -- see rule 1 above.
        logger.warning("mail send failed (subject=%r): %s", subject, exc)
        return False
    return True


def queue_email(to: list[str], subject: str, html: str, text: str) -> None:
    """Hand off to Celery, tolerating a broker that is down.

    `.delay()` raises when Redis is unreachable. The booking is committed by
    now, so that must not propagate -- we log and fall through rather than
    turning a successful booking into a 500.
    """
    recipients = [address for address in to if address]
    if not recipients:
        return

    if not get_settings().mail_enabled:
        # Skip the broker entirely rather than queueing a job whose only
        # outcome is the same log line. Also keeps a dev machine with no Redis
        # from waiting on connection retries for every booking.
        logger.info("[mail disabled] to=%s subject=%r", ", ".join(recipients), subject)
        return

    try:
        from app.jobs.tasks import send_email

        send_email.delay(recipients, subject, html, text)
    except Exception as exc:
        logger.warning("could not queue email (subject=%r): %s", subject, exc)


def admin_recipients() -> list[str]:
    return list(get_settings().mail_admin_recipients)
