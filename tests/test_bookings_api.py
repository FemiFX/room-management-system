"""API-level tests for the bookings endpoints.

Nothing exercised POST /api/v1/bookings before this: the booking rules were
covered only at the service layer, so the endpoint's role gates, conflict
responses and audit trail were untested.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingStatus, OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room

TZ = ZoneInfo("Europe/Berlin")


def _iso(day: int, hour: int) -> str:
    return datetime(2030, 6, day, hour, 0, tzinfo=TZ).isoformat()


@pytest.fixture
def seeded(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="A-1", name="Hall", usage_type="meeting",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True, capacity=20,
        cleaning_rate_daily=Decimal("45.00"),
    )
    party = Party(party_type=PartyType.ORGANIZATION, name="Org", is_active=True)
    db_session.add_all([room, party])
    db_session.commit()
    return {"room_id": room.id, "party_id": party.id}


def _payload(seeded, day=10, start=10, end=12, **extra):
    return {
        "room_id": seeded["room_id"],
        "party_id": seeded["party_id"],
        "title": "Board meeting",
        "start_at": _iso(day, start),
        "end_at": _iso(day, end),
        **extra,
    }


def test_staff_can_create_a_booking(client, dev_login, seeded):
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    response = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["source"] == "staff"
    assert body["conflicts"] == []


def test_create_requires_csrf(client, dev_login, seeded):
    dev_login(role="editor", email="editor@example.com", display_name="Editor")
    assert client.post("/api/v1/bookings", json=_payload(seeded)).status_code == 400


def test_viewer_cannot_create(client, dev_login, seeded):
    csrf = dev_login(role="viewer", email="viewer@example.com", display_name="Viewer")
    response = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    assert response.status_code == 403


def test_create_reports_conflicts_without_refusing(client, dev_login, seeded, db_session):
    """Staff must still be able to record a competing request.

    The conflict check bites at approval, not at creation.
    """
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    first = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    booking_id = first.json()["id"]
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "approved"},
        headers={"x-csrf-token": csrf},
    )

    second = client.post(
        "/api/v1/bookings",
        json=_payload(seeded, start=11, end=13),
        headers={"x-csrf-token": csrf},
    )
    assert second.status_code == 201
    assert second.json()["conflicts"], "an overlapping approved booking should be reported"
    assert second.json()["conflicts"][0]["kind"] == "booking"


def test_approving_an_overlapping_booking_is_refused_with_the_clash(client, dev_login, seeded):
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    first = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    client.patch(
        f"/api/v1/bookings/{first.json()['id']}",
        json={"status": "approved"},
        headers={"x-csrf-token": csrf},
    )
    second = client.post(
        "/api/v1/bookings", json=_payload(seeded, start=11, end=13), headers={"x-csrf-token": csrf}
    )

    refused = client.patch(
        f"/api/v1/bookings/{second.json()['id']}",
        json={"status": "approved"},
        headers={"x-csrf-token": csrf},
    )
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "room_unavailable"
    assert detail["conflicts"][0]["start_at"] is not None


def test_touching_bookings_can_both_be_approved(client, dev_login, seeded):
    """Half-open intervals: 10-12 and 12-14 are not a clash."""
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    first = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    second = client.post(
        "/api/v1/bookings", json=_payload(seeded, start=12, end=14), headers={"x-csrf-token": csrf}
    )
    for booking in (first, second):
        response = client.patch(
            f"/api/v1/bookings/{booking.json()['id']}",
            json={"status": "approved"},
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 200, response.json()


def test_reject_records_the_reason(client, dev_login, seeded, db_session):
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    created = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    booking_id = created.json()["id"]

    response = client.post(
        f"/api/v1/bookings/{booking_id}/reject",
        json={"reason": "Room is being redecorated that week."},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    booking = db_session.get(Booking, booking_id)
    db_session.refresh(booking)
    assert booking.request.staff_note == "Room is being redecorated that week."


def test_cancel_is_a_status_change_not_a_delete(client, dev_login, seeded, db_session):
    """The reference app hard-deleted on cancellation, losing the record."""
    csrf = dev_login(role="editor", email="editor@example.com", display_name="Editor")
    created = client.post("/api/v1/bookings", json=_payload(seeded), headers={"x-csrf-token": csrf})
    booking_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/bookings/{booking_id}", json={"status": "cancelled"}, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 200

    booking = db_session.get(Booking, booking_id)
    assert booking is not None
    assert booking.status == BookingStatus.CANCELLED
    db_session.refresh(booking)
    assert booking.request.cancelled_by == "staff"
    # A cancelled booking's manage link must stop working.
    assert booking.request.token_version == 2
