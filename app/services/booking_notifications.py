"""Turn booking events into emails and in-app notifications.

Kept apart from `services.bookings` so the booking rules stay testable without
touching a mail transport, and so a notification failure can never roll back a
committed booking.

Every function here is best-effort by design: it is called *after* the commit,
and it swallows its own errors. A booking that exists must not be undone
because an email could not be rendered.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.time_utils import to_app_tz
from app.models.booking import Booking
from app.services.mailer import admin_recipients, queue_email, render_email
from app.services.notifications import fanout_admin_notification

logger = logging.getLogger(__name__)


def _format(value) -> str:
    if value is None:
        return ""
    try:
        return to_app_tz(value).strftime("%d.%m.%Y %H:%M")
    except (AttributeError, TypeError):  # a date, not a datetime
        return str(value)


def booking_context(booking: Booking, *, manage_url: str | None = None) -> dict:
    request = booking.request
    context = {
        "public_ref": request.public_ref if request else "",
        "title": booking.title,
        "room_name": booking.room.name if booking.room else "",
        "start_at": _format(booking.start_at),
        "end_at": _format(booking.end_at),
        "manage_url": manage_url,
    }
    if request is not None:
        context.update(
            {
                "cleaning_charge": request.cleaning_charge,
                "cleaning_days": request.cleaning_days,
                "cleaning_rate_daily": request.cleaning_rate_daily,
                "currency": request.currency,
                "staff_note": request.staff_note,
                "requester_name": request.requester_display_name or "",
                "requester_email": request.requester_email or "",
            }
        )
    return context


def _requester_email(booking: Booking) -> str | None:
    if booking.request is not None and booking.request.requester_email:
        return booking.request.requester_email
    if booking.party is not None and booking.party.email:
        return booking.party.email
    return None


def notify(booking: Booking, template: str, *, to: list[str] | None = None, **extra) -> None:
    """Render and queue one email. Never raises."""
    try:
        recipients = to if to is not None else [_requester_email(booking)]
        recipients = [address for address in recipients if address]
        if not recipients:
            return
        language = booking.request.language if booking.request else None
        subject, html, text = render_email(
            template, lang=language, **{**booking_context(booking), **extra}
        )
        queue_email(recipients, subject, html, text)
    except Exception as exc:
        # The booking is already committed. Losing an email is bad; losing the
        # booking because of an email is worse.
        logger.warning("could not send %s for booking %s: %s", template, booking.id, exc)


def notify_public_request_created(db: Session, booking: Booking, *, manage_url: str | None) -> None:
    notify(booking, "public_booking_received", manage_url=manage_url)

    admin_url = _admin_url(booking)
    notify(
        booking,
        "staff_new_public_request",
        to=admin_recipients(),
        admin_url=admin_url,
    )
    try:
        # External requesters cannot receive an in-app notification --
        # Notification.user_id is NOT NULL -- so this reaches staff only.
        fanout_admin_notification(
            db,
            title="New booking request",
            message=f"{booking.title} — {booking.room.name if booking.room else ''}",
            link=f"/bookings/{booking.id}",
            details_json={"booking_id": booking.id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("could not raise admin notification for booking %s: %s", booking.id, exc)


def _admin_url(booking: Booking) -> str:
    from app.core.config import get_settings

    return f"{get_settings().public_base_url.rstrip('/')}/bookings/{booking.id}"


def notify_decision(booking: Booking, *, manage_url: str | None = None) -> None:
    from app.models.enums import BookingStatus

    template = {
        BookingStatus.APPROVED: "public_booking_approved",
        BookingStatus.REJECTED: "public_booking_rejected",
        BookingStatus.CANCELLED: "public_booking_cancelled",
    }.get(booking.status)
    if template:
        notify(booking, template, manage_url=manage_url)


def notify_member_booking(booking: Booking, *, cancelled: bool = False) -> None:
    template = "member_booking_cancelled" if cancelled else "member_booking_confirmed"
    notify(booking, template)
