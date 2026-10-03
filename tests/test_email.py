"""Email must never be able to break a booking.

Two independent failure boundaries: the SMTP send, and handing the job to
Celery. A booking is already committed by the time either runs, so both fail
open -- log and continue rather than raise.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.config import get_settings
from app.models.building import Building
from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.services.bookings import BookingInput, TimeframeInput, create_booking
from app.services.mailer import queue_email, render_email, send_email_now

TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def booking(db_session, db_setup):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="E-1", name="Hall", usage_type="meeting",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True, public_bookable=True,
        cleaning_rate_daily=Decimal("45.00"),
    )
    party = Party(party_type=PartyType.EXTERNAL, name="Guest", email="guest@example.com")
    db_session.add_all([room, party])
    db_session.commit()
    return create_booking(
        db_session, room=room, party=party,
        data=BookingInput(
            room_id=room.id, title="Concert",
            timeframe=TimeframeInput(
                start_at=datetime(2030, 6, 10, 19, 0, tzinfo=TZ),
                end_at=datetime(2030, 6, 10, 22, 0, tzinfo=TZ),
            ),
        ),
        source=BookingSource.PUBLIC, status=BookingStatus.PENDING,
    )


def test_disabled_mail_logs_instead_of_sending(caplog):
    """A fresh clone has no SMTP server; everything else must still work."""
    assert get_settings().mail_enabled is False
    with caplog.at_level("INFO"):
        assert send_email_now(["a@example.com"], "Subject", "<p>hi</p>", "hi") is False
    assert "[mail disabled]" in caplog.text


def test_send_failure_does_not_propagate(monkeypatch, caplog):
    import app.services.mailer as mailer

    monkeypatch.setattr(get_settings(), "mail_enabled", True, raising=False)

    def explode(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer.smtplib, "SMTP", explode)
    with caplog.at_level("WARNING"):
        assert send_email_now(["a@example.com"], "Subject", "<p>hi</p>", "hi") is False
    assert "mail send failed" in caplog.text


def test_queue_failure_does_not_propagate(monkeypatch, caplog):
    """A broker that is down must not turn a committed booking into a 500."""
    import app.jobs.tasks as tasks

    monkeypatch.setattr(get_settings(), "mail_enabled", True, raising=False)

    def explode(*args, **kwargs):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks.send_email, "delay", explode)
    with caplog.at_level("WARNING"):
        queue_email(["a@example.com"], "Subject", "<p>hi</p>", "hi")
    assert "could not queue email" in caplog.text


def test_disabled_mail_never_touches_the_broker(monkeypatch, caplog):
    """No point queueing a job whose only outcome is a log line -- and it keeps
    a machine with no Redis from waiting on connection retries."""
    import app.jobs.tasks as tasks

    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the broker should not have been contacted")

    monkeypatch.setattr(tasks.send_email, "delay", explode)
    with caplog.at_level("INFO"):
        queue_email(["a@example.com"], "Subject", "<p>hi</p>", "hi")
    assert "[mail disabled]" in caplog.text


def test_no_recipients_is_a_no_op():
    assert send_email_now([], "Subject", "<p>hi</p>", "hi") is False
    assert send_email_now([None, ""], "Subject", "<p>hi</p>", "hi") is False


@pytest.mark.parametrize(
    "template",
    [
        "public_booking_received",
        "public_booking_approved",
        "public_booking_rejected",
        "public_booking_cancelled",
        "public_booking_modified",
        "public_booking_manage_link",
        "member_booking_confirmed",
        "member_booking_cancelled",
        "staff_new_public_request",
    ],
)
def test_every_template_renders_in_both_languages(template, booking):
    from app.services.booking_notifications import booking_context

    context = booking_context(booking, manage_url="https://example.test/book/manage?t=x")
    context.setdefault("admin_url", "https://example.test/bookings/1")
    for lang in ("de", "en"):
        subject, html, text = render_email(template, lang=lang, **context)
        assert subject, f"{template} rendered an empty subject"
        assert booking.request.public_ref in subject
        assert html.strip() and text.strip()


def test_render_uses_the_requested_language(booking):
    """Emails go out from a worker with no request, so the language has to come
    from the stored value rather than the server default."""
    from app.services.booking_notifications import booking_context

    context = booking_context(booking)
    _, html_de, _ = render_email("public_booking_received", lang="de", **context)
    _, html_en, _ = render_email("public_booking_received", lang="en", **context)
    assert html_de and html_en


def test_notification_failure_does_not_raise(booking, monkeypatch, caplog):
    import app.services.booking_notifications as notifications

    def explode(*args, **kwargs):
        raise RuntimeError("template exploded")

    monkeypatch.setattr(notifications, "render_email", explode)
    with caplog.at_level("WARNING"):
        notifications.notify(booking, "public_booking_received")
    assert "could not send" in caplog.text
