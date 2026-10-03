from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from app.db.session import get_session_factory
from app.jobs.celery_app import celery_app
from app.models.booking import Booking
from app.models.enums import BookingStatus, LeaseStatus
from app.models.key import KeyAssignment
from app.models.lease import Lease
from app.services.party_sync import sync_nextcloud_person_parties as run_nextcloud_person_sync
from app.services.notifications import fanout_admin_notification


@celery_app.task(name="app.jobs.tasks.scan_lease_expiry")
def scan_lease_expiry() -> dict[str, int]:
    session = get_session_factory()()
    try:
        today = date.today()
        horizon = today + timedelta(days=90)
        leases = session.scalars(
            select(Lease).where(
                Lease.status == LeaseStatus.ACTIVE,
                Lease.end_date.is_not(None),
                Lease.end_date >= today,
                Lease.end_date <= horizon,
            )
        ).all()
        count = 0
        for lease in leases:
            days_left = (lease.end_date - today).days
            if days_left in {90, 30, 7}:
                fanout_admin_notification(
                    session,
                    title="Lease Expiry Alert",
                    message=f"Lease {lease.id} for room {lease.room_id} expires in {days_left} days.",
                    link=f"/leases/{lease.id}",
                    details_json={"lease_id": lease.id, "days_left": days_left},
                )
                count += 1
        return {"alerts": count}
    finally:
        session.close()


@celery_app.task(name="app.jobs.tasks.scan_booking_conflicts")
def scan_booking_conflicts() -> dict[str, int]:
    session = get_session_factory()()
    try:
        bookings = session.scalars(
            select(Booking).where(Booking.status == BookingStatus.APPROVED).order_by(Booking.room_id, Booking.start_at)
        ).all()
        conflicts = 0
        for index, current in enumerate(bookings):
            for nxt in bookings[index + 1 :]:
                if nxt.room_id != current.room_id:
                    break
                if nxt.start_at < current.end_at and current.start_at < nxt.end_at:
                    fanout_admin_notification(
                        session,
                        title="Booking Conflict Detected",
                        message=f"Approved bookings {current.id} and {nxt.id} overlap for room {current.room_id}.",
                        link=f"/bookings/{current.id}",
                        details_json={"booking_a": current.id, "booking_b": nxt.id, "room_id": current.room_id},
                    )
                    conflicts += 1
        return {"conflicts": conflicts}
    finally:
        session.close()


@celery_app.task(name="app.jobs.tasks.scan_unreturned_keys")
def scan_unreturned_keys() -> dict[str, int]:
    session = get_session_factory()()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(days=30)
        assignments = session.scalars(
            select(KeyAssignment).where(
                KeyAssignment.returned_at.is_(None),
                KeyAssignment.issued_at <= threshold,
            )
        ).all()
        if assignments:
            fanout_admin_notification(
                session,
                title="Unreturned Keys",
                message=f"{len(assignments)} key assignments are older than 30 days and still open.",
                link="/keys",
                details_json={"assignment_ids": [row.id for row in assignments]},
            )
        return {"open_assignments": len(assignments)}
    finally:
        session.close()


@celery_app.task(name="app.jobs.tasks.sync_nextcloud_person_parties")
def sync_nextcloud_person_parties() -> dict[str, int]:
    session = get_session_factory()()
    try:
        return run_nextcloud_person_sync(session)
    finally:
        session.close()


@celery_app.task(name="app.jobs.tasks.send_email")
def send_email(to: list[str], subject: str, html: str, text: str) -> dict[str, object]:
    """Deliver one pre-rendered email.

    Generic on purpose: rendering happens in the request process where the ORM
    objects are live, so this task touches no database and holds no session.

    No `autoretry_for`. A retry storm against a dead SMTP host is worse than a
    lost notification -- the booking itself is safe either way, and the failure
    is in the log.
    """
    from app.services.mailer import send_email_now

    sent = send_email_now(to, subject, html, text)
    return {"sent": 1 if sent else 0, "recipients": len(to)}
